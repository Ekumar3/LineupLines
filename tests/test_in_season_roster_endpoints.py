"""Integration tests for in-season roster API endpoints.

Covers:
- GET /api/v1/in-season/{league_id}/rosters
- GET /api/v1/in-season/{league_id}/{user_id}/roster

Sleeper API calls are mocked via unittest.mock.patch rather than making real
HTTP requests, following the conventions in tests/test_draft_endpoints.py.
The optional projection/matchup services are allowed to degrade naturally
(their marts don't exist in the test environment), so those response fields
come back null/omitted.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.api.main import app
from src.data_sources.sleeper_client import Roster


class TestInSeasonRosterEndpoints:
    """Integration tests for the in-season roster endpoints."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_rosters(self):
        """Two league rosters with starters, bench, and reserve players.

        Roster 1 (owner user_1):
          players = [p_qb, p_rb, p_wr, p_bench1, p_ir]
          starters = [p_qb, p_rb, p_wr]
          reserve = [p_ir]
          => bench = [p_bench1]  (players - starters - reserve)

        Roster 2 (owner user_2):
          players = [p_qb2, p_bench2]
          starters = [p_qb2]
          reserve = []
          => bench = [p_bench2]
        """
        return [
            Roster(
                roster_id="1",
                owner_id="user_1",
                starters=["p_qb", "p_rb", "p_wr"],
                players=["p_qb", "p_rb", "p_wr", "p_bench1", "p_ir"],
                reserve=["p_ir"],
            ),
            Roster(
                roster_id="2",
                owner_id="user_2",
                starters=["p_qb2"],
                players=["p_qb2", "p_bench2"],
                reserve=[],
            ),
        ]

    @pytest.fixture
    def mock_players(self):
        """Player universe keyed by player_id (as returned by Sleeper get_players)."""
        return {
            "p_qb": {"first_name": "Patrick", "last_name": "Mahomes", "position": "QB", "team": "KC"},
            "p_rb": {"first_name": "Christian", "last_name": "McCaffrey", "position": "RB", "team": "SF"},
            "p_wr": {"first_name": "Tyreek", "last_name": "Hill", "position": "WR", "team": "MIA"},
            "p_bench1": {"first_name": "Jaylen", "last_name": "Waddle", "position": "WR", "team": "MIA"},
            "p_ir": {"first_name": "Hurt", "last_name": "Player", "position": "RB", "team": "DAL", "injury_status": "IR"},
            "p_qb2": {"first_name": "Josh", "last_name": "Allen", "position": "QB", "team": "BUF"},
            "p_bench2": {"first_name": "Stefon", "last_name": "Diggs", "position": "WR", "team": "HOU"},
        }

    @pytest.fixture
    def mock_nfl_state(self):
        """Known week/season from Sleeper NFL state."""
        return {"week": 8, "season": "2025", "season_type": "regular"}

    # ---- helper to wire all the mocks in one place -----------------------

    def _patches(self, rosters, players, nfl_state, scoring="ppr"):
        """Patch all Sleeper/storage dependencies the endpoints touch."""
        return [
            patch("src.api.main.sleeper_client.get_league_rosters", return_value=rosters),
            patch("src.api.main.sleeper_client.get_nfl_state", return_value=nfl_state),
            patch("src.api.main.sleeper_client.get_scoring_format", return_value=scoring),
            patch("src.api.main.load_player_universe", return_value=players),
        ]

    # ---- GET /rosters ----------------------------------------------------

    def test_get_league_rosters_success(self, client, mock_rosters, mock_players, mock_nfl_state):
        """200 with LeagueRostersResponse structure, enriched + categorized players."""
        patches = self._patches(mock_rosters, mock_players, mock_nfl_state)
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/v1/in-season/LEAGUE1/rosters")

        assert response.status_code == 200
        data = response.json()

        # Top-level structure
        assert data["league_id"] == "LEAGUE1"
        assert data["week"] == 8
        assert data["season"] == 2025
        assert len(data["rosters"]) == 2

        # First roster categorization: bench = players - starters - reserve
        roster1 = next(r for r in data["rosters"] if r["user_id"] == "user_1")
        assert roster1["roster_id"] == "1"
        assert [p["player_id"] for p in roster1["starters"]] == ["p_qb", "p_rb", "p_wr"]
        assert [p["player_id"] for p in roster1["bench"]] == ["p_bench1"]
        assert [p["player_id"] for p in roster1["reserve"]] == ["p_ir"]

        # Player enrichment: name/position/team pulled from the universe
        qb = roster1["starters"][0]
        assert qb["player_name"] == "Patrick Mahomes"
        assert qb["position"] == "QB"
        assert qb["team"] == "KC"

        # Second roster
        roster2 = next(r for r in data["rosters"] if r["user_id"] == "user_2")
        assert [p["player_id"] for p in roster2["starters"]] == ["p_qb2"]
        assert [p["player_id"] for p in roster2["bench"]] == ["p_bench2"]
        assert roster2["reserve"] == []

    def test_get_league_rosters_404_when_no_rosters(self, client, mock_players, mock_nfl_state):
        """404 when the league has no rosters (get_league_rosters returns [])."""
        patches = self._patches([], mock_players, mock_nfl_state)
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/v1/in-season/EMPTY/rosters")

        assert response.status_code == 404
        assert "EMPTY" in response.json()["detail"]

    def test_get_league_rosters_graceful_degradation(self, client, mock_rosters, mock_players, mock_nfl_state):
        """Projections unavailable -> still 200, projected_points degrades to null.

        Projections and matchup grades are independent: when the projection
        parquet isn't built, projected_points is null, but the matchup grade is
        resolved separately from mart_matchup_grade (which carries opponent rows
        from the schedule even for unplayed weeks). So a matchup_grade may be a
        populated object with real signals, or null when no grade is available —
        either way the service never raises and signals stay in the valid set.
        """
        patches = self._patches(mock_rosters, mock_players, mock_nfl_state)
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/v1/in-season/LEAGUE1/rosters")

        assert response.status_code == 200
        data = response.json()
        valid_signals = {"favorable", "neutral", "unfavorable"}
        for roster in data["rosters"]:
            for player in roster["starters"] + roster["bench"] + roster["reserve"]:
                # Projections degrade to null when the mart isn't built.
                assert player["projected_points"] is None

                grade = player["matchup_grade"]
                if grade is not None:
                    # Matchup grade is independent of projections. Signals must
                    # be valid; they are NOT forced to neutral.
                    assert grade["pass_signal"] in valid_signals
                    assert grade["rush_signal"] in valid_signals
                    assert grade["overall_signal"] in valid_signals

    def test_get_league_rosters_all_ids_are_strings(self, client, mock_rosters, mock_players, mock_nfl_state):
        """All IDs in the response are strings."""
        patches = self._patches(mock_rosters, mock_players, mock_nfl_state)
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/v1/in-season/LEAGUE1/rosters")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["league_id"], str)
        for roster in data["rosters"]:
            assert isinstance(roster["league_id"], str)
            assert isinstance(roster["user_id"], str)
            assert isinstance(roster["roster_id"], str)
            for player in roster["starters"] + roster["bench"] + roster["reserve"]:
                assert isinstance(player["player_id"], str)

    # ---- GET /{user_id}/roster ------------------------------------------

    def test_get_user_roster_success(self, client, mock_rosters, mock_players, mock_nfl_state):
        """200 with RosterResponse for the matching owner."""
        patches = self._patches(mock_rosters, mock_players, mock_nfl_state)
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/roster")

        assert response.status_code == 200
        data = response.json()
        assert data["league_id"] == "LEAGUE1"
        assert data["user_id"] == "user_1"
        assert data["roster_id"] == "1"
        assert data["week"] == 8
        assert data["season"] == 2025
        assert [p["player_id"] for p in data["starters"]] == ["p_qb", "p_rb", "p_wr"]
        assert [p["player_id"] for p in data["bench"]] == ["p_bench1"]
        assert [p["player_id"] for p in data["reserve"]] == ["p_ir"]

    def test_get_user_roster_404_when_no_rosters(self, client, mock_players, mock_nfl_state):
        """404 when the league has no rosters at all."""
        patches = self._patches([], mock_players, mock_nfl_state)
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/v1/in-season/EMPTY/user_1/roster")

        assert response.status_code == 404

    def test_get_user_roster_404_when_user_not_found(self, client, mock_rosters, mock_players, mock_nfl_state):
        """404 when user_id doesn't match any roster owner."""
        patches = self._patches(mock_rosters, mock_players, mock_nfl_state)
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/v1/in-season/LEAGUE1/nonexistent_user/roster")

        assert response.status_code == 404
        assert "nonexistent_user" in response.json()["detail"]

    def test_get_user_roster_all_ids_are_strings(self, client, mock_rosters, mock_players, mock_nfl_state):
        """All IDs in the user roster response are strings."""
        patches = self._patches(mock_rosters, mock_players, mock_nfl_state)
        with patches[0], patches[1], patches[2], patches[3]:
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/roster")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["league_id"], str)
        assert isinstance(data["user_id"], str)
        assert isinstance(data["roster_id"], str)
        for player in data["starters"] + data["bench"] + data["reserve"]:
            assert isinstance(player["player_id"], str)
