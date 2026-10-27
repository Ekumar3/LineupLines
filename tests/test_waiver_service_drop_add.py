"""Unit tests for src/services/waiver_service.py — WaiverService.drop_add_optimization.

Phase 2 (Task 14) coverage, kept separate from the Phase 1 free-agent-ranking
tests in ``tests/test_waiver_service.py``.

These tests inject a mocked ``SleeperClient`` (``get_league_rosters`` returning
``Roster`` objects, ``get_trending_players`` returning trending dicts) and patch
``src.services.waiver_service.load_projections`` to return a small in-memory
polars DataFrame. No real HTTP calls or parquet files are touched.

Drop candidates come from ``roster_bench(user_roster)`` = players - starters -
reserve, so the concrete rosters below are built so the expected drop/add pairs
are fully deterministic.
"""

from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from src.data_sources.sleeper_client import Roster
from src.services.waiver_service import WaiverService, DropAddRec


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

USER_ID = "u1"
LEAGUE_ID = "league"


def _roster(roster_id, owner_id, starters=None, players=None, reserve=None):
    return Roster(
        roster_id=str(roster_id),
        owner_id=str(owner_id),
        starters=starters or [],
        players=players or [],
        reserve=reserve or [],
    )


def _user_roster():
    """User u1's roster.

    starters = [s1], reserve = [ir1], players = [s1, b1, b2, ir1].
    Derived bench (players - starters - reserve) = [b1, b2] — the only valid
    drop candidates. s1 (starter) and ir1 (reserve) must NEVER be dropped.
    """
    return _roster(
        "r1",
        USER_ID,
        starters=["s1"],
        players=["s1", "b1", "b2", "ir1"],
        reserve=["ir1"],
    )


def _opponent_roster():
    """A second roster that rosters opp1, so opp1 is never a free agent."""
    return _roster(
        "r2",
        "u2",
        starters=["opp1"],
        players=["opp1"],
        reserve=[],
    )


def _projection_df():
    """Deterministic projections for every player referenced in the rosters.

    Rostered (never add candidates):
        s1   starter  QB 30.0
        b1   bench    RB  5.0  (drop candidate)
        b2   bench    WR  8.0  (drop candidate)
        ir1  reserve  RB  2.0
        opp1 on u2    WR 50.0
    Free agents (not rostered anywhere -> add candidates):
        fa_rb  RB 12.0
        fa_wr  WR 10.0
        fa_low TE  3.0
    """
    return pl.DataFrame(
        [
            {"player_id": "s1", "player_name": "Starter One", "position": "QB", "team": "KC", "projected_points": 30.0},
            {"player_id": "b1", "player_name": "Bench One", "position": "RB", "team": "SF", "projected_points": 5.0},
            {"player_id": "b2", "player_name": "Bench Two", "position": "WR", "team": "MIN", "projected_points": 8.0},
            {"player_id": "ir1", "player_name": "Reserve One", "position": "RB", "team": "DAL", "projected_points": 2.0},
            {"player_id": "opp1", "player_name": "Opp One", "position": "WR", "team": "BAL", "projected_points": 50.0},
            {"player_id": "fa_rb", "player_name": "FA RB", "position": "RB", "team": "MIA", "projected_points": 12.0},
            {"player_id": "fa_wr", "player_name": "FA WR", "position": "WR", "team": "GB", "projected_points": 10.0},
            {"player_id": "fa_low", "player_name": "FA Low", "position": "TE", "team": "NYJ", "projected_points": 3.0},
        ]
    )


@pytest.fixture
def mock_sleeper():
    client = MagicMock()
    client.get_league_rosters.return_value = [_user_roster(), _opponent_roster()]
    client.get_trending_players.return_value = []
    return client


@pytest.fixture
def service(mock_sleeper):
    return WaiverService(mock_sleeper)


def _run(service, **kwargs):
    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        return service.drop_add_optimization(
            LEAGUE_ID, USER_ID, 2026, 1, "ppr", **kwargs
        )


# ---------------------------------------------------------------------------
# 1. Drop candidates = bench only (never starters / reserve)
# ---------------------------------------------------------------------------

def test_drop_candidates_are_bench_only(service):
    results = _run(service)

    dropped = {r.drop_player_id for r in results}
    # Only bench players can be dropped.
    assert dropped <= {"b1", "b2"}
    # Starter and reserve players are NEVER dropped.
    assert "s1" not in dropped
    assert "ir1" not in dropped
    # Both bench players produce at least one upgrade pair here.
    assert dropped == {"b1", "b2"}


# ---------------------------------------------------------------------------
# 2. Add candidates = free agents only (rostered players never added)
# ---------------------------------------------------------------------------

def test_add_candidates_are_free_agents_only(service):
    results = _run(service)

    added = {r.add_player_id for r in results}
    rostered = {"s1", "b1", "b2", "ir1", "opp1"}
    # No rostered player is ever an add candidate.
    assert added.isdisjoint(rostered)
    # Only the projected free agents that beat a bench player show up.
    assert added <= {"fa_rb", "fa_wr", "fa_low"}
    # opp1 projects huge (50) but is rostered on another team — never offered.
    assert "opp1" not in added


# ---------------------------------------------------------------------------
# 3. Only positive net gain pairs included
# ---------------------------------------------------------------------------

def test_only_positive_net_gain_pairs_included(service):
    results = _run(service)

    # Every returned pair is a strict upgrade.
    for r in results:
        assert r.net_gain > 0
        assert r.net_gain == pytest.approx(
            r.add_projected_points - r.drop_projected_points
        )

    # fa_low (3.0) beats b1 (5.0)? No -> excluded for b1.
    # fa_low (3.0) beats b2 (8.0)? No -> excluded for b2.
    pairs = {(r.drop_player_id, r.add_player_id) for r in results}
    assert ("b1", "fa_low") not in pairs
    assert ("b2", "fa_low") not in pairs

    # Enumerate the expected positive-gain pairs deterministically:
    #   b1 (5.0): fa_rb 12->+7, fa_wr 10->+5           (fa_low 3 -> -2 excluded)
    #   b2 (8.0): fa_rb 12->+4, fa_wr 10->+2           (fa_low 3 -> -5 excluded)
    assert pairs == {
        ("b1", "fa_rb"),
        ("b1", "fa_wr"),
        ("b2", "fa_rb"),
        ("b2", "fa_wr"),
    }


# ---------------------------------------------------------------------------
# 4. Ranking order: net_gain desc, same-position tiebreak, 1-indexed rank
# ---------------------------------------------------------------------------

def test_ranking_sorted_by_net_gain_desc_with_contiguous_rank(service):
    results = _run(service)

    gains = [r.net_gain for r in results]
    assert gains == sorted(gains, reverse=True)

    # rank is 1-indexed and contiguous.
    assert [r.rank for r in results] == list(range(1, len(results) + 1))

    # Deterministic net gains:
    #   b1->fa_rb = +7 (RB->RB, same position)
    #   b1->fa_wr = +5
    #   b2->fa_rb = +4
    #   b2->fa_wr = +2 (WR->WR, same position)
    assert [(r.drop_player_id, r.add_player_id) for r in results] == [
        ("b1", "fa_rb"),
        ("b1", "fa_wr"),
        ("b2", "fa_rb"),
        ("b2", "fa_wr"),
    ]
    assert results[0].rank == 1
    assert results[0].net_gain == pytest.approx(7.0)


def test_same_position_tiebreak_preferred_on_equal_net_gain(mock_sleeper):
    """When two pairs tie on net_gain, a same-position swap sorts first."""
    # b1 is RB @ 5.0. Two FAs both yield +5 net gain:
    #   fa_rb_eq  RB 10.0  (same position as b1 -> preferred)
    #   fa_wr_eq  WR 10.0  (different position)
    df = pl.DataFrame(
        [
            {"player_id": "s1", "player_name": "S", "position": "QB", "team": "KC", "projected_points": 30.0},
            {"player_id": "b1", "player_name": "B1", "position": "RB", "team": "SF", "projected_points": 5.0},
            {"player_id": "ir1", "player_name": "IR", "position": "RB", "team": "DAL", "projected_points": 2.0},
            {"player_id": "fa_wr_eq", "player_name": "FA WR", "position": "WR", "team": "GB", "projected_points": 10.0},
            {"player_id": "fa_rb_eq", "player_name": "FA RB", "position": "RB", "team": "MIA", "projected_points": 10.0},
        ]
    )
    mock_sleeper.get_league_rosters.return_value = [
        _roster("r1", USER_ID, starters=["s1"], players=["s1", "b1", "ir1"], reserve=["ir1"]),
    ]
    service = WaiverService(mock_sleeper)

    with patch("src.services.waiver_service.load_projections", return_value=df):
        results = service.drop_add_optimization(LEAGUE_ID, USER_ID, 2026, 1, "ppr")

    # Both pairs have net_gain +5; the RB->RB swap is preferred first.
    assert [r.add_player_id for r in results] == ["fa_rb_eq", "fa_wr_eq"]
    assert results[0].net_gain == pytest.approx(5.0)
    assert results[1].net_gain == pytest.approx(5.0)
    assert [r.rank for r in results] == [1, 2]


# ---------------------------------------------------------------------------
# 5. Limit respected
# ---------------------------------------------------------------------------

def test_limit_respected(service):
    results = _run(service, limit=2)

    assert len(results) == 2
    assert [r.rank for r in results] == [1, 2]
    # The two highest net-gain pairs are retained.
    assert [(r.drop_player_id, r.add_player_id) for r in results] == [
        ("b1", "fa_rb"),
        ("b1", "fa_wr"),
    ]


def test_zero_limit_returns_empty(service):
    results = _run(service, limit=0)
    assert results == []


# ---------------------------------------------------------------------------
# 6. Graceful degradation
# ---------------------------------------------------------------------------

def test_missing_user_roster_returns_empty(mock_sleeper):
    # League has only an opponent roster; user u1 owns none.
    mock_sleeper.get_league_rosters.return_value = [_opponent_roster()]
    service = WaiverService(mock_sleeper)

    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        results = service.drop_add_optimization(LEAGUE_ID, USER_ID, 2026, 1, "ppr")

    assert results == []


def test_empty_projections_returns_empty(service, mock_sleeper):
    empty_df = pl.DataFrame(
        schema={
            "player_id": pl.Utf8,
            "player_name": pl.Utf8,
            "position": pl.Utf8,
            "team": pl.Utf8,
            "projected_points": pl.Float64,
        }
    )

    with patch("src.services.waiver_service.load_projections", return_value=empty_df):
        results = service.drop_add_optimization(LEAGUE_ID, USER_ID, 2026, 1, "ppr")

    assert results == []
    # No roster lookup needed when projections are empty.
    mock_sleeper.get_league_rosters.assert_not_called()


def test_none_projections_returns_empty(service):
    with patch("src.services.waiver_service.load_projections", return_value=None):
        results = service.drop_add_optimization(LEAGUE_ID, USER_ID, 2026, 1, "ppr")

    assert results == []


def test_empty_bench_returns_empty(mock_sleeper):
    # User roster has all players as starters -> no bench -> no drop candidates.
    mock_sleeper.get_league_rosters.return_value = [
        _roster("r1", USER_ID, starters=["s1"], players=["s1"], reserve=[]),
    ]
    service = WaiverService(mock_sleeper)

    with patch(
        "src.services.waiver_service.load_projections",
        return_value=_projection_df(),
    ):
        results = service.drop_add_optimization(LEAGUE_ID, USER_ID, 2026, 1, "ppr")

    assert results == []
