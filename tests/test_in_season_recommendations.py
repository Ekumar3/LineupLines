"""Integration tests for the in-season start/sit recommendations endpoint.

Covers:
- GET /api/v1/in-season/{league_id}/{user_id}/recommendations

Sleeper API calls and the optional projection/matchup services are mocked via
unittest.mock.patch rather than making real HTTP calls or reading dbt marts,
following the TestClient conventions in tests/test_in_season_roster_endpoints.py.

The lineup optimizer (apply_exclusions / assign_lineup) is exercised for real:
OptimizerPlayer objects are built from the mocked projections and the mocked
league roster_positions, so START/SIT labels and the optimal_lineup_set flag
reflect the genuine max-weight bipartite matching.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.api.main import app
from src.data_sources.sleeper_client import Roster
from src.services.matchup_grade import MatchupGrade


class TestInSeasonRecommendationsEndpoint:
    """Integration tests for the start/sit recommendations endpoint."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_rosters(self):
        """Two league rosters.

        Roster 1 (owner user_1) has a full complement for the league slots
        below plus one bench player and one IR (reserve) player:
          players  = [p_qb, p_rb, p_wr, p_te, p_flex, p_bench, p_ir]
          starters = [p_qb, p_rb, p_wr, p_te, p_flex]
          reserve  = [p_ir]
          => bench = [p_bench]  (players - starters - reserve)

        Roster 2 (owner user_2) is unrelated and used only for lookups.
        """
        return [
            Roster(
                roster_id="1",
                owner_id="user_1",
                starters=["p_qb", "p_rb", "p_wr", "p_te", "p_flex"],
                players=["p_qb", "p_rb", "p_wr", "p_te", "p_flex", "p_bench", "p_ir"],
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
    def mock_players(self):
        """Player universe keyed by player_id (Sleeper get_players shape)."""
        return {
            "p_qb": {"first_name": "Patrick", "last_name": "Mahomes", "position": "QB", "team": "KC"},
            "p_rb": {"first_name": "Christian", "last_name": "McCaffrey", "position": "RB", "team": "SF"},
            "p_wr": {"first_name": "Tyreek", "last_name": "Hill", "position": "WR", "team": "MIA"},
            "p_te": {"first_name": "Travis", "last_name": "Kelce", "position": "TE", "team": "KC"},
            "p_flex": {"first_name": "Bijan", "last_name": "Robinson", "position": "RB", "team": "ATL"},
            "p_bench": {"first_name": "Jaylen", "last_name": "Waddle", "position": "WR", "team": "MIA"},
            "p_ir": {"first_name": "Hurt", "last_name": "Player", "position": "RB", "team": "DAL", "injury_status": "IR"},
            "p_qb2": {"first_name": "Josh", "last_name": "Allen", "position": "QB", "team": "BUF"},
        }

    @pytest.fixture
    def mock_projections(self):
        """Projected points keyed by player_id (what _load_week_projections returns).

        Starters out-score the bench so the optimal lineup clearly starts the
        five intended players and sits p_bench.
        """
        return {
            "p_qb": 25.0,
            "p_rb": 22.0,
            "p_wr": 18.0,
            "p_te": 14.0,
            "p_flex": 16.0,
            "p_bench": 5.0,
            "p_ir": 30.0,  # high points, but on reserve -> must still be excluded
        }

    @pytest.fixture
    def mock_nfl_state(self):
        return {"week": 8, "season": "2025", "season_type": "regular"}

    @pytest.fixture
    def roster_positions(self):
        """League starting slots + bench + IR. One FLEX (RB/WR/TE eligible)."""
        return ["QB", "RB", "WR", "TE", "FLEX", "BN", "IR"]

    @pytest.fixture
    def mock_league_info(self, roster_positions):
        return {"roster_positions": roster_positions}

    # ---- patch helpers ---------------------------------------------------

    def _patches(
        self,
        rosters,
        players,
        projections,
        nfl_state,
        league_info,
        matchup_service=None,
        scoring="ppr",
    ):
        """Patch every dependency the recommendations endpoint touches.

        Returns a list of patch context managers; callers enter them with an
        ExitStack (see _enter)."""
        return [
            patch("src.api.main.sleeper_client.get_league_rosters", return_value=rosters),
            patch("src.api.main.sleeper_client.get_nfl_state", return_value=nfl_state),
            patch("src.api.main.sleeper_client.get_scoring_format", return_value=scoring),
            patch("src.api.main.sleeper_client.get_league_info", return_value=league_info),
            patch("src.api.main.load_player_universe", return_value=players),
            patch("src.api.main._load_week_projections", return_value=projections),
            patch("src.api.main._get_matchup_grade_service", return_value=matchup_service),
        ]

    @staticmethod
    def _enter(patches):
        from contextlib import ExitStack

        stack = ExitStack()
        for p in patches:
            stack.enter_context(p)
        return stack

    # ---- 1. success -------------------------------------------------------

    def test_recommendations_success(
        self, client, mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """200: optimal-lineup players START with a slot; the rest SIT; flag True."""
        patches = self._patches(
            mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/recommendations")

        assert response.status_code == 200
        data = response.json()

        assert data["league_id"] == "LEAGUE1"
        assert data["user_id"] == "user_1"
        assert data["week"] == 8
        assert data["season"] == 2025
        assert data["scoring_format"] == "ppr"
        assert data["optimal_lineup_set"] is True

        recs = {r["player_id"]: r for r in data["recommendations"]}

        # Every non-empty rostered player appears exactly once (incl. reserve).
        assert set(recs) == {"p_qb", "p_rb", "p_wr", "p_te", "p_flex", "p_bench", "p_ir"}

        # The five intended starters START, each with an assigned slot.
        started = {pid for pid, r in recs.items() if r["recommendation"] == "START"}
        assert started == {"p_qb", "p_rb", "p_wr", "p_te", "p_flex"}
        for pid in started:
            assert recs[pid]["slot"] is not None

        # Slots assigned are from the league's starting slots.
        assigned_slots = {recs[pid]["slot"] for pid in started}
        assert assigned_slots == {"QB", "RB", "WR", "TE", "FLEX"}

        # p_bench is simply out-scored -> plain SIT, no slot.
        assert recs["p_bench"]["recommendation"] == "SIT"
        assert recs["p_bench"]["slot"] is None

        # IDs are strings.
        assert isinstance(data["league_id"], str)
        assert isinstance(data["user_id"], str)
        for r in data["recommendations"]:
            assert isinstance(r["player_id"], str)

    # ---- 2. injured / reserve player -> SIT (INJURY) ---------------------

    def test_recommendations_reserve_player_sit_injury(
        self, client, mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """A reserve (IR) player is labeled SIT (INJURY) even with high points."""
        patches = self._patches(
            mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/recommendations")

        assert response.status_code == 200
        recs = {r["player_id"]: r for r in response.json()["recommendations"]}

        # p_ir is on the reserve list -> excluded from the lineup and flagged.
        assert recs["p_ir"]["recommendation"] == "SIT (INJURY)"
        assert recs["p_ir"]["slot"] is None

    def test_recommendations_out_injury_status_sit_injury(
        self, client, mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """A player with injury_status OUT is excluded and labeled SIT (INJURY)."""
        players = dict(mock_players)
        # Mark the bench WR as OUT; exclusion should drop it and _sit_reason
        # should classify it as an injury sit.
        players["p_bench"] = {**players["p_bench"], "injury_status": "OUT"}

        patches = self._patches(
            mock_rosters, players, mock_projections, mock_nfl_state, mock_league_info
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/recommendations")

        assert response.status_code == 200
        recs = {r["player_id"]: r for r in response.json()["recommendations"]}
        assert recs["p_bench"]["recommendation"] == "SIT (INJURY)"
        assert recs["p_bench"]["injury_status"] == "OUT"

    # ---- 3. projections pending -> 503 -----------------------------------

    def test_recommendations_projections_pending_503(
        self, client, mock_rosters, mock_players, mock_nfl_state, mock_league_info
    ):
        """No projections available -> HTTP 503."""
        patches = self._patches(
            mock_rosters, mock_players, {}, mock_nfl_state, mock_league_info
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/recommendations")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "Projections" in detail

    # ---- 4. empty roster -> 200, optimal_lineup_set False ----------------

    def test_recommendations_empty_roster(
        self, client, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """A roster with no players -> 200, empty recs, optimal_lineup_set False."""
        empty_owner = Roster(
            roster_id="9",
            owner_id="user_1",
            starters=[],
            players=[],
            reserve=[],
        )
        patches = self._patches(
            [empty_owner], mock_players, mock_projections, mock_nfl_state, mock_league_info
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/recommendations")

        assert response.status_code == 200
        data = response.json()
        assert data["recommendations"] == []
        assert data["optimal_lineup_set"] is False

    # ---- 5. missing league / missing user -> 404 ------------------------

    def test_recommendations_missing_league_404(
        self, client, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """No rosters for the league -> 404."""
        patches = self._patches(
            [], mock_players, mock_projections, mock_nfl_state, mock_league_info
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/NOPE/user_1/recommendations")

        assert response.status_code == 404
        assert "NOPE" in response.json()["detail"]

    def test_recommendations_missing_user_404(
        self, client, mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """user_id matches no roster owner -> 404."""
        patches = self._patches(
            mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/ghost_user/recommendations")

        assert response.status_code == 404
        assert "ghost_user" in response.json()["detail"]

    # ---- 6. matchup grade included / gracefully null ---------------------

    def test_recommendations_matchup_grade_included(
        self, client, mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """When the matchup service is available, grades are attached."""

        class FakeMatchupService:
            def grade_for(self, team, opponent, season, week):
                return MatchupGrade(
                    team=team,
                    opponent=opponent or "OPP",
                    season=season,
                    week=week,
                    pass_matchup=15.2,
                    rush_matchup=-3.1,
                    overall_matchup=8.4,
                    pass_signal="favorable",
                    rush_signal="neutral",
                    overall_signal="favorable",
                    ol_grade=78.5,
                    dl_grade=60.1,
                )

        patches = self._patches(
            mock_rosters,
            mock_players,
            mock_projections,
            mock_nfl_state,
            mock_league_info,
            matchup_service=FakeMatchupService(),
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/recommendations")

        assert response.status_code == 200
        recs = {r["player_id"]: r for r in response.json()["recommendations"]}

        # A real-team player (p_qb -> KC) gets a populated matchup grade.
        grade = recs["p_qb"]["matchup_grade"]
        assert grade is not None
        assert grade["team"] == "KC"
        assert grade["pass_signal"] == "favorable"
        assert grade["overall_signal"] == "favorable"
        assert grade["ol_grade"] == 78.5
        assert grade["dl_grade"] == 60.1

    def test_recommendations_matchup_grade_null_when_unavailable(
        self, client, mock_rosters, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """When no matchup service is wired up, matchup_grade degrades to null."""
        patches = self._patches(
            mock_rosters,
            mock_players,
            mock_projections,
            mock_nfl_state,
            mock_league_info,
            matchup_service=None,
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/recommendations")

        assert response.status_code == 200
        for r in response.json()["recommendations"]:
            assert r["matchup_grade"] is None

    # ---- 7. bye-week detection ------------------------------------------

    def test_recommendations_bye_player_is_sat(
        self, client, mock_players, mock_projections, mock_nfl_state, mock_league_info
    ):
        """A player whose NFL team has no scheduled game is sat as SIT (BYE).

        Sleeper doesn't flag byes, so we infer them from the schedule-backed
        matchup mart: a real-team player with no opponent row that week is on
        bye, excluded from the optimal lineup, and labeled SIT (BYE). This needs
        a matchup service whose mart actually has rows (via ._load()), so bye
        inference is enabled.
        """
        import polars as pl

        # Schedule mart: KC plays (vs LV), but MIA has NO row -> MIA is on bye.
        schedule_df = pl.DataFrame(
            [
                {"season": 2025, "week": 8, "team": "KC", "opponent": "LV",
                 "pass_matchup": 5.0, "rush_matchup": 2.0, "overall_matchup": 3.0,
                 "pass_signal": "neutral", "rush_signal": "neutral",
                 "overall_signal": "neutral", "ol_grade": 55.0, "dl_grade": 52.0},
            ]
        )

        class ScheduleBackedMatchupService:
            def _load(self):
                return schedule_df

            def grade_for(self, team, opponent, season, week):
                row = schedule_df.filter(
                    (pl.col("team") == team)
                    & (pl.col("opponent") == (opponent or ""))
                    & (pl.col("season") == season)
                    & (pl.col("week") == week)
                )
                from src.services.matchup_grade import MatchupGrade

                if row.is_empty():
                    return MatchupGrade(
                        team=team, opponent=opponent or "", season=season, week=week,
                        pass_matchup=0.0, rush_matchup=0.0, overall_matchup=0.0,
                        pass_signal="neutral", rush_signal="neutral",
                        overall_signal="neutral", ol_grade=None, dl_grade=None,
                    )
                r = row.to_dicts()[0]
                return MatchupGrade(
                    team=team, opponent=opponent, season=season, week=week,
                    pass_matchup=r["pass_matchup"], rush_matchup=r["rush_matchup"],
                    overall_matchup=r["overall_matchup"], pass_signal=r["pass_signal"],
                    rush_signal=r["rush_signal"], overall_signal=r["overall_signal"],
                    ol_grade=r["ol_grade"], dl_grade=r["dl_grade"],
                )

        # Roster: one KC player (plays) and one MIA player (on bye).
        rosters = [
            Roster(
                roster_id="1",
                owner_id="user_1",
                starters=["p_qb", "p_wr"],
                players=["p_qb", "p_wr"],
                reserve=[],
            )
        ]
        players = {
            "p_qb": {"first_name": "Patrick", "last_name": "Mahomes", "position": "QB", "team": "KC"},
            "p_wr": {"first_name": "Tyreek", "last_name": "Hill", "position": "WR", "team": "MIA"},
        }
        projections = {"p_qb": 25.0, "p_wr": 18.0}
        # Only a QB and WR slot so both would start if neither were on bye.
        league_info = {"roster_positions": ["QB", "WR", "BN"]}

        patches = self._patches(
            rosters,
            players,
            projections,
            mock_nfl_state,
            league_info,
            matchup_service=ScheduleBackedMatchupService(),
        )
        with self._enter(patches):
            response = client.get("/api/v1/in-season/LEAGUE1/user_1/recommendations")

        assert response.status_code == 200
        recs = {r["player_id"]: r for r in response.json()["recommendations"]}

        # KC player plays -> START with a slot.
        assert recs["p_qb"]["recommendation"] == "START"
        assert recs["p_qb"]["slot"] == "QB"
        assert recs["p_qb"]["on_bye"] is False

        # MIA player is on bye -> excluded from the lineup, labeled SIT (BYE).
        assert recs["p_wr"]["recommendation"] == "SIT (BYE)"
        assert recs["p_wr"]["slot"] is None
        assert recs["p_wr"]["on_bye"] is True
