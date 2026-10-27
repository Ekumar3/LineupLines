"""Integration tests for the in-season waiver API endpoint.

Covers:
- GET /api/v1/in-season/{league_id}/waiver

Sleeper API calls are mocked via unittest.mock.patch rather than making real
HTTP requests, following the conventions in tests/test_draft_endpoints.py,
tests/test_in_season_roster_endpoints.py and
tests/test_in_season_drop_add_endpoint.py.

The endpoint delegates ranking to WaiverService.free_agent_ranking, which reads
projections through src.services.waiver_service.load_projections. We patch that
loader with a deterministic polars DataFrame so the ranking is predictable. The
endpoint's own 503 gate reads projections through
src.api.main._load_week_projections, which we patch to a non-empty mapping so
availability is signalled as "ready".
"""

import polars as pl
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.api.main import app
from src.data_sources.sleeper_client import Roster


class TestInSeasonWaiverEndpoint:
    """Integration tests for GET /in-season/{league_id}/waiver."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_rosters(self):
        """Two league rosters establishing the rostered set.

        Rostered league-wide: p_qb, p_rb, p_wr, p_ir (roster 1) + p_qb2
        (roster 2). Everything else in the projection set is a free agent.
        """
        return [
            Roster(
                roster_id="1",
                owner_id="user_1",
                starters=["p_qb", "p_rb", "p_wr"],
                players=["p_qb", "p_rb", "p_wr", "p_ir"],
                reserve=["p_ir"],
            ),
            Roster(
                roster_id="2",
                owner_id="user_2",
                starters=["p_qb2"],
                players=["p_qb2"],
                reserve=[],
            ),
        ]

    @pytest.fixture
    def mock_nfl_state(self):
        return {"week": 8, "season": "2025", "season_type": "regular"}

    @pytest.fixture
    def mock_projections_df(self):
        """Deterministic projections with a mix of free agents and rostered.

        Free agents (not on any roster), by projected points desc:
          p_fa_rb (18.0, RB) > p_fa_wr (15.0, WR) > p_fa_te (9.0, TE)
            > p_fa_rb2 (7.5, RB)
        Rostered-elsewhere players are included so the FA-pool exclusion is
        exercised (they must NOT appear in the ranking).
        """
        return pl.DataFrame(
            [
                {"player_id": "p_fa_rb", "player_name": "FA RB", "position": "RB", "team": "SF", "projected_points": 18.0},
                {"player_id": "p_fa_wr", "player_name": "FA WR", "position": "WR", "team": "BUF", "projected_points": 15.0},
                {"player_id": "p_fa_te", "player_name": "FA TE", "position": "TE", "team": "DET", "projected_points": 9.0},
                {"player_id": "p_fa_rb2", "player_name": "FA RB Two", "position": "RB", "team": "NYJ", "projected_points": 7.5},
                # Rostered players -> excluded from FA pool.
                {"player_id": "p_qb", "player_name": "Patrick Mahomes", "position": "QB", "team": "KC", "projected_points": 25.0},
                {"player_id": "p_rb", "player_name": "Rostered RB", "position": "RB", "team": "KC", "projected_points": 20.0},
                {"player_id": "p_wr", "player_name": "Rostered WR", "position": "WR", "team": "MIA", "projected_points": 19.0},
                {"player_id": "p_ir", "player_name": "IR Guy", "position": "WR", "team": "LAR", "projected_points": 12.0},
                {"player_id": "p_qb2", "player_name": "Josh Allen", "position": "QB", "team": "BUF", "projected_points": 24.0},
            ]
        )

    # ---- helpers ---------------------------------------------------------

    def _patches(
        self,
        rosters,
        nfl_state,
        projections_df,
        *,
        week_projections=None,
        scoring="ppr",
        trending=None,
    ):
        """Patch every dependency the endpoint + service touch.

        - get_league_rosters: 404 gate + FA-pool lookup in the service
        - get_nfl_state: resolves (season, week)
        - get_scoring_format: scoring format for the slate
        - _load_week_projections: the endpoint's own 503 availability gate
        - waiver_service.load_projections: the data the ranking is built over
        - get_trending_players: optional tiebreak augmentation in the service
        """
        if week_projections is None:
            # Non-empty -> availability gate passes (503 not raised).
            week_projections = {"p_fa_rb": 18.0}
        return [
            patch("src.api.main.sleeper_client.get_league_rosters", return_value=rosters),
            patch("src.api.main.sleeper_client.get_nfl_state", return_value=nfl_state),
            patch("src.api.main.sleeper_client.get_scoring_format", return_value=scoring),
            patch("src.api.main._load_week_projections", return_value=week_projections),
            patch("src.services.waiver_service.load_projections", return_value=projections_df),
            patch("src.api.main.sleeper_client.get_trending_players", return_value=(trending or [])),
        ]

    # ---- 1. success ------------------------------------------------------

    def test_waiver_success_ranked_free_agents(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """200 with WaiverResponse: FAs ranked by projected points desc."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/waiver")

        assert response.status_code == 200
        data = response.json()

        # Top-level structure.
        assert data["league_id"] == "LEAGUE1"
        assert data["week"] == 8
        assert data["season"] == 2025
        assert data["position"] is None

        recs = data["recommendations"]
        # Four free agents remain after excluding the five rostered players.
        assert len(recs) == 4

        fa_ids = [r["player_id"] for r in recs]
        assert fa_ids == ["p_fa_rb", "p_fa_wr", "p_fa_te", "p_fa_rb2"]

        # Ranking: projected_points descending.
        points = [r["projected_points"] for r in recs]
        assert points == sorted(points, reverse=True)
        assert points == [18.0, 15.0, 9.0, 7.5]

        # Rank is 1-indexed and contiguous.
        assert [r["rank"] for r in recs] == [1, 2, 3, 4]

    def test_waiver_excludes_rostered_players(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """Players rostered anywhere in the league never appear as free agents."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/waiver")

        assert response.status_code == 200
        returned_ids = {r["player_id"] for r in response.json()["recommendations"]}
        rostered_ids = {"p_qb", "p_rb", "p_wr", "p_ir", "p_qb2"}
        assert returned_ids.isdisjoint(rostered_ids)

    def test_waiver_all_ids_are_strings(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """All IDs in the response are strings."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/waiver")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["league_id"], str)
        for r in data["recommendations"]:
            assert isinstance(r["player_id"], str)
            assert isinstance(r["position"], str)
            assert isinstance(r["team"], str)

    def test_waiver_merges_trending_add_counts(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """Trending-add counts are merged into recs when Sleeper data exists."""
        trending = [
            {"player_id": "p_fa_rb", "count": 15230},
            {"player_id": "p_fa_te", "count": 4100},
        ]
        patches = self._patches(
            mock_rosters, mock_nfl_state, mock_projections_df, trending=trending
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/waiver")

        assert response.status_code == 200
        by_id = {r["player_id"]: r for r in response.json()["recommendations"]}
        assert by_id["p_fa_rb"]["trending_add_count"] == 15230
        assert by_id["p_fa_te"]["trending_add_count"] == 4100
        # No trending data for this FA -> null.
        assert by_id["p_fa_wr"]["trending_add_count"] is None

    # ---- 2. position filter ---------------------------------------------

    def test_waiver_position_filter_returns_only_that_position(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """?position=RB returns only RB free agents, still ranked by points."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/waiver?position=RB")

        assert response.status_code == 200
        data = response.json()
        assert data["position"] == "RB"

        recs = data["recommendations"]
        # Only the two RB free agents (p_fa_rb, p_fa_rb2) survive the filter.
        assert [r["player_id"] for r in recs] == ["p_fa_rb", "p_fa_rb2"]
        assert all(r["position"] == "RB" for r in recs)
        assert [r["projected_points"] for r in recs] == [18.0, 7.5]
        assert [r["rank"] for r in recs] == [1, 2]

    # ---- 3. limit parameter ---------------------------------------------

    def test_waiver_limit_respected(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """?limit=N caps the number of returned free agents to the top N."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/waiver?limit=2")

        assert response.status_code == 200
        recs = response.json()["recommendations"]
        assert len(recs) == 2
        # The two highest-projected free agents survive the cap.
        assert [r["player_id"] for r in recs] == ["p_fa_rb", "p_fa_wr"]
        assert [r["rank"] for r in recs] == [1, 2]

    # ---- 4. empty results (no FAs rank) ---------------------------------

    def test_waiver_empty_when_every_projected_player_rostered(
        self, client, mock_nfl_state
    ):
        """Projections present but every projected player is rostered -> 200 empty.

        Availability gate still passes (projections exist), so the endpoint
        must return HTTP 200 with an empty recommendation list, not 503.
        """
        rosters = [
            Roster(
                roster_id="1",
                owner_id="user_1",
                starters=["p_a"],
                players=["p_a", "p_b"],
                reserve=[],
            ),
            Roster(
                roster_id="2",
                owner_id="user_2",
                starters=["p_c"],
                players=["p_c", "p_d"],
                reserve=[],
            ),
        ]
        # Every projected player_id is on a roster above -> FA pool is empty.
        projections_df = pl.DataFrame(
            [
                {"player_id": "p_a", "player_name": "A", "position": "QB", "team": "KC", "projected_points": 20.0},
                {"player_id": "p_b", "player_name": "B", "position": "RB", "team": "KC", "projected_points": 15.0},
                {"player_id": "p_c", "player_name": "C", "position": "WR", "team": "SF", "projected_points": 12.0},
                {"player_id": "p_d", "player_name": "D", "position": "TE", "team": "SF", "projected_points": 8.0},
            ]
        )
        patches = self._patches(rosters, mock_nfl_state, projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/waiver")

        assert response.status_code == 200
        assert response.json()["recommendations"] == []

    # ---- 5. missing league ----------------------------------------------

    def test_waiver_404_when_no_rosters(
        self, client, mock_nfl_state, mock_projections_df
    ):
        """404 when the league has no rosters (get_league_rosters returns [])."""
        patches = self._patches([], mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/EMPTY/waiver")

        assert response.status_code == 404
        assert "EMPTY" in response.json()["detail"]

    # ---- 6. projections pending -----------------------------------------

    def test_waiver_503_when_projections_pending(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """503 when no projections are available yet for the slate.

        The endpoint probes availability via _load_week_projections; an empty
        mapping means projections are pending even though rosters resolve.
        """
        patches = self._patches(
            mock_rosters,
            mock_nfl_state,
            mock_projections_df,
            week_projections={},  # availability gate: nothing ready yet
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/waiver")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "Projections pending" in detail
