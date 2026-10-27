"""Property-based tests for ``WaiverService.drop_add_optimization`` (Task 14.3).

Validates the Phase 2 drop/add optimization invariants with Hypothesis-generated
projections (as polars DataFrames) and league rosters drawn from a shared id
space (so bench players and free agents overlap meaningfully):

- Property 9  — Drop/add correctness: for any generated projections + rosters +
  target user, every returned pair has ``drop_player`` on the user's BENCH
  (``roster_bench`` = players - starters - reserve; never a starter, never on
  reserve), ``add_player`` a league-wide free agent (not rostered anywhere),
  and ``net_gain == add_projected - drop_projected > 0`` (strictly positive).
- Property 16 — Ranking order: results are non-increasing by ``net_gain``;
  ``rank`` is 1-indexed and contiguous (1..n).
- Property 23 — Limit enforcement: ``len(results) <= limit`` for any
  ``limit >= 0``.

The ``SleeperClient`` is mocked (``get_league_rosters`` / ``get_trending_players``)
and injected via the constructor; projections are patched at
``src.services.waiver_service.load_projections`` so the tests never touch disk.
The target ``user_id`` always owns one of the generated rosters.
"""

from unittest.mock import MagicMock, patch

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from src.data_sources.sleeper_client import Roster, roster_bench
from src.services.waiver_service import WaiverService

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
TEAMS = ["AAA", "BBB", "CCC", "DDD", "FA"]

PROJ_COLUMNS = ["player_id", "player_name", "position", "team", "projected_points"]

# Shared id space: rosters and projections draw player ids from this range so
# bench players and free agents actually overlap the projection set.
ID_SPACE = st.integers(min_value=1, max_value=60).map(str)

# The target user always owns roster 0 (owner_id == TARGET_USER_ID).
TARGET_USER_ID = "1000"


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

@st.composite
def _projections_df(draw):
    """A projections frame with unique player_ids over the shared id space.

    Projected points may be a float or None (the service tolerates None by
    skipping un-projectable players for both drop and add candidates).
    """
    n = draw(st.integers(min_value=0, max_value=25))
    ids = draw(st.lists(ID_SPACE, min_size=n, max_size=n, unique=True))
    rows = []
    for pid in ids:
        points = draw(st.one_of(
            st.none(),
            st.floats(min_value=0.0, max_value=500.0,
                      allow_nan=False, allow_infinity=False),
        ))
        rows.append({
            "player_id": pid,
            "player_name": f"Player {pid}",
            "position": draw(st.sampled_from(POSITIONS)),
            "team": draw(st.sampled_from(TEAMS)),
            "projected_points": points,
        })
    if not rows:
        # polars needs a schema for an empty frame; is_empty() short-circuits.
        return pl.DataFrame(schema={c: pl.Utf8 for c in PROJ_COLUMNS})
    return pl.DataFrame(rows)


@st.composite
def _roster(draw, roster_id, owner_id):
    """A single Roster drawn from the shared id space.

    ``starters`` and ``reserve`` are subsets of ``players`` so the derived
    bench (``players - starters - reserve``) matches real Sleeper shape.
    """
    players = draw(st.lists(ID_SPACE, min_size=0, max_size=12, unique=True))
    if players:
        starters = draw(st.lists(
            st.sampled_from(players), min_size=0, max_size=len(players),
            unique=True,
        ))
        remaining = [p for p in players if p not in starters]
        reserve = draw(st.lists(
            st.sampled_from(remaining) if remaining else st.nothing(),
            min_size=0, max_size=len(remaining), unique=True,
        )) if remaining else []
    else:
        starters = []
        reserve = []
    return Roster(
        roster_id=str(roster_id),
        owner_id=str(owner_id),
        starters=starters,
        players=players,
        reserve=reserve,
    )


@st.composite
def _rosters(draw):
    """A list of Rosters where roster 0 is owned by the target user.

    At least one roster always exists (the target user's), so the target
    ``user_id`` always owns a roster in the league.
    """
    n_extra = draw(st.integers(min_value=0, max_value=3))
    rosters = [draw(_roster(roster_id=1, owner_id=TARGET_USER_ID))]
    for i in range(n_extra):
        rosters.append(draw(_roster(roster_id=i + 2, owner_id=str(2000 + i))))
    return rosters


@st.composite
def _trending(draw):
    """Optional Sleeper trending-add payload (player_id -> count)."""
    n = draw(st.integers(min_value=0, max_value=10))
    return [
        {
            "player_id": draw(ID_SPACE),
            "count": draw(st.integers(min_value=0, max_value=100000)),
        }
        for _ in range(n)
    ]


def _make_service(rosters, trending):
    """A WaiverService wired to a mocked SleeperClient."""
    client = MagicMock()
    client.get_league_rosters.return_value = rosters
    client.get_trending_players.return_value = trending
    return WaiverService(client)


def _rostered_ids(rosters):
    """All player ids rostered anywhere (players ∪ reserve, every roster)."""
    rostered = set()
    for r in rosters:
        rostered.update(r.players)
        rostered.update(r.reserve)
    return rostered


# ===========================================================================
# Property 9 — Drop/add correctness
# ===========================================================================

@settings(max_examples=200)
@given(projections=_projections_df(), rosters=_rosters(), trending=_trending())
def test_drop_add_correctness(projections, rosters, trending):
    """Property 9: ∀ pair ∈ results: add ∉ rostered (league-wide free agent),
    drop ∈ user_bench (never a starter, never on reserve), and
    net_gain == add_projected - drop_projected > 0 (strictly positive).

    **Validates: Requirements 10.5, 10.6, 10.11**
    """
    svc = _make_service(rosters, trending)
    with patch("src.services.waiver_service.load_projections",
               return_value=projections):
        results = svc.drop_add_optimization(
            league_id="L1", user_id=TARGET_USER_ID,
            season=2025, week=1, scoring_format="ppr", limit=1000,
        )

    rostered = _rostered_ids(rosters)
    user_roster = next(r for r in rosters if r.owner_id == TARGET_USER_ID)
    bench = set(roster_bench(user_roster))
    starters = set(user_roster.starters)
    reserve = set(user_roster.reserve)

    for pair in results:
        # add player is a league-wide free agent.
        assert pair.add_player_id not in rostered
        # drop player is on the user's bench, and never a starter/reserve.
        assert pair.drop_player_id in bench
        assert pair.drop_player_id not in starters
        assert pair.drop_player_id not in reserve
        # net_gain is exactly the projected delta and strictly positive.
        expected = pair.add_projected_points - pair.drop_projected_points
        assert pair.net_gain == expected
        assert pair.net_gain > 0


# ===========================================================================
# Property 16 — Ranking order
# ===========================================================================

@settings(max_examples=200)
@given(projections=_projections_df(), rosters=_rosters(), trending=_trending())
def test_ranking_order_and_contiguous_ranks(projections, rosters, trending):
    """Property 16: results are non-increasing by net_gain; ranks are 1-indexed
    and contiguous (1..n).

    **Validates: Requirements 10.6**
    """
    svc = _make_service(rosters, trending)
    with patch("src.services.waiver_service.load_projections",
               return_value=projections):
        results = svc.drop_add_optimization(
            league_id="L1", user_id=TARGET_USER_ID,
            season=2025, week=1, scoring_format="ppr", limit=1000,
        )

    # Ranks are 1-indexed and contiguous.
    assert [pair.rank for pair in results] == list(range(1, len(results) + 1))

    # net_gain is non-increasing across consecutive pairs.
    for prev, curr in zip(results, results[1:]):
        assert prev.net_gain >= curr.net_gain


# ===========================================================================
# Property 23 — Limit enforcement
# ===========================================================================

@settings(max_examples=200)
@given(
    projections=_projections_df(),
    rosters=_rosters(),
    trending=_trending(),
    limit=st.integers(min_value=0, max_value=100),
)
def test_limit_enforced(projections, rosters, trending, limit):
    """Property 23: len(results) <= limit for any limit >= 0.

    **Validates: Requirements 10.10**
    """
    svc = _make_service(rosters, trending)
    with patch("src.services.waiver_service.load_projections",
               return_value=projections):
        results = svc.drop_add_optimization(
            league_id="L1", user_id=TARGET_USER_ID,
            season=2025, week=1, scoring_format="ppr", limit=limit,
        )

    assert len(results) <= limit
