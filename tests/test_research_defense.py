"""Tests for research/defense.py and the v2 projection in research/model.py."""

import polars as pl

from research import defense
from research.model import STAT_COMPONENTS, expected_line_v2

TEAMS = [f"T{i:02d}" for i in range(8)]


def _row(season, week, team, opp, pass_yds, rush_yds):
    row = {c: 0.0 for c in STAT_COMPONENTS}
    row.update({
        "season": season, "week": week, "player_id": f"{team}-qb", "position": "QB",
        "team": team, "opponent_team": opp, "passing_yards": pass_yds, "rushing_yards": rush_yds,
    })
    return row


def _round_robin_season(season, weeks, sieve_team="T00", sieve_mult=2.0):
    """Every team plays every week; `sieve_team` allows sieve_mult x the passing yards."""
    rows = []
    n = len(TEAMS)
    for week in range(1, weeks + 1):
        # rotate pairings so each team faces a mix of opponents
        order = TEAMS[:1] + TEAMS[1:][week % (n - 1):] + TEAMS[1:][: week % (n - 1)]
        for i in range(n // 2):
            a, b = order[i], order[n - 1 - i]
            for off, d in ((a, b), (b, a)):
                mult = sieve_mult if d == sieve_team else 1.0
                rows.append(_row(season, week, off, d, 220.0 * mult, 110.0))
    return rows


def test_sieve_defense_gets_a_factor_above_league_average_and_others_do_not():
    table = pl.DataFrame(_round_robin_season(2025, weeks=8))
    factors = defense.defense_factors(table)

    # After 7 weeks of evidence, the sieve should be well above 1.0 for pass...
    sieve = factors[("T00", 2025, 8, "pass")]
    others = [factors[(t, 2025, 8, "pass")] for t in TEAMS[1:]]
    assert sieve > 1.15
    assert all(o < sieve for o in others)
    # ...and ~neutral for rush, which nothing in the data varies.
    assert abs(factors[("T00", 2025, 8, "rush")] - 1.0) < 0.05


def test_factors_never_use_the_target_week_or_later():
    # Sieve only starts leaking from week 5 on; weeks 1-4 are perfectly average.
    rows = _round_robin_season(2025, weeks=4, sieve_mult=1.0)
    rows += [r for r in _round_robin_season(2025, weeks=8, sieve_mult=3.0) if r["week"] > 4]
    factors = defense.defense_factors(pl.DataFrame(rows))

    # The week-5 factor is fit on weeks 1-4 only -> must not see the week-5+ leak.
    assert abs(factors[("T00", 2025, 5, "pass")] - 1.0) < 0.02
    # By week 8 it has seen weeks 5-7 and should have moved.
    assert factors[("T00", 2025, 8, "pass")] > 1.10


def test_prior_season_seeds_week_one_but_is_downweighted():
    rows = _round_robin_season(2024, weeks=17, sieve_mult=1.2)
    rows += _round_robin_season(2025, weeks=2, sieve_mult=1.0)
    factors = defense.defense_factors(pl.DataFrame(rows))

    week1 = factors[("T00", 2025, 1, "pass")]
    assert week1 > 1.05  # prior season says sieve
    assert week1 < factors[("T00", 2024, 17, "pass")]  # but regressed vs. full-weight in-season evidence


def test_missing_key_defaults_to_league_average():
    assert defense.factor_for({}, "NOPE", 2025, 1, "pass") == 1.0


def test_v2_pass_factor_scales_receiving_but_not_rushing():
    baseline = {c: 10.0 for c in STAT_COMPONENTS}
    expected = expected_line_v2(baseline, pass_factor=1.2, rush_factor=0.8, environment_multiplier=1.0)

    assert expected["receiving_yards"] == 12.0
    assert expected["receptions"] == 12.0
    assert expected["passing_yards"] == 12.0
    assert expected["rushing_yards"] == 8.0
    assert expected["rushing_tds"] == 8.0
    assert expected["fumbles_lost"] == 10.0  # no channel


def test_v2_environment_multiplier_applies_to_every_component():
    baseline = {c: 10.0 for c in STAT_COMPONENTS}
    expected = expected_line_v2(baseline, pass_factor=1.0, rush_factor=1.0, environment_multiplier=1.1)
    assert all(abs(v - 11.0) < 1e-9 for v in expected.values())
