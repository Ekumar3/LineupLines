"""Tests for research/model.py — baseline projection (no future data leaks)."""

from research.model import STAT_COMPONENTS, actual_stat_line, baseline_stat_line, current_team


def _row(season, week, team="KC", **overrides):
    row = {"season": season, "week": week, "team": team, "opponent_team": "BUF"}
    for component in STAT_COMPONENTS:
        row[component] = 0.0
    row.update(overrides)
    return row


def test_baseline_uses_only_weeks_strictly_before_target():
    rows = [
        _row(2025, 1, receiving_yards=50.0),
        _row(2025, 2, receiving_yards=60.0),
        _row(2025, 3, receiving_yards=70.0),
        # This is the target week — an extreme value that must NEVER leak into the baseline.
        _row(2025, 4, receiving_yards=999.0),
        # Nor should anything after the target week.
        _row(2025, 5, receiving_yards=999.0),
    ]

    baseline = baseline_stat_line(rows, season=2025, week=4)

    assert baseline["receiving_yards"] == (50.0 + 60.0 + 70.0) / 3


def test_baseline_uses_whatever_prior_weeks_exist_within_window():
    rows = [
        _row(2025, 1, receiving_yards=40.0),
        _row(2025, 2, receiving_yards=60.0),
    ]

    baseline = baseline_stat_line(rows, season=2025, week=3)

    assert baseline["receiving_yards"] == 50.0  # average of weeks 1-2, week 3 not included


def test_baseline_falls_back_to_prior_season_average_when_no_current_season_weeks():
    rows = [
        _row(2024, 15, receiving_yards=80.0),
        _row(2024, 16, receiving_yards=100.0),
        _row(2024, 17, receiving_yards=60.0),
    ]

    baseline = baseline_stat_line(rows, season=2025, week=1)

    assert baseline["receiving_yards"] == (80.0 + 100.0 + 60.0) / 3


def test_baseline_returns_none_when_no_data_exists_at_all():
    assert baseline_stat_line([], season=2025, week=1) is None


def test_baseline_ignores_future_season_rows_even_if_present_in_the_list():
    rows = [
        _row(2025, 1, receiving_yards=30.0),
        _row(2026, 1, receiving_yards=999.0),  # future season, must never leak
    ]

    baseline = baseline_stat_line(rows, season=2025, week=2)

    assert baseline["receiving_yards"] == 30.0


def test_actual_stat_line_reads_only_the_exact_target_week():
    rows = [
        _row(2025, 3, receiving_yards=10.0),
        _row(2025, 4, receiving_yards=99.0),
    ]
    assert actual_stat_line(rows, 2025, 4)["receiving_yards"] == 99.0
    assert actual_stat_line(rows, 2025, 5) is None


def test_current_team_uses_most_recent_prior_row_not_target_week():
    rows = [
        _row(2025, 1, team="KC"),
        _row(2025, 2, team="KC"),
    ]
    assert current_team(rows, season=2025, week=3) == "KC"
