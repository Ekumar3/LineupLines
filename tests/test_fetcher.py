"""Tests for Sleeper API fetcher."""

import pytest
from unittest.mock import Mock, patch

from src.data_sources.sleeper_client import SleeperClient


class TestGetUserDrafts:
    """Tests for get_user_drafts method."""

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_drafts_success(self, mock_request):
        """Test successful fetch of user drafts."""
        # Mock API response
        mock_response = [
            {
                "draft_id": "123",
                "league_id": "456",
                "status": "in_progress",
                "type": "snake",
                "settings": {"teams": 12, "rounds": 15},
                "metadata": {"name": "Test League", "scoring_type": "ppr"},
                "start_time": 1234567890000,
                "sport": "nfl",
                "season": "2026",
            },
            {
                "draft_id": "789",
                "league_id": "456",
                "status": "complete",
                "type": "snake",
                "settings": {"teams": 10, "rounds": 12},
                "metadata": {"name": "Another League", "scoring_type": "standard"},
                "start_time": 1234567800000,
                "sport": "nfl",
                "season": "2026",
            },
        ]
        mock_request.return_value = mock_response

        client = SleeperClient()
        drafts = client.get_user_drafts("test_user", "nfl", "2026")

        assert len(drafts) == 2
        assert drafts[0]["draft_id"] == "123"
        assert drafts[0]["status"] == "in_progress"
        assert drafts[1]["status"] == "complete"

        # Verify API call
        mock_request.assert_called_once_with("/user/test_user/drafts/nfl/2026")

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_drafts_empty(self, mock_request):
        """Test when user has no drafts."""
        mock_request.return_value = []

        client = SleeperClient()
        drafts = client.get_user_drafts("test_user", "nfl", "2026")

        assert drafts == []

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_drafts_api_error(self, mock_request):
        """Test handling of API errors."""
        mock_request.side_effect = Exception("API Error")

        client = SleeperClient()
        drafts = client.get_user_drafts("test_user", "nfl", "2026")

        # Should return empty list on error
        assert drafts == []

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_drafts_invalid_response(self, mock_request):
        """Test handling of invalid response format."""
        # Return dict instead of list
        mock_request.return_value = {"error": "invalid"}

        client = SleeperClient()
        drafts = client.get_user_drafts("test_user", "nfl", "2026")

        # Should return empty list for invalid format
        assert drafts == []

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_drafts_default_params(self, mock_request):
        """Test default sport and season parameters."""
        mock_request.return_value = []

        client = SleeperClient()
        client.get_user_drafts("test_user")

        # Should use default values
        mock_request.assert_called_once_with("/user/test_user/drafts/nfl/2026")

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_drafts_custom_params(self, mock_request):
        """Test custom sport and season parameters."""
        mock_request.return_value = []

        client = SleeperClient()
        client.get_user_drafts("user123", sport="nba", season="2025")

        # Should use custom values
        mock_request.assert_called_once_with("/user/user123/drafts/nba/2025")


class TestGetUser:
    """Tests for get_user method."""

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_success(self, mock_request):
        """Test successful user lookup."""
        mock_response = {
            "user_id": "123456789",
            "username": "testuser",
            "display_name": "Test User",
            "avatar": "https://example.com/avatar.jpg",
            "verified": False,
        }
        mock_request.return_value = mock_response

        client = SleeperClient()
        user = client.get_user("testuser")

        assert user is not None
        assert user["user_id"] == "123456789"
        assert user["username"] == "testuser"
        assert user["display_name"] == "Test User"

        # Verify API call
        mock_request.assert_called_once_with("/user/testuser")

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_not_found(self, mock_request):
        """Test user not found."""
        mock_request.return_value = None

        client = SleeperClient()
        user = client.get_user("nonexistent")

        assert user is None

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_api_error(self, mock_request):
        """Test API error handling."""
        mock_request.side_effect = Exception("API Error")

        client = SleeperClient()
        user = client.get_user("testuser")

        assert user is None

    @patch("src.data_sources.sleeper_client.SleeperClient._make_request")
    def test_get_user_invalid_response(self, mock_request):
        """Test invalid response format."""
        mock_request.return_value = []  # Return list instead of dict

        client = SleeperClient()
        user = client.get_user("testuser")

        assert user is None
