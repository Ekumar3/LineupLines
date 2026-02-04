"""Tests for draft-related API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from src.api.main import app


class TestGetUserDrafts:
    """Tests for GET /api/v1/users/{user_id}/drafts endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_draft_list(self):
        """Mock draft list response."""
        return [
            {
                "draft_id": "123",
                "league_id": "456",
                "status": "in_progress",
                "type": "snake",
                "settings": {"teams": 12, "rounds": 15, "reversal_round": 1},
                "metadata": {"name": "Test League", "scoring_type": "ppr"},
                "start_time": 1735689600000,
                "sport": "nfl",
                "season": "2026",
            },
            {
                "draft_id": "789",
                "league_id": "456",
                "status": "pre_draft",
                "type": "snake",
                "settings": {"teams": 12, "rounds": 15},
                "metadata": {"name": "Another League", "scoring_type": "standard"},
                "start_time": 1735700000000,
                "sport": "nfl",
                "season": "2026",
            },
            {
                "draft_id": "999",
                "league_id": "111",
                "status": "complete",
                "type": "snake",
                "settings": {"teams": 10, "rounds": 12},
                "metadata": {"name": "Old League", "scoring_type": "half_ppr"},
                "start_time": 1700000000000,
                "sport": "nfl",
                "season": "2026",
            },
        ]

    def test_get_user_drafts_success(self, client, mock_draft_list):
        """Test successful retrieval of user drafts by ID."""
        with patch(
            "src.api.main.sleeper_client.get_user_drafts", return_value=mock_draft_list
        ):
            response = client.get("/api/v1/users/by-id/test_user/drafts")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "test_user"
        assert data["total_drafts"] == 3
        assert data["active_drafts"] == 2
        assert len(data["drafts"]) == 3

    def test_get_user_drafts_with_filter_active(self, client, mock_draft_list):
        """Test filtering for active drafts only."""
        with patch(
            "src.api.main.sleeper_client.get_user_drafts", return_value=mock_draft_list
        ):
            response = client.get(
                "/api/v1/users/by-id/test_user/drafts?status_filter=active"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total_drafts"] == 3
        assert data["active_drafts"] == 2
        assert len(data["drafts"]) == 2
        # All returned drafts should be active
        for draft in data["drafts"]:
            assert draft["status"] in ["in_progress", "pre_draft"]

    def test_get_user_drafts_with_filter_complete(self, client, mock_draft_list):
        """Test filtering for complete drafts only."""
        with patch(
            "src.api.main.sleeper_client.get_user_drafts", return_value=mock_draft_list
        ):
            response = client.get(
                "/api/v1/users/by-id/test_user/drafts?status_filter=complete"
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["status"] == "complete"

    def test_get_user_drafts_not_found(self, client):
        """Test 404 when user has no drafts."""
        with patch("src.api.main.sleeper_client.get_user_drafts", return_value=[]):
            response = client.get("/api/v1/users/by-id/nonexistent_user/drafts")

        assert response.status_code == 404
        assert "No drafts found" in response.json()["detail"]

    def test_get_user_drafts_server_error(self, client):
        """Test 500 on server error."""
        with patch(
            "src.api.main.sleeper_client.get_user_drafts",
            side_effect=Exception("DB Error"),
        ):
            response = client.get("/api/v1/users/by-id/test_user/drafts")

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]

    def test_get_active_drafts_endpoint(self, client, mock_draft_list):
        """Test convenience endpoint for active drafts."""
        with patch(
            "src.api.main.sleeper_client.get_user_drafts", return_value=mock_draft_list
        ):
            response = client.get("/api/v1/users/by-id/test_user/drafts/active")

        assert response.status_code == 200
        data = response.json()
        assert data["active_drafts"] == 2
        assert len(data["drafts"]) == 2
        # All should be active status
        for draft in data["drafts"]:
            assert draft["status"] in ["in_progress", "pre_draft"]

    def test_draft_sorting(self, client, mock_draft_list):
        """Test that drafts are sorted correctly."""
        with patch(
            "src.api.main.sleeper_client.get_user_drafts", return_value=mock_draft_list
        ):
            response = client.get("/api/v1/users/by-id/test_user/drafts")

        drafts = response.json()["drafts"]
        # Should be sorted: in_progress first, then pre_draft, then complete
        assert drafts[0]["status"] == "in_progress"
        assert drafts[1]["status"] == "pre_draft"
        assert drafts[2]["status"] == "complete"

    def test_custom_sport_and_season(self, client, mock_draft_list):
        """Test passing custom sport and season parameters."""
        with patch(
            "src.api.main.sleeper_client.get_user_drafts",
            return_value=mock_draft_list,
        ) as mock_get:
            response = client.get("/api/v1/users/by-id/test_user/drafts?sport=nba&season=2025")

        assert response.status_code == 200
        mock_get.assert_called_once_with("test_user", "nba", "2025")

    def test_invalid_status_filter(self, client):
        """Test that invalid status_filter is rejected."""
        response = client.get(
            "/api/v1/users/by-id/test_user/drafts?status_filter=invalid"
        )

        # Should get validation error (422)
        assert response.status_code == 422

    def test_draft_sorting_within_status(self, client):
        """Test that drafts are sorted by start_time within same status."""
        # Create three pre_draft drafts with different start times
        drafts = [
            {
                "draft_id": "old",
                "league_id": "1",
                "status": "pre_draft",
                "type": "snake",
                "settings": {"teams": 12, "rounds": 15},
                "metadata": {"name": "Old"},
                "start_time": 1000000000000,  # Oldest
                "sport": "nfl",
                "season": "2026",
            },
            {
                "draft_id": "newest",
                "league_id": "1",
                "status": "pre_draft",
                "type": "snake",
                "settings": {"teams": 12, "rounds": 15},
                "metadata": {"name": "Newest"},
                "start_time": 2000000000000,  # Newest
                "sport": "nfl",
                "season": "2026",
            },
            {
                "draft_id": "middle",
                "league_id": "1",
                "status": "pre_draft",
                "type": "snake",
                "settings": {"teams": 12, "rounds": 15},
                "metadata": {"name": "Middle"},
                "start_time": 1500000000000,  # Middle
                "sport": "nfl",
                "season": "2026",
            },
        ]

        with patch("src.api.main.sleeper_client.get_user_drafts", return_value=drafts):
            response = client.get("/api/v1/users/by-id/test_user/drafts")

        returned_drafts = response.json()["drafts"]
        # Newest (highest start_time) should come first
        assert returned_drafts[0]["draft_id"] == "newest"
        assert returned_drafts[1]["draft_id"] == "middle"
        assert returned_drafts[2]["draft_id"] == "old"


class TestAPIDocumentation:
    """Tests for API documentation and schema."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_openapi_schema(self, client):
        """Test that OpenAPI schema is generated correctly."""
        response = client.get("/openapi.json")

        assert response.status_code == 200
        schema = response.json()

        # Verify endpoints are documented
        assert "/api/v1/users/lookup/{username}" in schema["paths"]
        assert "/api/v1/users/{username}/drafts" in schema["paths"]
        assert "/api/v1/users/by-id/{user_id}/drafts" in schema["paths"]
        assert "/api/v1/users/by-id/{user_id}/drafts/active" in schema["paths"]
        assert "/api/v1/drafts/{draft_id}/picks" in schema["paths"]

        # Verify models are documented
        assert "UserDraftsResponse" in schema["components"]["schemas"]
        assert "DraftSummary" in schema["components"]["schemas"]
        assert "DraftSettings" in schema["components"]["schemas"]
        assert "UserLookupResponse" in schema["components"]["schemas"]
        assert "DraftPicksResponse" in schema["components"]["schemas"]
        assert "PickDetail" in schema["components"]["schemas"]

    def test_api_docs_endpoint(self, client):
        """Test that OpenAPI docs endpoint exists."""
        response = client.get("/docs")

        assert response.status_code == 200
        assert "swagger" in response.text.lower()

    def test_health_endpoint(self, client):
        """Test health check endpoint still works."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "draft-helper"}


class TestUserLookup:
    """Tests for user lookup endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_user_data(self):
        """Mock user data response."""
        return {
            "user_id": "123456789",
            "username": "testuser",
            "display_name": "Test User",
            "avatar": "https://example.com/avatar.jpg",
            "verified": False,
        }

    def test_lookup_user_success(self, client, mock_user_data):
        """Test successful user lookup."""
        with patch(
            "src.api.main.sleeper_client.get_user", return_value=mock_user_data
        ):
            response = client.get("/api/v1/users/lookup/testuser")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "123456789"
        assert data["username"] == "testuser"
        assert data["display_name"] == "Test User"

    def test_lookup_user_not_found(self, client):
        """Test user not found."""
        with patch("src.api.main.sleeper_client.get_user", return_value=None):
            response = client.get("/api/v1/users/lookup/nonexistent")

        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]

    def test_lookup_user_server_error(self, client):
        """Test server error during lookup."""
        with patch(
            "src.api.main.sleeper_client.get_user", side_effect=Exception("API Error")
        ):
            response = client.get("/api/v1/users/lookup/testuser")

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]


class TestGetDraftsByUsername:
    """Tests for get drafts by username endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_user_data(self):
        """Mock user data."""
        return {
            "user_id": "123456789",
            "username": "testuser",
            "display_name": "Test User",
        }

    @pytest.fixture
    def mock_draft_list(self):
        """Mock draft list response."""
        return [
            {
                "draft_id": "123",
                "league_id": "456",
                "status": "in_progress",
                "type": "snake",
                "settings": {"teams": 12, "rounds": 15},
                "metadata": {"name": "Test League", "scoring_type": "ppr"},
                "start_time": 1735689600000,
                "sport": "nfl",
                "season": "2026",
            }
        ]

    def test_get_drafts_by_username_success(
        self, client, mock_user_data, mock_draft_list
    ):
        """Test getting drafts by username."""
        with patch(
            "src.api.main.sleeper_client.get_user", return_value=mock_user_data
        ):
            with patch(
                "src.api.main.sleeper_client.get_user_drafts",
                return_value=mock_draft_list,
            ):
                response = client.get("/api/v1/users/testuser/drafts")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "123456789"
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["draft_id"] == "123"

    def test_get_drafts_by_username_user_not_found(self, client):
        """Test when username doesn't exist."""
        with patch("src.api.main.sleeper_client.get_user", return_value=None):
            response = client.get("/api/v1/users/nonexistent/drafts")

        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]

    def test_get_drafts_by_username_with_filter(
        self, client, mock_user_data, mock_draft_list
    ):
        """Test filtering drafts by username."""
        with patch(
            "src.api.main.sleeper_client.get_user", return_value=mock_user_data
        ):
            with patch(
                "src.api.main.sleeper_client.get_user_drafts",
                return_value=mock_draft_list,
            ):
                response = client.get(
                    "/api/v1/users/testuser/drafts?status_filter=active"
                )

        assert response.status_code == 200
        data = response.json()
        assert len(data["drafts"]) == 1
        assert data["drafts"][0]["status"] == "in_progress"

    def test_get_drafts_by_username_no_drafts(self, client, mock_user_data):
        """Test when user has no drafts."""
        with patch(
            "src.api.main.sleeper_client.get_user", return_value=mock_user_data
        ):
            with patch(
                "src.api.main.sleeper_client.get_user_drafts", return_value=[]
            ):
                response = client.get("/api/v1/users/testuser/drafts")

        assert response.status_code == 404
        assert "No drafts found" in response.json()["detail"]


class TestGetDraftPicks:
    """Tests for GET /api/v1/drafts/{draft_id}/picks endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_picks_list(self):
        """Mock draft picks response."""
        from src.data_sources.sleeper_client import DraftPick
        from datetime import datetime

        return [
            DraftPick(
                pick_no=1,
                draft_id="123",
                roster_id=1,
                player_id="2307",
                player_name="Christian McCaffrey",
                position="RB",
                team="SF",
                round=1,
                timestamp=datetime(2026, 8, 15, 19, 30, 0),
            ),
            DraftPick(
                pick_no=2,
                draft_id="123",
                roster_id=2,
                player_id="4866",
                player_name="CeeDee Lamb",
                position="WR",
                team="DAL",
                round=1,
                timestamp=datetime(2026, 8, 15, 19, 32, 0),
            ),
        ]

    def test_get_draft_picks_success(self, client, mock_picks_list):
        """Test successful retrieval of draft picks."""
        with patch(
            "src.api.main.sleeper_client.get_draft_picks", return_value=mock_picks_list
        ):
            response = client.get("/api/v1/drafts/123/picks")

        assert response.status_code == 200
        data = response.json()
        assert data["draft_id"] == "123"
        assert data["total_picks"] == 2
        assert len(data["picks"]) == 2

        # Verify first pick
        assert data["picks"][0]["pick_no"] == 1
        assert data["picks"][0]["player_name"] == "Christian McCaffrey"
        assert data["picks"][0]["position"] == "RB"
        assert data["picks"][0]["team"] == "SF"

    def test_get_draft_picks_not_found(self, client):
        """Test 404 when draft has no picks."""
        with patch("src.api.main.sleeper_client.get_draft_picks", return_value=[]):
            response = client.get("/api/v1/drafts/nonexistent/picks")

        assert response.status_code == 404
        assert "No picks found" in response.json()["detail"]

    def test_get_draft_picks_server_error(self, client):
        """Test 500 on server error."""
        with patch(
            "src.api.main.sleeper_client.get_draft_picks",
            side_effect=Exception("API Error"),
        ):
            response = client.get("/api/v1/drafts/123/picks")

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]

    def test_draft_picks_order(self, client, mock_picks_list):
        """Test that picks are returned in chronological order."""
        with patch(
            "src.api.main.sleeper_client.get_draft_picks", return_value=mock_picks_list
        ):
            response = client.get("/api/v1/drafts/123/picks")

        picks = response.json()["picks"]
        assert picks[0]["pick_no"] == 1
        assert picks[1]["pick_no"] == 2

    def test_draft_picks_enrichment(self, client, mock_picks_list):
        """Test that picks include enriched player data."""
        with patch(
            "src.api.main.sleeper_client.get_draft_picks", return_value=mock_picks_list
        ):
            response = client.get("/api/v1/drafts/123/picks")

        picks = response.json()["picks"]
        # Verify all picks have enriched data
        for pick in picks:
            assert "player_name" in pick
            assert "position" in pick
            assert "team" in pick
            assert pick["player_name"] != ""  # Not just player_id
