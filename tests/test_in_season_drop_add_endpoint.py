"""Integration tests for the in-season drop/add API endpoint.

Covers:
- GET /api/v1/in-season/{league_id}/{user_id}/drop-add

Sleeper API calls are mocked via unittest.mock.patch rather than making real
HTTP requests, following the conventions in tests/test_draft_endpoints.py and
tests/test_in_season_roster_endpoints.py.

The endpoint delegates ranking to WaiverService.drop_add_optimization, which
reads projections through src.services.waiver_service.load_projections. We
patch that loader with a deterministic polars DataFrame so the optimizer yields
predictable positive-net-gain pairs. The endpoint's own 503 gate reads
projections through src.api.main._load_week_projections, which we patch to a
non-empty mapping so availability is signalled as "ready".
"""

import polars as pl
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.api.main import app
from src.data_sources.sleeper_client import Roster


class TestInSeasonDropAddEndpoint:
    """Integration tests for GET /in-season/{league_id}/{user_id}/drop-add."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_rosters(self):
        """Two league rosters.

        Roster 1 (owner user_1):
          starters = [p_qb, p_rb, p_wr]
          players  = [p_qb, p_rb, p_wr, p_bench_rb, p_bench_wr, p_ir]
          reserve  = [p_ir]
          => bench = [p_bench_rb, p_bench_wr]  (drop candidates)

        Roster 2 (owner user_2): rosters the remaining universe players so they
        are NOT free agents; p_fa_rb / p_fa_wr stay off every roster so they
        remain the only add candidates.
        """
        return [
            Roster(
                roster_id="1",
                owner_id="user_1",
                starters=["p_qb", "p_rb", "p_wr"],
                players=["p_qb", "p_rb", "p_wr", "p_bench_rb", "p_bench_wr", "p_ir"],
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
        """Deterministic projections producing clear positive-net-gain pairs.

        Bench (drop candidates) are projected low; free agents (add candidates)
        are projected high. Rostered-elsewhere players are included too so the
        FA-pool exclusion is exercised (they must NOT appear as adds).

        Free agents, sorted by projected points desc:
          p_fa_rb (18.0, RB)  > p_fa_wr (15.0, WR)
        Bench:
          p_bench_rb (6.0, RB), p_bench_wr (4.0, WR)

        Positive-net-gain pairs (add - drop > 0), ranked by net_gain desc:
          drop p_bench_wr / add p_fa_rb  -> 14.0
          drop p_bench_rb / add p_fa_rb  -> 12.0
          drop p_bench_wr / add p_fa_wr  -> 11.0
          drop p_bench_rb / add p_fa_wr  ->  9.0
        """
        return pl.DataFrame(
            [
                {"player_id": "p_bench_rb", "player_name": "Bench RB", "position": "RB", "team": "KC", "projected_points": 6.0},
                {"player_id": "p_bench_wr", "player_name": "Bench WR", "position": "WR", "team": "MIA", "projected_points": 4.0},
                {"player_id": "p_fa_rb", "player_name": "FA RB", "position": "RB", "team": "SF", "projected_points": 18.0},
                {"player_id": "p_fa_wr", "player_name": "FA WR", "position": "WR", "team": "BUF", "projected_points": 15.0},
                # Rostered elsewhere -> excluded from FA pool.
                {"player_id": "p_qb2", "player_name": "Josh Allen", "position": "QB", "team": "BUF", "projected_points": 25.0},
                # On user_1's own roster (starter) -> excluded from FA pool.
                {"player_id": "p_qb", "player_name": "Patrick Mahomes", "position": "QB", "team": "KC", "projected_points": 24.0},
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

        - get_league_rosters: 404 gate + FA-pool/roster lookup in the service
        - get_nfl_state: resolves (season, week)
        - get_scoring_format: scoring format for the slate
        - _load_week_projections: the endpoint's own 503 availability gate
        - waiver_service.load_projections: the data the optimizer ranks over
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

    def test_drop_add_success_ranked_pairs(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """200 with DropAddResponse: ranked pairs, net_gain desc, bench->FA."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/drop-add")

        assert response.status_code == 200
        data = response.json()

        # Top-level structure.
        assert data["league_id"] == "LEAGUE1"
        assert data["user_id"] == "user_1"
        assert data["week"] == 8
        assert data["season"] == 2025

        recs = data["recommendations"]
        # 2 bench drops x 2 FA adds = 4 positive-net-gain pairs.
        assert len(recs) == 4

        # Ranking: net_gain descending, rank 1-indexed and contiguous.
        net_gains = [r["net_gain"] for r in recs]
        assert net_gains == sorted(net_gains, reverse=True)
        assert net_gains == [14.0, 12.0, 11.0, 9.0]
        assert [r["rank"] for r in recs] == [1, 2, 3, 4]

        # Every net gain strictly positive and equals add - drop.
        for r in recs:
            assert r["net_gain"] > 0
            assert r["net_gain"] == pytest.approx(
                r["add_projected_points"] - r["drop_projected_points"]
            )

        # Drops are the user's bench players; adds are the free agents.
        bench_ids = {"p_bench_rb", "p_bench_wr"}
        fa_ids = {"p_fa_rb", "p_fa_wr"}
        for r in recs:
            assert r["drop_player_id"] in bench_ids
            assert r["add_player_id"] in fa_ids
            # Never recommend dropping a starter or reserve player.
            assert r["drop_player_id"] not in {"p_qb", "p_rb", "p_wr", "p_ir"}
            # Rostered-elsewhere players are never adds.
            assert r["add_player_id"] not in {"p_qb2", "p_qb"}

        # Top recommendation is the best swap.
        top = recs[0]
        assert top["drop_player_id"] == "p_bench_wr"
        assert top["add_player_id"] == "p_fa_rb"
        assert top["net_gain"] == pytest.approx(14.0)

    def test_drop_add_all_ids_are_strings(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """All IDs in the response are strings."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/drop-add")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["league_id"], str)
        assert isinstance(data["user_id"], str)
        for r in data["recommendations"]:
            assert isinstance(r["drop_player_id"], str)
            assert isinstance(r["add_player_id"], str)
            assert isinstance(r["position"], str)

    # ---- 2. limit parameter ---------------------------------------------

    def test_drop_add_limit_respected(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """?limit=N caps the number of returned pairs to the top N by net gain."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/drop-add?limit=2")

        assert response.status_code == 200
        recs = response.json()["recommendations"]
        assert len(recs) == 2
        # The two highest net-gain pairs survive the cap.
        assert [r["net_gain"] for r in recs] == [14.0, 12.0]
        assert [r["rank"] for r in recs] == [1, 2]

    def test_drop_add_default_limit_is_20(
        self, client, mock_rosters, mock_nfl_state
    ):
        """Default limit (no query param) is 20: more pairs than that are capped."""
        # Build a roster with many bench players and many free agents so the
        # raw pair count exceeds 20, forcing the default cap to bite.
        bench_ids = [f"p_bench_{i}" for i in range(6)]
        fa_ids = [f"p_fa_{i}" for i in range(6)]
        roster = Roster(
            roster_id="1",
            owner_id="user_1",
            starters=["p_qb"],
            players=["p_qb"] + bench_ids,
            reserve=[],
        )
        rosters = [roster]

        rows = [
            {"player_id": "p_qb", "player_name": "QB", "position": "QB", "team": "KC", "projected_points": 20.0},
        ]
        # Bench projected low (1.0); FAs projected high (10.0) -> every one of
        # the 6x6 = 36 pairs has a positive net gain.
        for bid in bench_ids:
            rows.append({"player_id": bid, "player_name": bid, "position": "RB", "team": "KC", "projected_points": 1.0})
        for fid in fa_ids:
            rows.append({"player_id": fid, "player_name": fid, "position": "RB", "team": "SF", "projected_points": 10.0})
        projections_df = pl.DataFrame(rows)

        patches = self._patches(rosters, mock_nfl_state, projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/drop-add")

        assert response.status_code == 200
        recs = response.json()["recommendations"]
        # 36 positive pairs available, default cap keeps only 20.
        assert len(recs) == 20
        assert [r["rank"] for r in recs] == list(range(1, 21))

    # ---- 3. no positive-net-gain pairs ----------------------------------

    def test_drop_add_no_positive_pairs_returns_empty_200(
        self, client, mock_rosters, mock_nfl_state
    ):
        """Projections exist but no FA beats any bench player -> 200 empty list."""
        # Bench projected high, free agents projected low -> no positive gains.
        projections_df = pl.DataFrame(
            [
                {"player_id": "p_bench_rb", "player_name": "Bench RB", "position": "RB", "team": "KC", "projected_points": 20.0},
                {"player_id": "p_bench_wr", "player_name": "Bench WR", "position": "WR", "team": "MIA", "projected_points": 18.0},
                {"player_id": "p_fa_rb", "player_name": "FA RB", "position": "RB", "team": "SF", "projected_points": 3.0},
                {"player_id": "p_fa_wr", "player_name": "FA WR", "position": "WR", "team": "BUF", "projected_points": 2.0},
            ]
        )
        patches = self._patches(mock_rosters, mock_nfl_state, projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/drop-add")

        assert response.status_code == 200
        data = response.json()
        assert data["recommendations"] == []

    # ---- 4. missing league / missing user -------------------------------

    def test_drop_add_404_when_no_rosters(
        self, client, mock_nfl_state, mock_projections_df
    ):
        """404 when the league has no rosters (get_league_rosters returns [])."""
        patches = self._patches([], mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/EMPTY/user_1/drop-add")

        assert response.status_code == 404
        assert "EMPTY" in response.json()["detail"]

    def test_drop_add_404_when_user_not_found(
        self, client, mock_rosters, mock_nfl_state, mock_projections_df
    ):
        """404 when user_id matches no roster owner in the league."""
        patches = self._patches(mock_rosters, mock_nfl_state, mock_projections_df)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            response = client.get("/api/v1/in-season/LEAGUE1/nonexistent_user/drop-add")

        assert response.status_code == 404
        assert "nonexistent_user" in response.json()["detail"]

    # ---- 5. projections pending -----------------------------------------

    def test_drop_add_503_when_projections_pending(
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
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/drop-add")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "Projections pending" in detail
