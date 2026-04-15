"""Tests for SleeperClient draft data caching."""

import time
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.data_sources.sleeper_client import SleeperClient


class TestDraftCache:
    """Tests for the TTL cache on get_draft_picks and get_draft_details."""

    def _make_client(self, draft_ttl=2.0):
        """Create a SleeperClient with player cache pre-populated to avoid real API calls."""
        client = SleeperClient(rate_limit_delay=0, draft_ttl=draft_ttl)
        # Pre-populate player cache so _get_player_name etc. don't hit the API
        client._player_cache = {}
        client._player_cache_time = datetime.now()
        return client

    @patch.object(SleeperClient, "_make_request")
    def test_draft_picks_cached_within_ttl(self, mock_request):
        """Second call within TTL should return cached data without hitting API."""
        mock_request.return_value = [
            {
                "pick_no": 1,
                "draft_id": "d1",
                "picked_by": "u1",
                "player_id": "p1",
                "round": 1,
                "timestamp": None,
            }
        ]
        client = self._make_client(draft_ttl=2.0)

        result1 = client.get_draft_picks("d1")
        result2 = client.get_draft_picks("d1")

        assert mock_request.call_count == 1
        assert len(result1) == 1
        assert result1 == result2

    @patch.object(SleeperClient, "_make_request")
    def test_draft_picks_cache_expires(self, mock_request):
        """After TTL expires, should fetch from API again."""
        mock_request.return_value = [
            {
                "pick_no": 1,
                "draft_id": "d1",
                "picked_by": "u1",
                "player_id": "p1",
                "round": 1,
                "timestamp": None,
            }
        ]
        client = self._make_client(draft_ttl=0.1)

        client.get_draft_picks("d1")
        assert mock_request.call_count == 1

        time.sleep(0.15)
        client.get_draft_picks("d1")
        assert mock_request.call_count == 2

    @patch.object(SleeperClient, "_make_request")
    def test_draft_details_cached_within_ttl(self, mock_request):
        """get_draft_details should also use the cache."""
        mock_request.return_value = {
            "draft_order": {"u1": 1, "u2": 2},
            "settings": {"teams": 2, "rounds": 15},
            "metadata": {"name": "Test", "scoring_type": "ppr"},
            "league_id": "L1",
            "status": "in_progress",
            "type": "snake",
            "slot_to_roster_id": {},
        }
        client = self._make_client(draft_ttl=2.0)

        result1 = client.get_draft_details("d1")
        result2 = client.get_draft_details("d1")

        assert mock_request.call_count == 1
        assert result1 == result2
        assert result1["draft_id"] == "d1"

    @patch.object(SleeperClient, "_make_request")
    def test_different_draft_ids_cached_separately(self, mock_request):
        """Different draft IDs should have separate cache entries."""
        mock_request.return_value = []
        client = self._make_client(draft_ttl=2.0)

        client.get_draft_picks("d1")
        client.get_draft_picks("d2")

        assert mock_request.call_count == 2

    @patch.object(SleeperClient, "_make_request")
    def test_clear_draft_cache(self, mock_request):
        """clear_draft_cache should force re-fetch on next call."""
        mock_request.return_value = []
        client = self._make_client(draft_ttl=2.0)

        client.get_draft_picks("d1")
        assert mock_request.call_count == 1

        client.clear_draft_cache()
        client.get_draft_picks("d1")
        assert mock_request.call_count == 2

    @patch.object(SleeperClient, "_make_request")
    def test_cache_disabled_with_zero_ttl(self, mock_request):
        """With draft_ttl=0, every call should hit the API."""
        mock_request.return_value = []
        client = self._make_client(draft_ttl=0)

        client.get_draft_picks("d1")
        client.get_draft_picks("d1")
        client.get_draft_picks("d1")

        assert mock_request.call_count == 3
