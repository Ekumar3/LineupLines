"""Fetch in-season start/sit recommendations from the LOCAL running API.

This is a convenience client so you don't have to hand-run several curls. It
resolves a Sleeper username (or raw user_id) to a roster, picks a league, then
calls the local LineupLines API's in-season recommendations endpoint and prints
a clean start/sit table.

Username -> user_id resolution and league listing go straight through
``SleeperClient`` (Sleeper's public API), so they work without the local API
running. Only the recommendations call needs the local API up.

Prerequisites:
  * The API must already be running locally:  python scripts/run_api.py
  * Projections for the resolved week must already be generated — either by
    running ``python scripts/generate_projections.py <season> <week>`` yourself,
    or by passing ``--load-current`` (below).

Optional data loading (--load-current):
  Pass ``--load-current`` to make the run self-sufficient. Before fetching
  recommendations it brings the current (season, week) up to date, in order:
    1. raw nflverse parquet — re-pulled if absent, or if the schedule lists
       finished games the play-by-play file doesn't have yet;
    2. dbt marts — rebuilt if absent or the raw data just changed;
    3. Vegas lines from The Odds API (needs ODDS_API_KEY in .env) — best-effort,
       falls back to the nflverse schedule lines, skipped if fetched < 6h ago;
    4. the week's projection — regenerated if absent, or if the marts or odds
       are newer than it.
  Anything already current is logged and skipped. This is the local stand-in
  for the Airflow DAG. Requires the projection stack (dbt, polars, duckdb).
  Run it before the week's first kickoff to get fresh odds: once a game starts
  it leaves the Odds API feed (earlier lines for it are kept, not lost).

Usage:
    python scripts/recommend.py --username YOUR_SLEEPER_NAME
    python scripts/recommend.py --username YOUR_SLEEPER_NAME --league-id 123456789
    python scripts/recommend.py --user-id 987654321 --league-id 123456789
    python scripts/recommend.py --username YOUR_SLEEPER_NAME --load-current
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

# Ensure the project root is on sys.path so 'src' is importable, and set CWD to
# it so relative data/ paths resolve — exactly like run_api.py. This MUST happen
# before importing any src.* modules.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import requests  # noqa: E402  (import after sys.path/CWD setup)

from src.data_sources.sleeper_client import SleeperClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# recommendation values that count as "starting"; everything else is a SIT variant.
_START_REC = "START"


def _resolve_user_id(args: argparse.Namespace, client: SleeperClient) -> str | None:
    """Resolve the user_id from --username or --user-id (exactly one required)."""
    if args.user_id:
        return str(args.user_id)

    user = client.get_user(args.username)
    if not user or not user.get("user_id"):
        logger.error("Could not resolve Sleeper username %r to a user_id.", args.username)
        return None
    return str(user["user_id"])


def _resolve_league_id(args: argparse.Namespace, client: SleeperClient, user_id: str) -> str | None:
    """Resolve the league_id, listing/prompting when --league-id is omitted."""
    if args.league_id:
        return str(args.league_id)

    leagues = client.get_user_leagues(user_id, "nfl", args.season)
    if not leagues:
        logger.error(
            "No NFL leagues found for user_id=%s in season %s. "
            "Pass --league-id explicitly or check the --season.",
            user_id,
            args.season,
        )
        return None

    if len(leagues) == 1:
        league = leagues[0]
        league_id = str(league.get("league_id"))
        logger.info("Using your only %s league: %s (%s)", args.season, league.get("name"), league_id)
        return league_id

    print(f"\nFound {len(leagues)} NFL leagues for season {args.season}:")
    for i, league in enumerate(leagues):
        print(f"  [{i}] {league.get('name')} ({league.get('league_id')})")

    while True:
        raw = input("\nPick a league by index: ").strip()
        try:
            idx = int(raw)
        except ValueError:
            print("Please enter a number.")
            continue
        if 0 <= idx < len(leagues):
            return str(leagues[idx].get("league_id"))
        print(f"Index out of range (0-{len(leagues) - 1}).")


def _resolve_current_week(client: SleeperClient, fallback_season: str) -> tuple[int, int]:
    """Resolve the current (season, week) from Sleeper NFL state.

    Mirrors the API's own ``_resolve_nfl_week_season`` so --load-current ensures
    data for the exact (season, week) the recommendations endpoint will request.
    Falls back to (fallback_season, 1) if the state call fails.
    """
    from datetime import datetime as _dt

    try:
        state = client.get_nfl_state()
    except Exception:
        state = None

    season = week = None
    if state:
        try:
            season = int(state.get("season")) if state.get("season") is not None else None
        except (TypeError, ValueError):
            season = None
        try:
            week = int(state.get("week")) if state.get("week") is not None else None
        except (TypeError, ValueError):
            week = None

    if season is None:
        try:
            season = int(fallback_season)
        except (TypeError, ValueError):
            season = _dt.now().year
    if week is None or week < 1:
        week = 1
    return season, week


# After a forced re-ingest, don't force another within this window: nflverse
# publishes play-by-play some hours after a game ends, so re-pulling right away
# would just re-download the same file.
_RAW_REINGEST_COOLDOWN_HOURS = 3.0

# A week's odds file younger than this is considered fresh and not re-fetched
# (each fetch costs 1 of the Odds API free tier's 500 monthly requests).
_ODDS_MAX_AGE_HOURS = 6.0


def _missing_completed_games(season: int) -> int | None:
    """Count games that should be finished but are absent from the raw pbp parquet.

    The current season's pbp file grows as games are played, so "file exists"
    doesn't mean "data is current", and neither does "it has week N" (a file
    pulled on Thursday night has week N but only one of its games). This
    compares the schedule's game ids with a date before today against the game
    ids actually present in the pbp file, so a partially ingested week is
    caught.

    Returns None when either file is missing or unreadable (the caller then
    falls back to the absent-only pull).
    """
    from datetime import date

    raw_dir = project_root / "data" / "raw"
    sched = raw_dir / f"schedules_{season}.parquet"
    pbp = raw_dir / f"pbp_{season}.parquet"
    if not sched.exists() or not pbp.exists():
        return None
    try:
        import duckdb

        con = duckdb.connect()
        try:
            row = con.execute(
                f"""
                select count(*) from (
                    select distinct game_id from read_parquet('{sched.as_posix()}')
                    where game_type = 'REG'
                      and cast(gameday as date) < cast(? as date)
                    except
                    select distinct game_id from read_parquet('{pbp.as_posix()}')
                )
                """,
                [date.today().isoformat()],
            ).fetchone()
        finally:
            con.close()
        return int(row[0])
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("Could not compare schedule and pbp games (%s); treating as unknown.", e)
        return None


def _odds_path(season: int, week: int) -> Path:
    return project_root / "data" / "odds" / f"implied_totals_{season}_wk{week:02d}.parquet"


def _file_age_hours(path: Path) -> float:
    import time

    return (time.time() - path.stat().st_mtime) / 3600.0


def _refresh_odds(season: int, week: int) -> bool:
    """Best-effort fetch of the week's Vegas lines. Returns True if a file was written.

    Never fails the run: a missing key, exhausted quota, network error, or games
    that already kicked off just log a warning, and the projection falls back to
    the (older) nflverse schedule lines. Skipped when the week's file is fresh,
    to save the free tier's monthly request quota. Games that have already
    started have left the feed, so their earlier lines are kept (see
    scripts/refresh_odds.write_rows_by_week).
    """
    path = _odds_path(season, week)
    if path.exists() and _file_age_hours(path) < _ODDS_MAX_AGE_HOURS:
        logger.info(
            "Odds for season=%d week=%d fetched %.1fh ago (< %.0fh); skipping fetch.",
            season, week, _file_age_hours(path), _ODDS_MAX_AGE_HOURS,
        )
        return False

    try:
        from scripts import refresh_odds as ro

        api_key = os.environ.get("ODDS_API_KEY", "").strip()
        if not api_key:
            logger.warning(
                "ODDS_API_KEY not set; using nflverse schedule lines for week %d "
                "(add it to .env for fresher lines).", week,
            )
            return False

        schedule_weeks = ro._load_schedule_weeks(season)
        if not schedule_weeks:
            logger.warning("No schedule parquet; cannot label odds by week. Skipping odds refresh.")
            return False

        games = ro.fetch_game_lines(api_key)
        rows = ro.build_implied_rows(
            games, ro._load_name_to_abbr(), schedule_weeks, season, only_week=week
        )
        if not rows:
            logger.warning(
                "No week %d games in the odds feed (all started, or lines not posted yet); "
                "using nflverse schedule lines.", week,
            )
            return False

        ro.write_rows_by_week(rows, season)
        logger.info("Fetched fresh Vegas lines for %d team(s) in week %d.", len(rows), week)
        return True
    except Exception as e:
        logger.warning("Odds refresh failed (%s); using nflverse schedule lines.", e)
        return False


def _marts_present(season: int) -> bool:
    """True when the dbt feature mart already has rows for ``season``.

    Used as the absent-only check for the dbt build stage: if the mart carries
    this season's data we skip the (slow) rebuild.
    """
    try:
        from src.data_sources.projections_store import load_mart

        df = load_mart("mart_player_week_features", season=season)
        return df is not None and df.height > 0
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("Mart presence check failed (%s); treating marts as absent.", e)
        return False


def _run_dbt_build() -> bool:
    """Run ``dbt build`` for the local dev target. Returns True on success.

    dbt must run as a subprocess (there is no in-process build). Invoked via the
    current interpreter's dbt module so it uses the active venv, from the dbt/
    project directory with the repo's profiles.
    """
    dbt_dir = project_root / "dbt"
    cmd = [sys.executable, "-m", "dbt.cli.main", "build", "--profiles-dir", ".", "--target", "dev"]
    logger.info("Building dbt marts: %s (cwd=%s)", " ".join(cmd), dbt_dir)
    try:
        result = subprocess.run(cmd, cwd=str(dbt_dir))
    except FileNotFoundError:
        logger.error("Could not invoke dbt. Is the projection stack installed in this environment?")
        return False
    if result.returncode != 0:
        logger.error("dbt build failed (exit code %d). See the dbt output above.", result.returncode)
        return False
    return True


def _projection_present(season: int, week: int, scoring_format: str) -> bool:
    """True when the projection parquet for (season, week, format) already exists."""
    path = project_root / "data" / "projections" / f"{season}_wk{week:02d}_{scoring_format}.parquet"
    return path.exists()


def _generate_projection(season: int, week: int, scoring_format: str) -> bool:
    """Generate the week's projection parquet in-process. Returns True on success.

    Mirrors scripts/generate_projections.py (and the DAG's generate_projections
    task) but called directly so --load-current stays self-contained.
    """
    try:
        from research.scoring import get_scoring_settings
        from src.services.projection_service import ProjectionService

        scoring_settings = get_scoring_settings(scoring_format)
        service = ProjectionService()
        service.load_marts(season)
        projections = service.project_week(season, week, scoring_settings)
        if not projections:
            logger.error(
                "No projections produced for season=%d week=%d (%s) — the feature "
                "mart may be missing or have no players for this week.",
                season, week, scoring_format,
            )
            return False
        service.write_output(projections, season, week, scoring_format)
        logger.info(
            "Generated %d projections for season=%d week=%d (%s).",
            len(projections), season, week, scoring_format,
        )
        return True
    except Exception as e:
        logger.error("Projection generation failed: %s", e)
        return False


def ensure_data_current(season: int, week: int, scoring_format: str) -> bool:
    """Load with cascade invalidation: pull/build/generate what the slate
    needs, and rebuild any downstream stage whose upstream just changed.

    Three stages run in dependency order (raw -> marts -> projection). Each is
    built from the one before it, so a stage is (re)run when EITHER its own
    output is absent OR an upstream stage actually did work this run:

      1. raw nflverse parquet for ``season`` — pulled if absent OR STALE. The
         in-progress season's pbp file grows as games finish, so it's stale
         when the schedule lists finished games the pbp file doesn't contain
         (this also catches a half-ingested week). Completed past seasons never
         change, so they stay absent-only.
      2. dbt marts for ``season`` — rebuilt if absent OR raw was just pulled
         (the marts are computed from the raw data, so new raw makes them stale).
      2.5 Vegas lines for the week from The Odds API — best-effort and never
         fatal (falls back to the nflverse schedule lines). Skipped when the
         week's file is under ``_ODDS_MAX_AGE_HOURS`` old to save API quota.
      3. the projection parquet — regenerated if absent, if the marts were just
         (re)built, or if the week's odds file is newer than the projection.

    This keeps the live season's marts, odds and projection consistent with the
    games that have been played, while keeping completed seasons cheap. Returns
    True when the slate is ready.
    """
    from scripts.ingest_nflverse import ingest_season

    logger.info("--load-current: ensuring data for season=%d week=%d (%s)", season, week, scoring_format)

    # Stage 1: raw nflverse data.
    #
    # Matchup grades and projections for week N are built from games already
    # played. The in-progress season's pbp file grows as games finish, so it's
    # stale whenever the schedule lists finished games the pbp file lacks. That
    # also catches a half-ingested week (e.g. pulled Thursday night, so it has
    # week N but only one of its games). Force a re-ingest in that case,
    # otherwise the absent-only pull suffices.
    missing = _missing_completed_games(season)
    force_reingest = bool(missing)

    if force_reingest:
        pbp_path = project_root / "data" / "raw" / f"pbp_{season}.parquet"
        if pbp_path.exists() and _file_age_hours(pbp_path) < _RAW_REINGEST_COOLDOWN_HOURS:
            logger.warning(
                "%d finished game(s) aren't in the raw pbp yet, but it was pulled %.1fh ago; "
                "nflverse likely hasn't published them. Not re-pulling yet.",
                missing, _file_age_hours(pbp_path),
            )
            force_reingest = False
        else:
            logger.info(
                "%d finished game(s) missing from the raw pbp for season %d; forcing a fresh ingest.",
                missing, season,
            )

    try:
        written = ingest_season(season, force=force_reingest)
    except Exception as e:
        logger.error("Raw nflverse ingest failed: %s", e)
        return False

    # When we force a re-ingest, ingest_season rewrites files it "skips" too, so
    # treat a forced run as having changed the raw data regardless of the
    # returned list.
    raw_pulled = force_reingest or bool(written)
    if force_reingest:
        logger.info("Re-ingested raw data for season %d (was stale).", season)
    elif written:
        logger.info("Pulled %d missing raw file(s) for season %d.", len(written), season)
    else:
        logger.info("Raw nflverse data for season %d already present and current; skipping ingest.", season)

    # Stage 2: dbt marts. Rebuild if absent OR upstream (raw) just changed.
    marts_rebuilt = False
    if raw_pulled:
        logger.info("Raw data changed; rebuilding dbt marts to stay consistent.")
        if not _run_dbt_build():
            return False
        marts_rebuilt = True
    elif not _marts_present(season):
        logger.info("dbt marts for season %d absent; building.", season)
        if not _run_dbt_build():
            return False
        marts_rebuilt = True
    else:
        logger.info("dbt marts for season %d already present and up to date; skipping dbt build.", season)

    # Stage 2.5: live Vegas lines for the week (best-effort, never fatal). Must
    # come before projection generation, which reads data/odds/ at generation
    # time and doesn't pick up odds that arrive after the file is written.
    _refresh_odds(season, week)

    # Stage 3: projection. Regenerate if absent, if upstream (marts) just
    # changed, or if the odds file is newer than the projection (covers odds
    # fetched here or by a manual refresh_odds.py run).
    odds_path = _odds_path(season, week)
    proj_path = project_root / "data" / "projections" / f"{season}_wk{week:02d}_{scoring_format}.parquet"
    marts_path = project_root / "dbt" / "lineuplines.duckdb"
    odds_newer = (
        odds_path.exists()
        and proj_path.exists()
        and odds_path.stat().st_mtime > proj_path.stat().st_mtime
    )
    # Also covers a projection for ANOTHER scoring format: when the marts are
    # rebuilt while refreshing one format, the others' existing files are stale.
    marts_newer = (
        marts_path.exists()
        and proj_path.exists()
        and marts_path.stat().st_mtime > proj_path.stat().st_mtime
    )
    if marts_rebuilt:
        logger.info("Marts changed; regenerating the week's projection to stay consistent.")
        if not _generate_projection(season, week, scoring_format):
            return False
    elif odds_newer or marts_newer:
        logger.info(
            "%s newer than the week's projection; regenerating it.",
            "Odds are" if odds_newer else "Marts are",
        )
        if not _generate_projection(season, week, scoring_format):
            return False
    elif not _projection_present(season, week, scoring_format):
        logger.info("Projection for season=%d week=%d (%s) absent; generating.", season, week, scoring_format)
        if not _generate_projection(season, week, scoring_format):
            return False
    else:
        logger.info(
            "Projection for season=%d week=%d (%s) already present and up to date; "
            "skipping generation.",
            season, week, scoring_format,
        )

    return True


def _fetch_recommendations(base_url: str, league_id: str, user_id: str) -> dict | None:
    """Call the local API's recommendations endpoint; return parsed JSON or None on error."""
    url = f"{base_url.rstrip('/')}/api/v1/in-season/{league_id}/{user_id}/recommendations"
    logger.info("Fetching recommendations from %s", url)

    try:
        response = requests.get(url, timeout=30)
    except requests.exceptions.ConnectionError:
        logger.error(
            "Could not connect to the API at %s. Is it running? "
            "Start it with:  python scripts/run_api.py",
            base_url,
        )
        return None

    if response.status_code == 200:
        return response.json()

    detail = _response_detail(response)

    if response.status_code == 503:
        logger.error(
            "Projections aren't generated yet for the resolved week. "
            "Generate them first with:  python scripts/generate_projections.py <season> <week>"
        )
        if detail:
            logger.error("API said: %s", detail)
        return None

    if response.status_code == 404:
        logger.error(
            "League or user not found (bad league_id/user_id, or the user isn't in that league)."
        )
        if detail:
            logger.error("API said: %s", detail)
        return None

    logger.error("Request failed with HTTP %d: %s", response.status_code, detail or response.text)
    return None


def _response_detail(response: requests.Response) -> str | None:
    """Best-effort extraction of a FastAPI 'detail' message from a response body."""
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    return None


def _sort_key_start(rec: dict) -> tuple:
    """Sort STARTers by slot label, then projected points descending."""
    slot = rec.get("slot") or ""
    proj = rec.get("projected_points")
    proj = proj if isinstance(proj, (int, float)) else float("-inf")
    return (slot, -proj)


def _sort_key_sit(rec: dict) -> tuple:
    """Sort SIT variants by projected points descending."""
    proj = rec.get("projected_points")
    proj = proj if isinstance(proj, (int, float)) else float("-inf")
    return (-proj,)


def _format_proj(value) -> str:
    return f"{value:.1f}" if isinstance(value, (int, float)) else "-"


def _print_table(data: dict) -> None:
    """Print the header block and the sorted start/sit table."""
    print()
    print("=" * 60)
    print(f"League:          {data.get('league_id')}")
    print(f"User:            {data.get('user_id')}")
    print(f"Season / Week:   {data.get('season')} / week {data.get('week')}")
    print(f"Scoring format:  {data.get('scoring_format')}")
    print(f"Optimal lineup:  {data.get('optimal_lineup_set')}")
    print("=" * 60)

    recommendations = data.get("recommendations") or []
    if not recommendations:
        print("\nNo recommendations — this roster is empty or has no projectable players.\n")
        return

    starters = sorted(
        (r for r in recommendations if r.get("recommendation") == _START_REC),
        key=_sort_key_start,
    )
    sitters = sorted(
        (r for r in recommendations if r.get("recommendation") != _START_REC),
        key=_sort_key_sit,
    )
    ordered = starters + sitters

    headers = ["SLOT", "REC", "POS", "PLAYER", "TEAM", "OPP", "PROJ", "MATCHUP"]
    rows = []
    for rec in ordered:
        grade = rec.get("matchup_grade") or {}
        rows.append(
            [
                str(rec.get("slot") or "-"),
                str(rec.get("recommendation") or "-"),
                str(rec.get("position") or "-"),
                str(rec.get("player_name") or "-"),
                str(rec.get("team") or "-"),
                str(grade.get("opponent") or "-"),
                _format_proj(rec.get("projected_points")),
                str(grade.get("overall_signal") or "-"),
            ]
        )

    # Column widths: max of header and all cell lengths.
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    # PROJ is numeric -> right-justify; everything else left-justify.
    right_justify = {headers.index("PROJ")}

    def render(cells: list) -> str:
        parts = []
        for i, cell in enumerate(cells):
            parts.append(cell.rjust(widths[i]) if i in right_justify else cell.ljust(widths[i]))
        return "  ".join(parts).rstrip()

    print()
    print(render(headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(render(row))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch in-season start/sit recommendations from the LOCAL running API "
            "and print a clean table."
        )
    )
    parser.add_argument("--username", help="Sleeper username to resolve into a user_id.")
    parser.add_argument("--user-id", dest="user_id", help="Sleeper user_id to use directly.")
    parser.add_argument(
        "--league-id",
        dest="league_id",
        help="League to query. If omitted, your NFL leagues for --season are listed.",
    )
    parser.add_argument(
        "--season",
        default="2026",
        help="Season used only for listing leagues when --league-id is omitted (default: 2026).",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default="http://localhost:8000",
        help="Base URL of the local API (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--load-current",
        dest="load_current",
        action="store_true",
        help=(
            "Before fetching, bring the current week up to date: raw nflverse "
            "data (re-pulled if finished games are missing), dbt marts, Vegas "
            "lines (best-effort), and the week's projection. Only stale or "
            "absent pieces are rebuilt. The local stand-in for the Airflow DAG."
        ),
    )
    args = parser.parse_args()

    if bool(args.username) == bool(args.user_id):
        parser.error("Provide exactly one of --username or --user-id.")

    client = SleeperClient()

    user_id = _resolve_user_id(args, client)
    if user_id is None:
        return 1

    league_id = _resolve_league_id(args, client, user_id)
    if league_id is None:
        return 1

    # Absent-only data load (opt-in). Resolve the current week + the league's
    # scoring format first so we ensure exactly the slate the API will request.
    if args.load_current:
        season, week = _resolve_current_week(client, args.season)
        scoring_format = client.get_scoring_format(league_id) or "ppr"
        if not ensure_data_current(season, week, scoring_format):
            logger.error("--load-current could not prepare the data; aborting.")
            return 1

    data = _fetch_recommendations(args.base_url, league_id, user_id)
    if data is None:
        return 1

    _print_table(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
