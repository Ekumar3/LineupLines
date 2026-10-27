"""Property test for signal assignment consistency (design Property 13).

Property 13 — Signal assignment consistency:
    ``∀ matchup_grade result:
        (pass_matchup > 10  ⟹ pass_signal = "favorable") ∧
        (pass_matchup < -10 ⟹ pass_signal = "unfavorable") ∧
        (-10 ≤ pass_matchup ≤ 10 ⟹ pass_signal = "neutral")``
    (same for rush and overall). (Validates Requirements 3.8, 3.9, 3.10)

Where the threshold logic lives
-------------------------------
``MatchupGradeService`` does NOT recompute signals — it trusts the signal
columns precomputed by the dbt ``mart_matchup_grade`` model and only applies a
null → ``"neutral"`` default. The authoritative threshold derivation (``> 10``
favorable, ``< -10`` unfavorable, else/null neutral) therefore lives in the dbt
layer and is guarded by the singular test
``dbt/tests/assert_matchup_signal_thresholds.sql``.

This file validates Property 13 from the Python side in two ways:

1. End-to-end over a hypothesis-generated mart: we build a mart row whose
   signals are derived by the same threshold rule the dbt model uses, patch
   ``load_mart`` to return it, and assert the signal the service surfaces
   satisfies the Property-13 relation against the matchup value. This confirms
   the service faithfully passes the mart's signals through.

2. Service-owned invariants: signals are always in the allowed domain, and a
   null signal in the mart row is defaulted to ``"neutral"``.
"""

from unittest.mock import patch

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from src.services.matchup_grade import MatchupGradeService

SIGNAL_DOMAIN = {"favorable", "neutral", "unfavorable"}


def _signal_for(matchup):
    """Reference threshold derivation — mirrors mart_matchup_grade / the dbt
    singular test assert_matchup_signal_thresholds.sql."""
    if matchup is None:
        return "neutral"
    if matchup > 10:
        return "favorable"
    if matchup < -10:
        return "unfavorable"
    return "neutral"


def _assert_property_13(matchup, signal):
    """Assert the Property-13 relation holds for one channel."""
    if matchup is None:
        assert signal == "neutral"
    elif matchup > 10:
        assert signal == "favorable"
    elif matchup < -10:
        assert signal == "unfavorable"
    else:  # -10 <= matchup <= 10
        assert signal == "neutral"


# Matchup deltas range roughly [-100, 100] (two 0-100 grades subtracted), with
# explicit coverage around the ±10 thresholds and the null (missing-grade) case.
matchups = st.one_of(
    st.none(),
    st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
    st.sampled_from([-10.0, -10.01, -9.99, 0.0, 9.99, 10.0, 10.01]),
)
teams = st.text(
    alphabet=st.characters(min_codepoint=65, max_codepoint=90), min_size=2, max_size=4
)
seasons = st.integers(min_value=2000, max_value=2100)
weeks = st.integers(min_value=1, max_value=22)


@settings(max_examples=300)
@given(
    team=teams,
    opponent=teams,
    season=seasons,
    week=weeks,
    pass_matchup=matchups,
    rush_matchup=matchups,
    overall_matchup=matchups,
)
def test_signal_assignment_consistency(
    team, opponent, season, week, pass_matchup, rush_matchup, overall_matchup
):
    # Build a single mart row with signals derived by the threshold rule.
    row = pl.DataFrame(
        {
            "team": [team],
            "opponent": [opponent],
            "season": [season],
            "week": [week],
            "pass_matchup": [pass_matchup],
            "rush_matchup": [rush_matchup],
            "overall_matchup": [overall_matchup],
            "pass_signal": [_signal_for(pass_matchup)],
            "rush_signal": [_signal_for(rush_matchup)],
            "overall_signal": [_signal_for(overall_matchup)],
            "ol_grade": [None],
            "dl_grade": [None],
        }
    )

    with patch("src.services.matchup_grade.load_mart", return_value=row):
        service = MatchupGradeService()
        grade = service.grade_for(team, opponent, season, week)

    # Property 13: each surfaced signal matches its matchup value's threshold.
    _assert_property_13(grade.pass_matchup, grade.pass_signal)
    _assert_property_13(grade.rush_matchup, grade.rush_signal)
    _assert_property_13(grade.overall_matchup, grade.overall_signal)

    # Service-owned invariants: domain membership.
    assert grade.pass_signal in SIGNAL_DOMAIN
    assert grade.rush_signal in SIGNAL_DOMAIN
    assert grade.overall_signal in SIGNAL_DOMAIN


@settings(max_examples=100)
@given(team=teams, opponent=teams, season=seasons, week=weeks, matchup=matchups)
def test_null_signal_in_mart_defaults_to_neutral(
    team, opponent, season, week, matchup
):
    """A mart row carrying a null signal must be surfaced as 'neutral'
    (service-owned null → neutral default)."""
    row = pl.DataFrame(
        {
            "team": [team],
            "opponent": [opponent],
            "season": [season],
            "week": [week],
            "pass_matchup": [matchup],
            "rush_matchup": [matchup],
            "overall_matchup": [matchup],
            "pass_signal": [None],
            "rush_signal": [None],
            "overall_signal": [None],
            "ol_grade": [None],
            "dl_grade": [None],
        }
    )

    with patch("src.services.matchup_grade.load_mart", return_value=row):
        grade = MatchupGradeService().grade_for(team, opponent, season, week)

    assert grade.pass_signal == "neutral"
    assert grade.rush_signal == "neutral"
    assert grade.overall_signal == "neutral"
