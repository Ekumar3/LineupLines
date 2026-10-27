"""Property-based tests for ``src.services.projection_service.ProjectionService``.

Validates the backtest-critical invariants of the production projection
pipeline with Hypothesis-generated inputs:

- Property 1 / 19 — No future leak (projections + defense factors)
- Property 7     — Defense factor bounds (every factor in FACTOR_CLAMP)
- Property 30    — Prior-season weighting (prior season contributes at 0.3)
- Property 29    — Baseline window (trailing BASELINE_WINDOW, prior fallback)
- Property 18    — Scoring correctness (points == dot(stat line, scoring))

Marts are injected directly as polars DataFrames (``mart_player_week_features``
and ``int_defense_factor_inputs`` shaped) so the tests never touch
``projections_store`` / disk. The service's derived caches are left ``None`` so
they recompute from the injected frames.

Performance note: the ridge-fit properties (7, 30) are the slow path — a
weighted least-squares solve runs per snapshot per channel. Those are capped at
40 Hypothesis examples via ``@settings(max_examples=...)``; the pure
arithmetic/selection properties (1/19, 29, 18) run at 200 examples.
"""

import math

import numpy as np
import polars as pl
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.services.projection_service import (
    BASELINE_WINDOW,
    FACTOR_CLAMP,
    MIN_GAMES_TO_FIT,
    PRIOR_SEASON_WEIGHT,
    STAT_COMPONENTS,
    ProjectionService,
)

# ---------------------------------------------------------------------------
# Helpers for building mart-shaped polars frames
# ---------------------------------------------------------------------------

MODELED = ("QB", "RB", "WR", "TE")


def _feature_row(season, week, player_id, position, team, opponent, stats=None,
                 implied_team_total=None, name=None):
    """One ``mart_player_week_features``-shaped record."""
    row = {c: 0.0 for c in STAT_COMPONENTS}
    if stats:
        row.update(stats)
    row.update({
        "season": int(season),
        "week": int(week),
        "player_id": str(player_id),
        "player_display_name": name or str(player_id),
        "position": position,
        "team": team,
        "opponent_team": opponent,
        "implied_team_total": implied_team_total,
    })
    return row


def _features_df(rows):
    return pl.DataFrame(rows)


def _service_with(features_rows, defense_rows=None):
    """Build a ProjectionService with marts injected directly (no disk I/O)."""
    svc = ProjectionService()
    svc._features = _features_df(features_rows)
    svc._defense_inputs = (
        pl.DataFrame(defense_rows) if defense_rows is not None else pl.DataFrame([])
    )
    svc._loaded_season = None
    svc._player_index = None
    svc._team_env_trailing = None
    return svc


# ===========================================================================
# Property 1 / 19 — No future leak
# ===========================================================================

# A single player's history: trailing weeks in one season. We project a target
# week and then mutate/add rows strictly after it at (season', week') >
# (season, week); the projection for the target week must be byte-for-byte
# identical. (The target-week row itself holds pregame-known inputs — team,
# opponent, implied total — and is deliberately left unmutated.)

@st.composite
def _leak_scenario(draw):
    season = draw(st.integers(min_value=2021, max_value=2026))
    n_weeks = draw(st.integers(min_value=4, max_value=10))
    target_week = draw(st.integers(min_value=2, max_value=n_weeks - 1))

    def stat_line():
        return {c: draw(st.floats(min_value=0.0, max_value=400.0,
                                  allow_nan=False, allow_infinity=False))
                for c in STAT_COMPONENTS}

    rows = []
    for wk in range(1, n_weeks + 1):
        rows.append(_feature_row(
            season, wk, "p1", "WR", "AAA", "ZZZ",
            stats=stat_line(),
            implied_team_total=draw(st.floats(min_value=14.0, max_value=35.0,
                                              allow_nan=False, allow_infinity=False)),
        ))
    return season, target_week, rows


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(scenario=_leak_scenario(), seed=st.integers(min_value=0, max_value=2**31))
def test_projection_invariant_to_future_rows(scenario, seed):
    """Property 1/19: altering rows strictly after the target week never
    changes the target-week projection.

    **Validates: Requirements 1.12, 4.11, 4.7**
    """
    season, target_week, rows = scenario
    scoring = {c: 1.0 for c in STAT_COMPONENTS}

    svc = _service_with(rows)
    before = svc.project_week(season, target_week, scoring)
    assert before, "expected at least one projection"
    before_pts = {p.player_id: p.projected_points for p in before}
    before_line = {p.player_id: dict(p.expected_stat_line) for p in before}

    # Mutate every row STRICTLY AFTER the target week and add new future rows
    # with extreme values. None of this may leak. (The target-week row itself is
    # a pregame-known input — team, opponent, implied total — so it is left
    # untouched; only strictly-future rows are future leaks.)
    rng = np.random.default_rng(seed)
    mutated = []
    for r in rows:
        if (r["season"], r["week"]) > (season, target_week):
            r = dict(r)
            for c in STAT_COMPONENTS:
                r[c] = float(rng.uniform(0, 9999))
            r["implied_team_total"] = float(rng.uniform(0, 80))
        mutated.append(r)
    # Add brand-new future weeks and a future season.
    mutated.append(_feature_row(season, target_week + 50, "p1", "WR", "AAA", "ZZZ",
                                stats={c: 5000.0 for c in STAT_COMPONENTS},
                                implied_team_total=99.0))
    mutated.append(_feature_row(season + 1, 1, "p1", "WR", "AAA", "ZZZ",
                                stats={c: 5000.0 for c in STAT_COMPONENTS},
                                implied_team_total=99.0))

    svc2 = _service_with(mutated)
    after = svc2.project_week(season, target_week, scoring)
    after_pts = {p.player_id: p.projected_points for p in after}
    after_line = {p.player_id: dict(p.expected_stat_line) for p in after}

    assert after_pts.keys() >= before_pts.keys()
    for pid, pts in before_pts.items():
        assert after_pts[pid] == pytest.approx(pts, rel=1e-12, abs=1e-12)
        for c in STAT_COMPONENTS:
            assert after_line[pid][c] == pytest.approx(before_line[pid][c],
                                                        rel=1e-12, abs=1e-12)


# ===========================================================================
# Property 7 — Defense factor bounds
# ===========================================================================

TEAMS = [f"T{i:02d}" for i in range(8)]


@st.composite
def _defense_inputs(draw):
    """A defense-input matrix: enough team-games to clear MIN_GAMES_TO_FIT at
    the final snapshot, with arbitrary (bounded) yardage."""
    season = draw(st.integers(min_value=2022, max_value=2026))
    n_weeks = draw(st.integers(min_value=6, max_value=12))
    rows = []
    n = len(TEAMS)
    for wk in range(1, n_weeks + 1):
        # rotate pairings so each team faces a mix of opponents
        order = TEAMS[:1] + TEAMS[1:][wk % (n - 1):] + TEAMS[1:][: wk % (n - 1)]
        for i in range(n // 2):
            a, b = order[i], order[n - 1 - i]
            for off, d in ((a, b), (b, a)):
                rows.append({
                    "season": season,
                    "week": wk,
                    "team": off,
                    "opponent_team": d,
                    "passing_yards": draw(st.floats(min_value=0.0, max_value=600.0,
                                                    allow_nan=False, allow_infinity=False)),
                    "rushing_yards": draw(st.floats(min_value=0.0, max_value=400.0,
                                                    allow_nan=False, allow_infinity=False)),
                })
    return rows


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(defense_rows=_defense_inputs())
def test_defense_factors_within_clamp(defense_rows):
    """Property 7: every fitted factor lies within FACTOR_CLAMP = [0.75, 1.25].

    **Validates: Requirements 10.2, 10.3, 10.5, 10.11**
    """
    svc = _service_with([], defense_rows)
    # season/week args don't restrict the fit — _defense_factors fits every
    # snapshot. Use a late snapshot so the slow fits run on real data.
    factors = svc._defense_factors(9999, 1)
    lo, hi = FACTOR_CLAMP
    assert factors, "expected at least one fitted factor"
    for key, value in factors.items():
        assert lo <= value <= hi, f"factor {value} for {key} outside {FACTOR_CLAMP}"


# ===========================================================================
# Property 30 — Prior-season weighting (weight 0.3)
# ===========================================================================

def _constant_channel_rows(season, weeks, pass_mult_for_sieve, sieve="T00"):
    """Round-robin season where ``sieve`` concedes pass_mult x the pass yards."""
    rows = []
    n = len(TEAMS)
    for wk in range(1, weeks + 1):
        order = TEAMS[:1] + TEAMS[1:][wk % (n - 1):] + TEAMS[1:][: wk % (n - 1)]
        for i in range(n // 2):
            a, b = order[i], order[n - 1 - i]
            for off, d in ((a, b), (b, a)):
                mult = pass_mult_for_sieve if d == sieve else 1.0
                rows.append({
                    "season": season, "week": wk, "team": off, "opponent_team": d,
                    "passing_yards": 220.0 * mult, "rushing_yards": 110.0,
                })
    return rows


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(mult=st.floats(min_value=1.3, max_value=2.0,
                      allow_nan=False, allow_infinity=False),
       prior_weeks=st.integers(min_value=6, max_value=14))
def test_prior_season_contributes_at_reduced_weight(mult, prior_weeks):
    """Property 30: a prior-season-only fit shifts less than the identical
    evidence seen in the current season, because the prior season is weighted
    at PRIOR_SEASON_WEIGHT (0.3) < 1.0.

    We fit the same sieve signal twice:
      A) evidence lives entirely in the PRIOR season (weight 0.3)
      B) identical evidence lives in the CURRENT season (weight 1.0)
    and assert the current-season factor is strictly more extreme.

    **Validates: Requirements 4.9**
    """
    assert PRIOR_SEASON_WEIGHT < 1.0  # guard: the premise of this property

    # A: prior-season evidence only; target week 1 of the new season.
    prior_rows = _constant_channel_rows(2024, prior_weeks, mult)
    # one neutral current-season week so snapshot (2025, 1) exists and is fit
    prior_rows += _constant_channel_rows(2025, 1, pass_mult_for_sieve=1.0)
    svc_prior = _service_with([], prior_rows)
    factors_prior = svc_prior._defense_factors(9999, 1)
    prior_factor = factors_prior.get(("T00", 2025, 1, "pass"))

    # B: same volume of evidence, but in the current season (weight 1.0). Fit
    # the snapshot immediately after those weeks.
    cur_rows = _constant_channel_rows(2025, prior_weeks + 1, mult)
    svc_cur = _service_with([], cur_rows)
    factors_cur = svc_cur._defense_factors(9999, 1)
    cur_factor = factors_cur.get(("T00", 2025, prior_weeks + 1, "pass"))

    # Both snapshots must have cleared MIN_GAMES_TO_FIT to be comparable.
    if prior_factor is None or cur_factor is None:
        pytest.skip("not enough games to fit one of the snapshots")

    lo, hi = FACTOR_CLAMP
    # The sieve pushes the factor above 1.0. Downweighted prior evidence must
    # move it less than full-weight current evidence — unless the current fit
    # is already pinned at the clamp ceiling (saturation hides the ordering).
    if cur_factor >= hi - 1e-9:
        assert prior_factor <= cur_factor + 1e-9
    else:
        assert prior_factor < cur_factor, (
            f"prior-weighted factor {prior_factor} should be less extreme "
            f"than current-weighted {cur_factor}"
        )


# ===========================================================================
# Property 29 — Baseline calculation window
# ===========================================================================

@st.composite
def _baseline_scenario(draw):
    """Player history with a known target and extreme target/future values."""
    season = draw(st.integers(min_value=2021, max_value=2026))
    # number of current-season weeks strictly before the target
    n_prior_current = draw(st.integers(min_value=0, max_value=6))
    has_prior_season = draw(st.booleans())
    n_prior_season = draw(st.integers(min_value=1, max_value=5)) if has_prior_season else 0

    target_week = n_prior_current + 2  # leave room for exactly n_prior_current before it

    rows = []
    # prior-season weeks
    for wk in range(1, n_prior_season + 1):
        rows.append(_feature_row(
            season - 1, wk, "p1", "RB", "AAA", "ZZZ",
            stats={"rushing_yards": draw(st.floats(min_value=0.0, max_value=200.0,
                                                   allow_nan=False, allow_infinity=False))},
        ))
    # current-season weeks strictly before target (weeks 1..n_prior_current)
    cur_vals = []
    for wk in range(1, n_prior_current + 1):
        v = draw(st.floats(min_value=0.0, max_value=200.0,
                           allow_nan=False, allow_infinity=False))
        cur_vals.append(v)
        rows.append(_feature_row(season, wk, "p1", "RB", "AAA", "ZZZ",
                                 stats={"rushing_yards": v}))
    # the target week + a future week, both with huge values that must not leak
    rows.append(_feature_row(season, target_week, "p1", "RB", "AAA", "ZZZ",
                             stats={"rushing_yards": 99999.0}))
    rows.append(_feature_row(season, target_week + 1, "p1", "RB", "AAA", "ZZZ",
                             stats={"rushing_yards": 99999.0}))

    prior_vals = [r["rushing_yards"] for r in rows
                  if r["season"] == season - 1]
    return season, target_week, rows, cur_vals, prior_vals


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(scenario=_baseline_scenario())
def test_baseline_window_and_fallback(scenario):
    """Property 29: baseline is the mean of at most the trailing BASELINE_WINDOW
    current-season weeks strictly before target, else the whole prior season,
    else None — and never includes the target or future weeks.

    **Validates: Requirements 4.3**
    """
    season, target_week, rows, cur_vals, prior_vals = scenario
    svc = _service_with(rows)
    player_rows = svc._index_by_player()["p1"]

    baseline = svc._baseline_stat_line(player_rows, season, target_week)

    if cur_vals:
        expected = sum(cur_vals[-BASELINE_WINDOW:]) / len(cur_vals[-BASELINE_WINDOW:])
        assert baseline is not None
        assert baseline["rushing_yards"] == pytest.approx(expected, rel=1e-9, abs=1e-9)
        # window never exceeds BASELINE_WINDOW rows
        assert len(cur_vals[-BASELINE_WINDOW:]) <= BASELINE_WINDOW
    elif prior_vals:
        expected = sum(prior_vals) / len(prior_vals)
        assert baseline is not None
        assert baseline["rushing_yards"] == pytest.approx(expected, rel=1e-9, abs=1e-9)
    else:
        assert baseline is None

    # The leak guard: the extreme target/future value (99999) can never appear.
    if baseline is not None:
        assert baseline["rushing_yards"] < 99999.0


# ===========================================================================
# Property 18 — Scoring correctness
# ===========================================================================

@st.composite
def _scoring_scenario(draw):
    baseline = {c: draw(st.floats(min_value=0.0, max_value=500.0,
                                  allow_nan=False, allow_infinity=False))
                for c in STAT_COMPONENTS}
    scoring = {c: draw(st.floats(min_value=-10.0, max_value=10.0,
                                 allow_nan=False, allow_infinity=False))
               for c in STAT_COMPONENTS}
    return baseline, scoring


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(scenario=_scoring_scenario())
def test_scoring_is_dot_product_of_line_and_settings(scenario):
    """Property 18: projected_points == sum(expected_line[c] * scoring[c]) over
    all 9 components, for arbitrary non-negative baselines and arbitrary
    scoring settings.

    Build a single-player slate whose only usable history is the baseline (as a
    trailing current-season week), project the next week with no defense/env
    signal (opponent unknown, no implied total -> factors/env = 1.0) so
    expected_line == baseline, then assert the dot product.

    **Validates: Requirements 4.6**
    """
    baseline, scoring = scenario
    season, target_week = 2025, 2

    # One prior week carrying the baseline values; target week has no opponent
    # and no implied total so pass/rush factors and env multiplier are all 1.0.
    rows = [
        _feature_row(season, 1, "p1", "WR", "AAA", "ZZZ", stats=baseline,
                     implied_team_total=None),
        _feature_row(season, target_week, "p1", "WR", "AAA", None,
                     stats={c: 0.0 for c in STAT_COMPONENTS},
                     implied_team_total=None),
    ]
    svc = _service_with(rows)
    projections = svc.project_week(season, target_week, scoring)
    assert projections, "expected a projection"
    proj = projections[0]

    # With all factors == 1.0 the expected line equals the baseline.
    for c in STAT_COMPONENTS:
        assert proj.expected_stat_line[c] == pytest.approx(baseline[c], rel=1e-9, abs=1e-9)

    expected_points = sum(proj.expected_stat_line[c] * scoring[c] for c in STAT_COMPONENTS)
    assert proj.projected_points == pytest.approx(expected_points, rel=1e-9, abs=1e-9)
    assert not math.isnan(proj.projected_points)
