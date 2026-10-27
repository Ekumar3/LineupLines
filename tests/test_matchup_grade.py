"""Tests for src/services/matchup_grade.py.

Covers the MatchupGradeService lookup behavior: returning the correct grades
and signals when a matching mart row exists, and a neutral default (all
signals ``"neutral"``, matchup grades ``0.0``) when the mart is empty or no
row matches. Also verifies that the signals surfaced by the service follow the
threshold rules defined in the design (|matchup| > 10 favorable/unfavorable,
otherwise neutral).

``load_mart`` is patched to return an in-memory polars DataFrame so these tests
never touch DuckDB or S3.
"""

from unittest.mock import patch

import polars as pl
import pytest

from src.services.matchup_grade import MatchupGrade, MatchupGradeService


def _mart_df():
    """A small mart with one row whose signals follow the threshold rules.

    pass_matchup=15.2  (> 10)        -> favorable
    rush_matchup=-3.1  (within +-10) -> neutral
    overall_matchup=8.4 (within +-10)-> neutral
    """
    return pl.DataFrame(
        {
            "team": ["SF"],
            "opponent": ["SEA"],
            "season": [2025],
            "week": [8],
            "pass_matchup": [15.2],
            "rush_matchup": [-3.1],
            "overall_matchup": [8.4],
            "pass_signal": ["favorable"],
            "rush_signal": ["neutral"],
            "overall_signal": ["neutral"],
            "ol_grade": [78.5],
            "dl_grade": [60.1],
        }
    )


# ---------------------------------------------------------------------------
# Matching row -> correct grades and signals.
# ---------------------------------------------------------------------------

def test_grade_for_returns_row_values_when_matched():
    with patch(
        "src.services.matchup_grade.load_mart", return_value=_mart_df()
    ) as mock_load:
        service = MatchupGradeService()
        grade = service.grade_for("SF", "SEA", 2025, 8)

    assert isinstance(grade, MatchupGrade)
    assert grade.team == "SF"
    assert grade.opponent == "SEA"
    assert grade.season == 2025
    assert grade.week == 8
    assert grade.pass_matchup == pytest.approx(15.2)
    assert grade.rush_matchup == pytest.approx(-3.1)
    assert grade.overall_matchup == pytest.approx(8.4)
    assert grade.pass_signal == "favorable"
    assert grade.rush_signal == "neutral"
    assert grade.overall_signal == "neutral"
    assert grade.ol_grade == pytest.approx(78.5)
    assert grade.dl_grade == pytest.approx(60.1)
    mock_load.assert_called_once_with("mart_matchup_grade")


def test_signals_match_thresholds_for_each_channel():
    """favorable (>10), unfavorable (<-10), neutral (within +-10)."""
    df = pl.DataFrame(
        {
            "team": ["SF"],
            "opponent": ["SEA"],
            "season": [2025],
            "week": [8],
            "pass_matchup": [12.0],   # > 10  -> favorable
            "rush_matchup": [-15.0],  # < -10 -> unfavorable
            "overall_matchup": [5.0],  # within -> neutral
            "pass_signal": ["favorable"],
            "rush_signal": ["unfavorable"],
            "overall_signal": ["neutral"],
            "ol_grade": [80.0],
            "dl_grade": [55.0],
        }
    )
    with patch("src.services.matchup_grade.load_mart", return_value=df):
        grade = MatchupGradeService().grade_for("SF", "SEA", 2025, 8)

    # Signal buckets are consistent with the design's threshold rules.
    assert grade.pass_matchup > 10 and grade.pass_signal == "favorable"
    assert grade.rush_matchup < -10 and grade.rush_signal == "unfavorable"
    assert -10 <= grade.overall_matchup <= 10 and grade.overall_signal == "neutral"


# ---------------------------------------------------------------------------
# Neutral defaults.
# ---------------------------------------------------------------------------

def _assert_neutral(grade, team, opponent, season, week):
    assert grade.team == team
    assert grade.opponent == opponent
    assert grade.season == season
    assert grade.week == week
    assert grade.pass_matchup == 0.0
    assert grade.rush_matchup == 0.0
    assert grade.overall_matchup == 0.0
    assert grade.pass_signal == "neutral"
    assert grade.rush_signal == "neutral"
    assert grade.overall_signal == "neutral"
    assert grade.ol_grade is None
    assert grade.dl_grade is None


def test_grade_for_empty_mart_returns_neutral_default():
    with patch("src.services.matchup_grade.load_mart", return_value=pl.DataFrame()):
        grade = MatchupGradeService().grade_for("SF", "SEA", 2025, 8)

    _assert_neutral(grade, "SF", "SEA", 2025, 8)


def test_grade_for_no_matching_row_returns_neutral_default():
    with patch("src.services.matchup_grade.load_mart", return_value=_mart_df()):
        # Opponent/week that is not in the mart.
        grade = MatchupGradeService().grade_for("SF", "ARI", 2025, 9)

    _assert_neutral(grade, "SF", "ARI", 2025, 9)


# ---------------------------------------------------------------------------
# Lazy-load + caching: the mart is read once and reused.
# ---------------------------------------------------------------------------

def test_mart_is_loaded_once_and_cached():
    with patch(
        "src.services.matchup_grade.load_mart", return_value=_mart_df()
    ) as mock_load:
        service = MatchupGradeService()
        service.grade_for("SF", "SEA", 2025, 8)
        service.grade_for("SF", "SEA", 2025, 8)
        service.grade_for("SF", "ARI", 2025, 9)

    assert mock_load.call_count == 1
