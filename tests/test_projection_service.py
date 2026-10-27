"""Example-based unit tests for ``src.services.projection_service``.

These complement the Hypothesis property tests in
``tests/property_tests/test_projection_service_properties.py`` (no future leak,
factor bounds, prior-season weighting, baseline window, scoring correctness)
with focused, concrete fixtures that pin down exact numeric behavior:

- ``_baseline_stat_line``   — trailing-window mean, prior-season fallback, None
- ``_defense_factors``      — clamp bounds, direction, MIN_GAMES_TO_FIT gate
- ``project_week``          — hand-computed scoring dot product, 9-component line

Marts are injected directly as polars DataFrames (mirroring the property-test
``_service_with`` helper) so nothing touches ``projections_store`` or disk.
"""

import polars as pl
import pytest

from src.services.projection_service import (
    BASELINE_WINDOW,
    FACTOR_CLAMP,
    MIN_GAMES_TO_FIT,
    STAT_COMPONENTS,
    ProjectionService,
)


# ---------------------------------------------------------------------------
# Fixtures / builders (mirror the property-test helpers, kept local)
# ---------------------------------------------------------------------------

def _feature_row(season, week, player_id, position, team, opponent, stats=None,
                 implied_team_total=None, name=None):
    """One ``mart_player_week_features``-shaped record with zeroed stat line."""
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


def _service_with(features_rows, defense_rows=None):
    """Build a ProjectionService with marts injected directly (no disk I/O)."""
    svc = ProjectionService()
    svc._features = pl.DataFrame(features_rows) if features_rows else pl.DataFrame([])
    svc._defense_inputs = (
        pl.DataFrame(defense_rows) if defense_rows is not None else pl.DataFrame([])
    )
    svc._loaded_season = None
    svc._player_index = None
    svc._team_env_trailing = None
    return svc


# ===========================================================================
# 1. Baseline calculation
# ===========================================================================

class TestBaselineStatLine:
    """Concrete checks on ``_baseline_stat_line`` (Requirement 4.3)."""

    def test_trailing_window_is_mean_of_last_three_current_weeks(self):
        """With >BASELINE_WINDOW current-season weeks before the target, the
        baseline averages only the trailing BASELINE_WINDOW of them."""
        assert BASELINE_WINDOW == 3  # guard: fixtures below assume a 3-week window
        rows = [
            _feature_row(2025, 1, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 10.0, "rushing_tds": 0.0}),
            _feature_row(2025, 2, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 40.0, "rushing_tds": 1.0}),
            _feature_row(2025, 3, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 70.0, "rushing_tds": 0.0}),
            _feature_row(2025, 4, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 100.0, "rushing_tds": 2.0}),
            # target week — must be excluded
            _feature_row(2025, 5, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 9999.0}),
        ]
        svc = _service_with(rows)
        player_rows = svc._index_by_player()["p1"]

        baseline = svc._baseline_stat_line(player_rows, 2025, 5)

        assert baseline is not None
        # trailing 3 current-season weeks are weeks 2, 3, 4 (not week 1, not target)
        assert baseline["rushing_yards"] == pytest.approx((40.0 + 70.0 + 100.0) / 3)
        assert baseline["rushing_tds"] == pytest.approx((1.0 + 0.0 + 2.0) / 3)
        # zeroed components stay zero; all 9 present
        assert set(baseline) == set(STAT_COMPONENTS)
        assert baseline["passing_yards"] == pytest.approx(0.0)

    def test_fewer_than_window_weeks_averages_all_available(self):
        """With fewer than BASELINE_WINDOW current weeks, all are averaged."""
        rows = [
            _feature_row(2025, 1, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 20.0}),
            _feature_row(2025, 2, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 60.0}),
            _feature_row(2025, 3, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 9999.0}),  # target
        ]
        svc = _service_with(rows)
        player_rows = svc._index_by_player()["p1"]

        baseline = svc._baseline_stat_line(player_rows, 2025, 3)

        assert baseline is not None
        assert baseline["rushing_yards"] == pytest.approx((20.0 + 60.0) / 2)

    def test_prior_season_fallback_when_no_current_weeks(self):
        """With no current-season prior weeks, fall back to the whole prior
        season (not just the trailing window)."""
        rows = [
            _feature_row(2024, 15, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 30.0}),
            _feature_row(2024, 16, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 50.0}),
            _feature_row(2024, 17, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 70.0}),
            _feature_row(2024, 18, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 90.0}),
            # current-season target week 1 — no prior current weeks exist
            _feature_row(2025, 1, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 9999.0}),
        ]
        svc = _service_with(rows)
        player_rows = svc._index_by_player()["p1"]

        baseline = svc._baseline_stat_line(player_rows, 2025, 1)

        assert baseline is not None
        # all four prior-season weeks averaged (fallback ignores the window)
        assert baseline["rushing_yards"] == pytest.approx((30.0 + 50.0 + 70.0 + 90.0) / 4)

    def test_no_history_returns_none(self):
        """No rows strictly before the target → no usable baseline → None."""
        rows = [
            _feature_row(2025, 1, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 9999.0}),  # the target week itself
            _feature_row(2025, 2, "p1", "RB", "AAA", "ZZZ",
                         stats={"rushing_yards": 9999.0}),  # future
        ]
        svc = _service_with(rows)
        player_rows = svc._index_by_player()["p1"]

        assert svc._baseline_stat_line(player_rows, 2025, 1) is None


# ===========================================================================
# 2. Defense factor computation
# ===========================================================================

# A compact 6-team round-robin league. Three games per week => 6 team-game rows
# per week, so 6 full weeks (36 rows) clear MIN_GAMES_TO_FIT (32) at the
# snapshot that follows them.
_DEF_TEAMS = ["T0", "T1", "T2", "T3", "T4", "T5"]


def _round_robin_week(season, week, pass_yards_fn, rush_yards_fn=None):
    """Build the 12 team-game rows for one week of a 6-team round robin.

    ``pass_yards_fn(offense, defense)`` returns the passing yards the offense
    gained vs that defense; ``rush_yards_fn`` likewise (defaults to a flat 100).
    """
    if rush_yards_fn is None:
        rush_yards_fn = lambda off, d: 100.0
    # fixed pairings that rotate so every defense faces a spread of offenses
    order = _DEF_TEAMS[:1] + _DEF_TEAMS[1:][week % 5:] + _DEF_TEAMS[1:][: week % 5]
    rows = []
    for i in range(len(order) // 2):
        a, b = order[i], order[len(order) - 1 - i]
        for off, d in ((a, b), (b, a)):
            rows.append({
                "season": season,
                "week": week,
                "team": off,
                "opponent_team": d,
                "passing_yards": float(pass_yards_fn(off, d)),
                "rushing_yards": float(rush_yards_fn(off, d)),
            })
    return rows


class TestDefenseFactors:
    """Concrete checks on ``_defense_factors`` (Requirement 4.4)."""

    def test_min_games_gate_skips_undersized_snapshots(self):
        """A snapshot with fewer than MIN_GAMES_TO_FIT prior games gets no
        fitted factor (callers then default to 1.0)."""
        assert MIN_GAMES_TO_FIT == 32  # guard: fixture sizing depends on this
        # Five weeks = 30 team-game rows total; the latest snapshot (week 5)
        # sees only weeks 1-4 = 24 prior rows, below the 32 threshold.
        rows = []
        for wk in (1, 2, 3, 4, 5):
            rows += _round_robin_week(2025, wk, lambda off, d: 240.0)
        svc = _service_with([], rows)

        factors = svc._defense_factors(2025, 99)

        # No snapshot had >= 32 prior rows, so nothing was fitted.
        assert factors == {}

    def test_factors_within_clamp_bounds(self):
        """Every fitted factor lies within FACTOR_CLAMP = [0.75, 1.25]."""
        rows = []
        for wk in range(1, 9):  # 8 weeks => the week-7/8 snapshots clear the gate
            rows += _round_robin_week(2025, wk, lambda off, d: 240.0)
        svc = _service_with([], rows)

        factors = svc._defense_factors(2025, 99)

        assert factors, "expected at least one fitted factor once the gate clears"
        lo, hi = FACTOR_CLAMP
        for key, value in factors.items():
            assert lo <= value <= hi, f"{value} for {key} outside {FACTOR_CLAMP}"

    def test_defense_allowing_more_pass_yards_gets_higher_pass_factor(self):
        """Direction check: a defense (the 'sieve') that consistently concedes
        far more passing yards than the league earns a pass factor > 1.0 and
        above a stingy defense's factor."""
        sieve, stingy = "T0", "T1"

        def pass_yards(off, d):
            if d == sieve:
                return 360.0   # torched through the air
            if d == stingy:
                return 150.0   # locked down
            return 240.0       # league-ish

        rows = []
        for wk in range(1, 10):  # 9 weeks so late snapshots clear the gate
            rows += _round_robin_week(2025, wk, pass_yards)
        svc = _service_with([], rows)

        factors = svc._defense_factors(2025, 99)

        # Look at the latest fitted snapshot.
        snaps = sorted({(s, w) for (_t, s, w, _c) in factors})
        assert snaps, "expected fitted snapshots"
        snap_season, snap_week = snaps[-1]

        sieve_pass = factors[(sieve, snap_season, snap_week, "pass")]
        stingy_pass = factors[(stingy, snap_season, snap_week, "pass")]

        assert sieve_pass > 1.0, "pass-sieve defense should inflate pass output"
        assert sieve_pass > stingy_pass, "sieve should exceed the stingy defense"


# ===========================================================================
# 3. Scoring formula application
# ===========================================================================

class TestScoringFormula:
    """``project_week`` scoring + stat-line shape (Requirement 4.6)."""

    def test_projected_points_is_hand_computed_dot_product(self):
        """With neutral factors (unknown opponent, no implied total => all 1.0),
        the expected line equals the baseline and projected_points equals the
        explicit dot product against a concrete scoring dict."""
        baseline = {
            "passing_yards": 300.0,
            "passing_tds": 2.0,
            "interceptions": 1.0,
            "rushing_yards": 20.0,
            "rushing_tds": 0.0,
            "receptions": 0.0,
            "receiving_yards": 0.0,
            "receiving_tds": 0.0,
            "fumbles_lost": 1.0,
        }
        # Standard-ish QB scoring.
        scoring = {
            "passing_yards": 0.04,
            "passing_tds": 4.0,
            "interceptions": -2.0,
            "rushing_yards": 0.1,
            "rushing_tds": 6.0,
            "receptions": 0.0,
            "receiving_yards": 0.1,
            "receiving_tds": 6.0,
            "fumbles_lost": -2.0,
        }

        rows = [
            # one prior week carries the baseline
            _feature_row(2025, 1, "qb1", "QB", "AAA", "ZZZ", stats=baseline,
                         implied_team_total=None),
            # target week: opponent None + no implied total => factors/env = 1.0
            _feature_row(2025, 2, "qb1", "QB", "AAA", None,
                         stats={c: 0.0 for c in STAT_COMPONENTS},
                         implied_team_total=None),
        ]
        svc = _service_with(rows)

        projections = svc.project_week(2025, 2, scoring)

        assert len(projections) == 1
        proj = projections[0]

        # expected line equals baseline (all multipliers are 1.0)
        for c in STAT_COMPONENTS:
            assert proj.expected_stat_line[c] == pytest.approx(baseline[c])

        # hand-computed: 300*0.04 + 2*4 - 1*2 + 20*0.1 + 1*(-2)
        #              = 12 + 8 - 2 + 2 - 2 = 18.0
        assert proj.projected_points == pytest.approx(18.0)
        # and it equals the explicit dot product
        expected = sum(baseline[c] * scoring[c] for c in STAT_COMPONENTS)
        assert proj.projected_points == pytest.approx(expected)

    def test_expected_stat_line_has_all_nine_components(self):
        """The projected stat line always exposes exactly the 9 STAT_COMPONENTS."""
        baseline = {c: 5.0 for c in STAT_COMPONENTS}
        scoring = {c: 1.0 for c in STAT_COMPONENTS}
        rows = [
            _feature_row(2025, 1, "p1", "WR", "AAA", "ZZZ", stats=baseline),
            _feature_row(2025, 2, "p1", "WR", "AAA", None,
                         stats={c: 0.0 for c in STAT_COMPONENTS}),
        ]
        svc = _service_with(rows)

        proj = svc.project_week(2025, 2, scoring)[0]

        assert set(proj.expected_stat_line) == set(STAT_COMPONENTS)
        assert len(proj.expected_stat_line) == 9
        # all-ones scoring => points == sum of the (unchanged) baseline line
        assert proj.projected_points == pytest.approx(5.0 * 9)
