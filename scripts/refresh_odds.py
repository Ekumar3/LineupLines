"""Refresh Vegas-implied team totals from The Odds API (local, no AWS).

The projection model's environment multiplier compares each team's Vegas-implied
team total for the upcoming week against its trailing average. Those lines move
all week on injury/news, and move most in the 24-48h before kickoff — so a line
captured when the schedule was first published is nearly worthless. This script
pulls CURRENT NFL game lines (totals + spreads) from The Odds API, derives each
team's implied total, and writes them where the projection service prefers them
over the stale nflverse schedule lines.

This is the local stand-in for what will become a scheduled Lambda in
production (the handler in src/sleeper_pipeline/ already anticipates it). Run it
manually, or on a local scheduled task, leading up to kickoff.

Implied team total (matching the dbt feature mart's convention so live and
historical totals are defined identically):
    home implied = (total + spread_home_nflverse) / 2
    away implied = (total - spread_home_nflverse) / 2
where spread_home_nflverse is positive when the home team is favored. The Odds
API expresses spreads per-team with the favorite NEGATIVE, so the home team's
nflverse-convention spread = -(home team's Odds-API spread point).

Each returned game is labeled with its TRUE NFL week by matching it to the
nflverse schedule (by season + home/away team) — not with whatever ``--week``
was passed. The API returns the currently-upcoming slate, which can span the
current week plus any next-week games already posted, so the schedule is the
authority on which week a game belongs to. ``--week`` is therefore a FILTER:
omit it to write every upcoming week the API returned (correctly labeled), or
pass it to write only that week.

Output: data/odds/implied_totals_{season}_wk{NN}.parquet, one file per week,
one row per team:
    season, week, team, implied_team_total, total_line, spread_line, fetched_at

Free-tier limitation: The Odds API free tier serves only UPCOMING/live games —
it has NO historical odds. So you can only refresh a week's lines BEFORE that
week's games start; once a game has kicked off it drops out of the feed. In
normal use you run this before the week's first kickoff, when all of that week's
games are still upcoming. (A paid tier adds historical odds via a separate
endpoint; if we upgrade later we could backfill past weeks and build the trailing
baseline from the same provider — see "Future: paid tier" below.)

Future: paid tier (not implemented).
    The Odds API's paid plans expose a historical-odds endpoint
    (/v4/historical/sports/{sport}/odds) returning a point-in-time snapshot.
    Upgrading would let us (a) refresh/backfill lines for weeks already in
    progress or past, and (b) rebuild the env-multiplier's trailing baseline
    from Odds-API lines instead of nflverse closing lines, removing the small
    cross-provider mismatch noted in the projection service. Out of scope for
    now (local, free-tier only, no AWS).

Setup:
    1. Get a free API key at https://the-odds-api.com (free tier: 500 req/month;
       this script uses 1 request per run).
    2. Put it in a .env file at the repo root:  ODDS_API_KEY=your_key_here

Usage:
    python scripts/refresh_odds.py 2026            # all upcoming weeks returned
    python scripts/refresh_odds.py 2026 8          # only games the schedule says are week 8
    python scripts/refresh_odds.py 2026 8 --dry-run
    python scripts/refresh_odds.py --season 2026 --week 8
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

# Project root on sys.path + cwd, like the other scripts, before src imports.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import requests  # noqa: E402

try:
    from dotenv import load_dotenv  # noqa: E402
    load_dotenv(project_root / ".env")
except Exception:  # pragma: no cover - dotenv optional
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ODDS_HOST = "https://api.the-odds-api.com"
SPORT_KEY = "americanfootball_nfl"
SEED_CSV = project_root / "dbt" / "seeds" / "nfl_team_abbreviations.csv"
OUTPUT_DIR = project_root / "data" / "odds"

# The seed maps full team name -> abbreviation, but a few abbreviations differ
# from what the nflverse schedule / dbt marts use. Normalize to the schedule's
# convention so the output keys match what the projection service looks up.
# (Confirmed: seed says LAR for the Rams; schedule uses LA.)
_ABBR_OVERRIDES = {"LAR": "LA"}


def _load_name_to_abbr() -> dict:
    """Full team name -> schedule-convention abbreviation, from the dbt seed."""
    mapping = {}
    with open(SEED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["team_full_name"].strip()
            abbr = row["team_abbreviation"].strip()
            mapping[name] = _ABBR_OVERRIDES.get(abbr, abbr)
    return mapping


def _load_schedule_weeks(season: int) -> dict:
    """Map (home_abbr, away_abbr) -> week for a season, from the nflverse schedule.

    The schedule is the authority on which NFL week a matchup belongs to. Used
    to label each fetched game with its TRUE week rather than trusting the API's
    ordering or a CLI argument. Returns {} if the schedule parquet is missing.
    """
    import glob

    import polars as pl

    files = glob.glob(str(project_root / "data" / "raw" / f"schedules_{season}.parquet"))
    if not files:
        logger.warning(
            "No schedule parquet for season %d at data/raw/; cannot resolve game weeks. "
            "Run `python scripts/ingest_nflverse.py %d` first.",
            season, season,
        )
        return {}
    df = pl.read_parquet(files[0])
    need = {"season", "week", "home_team", "away_team"}
    if not need.issubset(set(df.columns)):
        logger.warning("Schedule parquet missing columns to resolve weeks: %s", df.columns)
        return {}
    weeks = {}
    for r in df.filter(pl.col("season") == season).iter_rows(named=True):
        weeks[(r["home_team"], r["away_team"])] = int(r["week"])
    return weeks


def _median_or_none(values):
    vals = [v for v in values if v is not None]
    return median(vals) if vals else None


def fetch_game_lines(api_key: str, regions: str = "us"):
    """Fetch current NFL totals + spreads from The Odds API.

    Returns a list of per-game dicts: {home_team, away_team, commence_time,
    total, home_spread_nflverse} where home_spread_nflverse is positive when the
    home team is favored (nflverse convention). Lines are the median across all
    returned bookmakers to reduce single-book noise. Games missing a total or
    the home spread are skipped. Raises on HTTP/auth errors so the caller can
    report them clearly.
    """
    url = f"{ODDS_HOST}/v4/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": "totals,spreads",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    # Usage headers are handy to watch the free-tier quota.
    remaining = resp.headers.get("x-requests-remaining")
    used = resp.headers.get("x-requests-used")
    if remaining is not None:
        logger.info("Odds API quota: used=%s remaining=%s", used, remaining)

    games = []
    for game in resp.json():
        home = game.get("home_team")
        away = game.get("away_team")
        if not home or not away:
            continue

        totals, home_spreads = [], []
        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                key = market.get("key")
                outcomes = market.get("outcomes", [])
                if key == "totals":
                    # Over/Under share the same point; take the first present.
                    pt = next((o.get("point") for o in outcomes if o.get("point") is not None), None)
                    if pt is not None:
                        totals.append(float(pt))
                elif key == "spreads":
                    # Per-team points; the favorite's point is negative. The
                    # home team's nflverse-convention spread = -(home point).
                    home_pt = next(
                        (o.get("point") for o in outcomes if o.get("name") == home and o.get("point") is not None),
                        None,
                    )
                    if home_pt is not None:
                        home_spreads.append(-float(home_pt))

        total = _median_or_none(totals)
        home_spread = _median_or_none(home_spreads)
        if total is None or home_spread is None:
            logger.warning("Skipping %s @ %s: missing total/spread in odds response.", away, home)
            continue

        games.append({
            "home_team": home,
            "away_team": away,
            "commence_time": game.get("commence_time"),
            "total": total,
            "home_spread_nflverse": home_spread,
        })
    return games


def build_implied_rows(games, name_to_abbr, schedule_weeks, season: int, only_week=None):
    """Turn fetched game lines into per-team implied-total rows, labeled by the
    game's TRUE NFL week (resolved from the schedule).

    Each game's week comes from ``schedule_weeks`` (keyed by home/away abbr), so
    a mixed upcoming slate is labeled correctly rather than all stamped with one
    week. ``only_week`` (optional) filters to a single week. Games whose teams
    don't map, or that aren't found in the schedule, are skipped with a warning
    rather than producing a mis-keyed or wrong-week row.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for g in games:
        home_abbr = name_to_abbr.get(g["home_team"])
        away_abbr = name_to_abbr.get(g["away_team"])
        if home_abbr is None or away_abbr is None:
            logger.warning(
                "Could not map team name to abbreviation (home=%r->%r away=%r->%r); skipping game.",
                g["home_team"], home_abbr, g["away_team"], away_abbr,
            )
            continue

        # Authoritative week from the schedule (try both orderings defensively).
        game_week = schedule_weeks.get((home_abbr, away_abbr))
        if game_week is None:
            game_week = schedule_weeks.get((away_abbr, home_abbr))
        if game_week is None:
            logger.warning(
                "No schedule row for %s @ %s (season %d); skipping (can't resolve week).",
                away_abbr, home_abbr, season,
            )
            continue

        if only_week is not None and game_week != only_week:
            continue

        total = g["total"]
        spread = g["home_spread_nflverse"]
        home_implied = (total + spread) / 2.0
        away_implied = (total - spread) / 2.0
        rows.append({
            "season": season, "week": game_week, "team": home_abbr,
            "implied_team_total": home_implied, "total_line": total,
            "spread_line": spread, "fetched_at": fetched_at,
        })
        rows.append({
            "season": season, "week": game_week, "team": away_abbr,
            "implied_team_total": away_implied, "total_line": total,
            "spread_line": -spread, "fetched_at": fetched_at,
        })
    return rows


def _output_path(season: int, week: int) -> Path:
    return OUTPUT_DIR / f"implied_totals_{season}_wk{week:02d}.parquet"


def write_rows_by_week(rows, season: int) -> list:
    """Write rows grouped by their week — one parquet per week. Returns paths.

    Rows can span multiple weeks (the upcoming slate often includes some
    next-week games), and the projection overlay reads one file per week, so we
    split the output accordingly rather than co-mingling weeks in one file.
    """
    import polars as pl

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    weeks = sorted({r["week"] for r in rows})
    paths = []
    for wk in weeks:
        wk_rows = [r for r in rows if r["week"] == wk]
        path = _output_path(season, wk)

        # Merge with any existing file for this week. Once a game kicks off it
        # drops out of the free-tier feed, so a later refresh would otherwise
        # overwrite the file and lose that game's lines. Keep the earlier rows
        # for teams the new fetch no longer returns; fresh rows win for the rest.
        if path.exists():
            try:
                fetched_teams = {r["team"] for r in wk_rows}
                kept = [
                    r for r in pl.read_parquet(path).to_dicts()
                    if r["team"] not in fetched_teams
                ]
                if kept:
                    logger.info(
                        "Week %d: keeping %d earlier row(s) for team(s) no longer in the feed (%s).",
                        wk, len(kept), ", ".join(sorted(r["team"] for r in kept)),
                    )
                    wk_rows = wk_rows + kept
            except Exception as e:  # pragma: no cover - never lose the fresh fetch over this
                logger.warning("Could not merge with existing %s (%s); overwriting.", path.name, e)

        pl.DataFrame(wk_rows).write_parquet(path)
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Vegas-implied team totals from The Odds API for one (season, week)."
    )
    parser.add_argument("season", nargs="?", type=int, help="Season year (e.g. 2026).")
    parser.add_argument("week", nargs="?", type=int, help="Week number (e.g. 7).")
    parser.add_argument("--season", dest="season_opt", type=int, help="Season (alternative to positional).")
    parser.add_argument("--week", dest="week_opt", type=int, help="Week (alternative to positional).")
    parser.add_argument("--regions", default="us", help="Odds API regions (default: us).")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print, but do not write the parquet.")
    args = parser.parse_args()

    season = args.season if args.season is not None else args.season_opt
    week = args.week if args.week is not None else args.week_opt  # optional filter
    if season is None:
        parser.error("season is required, e.g. `refresh_odds.py 2026` (week is an optional filter).")

    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        logger.error(
            "ODDS_API_KEY is not set. Get a free key at https://the-odds-api.com and "
            "add `ODDS_API_KEY=your_key` to a .env file at the repo root."
        )
        return 1

    name_to_abbr = _load_name_to_abbr()
    schedule_weeks = _load_schedule_weeks(season)
    if not schedule_weeks:
        logger.error(
            "Cannot resolve game weeks without the season schedule. "
            "Ingest it first: python scripts/ingest_nflverse.py %d", season,
        )
        return 1

    try:
        games = fetch_game_lines(api_key, regions=args.regions)
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", "?")
        if status == 401:
            logger.error("Odds API rejected the key (401). Check ODDS_API_KEY.")
        elif status == 429:
            logger.error("Odds API quota exhausted (429). Free tier is 500 req/month.")
        else:
            logger.error("Odds API request failed (HTTP %s): %s", status, e)
        return 1
    except requests.exceptions.RequestException as e:
        logger.error("Could not reach The Odds API: %s", e)
        return 1

    if not games:
        logger.warning("No games returned. The current NFL slate may be between weeks, or odds aren't posted yet.")
        return 1

    rows = build_implied_rows(games, name_to_abbr, schedule_weeks, season, only_week=week)
    if not rows:
        if week is not None:
            logger.warning(
                "No rows for season=%d week=%d. The upcoming slate may not include "
                "week %d yet, or those games have already started (free tier has no "
                "historical odds).", season, week, week,
            )
        else:
            logger.warning("No implied-total rows produced from the upcoming slate.")
        return 1

    # Readable preview, grouped by week then highest implied total first.
    weeks_present = sorted({r["week"] for r in rows})
    for wk in weeks_present:
        wk_rows = sorted(
            (r for r in rows if r["week"] == wk),
            key=lambda r: r["implied_team_total"], reverse=True,
        )
        logger.info("Implied team totals for season=%d week=%d (%d teams):", season, wk, len(wk_rows))
        for r in wk_rows:
            logger.info("  %-4s %.1f   (game total %.1f, spread %+.1f)",
                        r["team"], r["implied_team_total"], r["total_line"], r["spread_line"])

    if args.dry_run:
        logger.info("--dry-run: not writing. %d rows across weeks %s would be written.",
                    len(rows), weeks_present)
        return 0

    paths = write_rows_by_week(rows, season)
    for p in paths:
        logger.info("Wrote implied totals to %s", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
