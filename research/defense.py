"""Opponent-adjusted defense model: per-channel multiplicative factors.

Raw "points allowed to position" is mostly noise — it isn't adjusted for who
the defense played, it collapses pass and rush into one number, and it's
dominated by TD variance. This module replaces it.

For each stat channel (pass, rush) we fit a ridge fixed-effects model on
team-game yardage in log space:

    log(yards[g]) = mu + off[offense_team] + def[defense_team] + eps

so every team-game is explained by the offense's strength AND the defense's
strength jointly — the defense effect is opponent-adjusted by construction.
Ridge shrinks every effect toward 0 (= league average), which is the prior
we want early in the season; with one-hot effects, a team's shrinkage is
roughly n_games / (n_games + RIDGE_LAMBDA).

    factor[d, channel] = exp(def[d])     1.0 = league average
                                         >1.0 = this defense allows MORE

Rolling, no-leak: factors for (season, week) are refit using only games
strictly before that week. The prior season's games are included at
PRIOR_SEASON_WEIGHT so week 1 has a (regressed) prior rather than nothing —
defensive strength carries over year-to-year only weakly, so that weight is
deliberately small.
"""

from typing import Dict, List, Sequence, Tuple

import numpy as np
import polars as pl

from research.scoring import STAT_COMPONENTS

# channel -> (team-game yardage column the effect is fit on,
#             stat-line components that channel's factor is applied to)
CHANNELS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "pass": (
        "passing_yards",
        ("passing_yards", "passing_tds", "interceptions", "receptions", "receiving_yards", "receiving_tds"),
    ),
    "rush": (
        "rushing_yards",
        ("rushing_yards", "rushing_tds"),
    ),
}
# fumbles_lost belongs to no channel -> factor 1.0
COMPONENT_CHANNEL: Dict[str, str] = {
    component: channel for channel, (_, components) in CHANNELS.items() for component in components
}
assert set(COMPONENT_CHANNEL) | {"fumbles_lost"} == set(STAT_COMPONENTS)

RIDGE_LAMBDA = 4.0          # shrinkage: half-shrunk after ~4 games
PRIOR_SEASON_WEIGHT = 0.3   # how much a prior-season game counts vs. a current-season game
FACTOR_CLAMP = (0.75, 1.25)  # safety rail on exp(effect); ridge should keep us well inside
MIN_GAMES_TO_FIT = 32       # below this, factors default to 1.0

FactorKey = Tuple[str, int, int, str]  # (defense_team, season, week, channel)


def team_games(feature_table: pl.DataFrame) -> pl.DataFrame:
    """One row per (season, week, team, opponent_team) with the team's offensive yardage."""
    return (
        feature_table.group_by(["season", "week", "team", "opponent_team"])
        .agg(pl.col("passing_yards").sum(), pl.col("rushing_yards").sum())
        .sort(["season", "week", "team"])
    )


def _ridge_defense_effects(
    rows: List[dict],
    y_col: str,
    weights: Sequence[float],
    teams: Sequence[str],
    lam: float = RIDGE_LAMBDA,
) -> Dict[str, float]:
    """Weighted ridge fit of log(y) ~ 1 + offense + defense; returns {defense_team: effect}.

    Intercept is unpenalized; every team effect is penalized toward 0. The
    two one-hot blocks are only identified up to a constant without the
    penalty — the ridge term is what pins them to "0 = league average."
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


def defense_factors(
    feature_table: pl.DataFrame,
    lam: float = RIDGE_LAMBDA,
    prior_weight: float = PRIOR_SEASON_WEIGHT,
    clamp: Tuple[float, float] = FACTOR_CLAMP,
) -> Dict[FactorKey, float]:
    """Rolling per-(team, season, week, channel) defense factors, no future leak.

    Keys exist for every team at every (season, week) that has at least one
    played game before it (and MIN_GAMES_TO_FIT prior games available).
    Missing keys mean "no information" — callers should default to 1.0.
    """
    tg = team_games(feature_table).to_dicts()
    teams = sorted({r["team"] for r in tg} | {r["opponent_team"] for r in tg})
    snapshots = sorted({(r["season"], r["week"]) for r in tg})

    out: Dict[FactorKey, float] = {}
    for season, week in snapshots:
        rows: List[dict] = []
        weights: List[float] = []
        for r in tg:
            if (r["season"], r["week"]) >= (season, week):
                continue  # strictly-before only
            if r["season"] == season:
                rows.append(r)
                weights.append(1.0)
            elif r["season"] == season - 1:
                rows.append(r)
                weights.append(prior_weight)
        if len(rows) < MIN_GAMES_TO_FIT:
            continue

        for channel, (y_col, _components) in CHANNELS.items():
            effects = _ridge_defense_effects(rows, y_col, weights, teams, lam)
            for team, effect in effects.items():
                out[(team, season, week, channel)] = float(np.clip(np.exp(effect), *clamp))
    return out


def factor_for(factors: Dict[FactorKey, float], team: str, season: int, week: int, channel: str) -> float:
    """Lookup with the league-average (1.0) default for unknown/early keys."""
    return factors.get((team, season, week, channel), 1.0)
