"""Baseline projection + signed adjustment model for a player's weekly stat line.

Expected points are never stored or reasoned about as a single number — they
always derive from a projected 9-component STAT LINE (see
research.scoring.STAT_COMPONENTS), which any scoring-settings dict can be
dot-producted against later.

Pipeline for one (player, season, week):
    1. baseline_stat_line   — trailing per-component average, no future data
    2. compute_deltas       — 4 signed, ~-1..1 deviations from that baseline
    3. adjustment           — one clamped scalar combining the 4 deltas
    4. expected_line        — baseline * (1 + adjustment), component-wise

KNOWN v1 LIMITATION: `adjustment()` returns a single scalar applied uniformly
to every component of the stat line. If the driving signal this week was
"target share is way up," the model still scales the player's rushing line
by the exact same factor as their receiving line — it cannot express
"receiving up, rushing flat." Fixing this means moving from one multiplier
to per-role (rushing vs. receiving) multipliers, which is out of scope here.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import nflreadpy as nfl
import polars as pl

from research import defense
from research.scoring import STAT_COMPONENTS, get_scoring_settings, score_stat_line

logger = logging.getLogger(__name__)

MODEL_VERSION = "v1.0.0-backtest"
MODEL_VERSION_V2 = "v2.0.0-backtest"

# --- v2: per-channel defense factors instead of a scalar adjustment ---------
# expected_c = baseline_c * defense_factor[opponent, channel(c)] * (1 + V2_ENVIRONMENT_WEIGHT * delta_environment)
# The four-delta sum and its clamp are gone; delta_matchup is *replaced* by
# research.defense (opponent-adjusted, per channel), not re-weighted. Vegas
# keeps setting the level of team output; the defense model sets the split.
V2_ENVIRONMENT_WEIGHT = 0.25
V2_CONFIG = {
    "environment_weight": V2_ENVIRONMENT_WEIGHT,
    "ridge_lambda": defense.RIDGE_LAMBDA,
    "prior_season_weight": defense.PRIOR_SEASON_WEIGHT,
    "factor_clamp": list(defense.FACTOR_CLAMP),
}

RAW_DATA_DIR = Path(__file__).resolve().parent / "data" / "raw"

MODELED_POSITIONS = ("QB", "RB", "WR", "TE")

# nflverse column name for each of the 9 stat-line components we project.
# Most are 1:1; a few (interceptions, fumbles_lost) don't share our name.
STAT_COLUMN_MAP: Dict[str, str] = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "interceptions": "passing_interceptions",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "receiving_tds": "receiving_tds",
    "fumbles_lost": "fumbles_lost_total",
}

_FEATURE_NUMERIC_COLUMNS = (
    *STAT_COMPONENTS,
    "target_share",
    "carries",
    "team_carries",
    "targets",
    "attempts",
    "offense_pct",
    "implied_team_total",
    "passing_epa",
    "rushing_epa",
    "receiving_epa",
)

# --- Adjustment: one module-level weights dict, one clamp -----------------
WEIGHTS: Dict[str, float] = {
    "delta_opportunity": 0.45,
    "delta_environment": 0.25,
    "delta_efficiency": 0.20,
    "delta_matchup": 0.10,
}
ADJUSTMENT_CLAMP: Tuple[float, float] = (-0.25, 0.25)

# --- Normalization / shrinkage constants -----------------------------------
# Each delta is designed to land roughly in [-1, 1] before WEIGHTS is applied;
# these are the knobs that set that scale.
BASELINE_WINDOW = 3               # trailing weeks averaged for the baseline stat line
OPPORTUNITY_SHARE_SCALE = 0.15    # target/carry-share point deviation -> delta of 1.0
OPPORTUNITY_SNAP_SCALE = 0.15     # offense_pct point deviation -> delta of 1.0
ENVIRONMENT_SCALE = 3.0           # implied-team-total point deviation -> delta of 1.0
EFFICIENCY_SCALE = 0.12           # blended EPA/play + yards/touch deviation -> delta of 1.0
EFFICIENCY_SHRINK_K = 8           # shrinkage strength (in touches) toward position-mean efficiency
MATCHUP_SHRINK_K = 6              # shrinkage strength (in weeks of history) toward league-average matchup


# ---------------------------------------------------------------------------
# Data loading — cached to research/data/raw/*.parquet, offline after first pull.
# ---------------------------------------------------------------------------

def _cached_season(loader, name: str, season: int) -> pl.DataFrame:
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DATA_DIR / f"{name}_{season}.parquet"
    if path.exists():
        return pl.read_parquet(path)
    df = loader([season])
    df.write_parquet(path)
    return df


def load_player_stats(seasons: Sequence[int]) -> pl.DataFrame:
    """Weekly player stat lines, regular season only, cached per season."""
    frames = [_cached_season(nfl.load_player_stats, "player_stats", s) for s in seasons]
    return pl.concat(frames, how="vertical_relaxed").filter(pl.col("season_type") == "REG")


def load_snap_counts(seasons: Sequence[int]) -> pl.DataFrame:
    """Weekly snap counts (offense_pct), regular season only, cached per season."""
    frames = [_cached_season(nfl.load_snap_counts, "snap_counts", s) for s in seasons]
    return pl.concat(frames, how="vertical_relaxed").filter(pl.col("game_type") == "REG")


def load_schedules(seasons: Sequence[int]) -> pl.DataFrame:
    """Game schedules with Vegas lines, regular season only, cached per season."""
    frames = [_cached_season(nfl.load_schedules, "schedules", s) for s in seasons]
    return pl.concat(frames, how="vertical_relaxed").filter(pl.col("game_type") == "REG")


def _normalize_name(name: Optional[str]) -> str:
    """Lowercase, de-punctuated player name for joining player_stats <-> snap_counts.

    Deliberately simple and local: both tables already share the same
    "First Last" display-name convention (verified against real data), so
    this only needs to absorb punctuation drift — not the heavier alias
    resolution src/analytics/adp_service.py does for externally-scraped ADP.
    """
    if not name:
        return ""
    name = name.lower().strip()
    for ch in ("'", ".", "-"):
        name = name.replace(ch, "")
    for suffix in (" ii", " iii", " iv", " jr", " sr"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _implied_team_totals(schedules: pl.DataFrame) -> pl.DataFrame:
    """One row per (season, week, team) with that team's Vegas-implied point total.

    spread_line is the home team's favorite margin (positive = home favored);
    total_line is the game's over/under. Standard split:
        implied_home = (total_line + spread_line) / 2
        implied_away = (total_line - spread_line) / 2
    """
    home = schedules.select(
        "season", "week",
        pl.col("home_team").alias("team"),
        ((pl.col("total_line") + pl.col("spread_line")) / 2).alias("implied_team_total"),
    )
    away = schedules.select(
        "season", "week",
        pl.col("away_team").alias("team"),
        ((pl.col("total_line") - pl.col("spread_line")) / 2).alias("implied_team_total"),
    )
    return pl.concat([home, away], how="vertical_relaxed")


def build_feature_table(seasons: Sequence[int]) -> pl.DataFrame:
    """Join player_stats + snap_counts + schedules into one per-player-week table.

    One row per (season, week, player_id) for QB/RB/WR/TE, carrying the 9
    renamed stat-line components plus every input the delta model needs
    (target_share, team_carries, offense_pct, implied_team_total, EPA).
    Everything downstream reads from this table — no other function in this
    module touches nflreadpy directly.
    """
    stats = load_player_stats(seasons).filter(pl.col("position").is_in(MODELED_POSITIONS))

    team_carries = stats.group_by(["season", "week", "team"]).agg(
        pl.col("carries").sum().alias("team_carries")
    )
    stats = stats.join(team_carries, on=["season", "week", "team"], how="left")

    snaps = (
        load_snap_counts(seasons)
        .with_columns(
            pl.col("player").map_elements(_normalize_name, return_dtype=pl.Utf8).alias("_norm_name")
        )
        .select("season", "week", "team", "_norm_name", "offense_pct")
    )
    stats = stats.with_columns(
        pl.col("player_display_name").map_elements(_normalize_name, return_dtype=pl.Utf8).alias("_norm_name")
    ).join(snaps, on=["season", "week", "team", "_norm_name"], how="left")

    implied = _implied_team_totals(load_schedules(seasons))
    stats = stats.join(implied, on=["season", "week", "team"], how="left")

    stats = stats.rename({v: k for k, v in STAT_COLUMN_MAP.items() if v != k})

    keep = [
        "season", "week", "player_id", "player_display_name", "position", "team", "opponent_team",
        *_FEATURE_NUMERIC_COLUMNS,
    ]
    stats = stats.select([c for c in keep if c in stats.columns])
    stats = stats.with_columns([pl.col(c).fill_null(0.0) for c in _FEATURE_NUMERIC_COLUMNS if c in stats.columns])
    return stats.sort(["player_id", "season", "week"])


def index_by_player(feature_table: pl.DataFrame) -> Dict[str, List[dict]]:
    """Group the feature table into per-player, chronologically sorted row lists."""
    index: Dict[str, List[dict]] = {}
    for row in feature_table.sort(["player_id", "season", "week"]).to_dicts():
        index.setdefault(row["player_id"], []).append(row)
    return index


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def _weeks_before(rows: List[dict], season: int, week: int) -> List[dict]:
    """Rows strictly before (season, week). Rows must already be chronological."""
    return [r for r in rows if (r["season"], r["week"]) < (season, week)]


def baseline_stat_line(
    player_rows: List[dict],
    season: int,
    week: int,
    window: int = BASELINE_WINDOW,
) -> Optional[Dict[str, float]]:
    """Trailing per-component average stat line for a target (season, week).

    Uses ONLY rows strictly before the target week — never the target week
    itself or anything later. Weeks 1-3 of a season use whatever prior weeks
    exist in-season (even a single week); if there are none, falls back to
    the entire PRIOR season's per-game average; if that's unavailable too,
    returns None so the caller excludes the player from this week's slate.

    Args:
        player_rows: One player's rows across all cached seasons, any order.
        season, week: The target week being projected (NOT included).
        window: How many trailing in-season weeks to average over.
    """
    prior = _weeks_before(player_rows, season, week)
    current_season_prior = [r for r in prior if r["season"] == season]

    if current_season_prior:
        recent = current_season_prior[-window:]
    else:
        recent = [r for r in prior if r["season"] == season - 1]
        if not recent:
            return None

    return {component: sum(r[component] for r in recent) / len(recent) for component in STAT_COMPONENTS}


def actual_stat_line(player_rows: List[dict], season: int, week: int) -> Optional[Dict[str, float]]:
    """The player's real stat line for (season, week), or None if they didn't play."""
    for r in player_rows:
        if r["season"] == season and r["week"] == week:
            return {c: r[c] for c in STAT_COMPONENTS}
    return None


def current_team(player_rows: List[dict], season: int, week: int) -> Optional[str]:
    """Most recently known team for this player as of (season, week).

    A player's team affiliation is known before kickoff (unlike anything
    about how they'll perform), so this is safe to use for bye/schedule
    lookups even in a week they don't end up recording a stat line for
    (e.g. a bye — see backtest.py's on_bye computation).
    """
    prior = _weeks_before(player_rows, season, week)
    if prior:
        return prior[-1]["team"]
    for r in player_rows:
        if r["season"] == season and r["week"] == week:
            return r["team"]
    return None


def target_context(player_rows: List[dict], season: int, week: int) -> Optional[Dict[str, object]]:
    """Pregame-known context for a target week: team, opponent, implied total.

    Pulled from the same historical row `actual_stat_line` reads, but only
    these three fields. They're legitimately knowable before kickoff (roster
    assignment + market lines) — unlike every other column in that row,
    which is an outcome and must never feed the delta model.
    """
    for r in player_rows:
        if r["season"] == season and r["week"] == week:
            return {
                "team": r["team"],
                "opponent_team": r["opponent_team"],
                "implied_team_total": r.get("implied_team_total"),
            }
    return None


# ---------------------------------------------------------------------------
# League-wide trailing context for the deltas (also strictly no-future-leak)
# ---------------------------------------------------------------------------

def _efficiency(row: dict) -> Optional[float]:
    """Blended EPA-per-play + yards-per-touch efficiency for one player-week.

    None when the player had zero touches that week (no attempts/carries/
    targets) — such weeks are excluded from trailing/recent efficiency
    rather than counted as a zero, which would look like a huge bust.
    """
    touches = (row.get("attempts") or 0) + (row.get("carries") or 0) + (row.get("targets") or 0)
    if touches <= 0:
        return None
    total_epa = (row.get("passing_epa") or 0) + (row.get("rushing_epa") or 0) + (row.get("receiving_epa") or 0)
    yards = (row.get("rushing_yards") or 0) + (row.get("receiving_yards") or 0)
    epa_per_play = total_epa / touches
    yards_per_touch = yards / touches
    # yards_per_touch (~0-15 scale) and epa_per_play (~-1..1 scale) are put on
    # a comparable footing before blending.
    return (epa_per_play + yards_per_touch / 10.0) / 2.0


def _opportunity_share(row: dict) -> Optional[float]:
    """Share-of-team-work metric for the opportunity delta.

    RB: share of the team's rush attempts that week. WR/TE: nflverse's
    target_share directly. Not used for QB — see compute_deltas.
    """
    if row["position"] == "RB":
        team_carries = row.get("team_carries") or 0
        return (row["carries"] / team_carries) if team_carries > 0 else None
    return row.get("target_share")


def team_environment_trailing(schedules: pl.DataFrame) -> Dict[Tuple[str, int, int], Optional[float]]:
    """Trailing (expanding, in-season) average implied team total, keyed by (team, season, week).

    Falls back to the entire prior season's average when there are no
    current-season weeks yet (i.e. week 1). Only ever looks at weeks
    strictly before the key's (season, week).
    """
    rows = _implied_team_totals(schedules).sort(["team", "season", "week"]).to_dicts()
    by_team: Dict[str, List[dict]] = {}
    for r in rows:
        by_team.setdefault(r["team"], []).append(r)

    trailing: Dict[Tuple[str, int, int], Optional[float]] = {}
    for team, team_rows in by_team.items():
        for i, r in enumerate(team_rows):
            season, week = r["season"], r["week"]
            prior_current = [x["implied_team_total"] for x in team_rows[:i] if x["season"] == season]
            if prior_current:
                vals = prior_current
            else:
                vals = [x["implied_team_total"] for x in team_rows[:i] if x["season"] == season - 1] or None
            trailing[(team, season, week)] = (sum(vals) / len(vals)) if vals else None
    return trailing


def position_efficiency_trailing(feature_table: pl.DataFrame) -> Dict[Tuple[str, int, int], Optional[float]]:
    """Trailing league-wide mean efficiency, keyed by (position, season, week).

    This is the shrinkage target for delta_efficiency. Computed the same
    expanding, no-future-leak way as team_environment_trailing: only weeks
    strictly before the key's (season, week) contribute.
    """
    weekly: Dict[Tuple[str, int, int], List[float]] = {}
    for r in feature_table.to_dicts():
        eff = _efficiency(r)
        if eff is not None:
            weekly.setdefault((r["position"], r["season"], r["week"]), []).append(eff)
    weekly_mean = {k: sum(v) / len(v) for k, v in weekly.items()}

    by_position: Dict[str, List[Tuple[str, int, int]]] = {}
    for k in sorted(weekly_mean, key=lambda k: (k[0], k[1], k[2])):
        by_position.setdefault(k[0], []).append(k)

    trailing: Dict[Tuple[str, int, int], Optional[float]] = {}
    for position, keys in by_position.items():
        for i, k in enumerate(keys):
            _, season, week = k
            prior_current = [weekly_mean[pk] for pk in keys[:i] if pk[1] == season]
            if prior_current:
                vals = prior_current
            else:
                vals = [weekly_mean[pk] for pk in keys[:i] if pk[1] == season - 1] or None
            trailing[k] = (sum(vals) / len(vals)) if vals else None
    return trailing


def matchup_percentile_trailing(feature_table: pl.DataFrame) -> Dict[Tuple[str, str, int, int], float]:
    """Shrunk percentile rank (0-100, 50=average) of points allowed to a
    position, keyed by (position, opponent_team, season, week).

    Pipeline: PPR points allowed to `position` by `team` each week -> trailing
    (expanding, current-season-only) average -> percentile rank against all
    other teams at that same point in the season -> shrunk hard toward 50 by
    weeks of trailing data. Weakest signal in the model, meant as a
    tiebreaker — the heavy shrinkage is deliberate.
    """
    ppr = get_scoring_settings("ppr")
    rows = feature_table.to_dicts()

    weekly_allowed: Dict[Tuple[str, str, int, int], float] = {}
    for r in rows:
        key = (r["position"], r["opponent_team"], r["season"], r["week"])
        weekly_allowed[key] = weekly_allowed.get(key, 0.0) + score_stat_line(r, ppr)

    by_pos_team: Dict[Tuple[str, str], List[Tuple[int, int, float]]] = {}
    for (position, team, season, week), pts in weekly_allowed.items():
        by_pos_team.setdefault((position, team), []).append((season, week, pts))
    for key in by_pos_team:
        by_pos_team[key].sort()

    # (position, team, season, week) -> (trailing_avg, n_weeks)
    trailing: Dict[Tuple[str, str, int, int], Tuple[float, int]] = {}
    for (position, team), entries in by_pos_team.items():
        for i, (season, week, _pts) in enumerate(entries):
            prior = [pts for (s, _w, pts) in entries[:i] if s == season]
            if prior:
                trailing[(position, team, season, week)] = (sum(prior) / len(prior), len(prior))

    by_snapshot: Dict[Tuple[str, int, int], List[Tuple[str, float, int]]] = {}
    for (position, team, season, week), (avg, n) in trailing.items():
        by_snapshot.setdefault((position, season, week), []).append((team, avg, n))

    result: Dict[Tuple[str, str, int, int], float] = {}
    for (position, season, week), entries in by_snapshot.items():
        avgs = sorted(v for _, v, _ in entries)
        for team, avg, n in entries:
            raw_percentile = 100.0 * sum(1 for v in avgs if v <= avg) / len(avgs)
            weight = n / (n + MATCHUP_SHRINK_K)
            result[(position, team, season, week)] = 50.0 + weight * (raw_percentile - 50.0)
    return result


@dataclass
class DeltaContext:
    """Precomputed, league-wide, no-future-leak lookups the deltas share."""

    team_environment_trailing: Dict[Tuple[str, int, int], Optional[float]]
    position_efficiency_trailing: Dict[Tuple[str, int, int], Optional[float]]
    matchup_percentile_trailing: Dict[Tuple[str, str, int, int], float]
    # v2 only: (team, season, week, channel) -> multiplicative factor, from research.defense
    defense_factors: Dict[defense.FactorKey, float] = field(default_factory=dict)

    @classmethod
    def build(cls, feature_table: pl.DataFrame, schedules: pl.DataFrame) -> "DeltaContext":
        return cls(
            team_environment_trailing=team_environment_trailing(schedules),
            position_efficiency_trailing=position_efficiency_trailing(feature_table),
            matchup_percentile_trailing=matchup_percentile_trailing(feature_table),
            defense_factors=defense.defense_factors(feature_table),
        )


# ---------------------------------------------------------------------------
# Deltas + adjustment
# ---------------------------------------------------------------------------

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def environment_delta(
    team: str,
    season: int,
    week: int,
    implied_team_total: Optional[float],
    context: "DeltaContext",
) -> float:
    """This week's Vegas-implied team total vs. the team's trailing average, ~-1..1.

    Shared by v1 (as one of four deltas) and v2 (as the only level term —
    Vegas sets how much the team scores; the defense model sets the split).
    """
    baseline_env = context.team_environment_trailing.get((team, season, week))
    if baseline_env is None or implied_team_total is None:
        return 0.0
    return _clip((implied_team_total - baseline_env) / ENVIRONMENT_SCALE, -1.0, 1.0)


def compute_deltas(
    player_rows: List[dict],
    season: int,
    week: int,
    position: str,
    team: str,
    opponent_team: str,
    implied_team_total: Optional[float],
    context: DeltaContext,
    window: int = BASELINE_WINDOW,
) -> Dict[str, float]:
    """Four signed deltas (~-1..1) explaining why this week should differ
    from the trailing baseline.

    Every input is either (a) strictly from weeks before `week`, or (b) the
    pregame market/schedule context FOR `week` (implied_team_total,
    opponent_team) — legitimately known before kickoff, not a data leak.
    """
    prior = _weeks_before(player_rows, season, week)
    current_season_prior = [r for r in prior if r["season"] == season]
    trailing_rows = (
        current_season_prior[-window:]
        if current_season_prior
        else [r for r in prior if r["season"] == season - 1]
    )
    recent_row = trailing_rows[-1] if trailing_rows else None

    # --- opportunity: recent share/snaps vs. this player's own trailing average ---
    snaps = [r.get("offense_pct") for r in trailing_rows if r.get("offense_pct") is not None]
    recent_snap = recent_row.get("offense_pct") if recent_row else None
    snap_delta = (
        (recent_snap - sum(snaps) / len(snaps)) / OPPORTUNITY_SNAP_SCALE
        if snaps and recent_snap is not None
        else 0.0
    )

    if position == "QB":
        # QBs have no meaningful target/carry share; snap share alone stands in.
        delta_opportunity = _clip(snap_delta, -1.0, 1.0)
    else:
        shares = [s for s in (_opportunity_share(r) for r in trailing_rows) if s is not None]
        recent_share = _opportunity_share(recent_row) if recent_row else None
        share_delta = (
            (recent_share - sum(shares) / len(shares)) / OPPORTUNITY_SHARE_SCALE
            if shares and recent_share is not None
            else 0.0
        )
        delta_opportunity = _clip((share_delta + snap_delta) / 2.0, -1.0, 1.0)

    # --- environment: this week's implied total vs. the team's trailing average ---
    delta_environment = environment_delta(team, season, week, implied_team_total, context)

    # --- efficiency: recent vs. trailing, both shrunk toward the position mean ---
    trailing_effs = [
        (eff, (r.get("attempts") or 0) + (r.get("carries") or 0) + (r.get("targets") or 0))
        for r in trailing_rows
        for eff in [_efficiency(r)]
        if eff is not None
    ]
    recent_eff = _efficiency(recent_row) if recent_row else None
    recent_touches = (
        (recent_row.get("attempts") or 0) + (recent_row.get("carries") or 0) + (recent_row.get("targets") or 0)
        if recent_row
        else 0
    )
    position_mean_eff = context.position_efficiency_trailing.get((position, season, week))

    if trailing_effs and recent_eff is not None and position_mean_eff is not None:
        baseline_touches = sum(t for _, t in trailing_effs)
        baseline_eff = (
            sum(eff * t for eff, t in trailing_effs) / baseline_touches
            if baseline_touches
            else sum(eff for eff, _ in trailing_effs) / len(trailing_effs)
        )
        recent_weight = recent_touches / (recent_touches + EFFICIENCY_SHRINK_K)
        baseline_weight = baseline_touches / (baseline_touches + EFFICIENCY_SHRINK_K)
        shrunk_recent = recent_weight * recent_eff + (1 - recent_weight) * position_mean_eff
        shrunk_baseline = baseline_weight * baseline_eff + (1 - baseline_weight) * position_mean_eff
        delta_efficiency = _clip((shrunk_recent - shrunk_baseline) / EFFICIENCY_SCALE, -1.0, 1.0)
    else:
        delta_efficiency = 0.0

    # --- matchup: opponent's shrunk percentile of points allowed to this position ---
    percentile = context.matchup_percentile_trailing.get((position, opponent_team, season, week))
    delta_matchup = _clip((percentile - 50.0) / 50.0, -1.0, 1.0) if percentile is not None else 0.0

    return {
        "delta_opportunity": delta_opportunity,
        "delta_environment": delta_environment,
        "delta_efficiency": delta_efficiency,
        "delta_matchup": delta_matchup,
    }


def adjustment(deltas: Dict[str, float], weights: Dict[str, float] = WEIGHTS) -> float:
    """Single signed multiplier applied to the whole baseline stat line.

        adjustment = clamp(0.45*opp + 0.25*env + 0.20*eff + 0.10*matchup, -0.25, +0.25)

    See the module docstring for the v1 uniform-scaling limitation.
    """
    raw = sum(weights[key] * deltas[key] for key in weights)
    return _clip(raw, *ADJUSTMENT_CLAMP)


def expected_line(baseline: Dict[str, float], adj: float) -> Dict[str, float]:
    """expected_line = baseline_line * (1 + adjustment), component-wise."""
    return {component: value * (1.0 + adj) for component, value in baseline.items()}


@dataclass
class Projection:
    baseline: Dict[str, float]
    deltas: Dict[str, float]
    adjustment: float
    expected: Dict[str, float]


def project_player_week(
    player_rows: List[dict],
    season: int,
    week: int,
    position: str,
    team: str,
    opponent_team: str,
    implied_team_total: Optional[float],
    context: DeltaContext,
) -> Optional[Projection]:
    """Full pipeline: baseline -> deltas -> adjustment -> expected stat line.

    Returns None if there's no usable baseline (see baseline_stat_line) —
    the caller should exclude the player from this week's slate.
    """
    baseline = baseline_stat_line(player_rows, season, week)
    if baseline is None:
        return None
    deltas = compute_deltas(player_rows, season, week, position, team, opponent_team, implied_team_total, context)
    adj = adjustment(deltas)
    return Projection(baseline=baseline, deltas=deltas, adjustment=adj, expected=expected_line(baseline, adj))


# ---------------------------------------------------------------------------
# v2: per-channel defense factors
# ---------------------------------------------------------------------------

@dataclass
class ProjectionV2:
    baseline: Dict[str, float]
    expected: Dict[str, float]
    pass_factor: float
    rush_factor: float
    delta_environment: float
    environment_multiplier: float


def expected_line_v2(
    baseline: Dict[str, float],
    pass_factor: float,
    rush_factor: float,
    environment_multiplier: float,
) -> Dict[str, float]:
    """expected_c = baseline_c * channel_factor(c) * environment_multiplier.

    Pass-channel components get pass_factor, rush-channel get rush_factor,
    fumbles_lost gets neither (see research.defense.COMPONENT_CHANNEL). This
    is what lets a pass-funnel defense move a RB's receiving line up while
    leaving his rushing line alone — the thing v1's scalar could never do.
    """
    factors = {"pass": pass_factor, "rush": rush_factor}
    return {
        component: value * factors.get(defense.COMPONENT_CHANNEL.get(component, ""), 1.0) * environment_multiplier
        for component, value in baseline.items()
    }


def project_player_week_v2(
    player_rows: List[dict],
    season: int,
    week: int,
    position: str,
    team: str,
    opponent_team: Optional[str],
    implied_team_total: Optional[float],
    context: DeltaContext,
) -> Optional[ProjectionV2]:
    """v2 pipeline: baseline -> opponent-adjusted defense factors -> Vegas level.

    Same baseline and same None-means-exclude contract as v1. Unknown
    opponent (bye) or no fitted factors yet -> factors of 1.0 (league avg).
    """
    baseline = baseline_stat_line(player_rows, season, week)
    if baseline is None:
        return None
    if opponent_team is None:
        pass_factor = rush_factor = 1.0
    else:
        pass_factor = defense.factor_for(context.defense_factors, opponent_team, season, week, "pass")
        rush_factor = defense.factor_for(context.defense_factors, opponent_team, season, week, "rush")
    delta_env = environment_delta(team, season, week, implied_team_total, context)
    env_mult = 1.0 + V2_ENVIRONMENT_WEIGHT * delta_env
    return ProjectionV2(
        baseline=baseline,
        expected=expected_line_v2(baseline, pass_factor, rush_factor, env_mult),
        pass_factor=pass_factor,
        rush_factor=rush_factor,
        delta_environment=delta_env,
        environment_multiplier=env_mult,
    )
