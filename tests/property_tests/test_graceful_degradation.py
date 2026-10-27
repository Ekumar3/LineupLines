"""Property tests for graceful degradation (design Properties 10 and 20).

Property 20 — Graceful file handling:
    ``∀ missing_file request to Projections Store: returns empty DataFrame
    without raising exceptions``.
    (Validates Requirements 2.6, 2.8)

Property 10 — Graceful degradation:
    the matchup-grade service never raises when the mart is missing — it
    returns a neutral default (all signals ``"neutral"``, all grades ``0.0``).
    (Validates Requirements 3.3, 3.11, 12.1)

These tests exercise the real loaders/service with no mart present (no
``MART_S3_BUCKET`` set, DuckDB file absent) so that the graceful-degradation
path is what actually runs. ``load_mart`` / ``load_projections`` must return an
empty ``pl.DataFrame`` and ``MatchupGradeService.grade_for`` must always return
a ``MatchupGrade`` whose signals live in the allowed domain.
"""

from unittest.mock import patch

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from src.data_sources import projections_store
from src.data_sources.projections_store import load_mart, load_projections
from src.services.matchup_grade import MatchupGrade, MatchupGradeService

SIGNAL_DOMAIN = {"favorable", "neutral", "unfavorable"}

# Table/format names: arbitrary-ish text plus a few realistic mart names.
table_names = st.one_of(
    st.text(min_size=0, max_size=40),
    st.sampled_from(
        [
            "mart_matchup_grade",
            "mart_player_week_features",
            "mart_ol_grade",
            "does_not_exist",
        ]
    ),
)
seasons = st.integers(min_value=1900, max_value=2100)
weeks = st.integers(min_value=0, max_value=30)
scoring_formats = st.one_of(
    st.sampled_from(["ppr", "half_ppr", "standard"]),
    st.text(min_size=0, max_size=20),
)
teams = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=0, max_size=6
)


def _no_mart_env():
    """Patch the store so no mart is reachable, forcing the degradation path."""
    # No S3 bucket -> local path; point DuckDB at a path that does not exist.
    return patch.object(
        projections_store,
        "LOCAL_DUCKDB_PATH",
        projections_store.REPO_ROOT / "dbt" / "__no_such_db__.duckdb",
    )


# --- Property 20: load_mart never raises, returns empty when missing ---------


@settings(max_examples=200)
@given(name=table_names, season=st.one_of(st.none(), seasons))
def test_load_mart_never_raises_and_empty_when_missing(name, season):
    with patch.dict("os.environ", {}, clear=True), _no_mart_env():
        df = load_mart(name, season)
    assert isinstance(df, pl.DataFrame)
    assert df.is_empty()


# --- Property 20: load_projections never raises, returns empty when missing --


@settings(max_examples=200)
@given(season=seasons, week=weeks, scoring_format=scoring_formats)
def test_load_projections_never_raises_and_empty_when_missing(
    season, week, scoring_format
):
    with patch.dict("os.environ", {}, clear=True), _no_mart_env():
        df = load_projections(season, week, scoring_format)
    assert isinstance(df, pl.DataFrame)
    assert df.is_empty()


# --- Property 10: grade_for never raises; neutral default on missing mart ----


@settings(max_examples=200)
@given(team=teams, opponent=teams, season=seasons, week=weeks)
def test_grade_for_never_raises_and_returns_valid_signals(team, opponent, season, week):
    # Force an empty mart so the graceful-degradation branch is exercised.
    with patch("src.services.matchup_grade.load_mart", return_value=pl.DataFrame()):
        service = MatchupGradeService()
        grade = service.grade_for(team, opponent, season, week)

    assert isinstance(grade, MatchupGrade)
    # Signal domain invariant.
    assert grade.pass_signal in SIGNAL_DOMAIN
    assert grade.rush_signal in SIGNAL_DOMAIN
    assert grade.overall_signal in SIGNAL_DOMAIN
    # Neutral-default invariant when the mart is empty.
    assert grade.pass_signal == "neutral"
    assert grade.rush_signal == "neutral"
    assert grade.overall_signal == "neutral"
    assert grade.pass_matchup == 0.0
    assert grade.rush_matchup == 0.0
    assert grade.overall_matchup == 0.0
    # Query echoed back intact.
    assert grade.team == team
    assert grade.opponent == opponent
    assert grade.season == season
    assert grade.week == week
