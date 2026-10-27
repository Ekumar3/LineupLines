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

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

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

MODELED_POSITIONS = ("QB", "RB", "WR", "TE")

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
                prior_current = [
                    t for (s, _w, t) in entries[:i] if s == season and t is not None
                ]
                if prior_current:
                    vals = prior_current
                else:
                    vals = [
                        t for (s, _w, t) in entries[:i]
                        if s == season - 1 and t is not None
                    ] or None
                trailing[(team, season, week)] = (
                    sum(vals) / len(vals) if vals else None
                )
        self._team_env_trailing = trailing
        return trailing

    # -- baseline ----------------------------------------------------------

    def _baseline_stat_line(
        self, player_rows: List[dict], season: int, week: int,
        window: int = BASELINE_WINDOW,
    ) -> Optional[Dict[str, float]]:
        """Trailing per-component average, prior-season fallback.

        Uses ONLY rows strictly before (season, week). Current-season prior
        weeks (up to ``window`` of them) are averaged; if there are none, falls
        back to the entire prior season; if that's empty too, returns None so
        the caller excludes the player from this week's slate.
        """
        prior = _weeks_before(player_rows, season, week)
        current_season_prior = [r for r in prior if r["season"] == season]

        if current_season_prior:
            recent = current_season_prior[-window:]
        else:
            recent = [r for r in prior if r["season"] == season - 1]
            if not recent:
                return None

        return {
            component: sum(float(r.get(component, 0.0) or 0.0) for r in recent) / len(recent)
            for component in STAT_COMPONENTS
        }

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
        """Lookup with the league-average (1.0) default for unknown/early keys."""
        return factors.get((team, season, week, channel), 1.0)

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
            baseline = self._baseline_stat_line(rows, season, week)
            if baseline is None:
                continue  # no usable history -> exclude from slate

            # Pregame-known context for the target week: team, opponent, implied
            # total. These are knowable before kickoff (roster + market lines).
            target = next(
                (r for r in rows if r["season"] == season and r["week"] == week), None
            )
            if target is not None:
                team = target.get("team")
                opponent = target.get("opponent_team")
                implied = _implied_team_total(target)
                player_name = target.get("player_display_name") or player_id
                position = target.get("position")
            else:
                # Player has no row for the target week (bye / not yet played).
                # Fall back to most-recent known team for defense lookups.
                prior = _weeks_before(rows, season, week)
                last = prior[-1] if prior else rows[-1]
                team = last.get("team")
                opponent = None
                implied = None
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
            }
            for c in STAT_COMPONENTS:
                record[f"expected_{c}"] = p.expected_stat_line.get(c, 0.0)
                record[f"baseline_{c}"] = p.baseline.get(c, 0.0)
            records.append(record)

        df = pl.DataFrame(records)
        write_projections(df, season, week, scoring_format)
