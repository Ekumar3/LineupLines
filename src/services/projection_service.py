"""Production projection pipeline: dbt marts -> projected stat lines -> points.

Refactored from ``research/model.py`` (v2.1.0 per-channel defense factors) +
``research/defense.py`` (ridge fixed-effects defense model). The research code
pulled directly from nflreadpy; this production service reads the dbt feature
mart (``mart_player_week_features``) and the defense factor input mart
(``int_defense_factor_inputs``) instead, via ``projections_store``.

Pipeline for one (player, season, week):
    1. baseline_stat_line   — trailing BASELINE_WINDOW-week per-component average
                              with prior-season fallback (no future leak)
    2. defense factors      — per-channel (pass/rush) ridge fixed-effects fit on
                              team-game yardage, rolling, strictly-before-only,
                              prior season weighted at PRIOR_SEASON_WEIGHT,
                              clamped to FACTOR_CLAMP
    3. environment multiplier — Vegas-implied team total deviation vs trailing
                              (level term; defense factors set the split)
    4. expected_line        — baseline_c * channel_factor(c) * env_mult
    5. projected_points     — dot(expected_line, scoring_settings)

No-future-leak guarantee (ported verbatim): both the baseline AND the defense
factors for a target (season, week) use only rows strictly before it. The
prior season contributes at a reduced weight so week 1 has a regressed prior
rather than nothing.
"""

import glob
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# Repo-root-relative location of the raw nflverse schedule parquet. Resolved
# from this file (src/services/) so it works regardless of the process's cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCHEDULES_GLOB = str(_REPO_ROOT / "data" / "raw" / "schedules_*.parquet")
# Fresh Vegas-implied totals written by scripts/refresh_odds.py. When present
# they OVERRIDE the stale schedule-derived implied totals (the schedule lines
# are captured once; these move with injury/news up to kickoff).
_ODDS_GLOB = str(_REPO_ROOT / "data" / "odds" / "implied_totals_*.parquet")

try:  # polars is the mart I/O format; required for load_marts/write_output
    import polars as pl
except Exception:  # pragma: no cover - defensive, surfaced at load_marts time
    pl = None  # type: ignore[assignment]

# projections_store is implemented concurrently (task 5.1). Import defensively
# against the documented interface: load_mart(name, season=None),
# write_projections(df, season, week, scoring_format).
try:
    from src.data_sources.projections_store import load_mart, write_projections
except Exception:  # pragma: no cover - concurrent task not yet available
    load_mart = None  # type: ignore[assignment]
    write_projections = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

MODEL_VERSION = "v2.1.0-prod"

# --- Constants carried over verbatim from research/ (backtest-validated) -----
RIDGE_LAMBDA = 4.0            # shrinkage: half-shrunk after ~4 games
PRIOR_SEASON_WEIGHT = 0.3     # prior-season game weight vs. a current-season game
FACTOR_CLAMP: Tuple[float, float] = (0.75, 1.25)  # safety rail on exp(def effect)
MIN_GAMES_TO_FIT = 32         # below this, defense factors default to 1.0
BASELINE_WINDOW = 3           # trailing weeks averaged for the baseline stat line
V2_ENVIRONMENT_WEIGHT = 0.25  # weight on the Vegas environment delta
ENVIRONMENT_SCALE = 3.0       # implied-team-total point deviation -> delta of 1.0
TD_SHRINK_K = 6               # shrinkage strength (in games) toward position-mean per-game TD rate

MODELED_POSITIONS = ("QB", "RB", "WR", "TE")

# TD stat-line components shrunk toward a trailing position mean before the
# defense/environment factors apply. A player's trailing TD/game is a tiny,
# high-variance sample (a 3-game window with one fluky score projects
# 0.33 TD/game of pure noise, ~2 PPR pts), so each TD component is blended
# toward the league-wide per-game rate for their position, weighted by
# n_games/(n_games + TD_SHRINK_K). Yardage is left untouched — far more stable.
# K=6 was selected by backtest (research/results/backtest.md): it maximizes the
# model's lineup-points edge over the naive baseline while cutting per-position
# MAE. See research/model.py for the matching research implementation.
TD_COMPONENTS: Tuple[str, ...] = ("passing_tds", "rushing_tds", "receiving_tds")

# The 9-component projected/actual stat line every player-week is expressed as.
STAT_COMPONENTS: Tuple[str, ...] = (
    "passing_yards",
    "passing_tds",
    "interceptions",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "fumbles_lost",
)

# channel -> (team-game yardage column the effect is fit on,
#             stat-line components that channel's factor is applied to)
CHANNELS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "pass": (
        "passing_yards",
        ("passing_yards", "passing_tds", "interceptions",
         "receptions", "receiving_yards", "receiving_tds"),
    ),
    "rush": (
        "rushing_yards",
        ("rushing_yards", "rushing_tds"),
    ),
}
# fumbles_lost belongs to no channel -> factor 1.0
COMPONENT_CHANNEL: Dict[str, str] = {
    component: channel
    for channel, (_, components) in CHANNELS.items()
    for component in components
}

# (defense_team, season, week, channel) -> multiplicative factor
FactorKey = Tuple[str, int, int, str]


# ---------------------------------------------------------------------------
# Output data structure
# ---------------------------------------------------------------------------

@dataclass
class Projection:
    """One player's projected stat line + fantasy points for a (season, week)."""

    player_id: str
    player_name: str
    position: str
    team: str
    opponent: Optional[str]
    expected_stat_line: Dict[str, float]  # all 9 STAT_COMPONENTS
    projected_points: float
    pass_factor: float
    rush_factor: float
    baseline: Dict[str, float]
    # How the number was built, so a UI can explain it. The projection is
    # baseline -> x opponent defense factors -> x Vegas environment multiplier,
    # so  projected_points == defense_adjusted_points * env_multiplier.
    env_multiplier: float = 1.0
    implied_team_total: Optional[float] = None    # Vegas points expected for this team
    trailing_implied_total: Optional[float] = None  # team's usual implied total (the comparison point)
    baseline_points: Optional[float] = None       # recent form alone, scored
    defense_adjusted_points: Optional[float] = None  # after opponent factors, before Vegas
    component_points: Dict[str, float] = field(default_factory=dict)  # points per stat


# ---------------------------------------------------------------------------
# Small helpers (ported from research/)
# ---------------------------------------------------------------------------

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _weeks_before(rows: List[dict], season: int, week: int) -> List[dict]:
    """Rows strictly before (season, week). Rows must already be chronological."""
    return [r for r in rows if (r["season"], r["week"]) < (season, week)]


def _implied_team_total(row: dict) -> Optional[float]:
    """Pregame-known Vegas-implied team total for a feature row, if present."""
    val = row.get("implied_team_total")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _trailing_implied_mean(
    prior_entries: List[Tuple[int, int, Optional[float]]], season: int,
) -> Optional[float]:
    """Expanding mean of a team's implied totals before a target week.

    ``prior_entries`` are (season, week, implied_total) tuples for weeks
    strictly before the target. Uses the target's own season when any exist,
    else falls back to the prior season; returns None when neither has data.
    """
    vals = [t for (s, _w, t) in prior_entries if s == season and t is not None]
    if not vals:
        vals = [t for (s, _w, t) in prior_entries if s == season - 1 and t is not None]
    return sum(vals) / len(vals) if vals else None


# ---------------------------------------------------------------------------
# Precomputed league-wide no-future-leak context
# ---------------------------------------------------------------------------

@dataclass
class DeltaContext:
    """Precomputed league-wide, no-future-leak lookups shared across players.

    ``team_environment_trailing`` maps (team, season, week) to that team's
    trailing (expanding, in-season with prior-season fallback) average implied
    team total. ``defense_factors`` maps (team, season, week, channel) to the
    ridge-fit multiplicative defense factor. Both are strictly-before-only.
    """

    team_environment_trailing: Dict[Tuple[str, int, int], Optional[float]]
    defense_factors: Dict[FactorKey, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ProjectionService:
    """Reads dbt marts, produces projected stat lines, writes projection output."""

    def __init__(self) -> None:
        self._features = None          # polars.DataFrame of mart_player_week_features
        self._defense_inputs = None    # polars.DataFrame of int_defense_factor_inputs
        self._player_index: Optional[Dict[str, List[dict]]] = None
        self._team_env_trailing: Optional[Dict[Tuple[str, int, int], Optional[float]]] = None
        self._schedule_ctx: Optional[Dict[Tuple[str, int, int], Dict[str, object]]] = None
        self._position_td_rates: Optional[Dict[Tuple[str, int, int], Dict[str, float]]] = None
        self._loaded_season: Optional[int] = None

    # -- loading -----------------------------------------------------------

    def load_marts(self, season: int) -> None:
        """Load mart_player_week_features + int_defense_factor_inputs for a season.

        Imports from ``projections_store`` (concurrent task 5.1). Raises a clear
        error if that module or polars is unavailable rather than failing with
        an obscure NoneType error later.
        """
        if load_mart is None:
            raise RuntimeError(
                "projections_store.load_mart is unavailable; cannot load marts. "
                "Ensure src/data_sources/projections_store.py (task 5.1) is present."
            )
        if pl is None:
            raise RuntimeError("polars is required for ProjectionService but is not installed.")

        self._features = load_mart("mart_player_week_features", season=season)
        self._defense_inputs = load_mart("int_defense_factor_inputs", season=season)
        self._loaded_season = season
        # Invalidate derived caches on reload.
        self._player_index = None
        self._team_env_trailing = None
        self._schedule_ctx = None
        self._position_td_rates = None

    # -- derived lookups ---------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._features is None or self._defense_inputs is None:
            raise RuntimeError("load_marts(season) must be called before project_week().")

    def _feature_rows(self) -> List[dict]:
        """All feature-mart rows as dicts, restricted to modeled positions."""
        rows = self._features.to_dicts() if self._features is not None else []
        return [r for r in rows if r.get("position") in MODELED_POSITIONS]

    def _index_by_player(self) -> Dict[str, List[dict]]:
        """Group feature rows per player, sorted chronologically. Cached."""
        if self._player_index is None:
            index: Dict[str, List[dict]] = {}
            rows = sorted(self._feature_rows(), key=lambda r: (r["season"], r["week"]))
            for r in rows:
                index.setdefault(r["player_id"], []).append(r)
            self._player_index = index
        return self._player_index

    def _team_environment_trailing(self) -> Dict[Tuple[str, int, int], Optional[float]]:
        """Trailing (expanding, in-season, prior-season fallback) implied totals.

        Keyed by (team, season, week); only weeks strictly before the key
        contribute. Mirrors research/model.py::team_environment_trailing but
        sources implied totals from the feature mart instead of schedules.

        Mart rows only exist for games already played, so the loop below keys
        only played weeks. An UPCOMING week (the one a lineup is being set for)
        has no mart row and would otherwise have no entry, which made
        ``_environment_multiplier`` silently return 1.0 for every team and
        disabled the Vegas environment term exactly when it's needed. The
        second pass therefore also keys every scheduled (team, season, week)
        that is missing, using the same trailing rule over weeks strictly
        before it. (The research backtest never hit this because its target
        weeks are historical and always have a row.)
        """
        if self._team_env_trailing is not None:
            return self._team_env_trailing

        # One implied-total observation per (team, season, week) from the mart.
        by_team_week: Dict[Tuple[str, int, int], Optional[float]] = {}
        for r in self._feature_rows():
            key = (r["team"], r["season"], r["week"])
            if key not in by_team_week:
                by_team_week[key] = _implied_team_total(r)

        by_team: Dict[str, List[Tuple[int, int, Optional[float]]]] = {}
        for (team, season, week), total in by_team_week.items():
            by_team.setdefault(team, []).append((season, week, total))
        for team in by_team:
            by_team[team].sort()

        trailing: Dict[Tuple[str, int, int], Optional[float]] = {}
        for team, entries in by_team.items():
            for i, (season, week, _total) in enumerate(entries):
                trailing[(team, season, week)] = _trailing_implied_mean(entries[:i], season)

        # Second pass: scheduled weeks with no mart row yet (upcoming games).
        try:
            scheduled = self._schedule_context()
        except Exception as e:  # pragma: no cover - defensive, schedule is optional
            logger.debug("Schedule context unavailable for env trailing: %s", e)
            scheduled = {}
        for (team, season, week) in scheduled:
            if (team, season, week) in trailing:
                continue
            entries = by_team.get(team)
            if not entries:
                continue  # team has no history at all -> leave unkeyed (multiplier 1.0)
            before = [e for e in entries if (e[0], e[1]) < (season, week)]
            mean = _trailing_implied_mean(before, season)
            if mean is not None:  # no history -> leave unkeyed (multiplier 1.0)
                trailing[(team, season, week)] = mean

        self._team_env_trailing = trailing
        return trailing

    def _schedule_context(self) -> Dict[Tuple[str, int, int], Dict[str, object]]:
        """Map (team, season, week) -> {opponent, implied_team_total} from the schedule.

        For an UPCOMING week there is no feature-mart row, so opponent and the
        Vegas-implied team total can't come from the feature table. They can,
        however, come from the raw nflverse schedule parquet, which carries the
        matchup plus ``total_line`` / ``spread_line`` for scheduled games.

        Implied total uses the same formula the dbt feature mart uses for played
        weeks, so upcoming-week totals are defined identically to historical
        ones (the environment multiplier compares the two, so they must match):
            home implied = (total_line + spread_line) / 2
            away implied = (total_line - spread_line) / 2

        Degrades gracefully: missing schedule files, missing columns, or null
        lines simply leave that team-week out of the map, so callers fall back
        to neutral factors exactly as before. Cached per load.
        """
        if self._schedule_ctx is not None:
            return self._schedule_ctx

        ctx: Dict[Tuple[str, int, int], Dict[str, object]] = {}
        if pl is None:
            self._schedule_ctx = ctx
            return ctx

        files = sorted(glob.glob(_SCHEDULES_GLOB))
        if not files:
            logger.info("No schedule parquet found at %s; schedule context empty.", _SCHEDULES_GLOB)
            self._schedule_ctx = ctx
            return ctx

        try:
            df = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")
        except Exception as e:  # pragma: no cover - defensive
            logger.info("Could not read schedule parquet: %s", e)
            self._schedule_ctx = ctx
            return ctx

        needed = {"season", "week", "home_team", "away_team", "total_line", "spread_line"}
        if not needed.issubset(set(df.columns)):
            logger.info("Schedule parquet missing columns for context: have %s", df.columns)
            self._schedule_ctx = ctx
            return ctx

        for r in df.iter_rows(named=True):
            season = r.get("season")
            week = r.get("week")
            home = r.get("home_team")
            away = r.get("away_team")
            total = r.get("total_line")
            spread = r.get("spread_line")
            if season is None or week is None or not home or not away:
                continue
            season, week = int(season), int(week)

            # Opponent is always known from the matchup even if lines are missing.
            home_implied = away_implied = None
            if total is not None and spread is not None:
                # spread_line is from the home team's perspective in nflverse
                # schedules; home implied = (total + spread)/2.
                home_implied = (float(total) + float(spread)) / 2.0
                away_implied = (float(total) - float(spread)) / 2.0

            ctx[(home, season, week)] = {"opponent": away, "implied_team_total": home_implied}
            ctx[(away, season, week)] = {"opponent": home, "implied_team_total": away_implied}

        # Overlay fresh Vegas totals (scripts/refresh_odds.py) on top of the
        # schedule-derived ones. Opponent stays from the schedule (only it knows
        # the matchup); only implied_team_total is replaced, and only for teams
        # that already have a scheduled game that week.
        self._apply_fresh_odds(ctx)

        self._schedule_ctx = ctx
        return ctx

    def _apply_fresh_odds(self, ctx: Dict[Tuple[str, int, int], Dict[str, object]]) -> None:
        """Override implied_team_total in ``ctx`` with fresh odds when available.

        Reads any ``data/odds/implied_totals_*.parquet`` and, for each
        (team, season, week) already present in the schedule context, replaces
        its implied_team_total with the freshly-fetched value. A team-week with
        fresh odds but no scheduled game is ignored (opponent is unknown, so the
        env multiplier has nothing to attach to). Fully graceful: no odds files,
        missing columns, or read errors leave ``ctx`` untouched.
        """
        if pl is None:
            return
        files = sorted(glob.glob(_ODDS_GLOB))
        if not files:
            return
        try:
            odds = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")
        except Exception as e:  # pragma: no cover - defensive
            logger.info("Could not read fresh odds parquet: %s", e)
            return
        if not {"season", "week", "team", "implied_team_total"}.issubset(set(odds.columns)):
            return

        overridden = 0
        for r in odds.iter_rows(named=True):
            team = r.get("team")
            season = r.get("season")
            week = r.get("week")
            implied = r.get("implied_team_total")
            if team is None or season is None or week is None or implied is None:
                continue
            key = (team, int(season), int(week))
            if key in ctx:  # only override a real scheduled game
                ctx[key] = {**ctx[key], "implied_team_total": float(implied)}
                overridden += 1
        if overridden:
            logger.info("Applied fresh Vegas totals to %d team-week(s) from %d odds file(s).",
                        overridden, len(files))

    # -- baseline ----------------------------------------------------------

    def _position_td_rate_trailing(self) -> Dict[Tuple[str, int, int], Dict[str, float]]:
        """Trailing league-wide mean per-game TD rate, keyed by (position, season, week).

        For each TD component (TD_COMPONENTS), the value is the average per-game
        count across every modeled player-week at that position in all weeks
        strictly before the key's (season, week) — the shrinkage target a
        player's own trailing TD rate is pulled toward in ``_baseline_stat_line``.
        Expanding, current-season-with-prior-season-fallback, no future leak;
        mirrors research/model.py::position_td_rate_trailing. Cached.
        """
        if self._position_td_rates is not None:
            return self._position_td_rates

        # (position, season, week) -> {component: [per-game values across players]}
        weekly: Dict[Tuple[str, int, int], Dict[str, List[float]]] = {}
        for r in self._feature_rows():
            key = (r.get("position"), r["season"], r["week"])
            bucket = weekly.setdefault(key, {c: [] for c in TD_COMPONENTS})
            for c in TD_COMPONENTS:
                bucket[c].append(float(r.get(c, 0.0) or 0.0))

        weekly_mean: Dict[Tuple[str, int, int], Dict[str, float]] = {
            key: {c: (sum(vals) / len(vals)) if vals else 0.0 for c, vals in comps.items()}
            for key, comps in weekly.items()
        }

        by_position: Dict[str, List[Tuple[str, int, int]]] = {}
        for k in sorted(weekly_mean, key=lambda k: (str(k[0]), k[1], k[2])):
            by_position.setdefault(k[0], []).append(k)

        trailing: Dict[Tuple[str, int, int], Dict[str, float]] = {}
        for _position, keys in by_position.items():
            for i, k in enumerate(keys):
                _, season, week = k
                prior_current = [weekly_mean[pk] for pk in keys[:i] if pk[1] == season]
                if prior_current:
                    snapshots = prior_current
                else:
                    snapshots = [weekly_mean[pk] for pk in keys[:i] if pk[1] == season - 1]
                if not snapshots:
                    continue
                trailing[k] = {
                    c: sum(s[c] for s in snapshots) / len(snapshots) for c in TD_COMPONENTS
                }

        self._position_td_rates = trailing
        return trailing

    def _baseline_stat_line(
        self, player_rows: List[dict], season: int, week: int,
        window: int = BASELINE_WINDOW,
        position: Optional[str] = None,
    ) -> Optional[Dict[str, float]]:
        """Trailing per-component average, prior-season fallback, with TD shrinkage.

        Uses ONLY rows strictly before (season, week). Current-season prior
        weeks (up to ``window`` of them) are averaged; if there are none, falls
        back to the entire prior season; if that's empty too, returns None so
        the caller excludes the player from this week's slate.

        When ``position`` is supplied, each TD component (TD_COMPONENTS) is
        shrunk toward the trailing league mean for that position:

            shrunk = w * own + (1 - w) * position_mean,  w = n / (n + TD_SHRINK_K)

        where n is the number of games averaged. Yardage is untouched. Omitting
        ``position`` (or having no trailing position rate yet) leaves the TDs
        unshrunk, preserving the original behavior.
        """
        prior = _weeks_before(player_rows, season, week)
        current_season_prior = [r for r in prior if r["season"] == season]

        if current_season_prior:
            recent = current_season_prior[-window:]
        else:
            recent = [r for r in prior if r["season"] == season - 1]
            if not recent:
                return None

        baseline = {
            component: sum(float(r.get(component, 0.0) or 0.0) for r in recent) / len(recent)
            for component in STAT_COMPONENTS
        }

        if position is not None:
            position_mean = self._position_td_rate_trailing().get((position, season, week))
            if position_mean is not None:
                n = len(recent)
                weight = n / (n + TD_SHRINK_K)
                for component in TD_COMPONENTS:
                    prior_mean = position_mean.get(component)
                    if prior_mean is not None:
                        baseline[component] = weight * baseline[component] + (1.0 - weight) * prior_mean

        return baseline

    # -- defense factors ---------------------------------------------------

    def _defense_input_rows(self) -> List[dict]:
        """int_defense_factor_inputs as team-game dicts.

        Normalizes the ``opponent_team`` column name (the mart uses
        ``opponent_team``; research used the same) to what the ridge fit reads.
        """
        rows = self._defense_inputs.to_dicts() if self._defense_inputs is not None else []
        normalized: List[dict] = []
        for r in rows:
            opp = r.get("opponent_team", r.get("opponent"))
            normalized.append({
                "season": r["season"],
                "week": r["week"],
                "team": r["team"],
                "opponent_team": opp,
                "passing_yards": float(r.get("passing_yards", 0.0) or 0.0),
                "rushing_yards": float(r.get("rushing_yards", 0.0) or 0.0),
            })
        return normalized

    def _ridge_defense_effects(
        self, rows: List[dict], y_col: str, weights: Sequence[float],
        teams: Sequence[str], lam: float = RIDGE_LAMBDA,
    ) -> Dict[str, float]:
        """Weighted ridge fit of log(y) ~ 1 + offense + defense.

        Intercept unpenalized; every team effect penalized toward 0 (= league
        average). Returns {defense_team: effect}. Ported verbatim from
        research/defense.py::_ridge_defense_effects.
        """
        idx = {t: i for i, t in enumerate(teams)}
        n_teams = len(teams)
        n, p = len(rows), 1 + 2 * n_teams

        X = np.zeros((n, p))
        y = np.zeros(n)
        w = np.asarray(weights, dtype=float)
        for i, r in enumerate(rows):
            X[i, 0] = 1.0
            X[i, 1 + idx[r["team"]]] = 1.0
            X[i, 1 + n_teams + idx[r["opponent_team"]]] = 1.0
            y[i] = np.log(max(float(r[y_col]), 1.0))

        penalty = np.eye(p) * lam
        penalty[0, 0] = 0.0
        XtW = X.T * w
        beta = np.linalg.solve(XtW @ X + penalty, XtW @ y)
        defense_effects = beta[1 + n_teams:]
        return {t: float(defense_effects[i]) for t, i in idx.items()}

    def _defense_factors(
        self, season: int, week: int,
        lam: float = RIDGE_LAMBDA,
        prior_weight: float = PRIOR_SEASON_WEIGHT,
        clamp: Tuple[float, float] = FACTOR_CLAMP,
    ) -> Dict[FactorKey, float]:
        """Rolling per-(team, season, week, channel) defense factors, no leak.

        For every snapshot (season', week') among the defense inputs, fits a
        per-channel ridge model on all games strictly before it (current season
        at weight 1.0, prior season at ``prior_weight``). Snapshots with fewer
        than MIN_GAMES_TO_FIT prior games are skipped — their callers default
        to 1.0. Factors are clamped to ``clamp``.
        """
        tg = self._defense_input_rows()
        if not tg:
            return {}
        teams = sorted({r["team"] for r in tg} | {r["opponent_team"] for r in tg})
        snapshots = sorted({(r["season"], r["week"]) for r in tg})

        out: Dict[FactorKey, float] = {}
        for snap_season, snap_week in snapshots:
            rows: List[dict] = []
            weights: List[float] = []
            for r in tg:
                if (r["season"], r["week"]) >= (snap_season, snap_week):
                    continue  # strictly-before only
                if r["season"] == snap_season:
                    rows.append(r)
                    weights.append(1.0)
                elif r["season"] == snap_season - 1:
                    rows.append(r)
                    weights.append(prior_weight)
            if len(rows) < MIN_GAMES_TO_FIT:
                continue

            for channel, (y_col, _components) in CHANNELS.items():
                effects = self._ridge_defense_effects(rows, y_col, weights, teams, lam)
                for team, effect in effects.items():
                    out[(team, snap_season, snap_week, channel)] = float(
                        np.clip(np.exp(effect), *clamp)
                    )
        return out

    @staticmethod
    def _factor_for(
        factors: Dict[FactorKey, float], team: str, season: int, week: int, channel: str,
    ) -> float:
        """Defense factor for (team, season, week, channel), carried forward.

        Prefers an exact snapshot match. For an UPCOMING week there is no fitted
        snapshot (snapshots only exist for played weeks), so fall back to the
        most recent snapshot at or before (season, week) for this team+channel —
        a defense's latest estimated strength is the best read on next week.
        Defaults to 1.0 (league average) when the team has no fitted snapshot at
        all (e.g. too early in the season to fit).
        """
        exact = factors.get((team, season, week, channel))
        if exact is not None:
            return exact

        # Most recent fitted snapshot at or before the target week.
        best_key = None
        for (t, s, w, c) in factors:
            if t != team or c != channel:
                continue
            if (s, w) <= (season, week) and (best_key is None or (s, w) > best_key):
                best_key = (s, w)
        if best_key is not None:
            return factors[(team, best_key[0], best_key[1], channel)]
        return 1.0

    # -- expected line -----------------------------------------------------

    def _environment_multiplier(
        self, team: str, season: int, week: int,
        implied_team_total: Optional[float],
        env_trailing: Dict[Tuple[str, int, int], Optional[float]],
    ) -> float:
        """1 + V2_ENVIRONMENT_WEIGHT * clamp((implied - trailing)/SCALE, -1, 1)."""
        baseline_env = env_trailing.get((team, season, week))
        if baseline_env is None or implied_team_total is None:
            return 1.0
        delta_env = _clip(
            (implied_team_total - baseline_env) / ENVIRONMENT_SCALE, -1.0, 1.0
        )
        return 1.0 + V2_ENVIRONMENT_WEIGHT * delta_env

    def _expected_line_v2(
        self, baseline: Dict[str, float],
        pass_factor: float, rush_factor: float, env_mult: float,
    ) -> Dict[str, float]:
        """expected_c = baseline_c * channel_factor(c) * env_mult.

        Pass-channel components get pass_factor, rush-channel get rush_factor,
        fumbles_lost gets neither (factor 1.0). Ported from
        research/model.py::expected_line_v2.
        """
        factors = {"pass": pass_factor, "rush": rush_factor}
        return {
            component: value
            * factors.get(COMPONENT_CHANNEL.get(component, ""), 1.0)
            * env_mult
            for component, value in baseline.items()
        }

    # -- public projection -------------------------------------------------

    def project_week(
        self, season: int, week: int, scoring_settings: Dict[str, float],
    ) -> List[Projection]:
        """Project every modeled player's stat line + points for (season, week).

        Precondition: load_marts(season) has been called; ``scoring_settings``
        is keyed by STAT_COMPONENTS (e.g. ``research.scoring.get_scoring_settings``).
        Postcondition: each Projection.expected_stat_line has all 9 components;
        projected_points = sum(component * scoring_settings[component]); baseline
        and defense factors use only rows strictly before (season, week).
        """
        self._ensure_loaded()

        player_index = self._index_by_player()
        env_trailing = self._team_environment_trailing()
        defense_factors = self._defense_factors(season, week)

        projections: List[Projection] = []
        for player_id, rows in player_index.items():
            # Resolve position first (every row for a player carries the same
            # position) so the baseline can apply TD shrinkage toward the
            # trailing position mean. Prefer the target-week row, else the most
            # recent known row.
            target = next(
                (r for r in rows if r["season"] == season and r["week"] == week), None
            )
            position = (target or rows[-1]).get("position")

            baseline = self._baseline_stat_line(rows, season, week, position=position)
            if baseline is None:
                continue  # no usable history -> exclude from slate

            # Pregame-known context for the target week: team, opponent, implied
            # total. These are knowable before kickoff (roster + market lines).
            schedule_ctx = self._schedule_context()
            if target is not None:
                team = target.get("team")
                opponent = target.get("opponent_team")
                implied = _implied_team_total(target)
                player_name = target.get("player_display_name") or player_id
                position = target.get("position")
                # Fill any gaps from the schedule (e.g. a played-week row that
                # happens to be missing opponent/implied) without overriding
                # values the feature mart already provides.
                sched = schedule_ctx.get((team, season, week), {})
                if opponent is None:
                    opponent = sched.get("opponent")
                if implied is None:
                    implied = sched.get("implied_team_total")
            else:
                # Player has no row for the target week (bye / not yet played).
                # Fall back to most-recent known team, then source the opponent
                # and Vegas-implied total from the schedule so the matchup and
                # environment factors fire for upcoming weeks.
                prior = _weeks_before(rows, season, week)
                last = prior[-1] if prior else rows[-1]
                team = last.get("team")
                sched = schedule_ctx.get((team, season, week), {})
                opponent = sched.get("opponent")
                implied = sched.get("implied_team_total")
                player_name = last.get("player_display_name") or player_id
                position = last.get("position")

            if opponent is None:
                pass_factor = rush_factor = 1.0
            else:
                pass_factor = self._factor_for(defense_factors, opponent, season, week, "pass")
                rush_factor = self._factor_for(defense_factors, opponent, season, week, "rush")

            env_mult = self._environment_multiplier(
                team, season, week, implied, env_trailing
            )
            expected = self._expected_line_v2(baseline, pass_factor, rush_factor, env_mult)
            projected_points = sum(
                expected.get(c, 0.0) * scoring_settings.get(c, 0.0)
                for c in STAT_COMPONENTS
            )

            # The pieces of that number, for explanation only (not used above).
            def _scored(line: Dict[str, float]) -> float:
                return sum(
                    line.get(c, 0.0) * scoring_settings.get(c, 0.0) for c in STAT_COMPONENTS
                )

            projections.append(Projection(
                player_id=str(player_id),
                player_name=player_name,
                position=position,
                team=team,
                opponent=opponent,
                expected_stat_line=expected,
                projected_points=projected_points,
                pass_factor=pass_factor,
                rush_factor=rush_factor,
                baseline=baseline,
                env_multiplier=env_mult,
                implied_team_total=implied,
                trailing_implied_total=env_trailing.get((team, season, week)),
                baseline_points=_scored(baseline),
                defense_adjusted_points=_scored(
                    self._expected_line_v2(baseline, pass_factor, rush_factor, 1.0)
                ),
                component_points={
                    c: expected.get(c, 0.0) * scoring_settings.get(c, 0.0)
                    for c in STAT_COMPONENTS
                },
            ))

        projections.sort(key=lambda p: p.projected_points, reverse=True)
        return projections

    # -- output ------------------------------------------------------------

    def write_output(
        self, projections: List[Projection], season: int, week: int, scoring_format: str,
    ) -> None:
        """Write projection parquet via projections_store.write_projections.

        Serializes each Projection to a flat row: identity columns, the nested
        stat line (expanded to columns for portability), projected points and
        the two channel factors.
        """
        if write_projections is None:
            raise RuntimeError(
                "projections_store.write_projections is unavailable; cannot write output. "
                "Ensure src/data_sources/projections_store.py (task 5.1) is present."
            )
        if pl is None:
            raise RuntimeError("polars is required to write projection output.")

        records = []
        for p in projections:
            record = {
                "player_id": p.player_id,
                "player_name": p.player_name,
                "position": p.position,
                "team": p.team,
                "opponent": p.opponent,
                "projected_points": p.projected_points,
                "pass_factor": p.pass_factor,
                "rush_factor": p.rush_factor,
                "env_multiplier": p.env_multiplier,
                "implied_team_total": p.implied_team_total,
                "trailing_implied_total": p.trailing_implied_total,
                "baseline_points": p.baseline_points,
                "defense_adjusted_points": p.defense_adjusted_points,
            }
            for c in STAT_COMPONENTS:
                record[f"expected_{c}"] = p.expected_stat_line.get(c, 0.0)
                record[f"baseline_{c}"] = p.baseline.get(c, 0.0)
                record[f"points_{c}"] = p.component_points.get(c, 0.0)
            records.append(record)

        # Scan every row to infer types: the optional columns above are null for
        # some players, and polars' default 100-row sample could mistype them.
        df = pl.DataFrame(records, infer_schema_length=None)
        write_projections(df, season, week, scoring_format)
