"""Unit tests for src/services/waiver_service.py — WaiverService.free_agent_ranking.

These tests inject a mocked ``SleeperClient`` (``get_league_rosters`` returning
``Roster`` objects, ``get_trending_players`` returning trending dicts) and patch
``src.services.waiver_service.load_projections`` to return a small in-memory
polars DataFrame. No real HTTP calls or parquet files are touched.
"""

from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from src.data_sources.sleeper_client import Roster
from src.services.waiver_service import WaiverService, WaiverRec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _projection_df():
    """A small projection set spanning multiple positions and point values."""
    return pl.DataFrame(
        [
            {"player_id": "1", "player_name": "QB One", "position": "QB", "team": "KC", "projected_points": 25.0},
            {"player_id": "2", "player_name": "RB Two", "position": "RB", "team": "SF", "projected_points": 20.0},
            {"player_id": "3", "player_name": "WR Three", "position": "WR", "team": "MIN", "projected_points": 18.0},
            {"player_id": "4", "player_name": "RB Four", "position": "RB", "team": "DAL", "projected_points": 15.0},
            {"player_id": "5", "player_name": "WR Five", "position": "WR", "team": "MIA", "projected_points": 12.0},
            {"player_id": "6", "player_name": "TE Six", "position": "TE", "team": "BAL", "projected_points": 10.0},
        ]
    )


@pytest.fixture
def mock_sleeper():
    """A mocked SleeperClient with no rostered players and no trending data."""
    client = MagicMock()
    client.get_league_rosters.return_value = []
    client.get_trending_players.return_value = []
    return client


@pytest.fixture
def service(mock_sleeper):
    return WaiverService(mock_sleeper)


def _roster(roster_id, owner_id, starters=None, players=None, reserve=None):
    return Roster(
        roster_id=str(roster_id),
        owner_id=str(owner_id),
        starters=starters or [],
        players=players or [],
        reserve=reserve or [],
    )


# ---------------------------------------------------------------------------
# 1. FA pool excludes rostered players
# ---------------------------------------------------------------------------

def test_fa_pool_excludes_rostered_players(service, mock_sleeper):
    # Player "2" is a normal roster player; "6" is on reserve (IR).
    mock_sleeper.get_league_rosters.return_value = [
        _roster("r1", "u1", starters=["2"], players=["2"], reserve=["6"]),
    ]

    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        results = service.free_agent_ranking("league", 2026, 1, "ppr")

    returned_ids = {r.player_id for r in results}
    # Both the rostered player and the reserve player are excluded.
    assert "2" not in returned_ids
    assert "6" not in returned_ids
    # Everyone else remains.
    assert returned_ids == {"1", "3", "4", "5"}


# ---------------------------------------------------------------------------
# 2. Ranking order: projected_points desc, trending_add_count tiebreak desc
# ---------------------------------------------------------------------------

def test_ranking_sorted_by_projected_points_desc(service):
    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        results = service.free_agent_ranking("league", 2026, 1, "ppr")

    points = [r.projected_points for r in results]
    assert points == sorted(points, reverse=True)
    # Explicit ordering of the full set by point value.
    assert [r.player_id for r in results] == ["1", "2", "3", "4", "5", "6"]


def test_ranking_tiebreak_by_trending_add_count_desc(service, mock_sleeper):
    # Two players tied on projected points; trending count breaks the tie.
    tied_df = pl.DataFrame(
        [
            {"player_id": "10", "player_name": "A", "position": "WR", "team": "KC", "projected_points": 15.0},
            {"player_id": "11", "player_name": "B", "position": "WR", "team": "SF", "projected_points": 15.0},
        ]
    )
    mock_sleeper.get_trending_players.return_value = [
        {"player_id": "10", "count": 5},
        {"player_id": "11", "count": 99},
    ]

    with patch("src.services.waiver_service.load_projections", return_value=tied_df):
        results = service.free_agent_ranking("league", 2026, 1, "ppr")

    # Player 11 has the higher trending count, so it ranks ahead of 10.
    assert [r.player_id for r in results] == ["11", "10"]
    assert results[0].trending_add_count == 99
    assert results[1].trending_add_count == 5


# ---------------------------------------------------------------------------
# 3. Position filtering
# ---------------------------------------------------------------------------

def test_position_filter_returns_only_that_position(service):
    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        results = service.free_agent_ranking(
            "league", 2026, 1, "ppr", position="RB"
        )

    assert {r.player_id for r in results} == {"2", "4"}
    assert all(r.position == "RB" for r in results)


# ---------------------------------------------------------------------------
# 4. Limit enforcement + 1-indexed contiguous rank
# ---------------------------------------------------------------------------

def test_limit_enforced_and_rank_is_contiguous(service):
    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        results = service.free_agent_ranking("league", 2026, 1, "ppr", limit=3)

    assert len(results) <= 3
    assert len(results) == 3
    # rank is 1-indexed and contiguous.
    assert [r.rank for r in results] == [1, 2, 3]
    # The top-3 are the highest projected players in order.
    assert [r.player_id for r in results] == ["1", "2", "3"]


def test_rank_contiguous_without_explicit_limit(service):
    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        results = service.free_agent_ranking("league", 2026, 1, "ppr")

    assert [r.rank for r in results] == list(range(1, len(results) + 1))


# ---------------------------------------------------------------------------
# 5. Trending augmentation merged by player_id
# ---------------------------------------------------------------------------

def test_trending_augmentation_merged_by_player_id(service, mock_sleeper):
    mock_sleeper.get_trending_players.return_value = [
        {"player_id": "1", "count": 42},
        {"player_id": "3", "count": 7},
    ]

    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        results = service.free_agent_ranking("league", 2026, 1, "ppr")

    by_id = {r.player_id: r for r in results}
    assert by_id["1"].trending_add_count == 42
    assert by_id["3"].trending_add_count == 7
    # Players with no trending entry have None.
    assert by_id["2"].trending_add_count is None
    assert by_id["4"].trending_add_count is None
    # The trending endpoint was queried for adds.
    mock_sleeper.get_trending_players.assert_called_once_with(type="add")


# ---------------------------------------------------------------------------
# 6. Graceful: empty / missing projections -> []
# ---------------------------------------------------------------------------

def test_empty_projections_returns_empty_list(service, mock_sleeper):
    empty_df = pl.DataFrame(
        schema={
            "player_id": pl.Utf8,
            "player_name": pl.Utf8,
            "position": pl.Utf8,
            "team": pl.Utf8,
            "projected_points": pl.Float64,
        }
    )

    with patch("src.services.waiver_service.load_projections", return_value=empty_df):
        results = service.free_agent_ranking("league", 2026, 1, "ppr")

    assert results == []
    # No need to consult rosters/trending when there are no projections.
    mock_sleeper.get_league_rosters.assert_not_called()
    mock_sleeper.get_trending_players.assert_not_called()


def test_none_projections_returns_empty_list(service):
    with patch("src.services.waiver_service.load_projections", return_value=None):
        results = service.free_agent_ranking("league", 2026, 1, "ppr")

    assert results == []
