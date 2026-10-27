"""Property-based tests for SleeperClient ID normalization and error resilience.

Covers the in-season-matchup-recommendations design properties:

- **Property 11: ID normalization** — All IDs on returned ``Roster`` objects are
  strings, and starter/player/reserve lists never contain ``None`` or empty
  strings, for ANY shape of Sleeper rosters response.
  Validates: Requirements 5.5.

- **Property 25: Sleeper API error resilience** — For ANY exception raised by
  ``_make_request`` (or any malformed, non-list/non-dict response), the list
  methods return ``[]`` and ``get_nfl_state`` returns ``None`` — the exception
  is never propagated.
  Validates: Requirements 5.6, 12.3.
"""

from unittest.mock import patch

from hypothesis import given, settings, strategies as st

from src.data_sources.sleeper_client import (
    SleeperClient,
    Roster,
    roster_bench,
    _normalize_id_list,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A single Sleeper ID slot: int, numeric str, arbitrary str, or None (empty slot).
id_slot = st.one_of(
    st.integers(min_value=0, max_value=10_000),
    st.text(min_size=0, max_size=8),
    st.none(),
)

# A Sleeper slot list (starters/players/reserve): a list mixing ints, strs, None,
# or the whole thing being None / missing. Also allow non-list garbage.
id_slot_list = st.one_of(
    st.lists(id_slot, max_size=12),
    st.none(),
    st.integers(),           # malformed: not a list
    st.text(max_size=5),     # malformed: a bare string
)

# roster_id / owner_id: int, str, or None.
roster_scalar_id = st.one_of(
    st.integers(min_value=0, max_value=10_000),
    st.text(min_size=0, max_size=8),
    st.none(),
)


@st.composite
def roster_dict(draw):
    """Generate one (possibly malformed) Sleeper roster dict."""
    d = {}
    # Each key is independently present or absent to exercise .get() defaults.
    if draw(st.booleans()):
        d["roster_id"] = draw(roster_scalar_id)
    if draw(st.booleans()):
        d["owner_id"] = draw(roster_scalar_id)
    if draw(st.booleans()):
        d["starters"] = draw(id_slot_list)
    if draw(st.booleans()):
        d["players"] = draw(id_slot_list)
    if draw(st.booleans()):
        d["reserve"] = draw(id_slot_list)
    return d


# A rosters response: a list of roster dicts, optionally polluted with non-dict
# junk entries that get_league_rosters must skip.
rosters_response = st.lists(
    st.one_of(
        roster_dict(),
        st.none(),
        st.integers(),
        st.text(max_size=5),
        st.lists(st.integers(), max_size=3),
    ),
    max_size=14,
)

# A completely arbitrary malformed (non-list) response for the resilience tests.
malformed_response = st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=20),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=4),
    st.booleans(),
)

# Exception instances of varied types for the resilience tests.
exception_instances = st.one_of(
    st.builds(ValueError, st.text(max_size=20)),
    st.builds(KeyError, st.text(max_size=20)),
    st.builds(TypeError, st.text(max_size=20)),
    st.builds(RuntimeError, st.text(max_size=20)),
    st.builds(ConnectionError, st.text(max_size=20)),
    st.builds(TimeoutError, st.text(max_size=20)),
    st.builds(Exception, st.text(max_size=20)),
)


def _make_client():
    """SleeperClient with no rate-limit delay for fast tests."""
    return SleeperClient(rate_limit_delay=0, draft_ttl=0)


# ---------------------------------------------------------------------------
# Property 11: ID normalization
# ---------------------------------------------------------------------------

class TestProperty11IdNormalization:
    """Property 11: ID normalization.

    **Validates: Requirements 5.5**
    """

    @settings(max_examples=200)
    @given(response=rosters_response)
    def test_rosters_ids_are_strings_and_lists_clean(self, response):
        """For ANY rosters response, every returned Roster has string IDs and
        starter/player/reserve lists contain only non-empty strings."""
        client = _make_client()
        with patch.object(SleeperClient, "_make_request", return_value=response):
            rosters = client.get_league_rosters("league123")

        assert isinstance(rosters, list)
        for roster in rosters:
            assert isinstance(roster, Roster)

            # Scalar IDs are always strings.
            assert isinstance(roster.roster_id, str)
            assert isinstance(roster.owner_id, str)

            # Slot lists contain only non-empty strings — no None, no "".
            for slot_list in (roster.starters, roster.players, roster.reserve):
                assert isinstance(slot_list, list)
                for pid in slot_list:
                    assert isinstance(pid, str)
                    assert pid != ""
                    assert pid is not None

    @settings(max_examples=200)
    @given(response=rosters_response)
    def test_bench_is_subset_of_normalized_players(self, response):
        """Derived bench also contains only clean string IDs drawn from players."""
        client = _make_client()
        with patch.object(SleeperClient, "_make_request", return_value=response):
            rosters = client.get_league_rosters("league123")

        for roster in rosters:
            bench = roster_bench(roster)
            assert isinstance(bench, list)
            for pid in bench:
                assert isinstance(pid, str)
                assert pid != ""
                assert pid in roster.players

    @settings(max_examples=200)
    @given(raw=id_slot_list)
    def test_normalize_id_list_returns_non_empty_strings(self, raw):
        """_normalize_id_list(arbitrary) -> list of non-empty strings."""
        result = _normalize_id_list(raw)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)
            assert item != ""

    @settings(max_examples=200)
    @given(raw=st.lists(id_slot, max_size=12))
    def test_normalize_id_list_drops_none_and_empty(self, raw):
        """Every None/empty entry is dropped; every other entry becomes str(x)."""
        result = _normalize_id_list(raw)
        expected = [str(x) for x in raw if x is not None and str(x) != ""]
        assert result == expected


# ---------------------------------------------------------------------------
# Property 25: Sleeper API error resilience
# ---------------------------------------------------------------------------

class TestProperty25ErrorResilience:
    """Property 25: Sleeper API error resilience.

    **Validates: Requirements 5.6, 12.3**
    """

    @settings(max_examples=200)
    @given(exc=exception_instances)
    def test_methods_swallow_any_exception(self, exc):
        """For ANY exception from _make_request, list methods return [] and
        get_nfl_state returns None — never propagating the exception."""
        client = _make_client()
        with patch.object(SleeperClient, "_make_request", side_effect=exc):
            assert client.get_league_rosters("league123") == []
            assert client.get_league_transactions("league123", 5) == []
            assert client.get_trending_players() == []
            assert client.get_nfl_state() is None

    @settings(max_examples=200)
    @given(response=malformed_response)
    def test_methods_handle_malformed_responses(self, response):
        """For ANY malformed (non-list/non-dict) response, methods return the
        safe empty default."""
        client = _make_client()
        with patch.object(SleeperClient, "_make_request", return_value=response):
            rosters = client.get_league_rosters("league123")
            transactions = client.get_league_transactions("league123", 5)
            trending = client.get_trending_players()
            state = client.get_nfl_state()

        assert rosters == []
        assert transactions == []
        assert trending == []
        # get_nfl_state only accepts dict responses; a dict passes through,
        # anything else must be None.
        if isinstance(response, dict):
            assert state == response or isinstance(state, dict)
        else:
            assert state is None

    @settings(max_examples=200)
    @given(
        exc=exception_instances,
        kind=st.sampled_from(["add", "drop"]),
        lookback=st.integers(min_value=1, max_value=168),
        limit=st.integers(min_value=1, max_value=200),
    )
    def test_trending_players_resilient_across_params(self, exc, kind, lookback, limit):
        """get_trending_players stays safe for any param combo + exception."""
        client = _make_client()
        with patch.object(SleeperClient, "_make_request", side_effect=exc):
            result = client.get_trending_players(
                type=kind, lookback_hours=lookback, limit=limit
            )
        assert result == []
