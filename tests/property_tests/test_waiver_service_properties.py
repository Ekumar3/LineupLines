"""Property-based tests for ``WaiverService.free_agent_ranking`` (Task 11.3).

Validates the Phase 1 waiver free-agent ranking invariants with
Hypothesis-generated projections (as polars DataFrames) and league rosters:

- Property 8  — Waiver pool correctness: no rostered player_id (players ∪
  reserve, across every roster) ever appears in the FA ranking.
- Property 15 — Ranking order: results are non-increasing by
  ``projected_points`` with ``trending_add_count`` as the descending
  tiebreak; ``rank`` is 1-indexed and contiguous (1..n).
- Property 22 — Position filter: when a position filter is supplied, every
  result carries that position.
- Property 23 — Limit enforcement: ``len(results) <= limit`` for any
  ``limit >= 0``.

The ``SleeperClient`` is mocked (``get_league_rosters`` /
``get_trending_players``) and injected via the constructor; projections are
patched at ``src.services.waiver_service.load_projections`` so the tests never
touch disk.
"""

from unittest.mock import MagicMock, patch

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from src.data_sources.sleeper_client import Roster
from src.services.waiver_service import WaiverService

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
TEAMS = ["AAA", "BBB", "CCC", "DDD", "FA"]

PROJ_COLUMNS = ["player_id", "player_name", "position", "team", "projected_points"]


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

@st.composite
def _projections_df(draw):
    """A projections frame with unique player_ids over a fixed id space.

    Projected points may be a float or None (the service tolerates None by
    sorting it last). The id space is a small integer range so rosters drawn
    from the same space actually overlap the projection set.
    """
    n = draw(st.integers(min_value=0, max_value=25))
    # Draw a unique set of player ids from a bounded space so rosters (drawn
    # from the same space) can overlap meaningfully.
    ids = draw(st.lists(
        st.integers(min_value=1, max_value=60).map(str),
        min_size=n, max_size=n, unique=True,
    ))
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
def _rosters(draw):
    """A list of Roster objects drawn from the same id space as projections."""
    n_rosters = draw(st.integers(min_value=0, max_value=4))
    rosters = []
    for i in range(n_rosters):
        players = draw(st.lists(
            st.integers(min_value=1, max_value=60).map(str),
            min_size=0, max_size=12, unique=True,
        ))
        reserve = draw(st.lists(
            st.integers(min_value=1, max_value=60).map(str),
            min_size=0, max_size=4, unique=True,
        ))
        # starters are a subset of players (shape matches real rosters, though
        # free_agent_ranking only reads players ∪ reserve)
        starters = draw(st.lists(
            st.sampled_from(players) if players else st.nothing(),
            min_size=0, max_size=len(players), unique=True,
        )) if players else []
        rosters.append(Roster(
            roster_id=str(i + 1),
            owner_id=str(1000 + i),
            starters=starters,
            players=players,
            reserve=reserve,
        ))
    return rosters


@st.composite
def _trending(draw):
    """Optional Sleeper trending-add payload (player_id -> count)."""
    n = draw(st.integers(min_value=0, max_value=10))
    return [
        {
            "player_id": draw(st.integers(min_value=1, max_value=60).map(str)),
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
    rostered = set()
    for r in rosters:
        rostered.update(r.players)
        rostered.update(r.reserve)
    return rostered


# ===========================================================================
# Property 8 — Waiver pool correctness
# ===========================================================================

@settings(max_examples=200)
@given(projections=_projections_df(), rosters=_rosters(), trending=_trending())
def test_waiver_pool_excludes_all_rostered_players(projections, rosters, trending):
    """Property 8: no player rostered anywhere (players ∪ reserve, across every
    roster) ever appears in the free-agent ranking.

    **Validates: Requirements 7.2**
    """
    svc = _make_service(rosters, trending)
    with patch("src.services.waiver_service.load_projections",
               return_value=projections):
        results = svc.free_agent_ranking(
            league_id="L1", season=2025, week=1, scoring_format="ppr",
            limit=1000,
        )

    rostered = _rostered_ids(rosters)
    result_ids = {rec.player_id for rec in results}
    assert result_ids.isdisjoint(rostered)


# ===========================================================================
# Property 15 — Ranking order
# ===========================================================================

@settings(max_examples=200)
@given(projections=_projections_df(), rosters=_rosters(), trending=_trending())
def test_ranking_is_sorted_and_ranks_are_contiguous(projections, rosters, trending):
    """Property 15: results are non-increasing by projected_points (None last),
    tie-broken by trending_add_count descending (None last); ranks are
    1-indexed and contiguous (1..n).

    **Validates: Requirements 7.3**
    """
    svc = _make_service(rosters, trending)
    with patch("src.services.waiver_service.load_projections",
               return_value=projections):
        results = svc.free_agent_ranking(
            league_id="L1", season=2025, week=1, scoring_format="ppr",
            limit=1000,
        )

    # Ranks are 1-indexed and contiguous.
    assert [rec.rank for rec in results] == list(range(1, len(results) + 1))

    neg_inf = float("-inf")

    def sort_key(rec):
        pts = rec.projected_points if rec.projected_points is not None else neg_inf
        trend = rec.trending_add_count if rec.trending_add_count is not None else neg_inf
        return (pts, trend)

    # Each consecutive pair must be non-increasing on the (points, trend) key.
    for prev, curr in zip(results, results[1:]):
        assert sort_key(prev) >= sort_key(curr)


# ===========================================================================
# Property 22 — Position filter
# ===========================================================================

@settings(max_examples=200)
@given(
    projections=_projections_df(),
    rosters=_rosters(),
    trending=_trending(),
    position=st.sampled_from(POSITIONS),
)
def test_position_filter_applied(projections, rosters, trending, position):
    """Property 22: when a position filter is supplied, every result carries
    exactly that position.

    **Validates: Requirements 7.6**
    """
    svc = _make_service(rosters, trending)
    with patch("src.services.waiver_service.load_projections",
               return_value=projections):
        results = svc.free_agent_ranking(
            league_id="L1", season=2025, week=1, scoring_format="ppr",
            position=position, limit=1000,
        )

    assert all(rec.position == position for rec in results)


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

    **Validates: Requirements 7.5**
    """
    svc = _make_service(rosters, trending)
    with patch("src.services.waiver_service.load_projections",
               return_value=projections):
        results = svc.free_agent_ranking(
            league_id="L1", season=2025, week=1, scoring_format="ppr",
            limit=limit,
        )

    assert len(results) <= limit
