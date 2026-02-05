"""Tests for league settings endpoint."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.api.main import app


class TestLeagueSettings:
    """Tests for GET /api/v1/drafts/{draft_id}/league-settings endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_draft_details(self):
        """Mock draft details response."""
        return {
            "draft_id": "123456789",
            "league_id": "987654321",
            "status": "in_progress",
            "type": "snake",
            "settings": {"teams": 12, "rounds": 15, "reversal_round": 1},
            "metadata": {"name": "Test League", "scoring_type": "ppr"},
            "draft_order": ["user_1", "user_2", "user_3"],
            "roster_to_user": {"1": "user_1", "2": "user_2", "3": "user_3"},
        }

    @pytest.fixture
    def mock_league_info_ppr(self):
        """Mock PPR league info."""
        return {
            "league_id": "987654321",
            "name": "PPR League",
            "total_rosters": 12,
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
            "scoring_settings": {
                "rec": 1.0,  # PPR
                "pass_td": 4.0,
                "pass_yd": 0.04,
                "rush_yd": 0.1,
            },
        }

    @pytest.fixture
    def mock_league_info_half_ppr(self):
        """Mock Half-PPR league info."""
        return {
            "league_id": "987654321",
            "name": "Half-PPR League",
            "total_rosters": 12,
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
            "scoring_settings": {
                "rec": 0.5,  # Half-PPR
                "pass_td": 4.0,
                "pass_yd": 0.04,
                "rush_yd": 0.1,
            },
        }

    @pytest.fixture
    def mock_league_info_standard(self):
        """Mock Standard league info."""
        return {
            "league_id": "987654321",
            "name": "Standard League",
            "total_rosters": 12,
            "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
            "scoring_settings": {
                "rec": 0.0,  # Standard
                "pass_td": 4.0,
                "pass_yd": 0.04,
                "rush_yd": 0.1,
            },
        }

    def test_get_league_settings_ppr_success(
        self, client, mock_draft_details, mock_league_info_ppr
    ):
        """Test successful PPR league settings retrieval."""
        with patch("src.api.main.sleeper_client.get_draft_details", return_value=mock_draft_details):
            with patch("src.api.main.sleeper_client.get_league_info", return_value=mock_league_info_ppr):
                response = client.get("/api/v1/drafts/123456789/league-settings")

        assert response.status_code == 200
        data = response.json()

        assert data["draft_id"] == "123456789"
        assert data["league_id"] == "987654321"
        assert data["settings"]["scoring_format"] == "ppr"
        assert data["settings"]["total_rosters"] == 12
        assert isinstance(data["settings"]["roster_positions"], list)

    def test_get_league_settings_half_ppr_success(
        self, client, mock_draft_details, mock_league_info_half_ppr
    ):
        """Test successful Half-PPR league settings retrieval."""
        with patch("src.api.main.sleeper_client.get_draft_details", return_value=mock_draft_details):
            with patch("src.api.main.sleeper_client.get_league_info", return_value=mock_league_info_half_ppr):
                response = client.get("/api/v1/drafts/123456789/league-settings")

        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["scoring_format"] == "half_ppr"

    def test_get_league_settings_standard_success(
        self, client, mock_draft_details, mock_league_info_standard
    ):
        """Test successful Standard league settings retrieval."""
        with patch("src.api.main.sleeper_client.get_draft_details", return_value=mock_draft_details):
            with patch("src.api.main.sleeper_client.get_league_info", return_value=mock_league_info_standard):
                response = client.get("/api/v1/drafts/123456789/league-settings")

        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["scoring_format"] == "standard"

    def test_get_league_settings_draft_not_found(self, client):
        """Test 404 when draft not found."""
        with patch("src.api.main.sleeper_client.get_draft_details", return_value=None):
            response = client.get("/api/v1/drafts/nonexistent/league-settings")

        assert response.status_code == 404
        assert "Draft not found" in response.json()["detail"]

    def test_get_league_settings_missing_scoring_settings(self, client, mock_draft_details):
        """Test that league without scoring_settings defaults to standard."""
        # Mock league with missing scoring_settings
        bad_league_info = {
            "league_id": "987654321",
            "name": "League Without Settings",
            "total_rosters": 12,
            # No scoring_settings - will default to rec=0 (standard)
        }

        with patch("src.api.main.sleeper_client.get_draft_details", return_value=mock_draft_details):
            with patch("src.api.main.sleeper_client.get_league_info", return_value=bad_league_info):
                response = client.get("/api/v1/drafts/123456789/league-settings")

        # Should succeed and default to "standard" format
        assert response.status_code == 200
        assert response.json()["settings"]["scoring_format"] == "standard"

    def test_get_league_settings_server_error(self, client):
        """Test 500 on server error."""
        with patch(
            "src.api.main.sleeper_client.get_draft_details", side_effect=Exception("Connection Error")
        ):
            response = client.get("/api/v1/drafts/123456789/league-settings")

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]

    def test_get_league_settings_custom_scoring(self, client, mock_draft_details):
        """Test custom scoring format mapping."""
        custom_league = {
            "league_id": "987654321",
            "name": "Custom League",
            "total_rosters": 10,
            "roster_positions": ["QB", "RB", "WR", "TE"],
            "scoring_settings": {
                "rec": 0.8,  # Custom: between half-PPR and PPR
                "pass_td": 4.0,
                "pass_yd": 0.04,
                "rush_yd": 0.1,
            },
        }

        with patch("src.api.main.sleeper_client.get_draft_details", return_value=mock_draft_details):
            with patch("src.api.main.sleeper_client.get_league_info", return_value=custom_league):
                response = client.get("/api/v1/drafts/123456789/league-settings")

        assert response.status_code == 200
        # 0.8 rec points should map to ppr (> 0.75)
        assert response.json()["settings"]["scoring_format"] == "ppr"

    def test_league_settings_response_structure(self, client, mock_draft_details, mock_league_info_ppr):
        """Test response structure is correct."""
        with patch("src.api.main.sleeper_client.get_draft_details", return_value=mock_draft_details):
            with patch("src.api.main.sleeper_client.get_league_info", return_value=mock_league_info_ppr):
                response = client.get("/api/v1/drafts/123456789/league-settings")

        data = response.json()

        # Check top-level structure
        assert "draft_id" in data
        assert "league_id" in data
        assert "settings" in data

        # Check settings structure
        settings = data["settings"]
        assert "league_id" in settings
        assert "scoring_format" in settings
        assert "roster_positions" in settings
        assert "total_rosters" in settings

        # Check values
        assert isinstance(settings["league_id"], str)
        assert isinstance(settings["scoring_format"], str)
        assert isinstance(settings["roster_positions"], list)
        assert isinstance(settings["total_rosters"], int)
