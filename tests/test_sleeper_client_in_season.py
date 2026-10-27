"""Unit tests for SleeperClient in-season extensions.

Covers the methods added for the in-season matchup recommendations feature:
``get_league_rosters``, ``get_nfl_state``, ``get_league_transactions``,
``get_trending_players``, the ``Roster`` dataclass, and the ``roster_bench``
helper.

The HTTP layer is mocked by patching ``SleeperClient._make_request`` so no real
network calls are made.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""

from unittest.mock import patch

from src.data_sources.sleeper_client import (
    SleeperClient,
    Roster,
    roster_bench,
)


def _make_client():
    """Create a SleeperClient with rate limiting disabled for fast tests."""
    return SleeperClient(rate_limit_delay=0, draft_ttl=0)


class TestGetLeagueRosters:
    """Tests for get_league_rosters ID normalization and shape."""

    @patch.object(SleeperClient, "_make_request")
    def test_normalizes_all_ids_to_strings(self, mock_request):
        """Int IDs from Sleeper are coerced to strings on the Roster object."""
        mock_request.return_value = [
            {
                "roster_id": 1,
                "owner_id": 123456,
                "starters": [111, 222, 333],
                "players": [111, 222, 333, 444, 555],
                "reserve": [555],
            }
        ]
        client = _make_client()

        rosters = client.get_league_rosters("L1")

        assert len(rosters) == 1
        roster = rosters[0]
        assert isinstance(roster, Roster)
        assert roster.roster_id == "1"
        assert roster.owner_id == "123456"
        assert roster.starters == ["111", "222", "333"]
        assert roster.players == ["111", "222", "333", "444", "555"]
        assert roster.reserve == ["555"]
        # Every element in every slot list is a string
        for slot_list in (roster.starters, roster.players, roster.reserve):
            assert all(isinstance(pid, str) for pid in slot_list)

    @patch.object(SleeperClient, "_make_request")
    def test_drops_none_placeholders_from_slot_lists(self, mock_request):
        """None placeholders (empty starting slots) are dropped, not kept."""
        mock_request.return_value = [
            {
                "roster_id": 2,
                "owner_id": 789,
                "starters": ["111", None, "333", None],
                "players": ["111", "333", None, "444"],
                "reserve": None,
            }
        ]
        client = _make_client()

        roster = client.get_league_rosters("L1")[0]

        assert roster.starters == ["111", "333"]
        assert roster.players == ["111", "333", "444"]
        assert roster.reserve == []

    @patch.object(SleeperClient, "_make_request")
    def test_mixed_int_and_str_ids(self, mock_request):
        """Mixed int/str IDs in the same list all become strings."""
        mock_request.return_value = [
            {
                "roster_id": "3",
                "owner_id": 42,
                "starters": [111, "222"],
                "players": ["111", 222, 333],
                "reserve": [],
            }
        ]
        client = _make_client()

        roster = client.get_league_rosters("L1")[0]

        assert roster.starters == ["111", "222"]
        assert roster.players == ["111", "222", "333"]

    @patch.object(SleeperClient, "_make_request")
    def test_missing_ids_become_empty_string(self, mock_request):
        """Missing roster_id/owner_id normalize to empty strings, not None."""
        mock_request.return_value = [
            {
                "starters": [],
                "players": [],
                "reserve": [],
            }
        ]
        client = _make_client()

        roster = client.get_league_rosters("L1")[0]

        assert roster.roster_id == ""
        assert roster.owner_id == ""

    @patch.object(SleeperClient, "_make_request")
    def test_non_list_response_returns_empty(self, mock_request):
        """A non-list (e.g. dict error body) response yields an empty list."""
        mock_request.return_value = {"error": "not found"}
        client = _make_client()

        assert client.get_league_rosters("L1") == []

    @patch.object(SleeperClient, "_make_request")
    def test_request_error_returns_empty_list(self, mock_request):
        """When _make_request raises, get_league_rosters returns [] (never raises)."""
        mock_request.side_effect = RuntimeError("boom")
        client = _make_client()

        assert client.get_league_rosters("L1") == []


class TestRosterBench:
    """Tests for the roster_bench helper (players - starters - reserve)."""

    def test_bench_is_players_minus_starters_and_reserve(self):
        """Bench excludes both starters and reserve, preserving players order."""
        roster = Roster(
            roster_id="1",
            owner_id="u1",
            starters=["111", "222"],
            players=["111", "222", "333", "444", "555"],
            reserve=["555"],
        )

        bench = roster_bench(roster)

        # 333 and 444 are neither starters nor reserve
        assert bench == ["333", "444"]

    def test_bench_preserves_players_order(self):
        """Bench order follows the players list order, not sorted."""
        roster = Roster(
            roster_id="1",
            owner_id="u1",
            starters=["b"],
            players=["z", "b", "a", "m"],
            reserve=[],
        )

        assert roster_bench(roster) == ["z", "a", "m"]

    def test_bench_empty_when_all_rostered_are_starters_or_reserve(self):
        """No bench players when every player is a starter or on reserve."""
        roster = Roster(
            roster_id="1",
            owner_id="u1",
            starters=["111", "222"],
            players=["111", "222", "333"],
            reserve=["333"],
        )

        assert roster_bench(roster) == []

    @patch.object(SleeperClient, "_make_request")
    def test_bench_from_fetched_roster(self, mock_request):
        """End-to-end: fetch a roster then compute its bench."""
        mock_request.return_value = [
            {
                "roster_id": 1,
                "owner_id": 999,
                "starters": [10, 20],
                "players": [10, 20, 30, 40],
                "reserve": [40],
            }
        ]
        client = _make_client()

        roster = client.get_league_rosters("L1")[0]

        assert roster_bench(roster) == ["30"]


class TestGetNflState:
    """Tests for get_nfl_state normalization and error handling."""

    @patch.object(SleeperClient, "_make_request")
    def test_normalizes_season_to_string_and_passes_through(self, mock_request):
        """season is stringified; week and season_type pass through unchanged."""
        mock_request.return_value = {
            "week": 5,
            "season": 2025,
            "season_type": "regular",
            "leg": 5,
        }
        client = _make_client()

        state = client.get_nfl_state()

        assert state is not None
        assert state["season"] == "2025"
        assert isinstance(state["season"], str)
        assert state["week"] == 5
        assert state["season_type"] == "regular"
        # passthrough preserves other fields
        assert state["leg"] == 5

    @patch.object(SleeperClient, "_make_request")
    def test_season_already_string_stays_string(self, mock_request):
        """A season already given as a string remains a string."""
        mock_request.return_value = {
            "week": 1,
            "season": "2026",
            "season_type": "pre",
        }
        client = _make_client()

        state = client.get_nfl_state()

        assert state["season"] == "2026"

    @patch.object(SleeperClient, "_make_request")
    def test_non_dict_response_returns_none(self, mock_request):
        """A non-dict response yields None."""
        mock_request.return_value = []
        client = _make_client()

        assert client.get_nfl_state() is None

    @patch.object(SleeperClient, "_make_request")
    def test_request_error_returns_none(self, mock_request):
        """When _make_request raises, get_nfl_state returns None (never raises)."""
        mock_request.side_effect = RuntimeError("boom")
        client = _make_client()

        assert client.get_nfl_state() is None


class TestGetLeagueTransactions:
    """Tests for get_league_transactions error handling."""

    @patch.object(SleeperClient, "_make_request")
    def test_returns_list_passthrough(self, mock_request):
        """A list response is returned as-is."""
        payload = [
            {"transaction_id": "t1", "type": "waiver", "status": "complete"},
            {"transaction_id": "t2", "type": "trade", "status": "complete"},
        ]
        mock_request.return_value = payload
        client = _make_client()

        result = client.get_league_transactions("L1", 5)

        assert result == payload

    @patch.object(SleeperClient, "_make_request")
    def test_non_list_response_returns_empty(self, mock_request):
        """A non-list response yields an empty list."""
        mock_request.return_value = {"error": "bad week"}
        client = _make_client()

        assert client.get_league_transactions("L1", 5) == []

    @patch.object(SleeperClient, "_make_request")
    def test_request_error_returns_empty_list(self, mock_request):
        """When _make_request raises, returns [] (never raises)."""
        mock_request.side_effect = RuntimeError("boom")
        client = _make_client()

        assert client.get_league_transactions("L1", 5) == []


class TestGetTrendingPlayers:
    """Tests for get_trending_players normalization and error handling."""

    @patch.object(SleeperClient, "_make_request")
    def test_normalizes_player_id_and_includes_count(self, mock_request):
        """Int player_id is stringified and count is carried through."""
        mock_request.return_value = [
            {"player_id": 4034, "count": 1500},
            {"player_id": "6794", "count": 1200},
        ]
        client = _make_client()

        result = client.get_trending_players(type="add")

        assert result == [
            {"player_id": "4034", "count": 1500},
            {"player_id": "6794", "count": 1200},
        ]
        assert all(isinstance(item["player_id"], str) for item in result)

    @patch.object(SleeperClient, "_make_request")
    def test_missing_count_defaults_to_zero(self, mock_request):
        """An item without a count defaults to 0."""
        mock_request.return_value = [{"player_id": 100}]
        client = _make_client()

        result = client.get_trending_players()

        assert result == [{"player_id": "100", "count": 0}]

    @patch.object(SleeperClient, "_make_request")
    def test_missing_player_id_becomes_empty_string(self, mock_request):
        """An item without a player_id normalizes to empty string."""
        mock_request.return_value = [{"count": 5}]
        client = _make_client()

        result = client.get_trending_players()

        assert result == [{"player_id": "", "count": 5}]

    @patch.object(SleeperClient, "_make_request")
    def test_passes_query_parameters(self, mock_request):
        """lookback_hours and limit are included in the request endpoint."""
        mock_request.return_value = []
        client = _make_client()

        client.get_trending_players(type="drop", lookback_hours=48, limit=10)

        called_endpoint = mock_request.call_args[0][0]
        assert called_endpoint.startswith("/players/nfl/trending/drop")
        assert "lookback_hours=48" in called_endpoint
        assert "limit=10" in called_endpoint

    @patch.object(SleeperClient, "_make_request")
    def test_non_list_response_returns_empty(self, mock_request):
        """A non-list response yields an empty list."""
        mock_request.return_value = {"error": "bad type"}
        client = _make_client()

        assert client.get_trending_players() == []

    @patch.object(SleeperClient, "_make_request")
    def test_request_error_returns_empty_list(self, mock_request):
        """When _make_request raises, returns [] (never raises)."""
        mock_request.side_effect = RuntimeError("boom")
        client = _make_client()

        assert client.get_trending_players() == []
