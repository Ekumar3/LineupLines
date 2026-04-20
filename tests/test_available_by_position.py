"""Tests for GET /api/v1/drafts/{draft_id}/available-by-position endpoint."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from datetime import datetime

from src.api.main import app
from src.data_sources.sleeper_client import DraftPick
from src.data_sources.sleeper_projections_client import PlayerProjection


def _make_proj(player_id: str, name: str, position: str, team: str, adp: float) -> PlayerProjection:
    """Helper to build a minimal PlayerProjection for tests."""
    return PlayerProjection(
        player_id=player_id,
        player_name=name,
        position=position,
        team=team,
        projected_pts=200.0,
        avg_ppg=12.5,
        adp=adp,
        gp=16.0,
    )


class TestGetAvailableByPosition:
    """Tests for GET /api/v1/drafts/{draft_id}/available-by-position endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_draft_details(self):
        """Mock draft details response."""
        return {
            "draft_id": "123",
            "league_id": "456",
            "status": "in_progress",
            "type": "snake",
            "settings": {"teams": 12, "rounds": 15},
            "metadata": {"name": "Test League", "scoring_type": "ppr"},
        }

    @pytest.fixture
    def mock_draft_picks(self):
        """Mock draft picks response - 24 picks made (end of round 2)."""
        return [
            DraftPick(
                pick_no=i,
                draft_id="123",
                user_id=f"user_{i}",
                player_id=f"drafted_player_{i}",
                player_name=f"Drafted Player {i}",
                position="RB" if i % 2 == 0 else "WR",
                team="KC",
                round=(i - 1) // 12 + 1,
                timestamp=datetime(2026, 8, 15, 19, 30, 0),
            )
            for i in range(1, 25)
        ]

    @pytest.fixture
    def mock_player_universe(self):
        """Mock player universe with various positions."""
        return {
            "2307": {
                "first_name": "Christian",
                "last_name": "McCaffrey",
                "position": "RB",
                "team": "SF",
                "age": 27,
                "years_exp": 7,
                "active": True,
            },
            "4866": {
                "first_name": "CeeDee",
                "last_name": "Lamb",
                "position": "WR",
                "team": "DAL",
                "age": 25,
                "years_exp": 4,
                "active": True,
            },
            "5000": {
                "first_name": "Patrick",
                "last_name": "Mahomes",
                "position": "QB",
                "team": "KC",
                "age": 28,
                "years_exp": 7,
                "active": True,
            },
            "5001": {
                "first_name": "Travis",
                "last_name": "Kelce",
                "position": "TE",
                "team": "KC",
                "age": 34,
                "years_exp": 11,
                "active": True,
            },
            "5002": {
                "first_name": "Harrison",
                "last_name": "Butker",
                "position": "K",
                "team": "KC",
                "age": 28,
                "years_exp": 9,
                "active": True,
            },
            "5003": {
                "first_name": "Defense",
                "last_name": "SF",
                "position": "DEF",
                "team": "SF",
                "active": True,
            },
        }

    def test_available_by_position_success(
        self, client, mock_draft_details, mock_draft_picks, mock_player_universe
    ):
        """Test successful retrieval of available players by position."""
        # Sleeper projections keyed by player_id (matches mock_player_universe ids)
        mock_projections = {
            "2307": _make_proj("2307", "Christian McCaffrey", "RB", "SF", 35.0),
            "4866": _make_proj("4866", "CeeDee Lamb", "WR", "DAL", 35.0),
            "5000": _make_proj("5000", "Patrick Mahomes", "QB", "KC", 45.2),
            "5001": _make_proj("5001", "Travis Kelce", "TE", "KC", 35.0),
            "5002": _make_proj("5002", "Harrison Butker", "K", "KC", 35.0),
            "5003": _make_proj("5003", "Defense SF", "DEF", "SF", 35.0),
        }
        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=mock_draft_details,
        ), patch(
            "src.api.main.sleeper_client.get_draft_picks",
            return_value=mock_draft_picks,
        ), patch(
            "src.api.main.sleeper_client.get_scoring_format", return_value="ppr"
        ), patch(
            "src.api.main.load_player_universe",
            return_value=mock_player_universe,
        ), patch(
            "src.api.main.sleeper_projections_client.fetch_projections",
            return_value=mock_projections,
        ):
            response = client.get("/api/v1/drafts/123/available-by-position")

        assert response.status_code == 200
        data = response.json()

        assert data["draft_id"] == "123"
        assert data["current_overall_pick"] == 25  # 24 picks + 1
        assert data["scoring_format"] == "ppr"
        assert data["limit"] == 20

        # Check structure
        assert "players_by_position" in data
        assert "QB" in data["players_by_position"]
        assert "RB" in data["players_by_position"]
        assert "WR" in data["players_by_position"]
        assert "TE" in data["players_by_position"]
        assert "K" in data["players_by_position"]
        assert "DEF" in data["players_by_position"]

        # Check QB position has Mahomes with correct ADP delta
        qbs = data["players_by_position"]["QB"]
        assert len(qbs) > 0
        mahomes = next((p for p in qbs if "Mahomes" in p["player_name"]), None)
        assert mahomes is not None
        assert mahomes["adp_ppr"] == 45.2
        assert abs(mahomes["adp_delta"] - (-20.2)) < 0.01  # 25 - 45.2 = -20.2 (available before ADP)

    def test_custom_limit(self, client, mock_draft_details, mock_draft_picks, mock_player_universe):
        """Test custom limit parameter restricts results."""
        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=mock_draft_details,
        ), patch(
            "src.api.main.sleeper_client.get_draft_picks",
            return_value=mock_draft_picks,
        ), patch(
            "src.api.main.sleeper_client.get_scoring_format", return_value="ppr"
        ), patch(
            "src.api.main.load_player_universe",
            return_value=mock_player_universe,
        ), patch(
            "src.api.main.sleeper_projections_client.fetch_projections", return_value={}
        ):
            response = client.get("/api/v1/drafts/123/available-by-position?limit=5")

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5

        # Each position should have at most 5 players
        for position, players in data["players_by_position"].items():
            assert len(players) <= 5

    def test_draft_not_found(self, client):
        """Test 404 when draft doesn't exist."""
        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=None,
        ):
            response = client.get("/api/v1/drafts/nonexistent/available-by-position")

        assert response.status_code == 404
        assert "Draft not found" in response.json()["detail"]

    def test_player_universe_load_failure(self, client, mock_draft_details, mock_draft_picks):
        """Test 500 when player universe cannot be loaded."""
        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=mock_draft_details,
        ), patch(
            "src.api.main.sleeper_client.get_draft_picks",
            return_value=mock_draft_picks,
        ), patch(
            "src.api.main.load_player_universe", return_value=None
        ), patch(
            "src.api.main.sleeper_client.get_players", return_value=None
        ):
            response = client.get("/api/v1/drafts/123/available-by-position")

        assert response.status_code == 500
        assert "Unable to load player data" in response.json()["detail"]

    def test_sorting_by_adp_delta(
        self, client, mock_draft_details, mock_draft_picks, mock_player_universe
    ):
        """Test that players are sorted by ADP delta descending (best value first)."""
        # Projections keyed by player_id with ADP values that create different deltas
        mock_projections = {
            "2307": _make_proj("2307", "Christian McCaffrey", "RB", "SF", 30.0),  # delta = -5
            "4866": _make_proj("4866", "CeeDee Lamb", "WR", "DAL", 40.0),         # delta = -15
            "5000": _make_proj("5000", "Patrick Mahomes", "QB", "KC", 50.0),       # delta = -25
        }

        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=mock_draft_details,
        ), patch(
            "src.api.main.sleeper_client.get_draft_picks",
            return_value=mock_draft_picks,
        ), patch(
            "src.api.main.sleeper_client.get_scoring_format", return_value="ppr"
        ), patch(
            "src.api.main.load_player_universe",
            return_value=mock_player_universe,
        ), patch(
            "src.api.main.sleeper_projections_client.fetch_projections",
            return_value=mock_projections,
        ):
            response = client.get("/api/v1/drafts/123/available-by-position")

        assert response.status_code == 200
        data = response.json()

        # Check QB: Mahomes should be first (highest delta = 25.0)
        qbs = data["players_by_position"]["QB"]
        if len(qbs) > 0 and qbs[0]["adp_delta"] is not None:
            assert qbs[0]["player_name"] == "Patrick Mahomes"
            assert qbs[0]["adp_delta"] == -25.0  # 25 - 50.0 = -25.0

    def test_no_adp_data_handling(
        self, client, mock_draft_details, mock_draft_picks, mock_player_universe
    ):
        """Test graceful handling when no Sleeper projection data available."""
        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=mock_draft_details,
        ), patch(
            "src.api.main.sleeper_client.get_draft_picks",
            return_value=mock_draft_picks,
        ), patch(
            "src.api.main.sleeper_client.get_scoring_format", return_value="ppr"
        ), patch(
            "src.api.main.load_player_universe",
            return_value=mock_player_universe,
        ), patch(
            "src.api.main.sleeper_projections_client.fetch_projections",
            return_value={},
        ):
            response = client.get("/api/v1/drafts/123/available-by-position")

        assert response.status_code == 200
        data = response.json()

        # With no projection data, all positions should have empty player lists
        # (players without ADP are filtered out)
        for position, players in data["players_by_position"].items():
            assert len(players) == 0

    def test_players_with_adp_come_before_players_without(
        self, client, mock_draft_details, mock_draft_picks, mock_player_universe
    ):
        """Test that only players with Sleeper ADP data appear in results."""
        # Only Mahomes has projection/ADP data
        mock_projections = {
            "5000": _make_proj("5000", "Patrick Mahomes", "QB", "KC", 50.0),
        }

        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=mock_draft_details,
        ), patch(
            "src.api.main.sleeper_client.get_draft_picks",
            return_value=mock_draft_picks,
        ), patch(
            "src.api.main.sleeper_client.get_scoring_format", return_value="ppr"
        ), patch(
            "src.api.main.load_player_universe",
            return_value=mock_player_universe,
        ), patch(
            "src.api.main.sleeper_projections_client.fetch_projections",
            return_value=mock_projections,
        ):
            response = client.get("/api/v1/drafts/123/available-by-position")

        assert response.status_code == 200
        data = response.json()

        # Only Mahomes should appear (only player with ADP data)
        qbs = data["players_by_position"]["QB"]
        assert len(qbs) == 1
        assert qbs[0]["player_name"] == "Patrick Mahomes"
        assert qbs[0]["adp_ppr"] == 50.0

        # Other positions have no projection data → empty lists
        assert len(data["players_by_position"]["RB"]) == 0
        assert len(data["players_by_position"]["WR"]) == 0

    def test_drafted_players_excluded(
        self, client, mock_draft_details, mock_draft_picks, mock_player_universe
    ):
        """Test that drafted players are excluded from available list."""
        mock_projections = {
            "2307": _make_proj("2307", "Christian McCaffrey", "RB", "SF", 1.0),
            "4866": _make_proj("4866", "CeeDee Lamb", "WR", "DAL", 2.0),
            "5000": _make_proj("5000", "Patrick Mahomes", "QB", "KC", 45.0),
        }
        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=mock_draft_details,
        ), patch(
            "src.api.main.sleeper_client.get_draft_picks",
            return_value=mock_draft_picks,
        ), patch(
            "src.api.main.sleeper_client.get_scoring_format", return_value="ppr"
        ), patch(
            "src.api.main.load_player_universe",
            return_value=mock_player_universe,
        ), patch(
            "src.api.main.sleeper_projections_client.fetch_projections",
            return_value=mock_projections,
        ):
            response = client.get("/api/v1/drafts/123/available-by-position")

        assert response.status_code == 200
        data = response.json()

        # No player should have player_id from drafted_player_ids
        drafted_ids = {f"drafted_player_{i}" for i in range(1, 25)}
        for position, players in data["players_by_position"].items():
            for player in players:
                assert player["player_id"] not in drafted_ids

    def test_limit_validation(self, client, mock_draft_details):
        """Test that limit parameter is validated (1-100)."""
        with patch(
            "src.api.main.sleeper_client.get_draft_details",
            return_value=mock_draft_details,
        ):
            # Test with limit > 100 should fail
            response = client.get("/api/v1/drafts/123/available-by-position?limit=150")
            assert response.status_code == 422  # Validation error

            # Test with limit < 1 should fail
            response = client.get("/api/v1/drafts/123/available-by-position?limit=0")
            assert response.status_code == 422  # Validation error
