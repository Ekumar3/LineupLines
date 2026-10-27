"""Property-based tests for the in-season roster API responses.

Covers two design properties of the in-season-matchup-recommendations feature,
exercised end-to-end through the FastAPI roster endpoints with a
``fastapi.testclient.TestClient``:

- **Property 11: ID normalization in responses** — For ANY Sleeper rosters
  payload (mixed int/str IDs, ``None`` placeholders in slot lists, missing
  keys), every id that appears in the JSON response (``league_id``,
  ``user_id``, ``roster_id``, ``player_id``) is a string.
  Validates: Requirements 5.5, 7.8.

- **Property 28: Roster categorization consistency** — For ANY generated
  roster, the response's ``starters`` / ``bench`` / ``reserve`` categorization
  matches the Sleeper slot assignments: starters come from the ``starters``
  slot list, reserve from the ``reserve`` slot list, and bench is exactly
  ``players - starters - reserve``. No bench player is a starter or on reserve,
  and every bench player is drawn from the normalized ``players`` list.
  Validates: Requirements 7.6.

Design note on example budget:
    These tests drive a real ``TestClient`` request per example, which is
    heavier than a pure in-process property. We keep ``max_examples`` at 120
    (>= the 100-iteration guideline in the design) and bound the generated
    league to <= 12 rosters of <= 16 players so each example stays fast while
    still exercising mixed-type IDs, ``None`` slot placeholders, and the
    UNKNOWN/FA enrichment defaults (player universe may be empty).
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

from src.api.main import app
from src.data_sources.sleeper_client import Roster, roster_bench, _normalize_id_list


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A single Sleeper ID slot: int, numeric-ish str, arbitrary str, or None
# (an empty starting slot). This mirrors the raw shapes Sleeper returns.
id_slot = st.one_of(
    st.integers(min_value=0, max_value=10_000),
    st.text(min_size=1, max_size=8),
    st.just("0"),      # Sleeper's empty-starter sentinel
    st.none(),
)

# A slot list (starters / players / reserve) that may itself be None/missing or
# be malformed garbage, to exercise _normalize_id_list defenses.
id_slot_list = st.one_of(
    st.lists(id_slot, max_size=16),
    st.none(),
    st.integers(),
    st.text(max_size=5),
)

# roster_id / owner_id scalars: int, str, or None.
roster_scalar_id = st.one_of(
    st.integers(min_value=0, max_value=10_000),
    st.text(min_size=1, max_size=8),
    st.none(),
)


@st.composite
def roster_dict(draw):
    """Generate one (possibly malformed) raw Sleeper roster dict.

    ``players`` is drawn as a superset built from the starters + reserve lists
    plus extra ids so that there is usually a non-empty derived bench, but each
    key is still independently present/absent and may be malformed to exercise
    ``.get()`` defaults and ``_normalize_id_list``.
    """
    d = {}
    if draw(st.booleans()):
        d["roster_id"] = draw(roster_scalar_id)
    if draw(st.booleans()):
        d["owner_id"] = draw(roster_scalar_id)

    starters = draw(id_slot_list)
    reserve = draw(id_slot_list)
    if draw(st.booleans()):
        d["starters"] = starters
    if draw(st.booleans()):
        d["reserve"] = reserve

    # Build players so it usually overlaps starters/reserve plus has extras
    # (the extras become the derived bench). Still sometimes malformed/None.
    if draw(st.booleans()):
        base = []
        for src in (starters, reserve):
            if isinstance(src, (list, tuple)):
                base.extend(src)
        extras = draw(st.lists(id_slot, max_size=8))
        players = base + extras
        # Occasionally drop to a malformed value to keep the defenses covered.
        d["players"] = draw(
            st.one_of(st.just(players), id_slot_list)
        )
    return d


# Junk entries that get_league_rosters must skip (non-dict garbage).
_junk_entry = st.one_of(
    st.none(),
    st.integers(),
    st.text(max_size=5),
    st.lists(st.integers(), max_size=3),
)


@st.composite
def rosters_response(draw):
    """A rosters payload with >= 1 real roster dict, plus optional junk.

    At least one valid roster dict is guaranteed so the normalized roster list
    is non-empty and the endpoint returns 200 rather than the empty-league 404
    (which is covered separately by the integration tests). Junk entries are
    interleaved to exercise get_league_rosters' skip-non-dict defense. Kept
    <= 12 entries for TestClient-per-example speed.
    """
    real = draw(st.lists(roster_dict(), min_size=1, max_size=8))
    junk = draw(st.lists(_junk_entry, max_size=4))
    combined = real + junk
    draw(st.randoms()).shuffle(combined)
    return combined[:12]

# Unique owner_ids so get_in_season_user_roster can target exactly one roster.
unique_owner_ids = st.lists(
    st.integers(min_value=1, max_value=10_000),
    min_size=1,
    max_size=10,
    unique=True,
)

# NFL state responses (season/week) and scoring format for patching.
nfl_states = st.fixed_dictionaries(
    {
        "season": st.one_of(
            st.integers(min_value=2000, max_value=2100),
            st.builds(str, st.integers(min_value=2000, max_value=2100)),
        ),
        "week": st.integers(min_value=1, max_value=18),
        "season_type": st.sampled_from(["regular", "post", "pre"]),
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_player_universe(rosters, include_fraction):
    """Build a mocked player universe covering a fraction of referenced ids.

    When ``include_fraction`` is 0 the universe is empty, exercising the
    UNKNOWN/FA enrichment defaults; otherwise every Nth referenced id gets a
    real entry so both enrichment branches are covered.
    """
    all_ids = []
    for r in rosters:
        all_ids.extend(r.starters)
        all_ids.extend(r.players)
        all_ids.extend(r.reserve)

    universe = {}
    if include_fraction <= 0:
        return universe
    step = max(1, int(1 / include_fraction))
    for i, pid in enumerate(all_ids):
        if i % step == 0:
            universe[pid] = {
                "first_name": "First",
                "last_name": f"Last{i}",
                "position": "RB",
                "team": "KC",
                "injury_status": None,
            }
    return universe


def _collect_response_ids(roster_json):
    """Collect every id field value appearing in a RosterResponse JSON dict."""
    ids = [
        roster_json["league_id"],
        roster_json["user_id"],
        roster_json["roster_id"],
    ]
    for category in ("starters", "bench", "reserve"):
        for player in roster_json.get(category, []):
            ids.append(player["player_id"])
    return ids


def _patched_client(rosters, universe, state):
    """Context managers patching all external deps for the roster endpoints."""
    return [
        patch(
            "src.api.main.sleeper_client.get_league_rosters",
            return_value=rosters,
        ),
        patch(
            "src.api.main.sleeper_client.get_players",
            return_value=universe,
        ),
        patch(
            "src.api.main.sleeper_client.get_nfl_state",
            return_value=state,
        ),
        patch(
            "src.api.main.sleeper_client.get_scoring_format",
            return_value="ppr",
        ),
        # Inject the generated universe directly as the enrichment source so we
        # do not depend on on-disk player data.
        patch(
            "src.api.main._load_in_season_players",
            return_value=universe if universe else {"__none__": {}},
        ),
        # No projections / matchup services wired for these tests.
        patch("src.api.main._load_week_projections", return_value={}),
        patch("src.api.main._get_matchup_grade_service", return_value=None),
    ]


def _enter_all(cms):
    for cm in cms:
        cm.__enter__()


def _exit_all(cms):
    for cm in reversed(cms):
        cm.__exit__(None, None, None)


def _rosters_from_raw(raw_response):
    """Mirror get_league_rosters normalization to predict expected rosters.

    Used by the categorization test to know the normalized slot lists the
    endpoint will build its response from.
    """
    rosters = []
    for roster_data in raw_response:
        if not isinstance(roster_data, dict):
            continue
        roster_id = roster_data.get("roster_id")
        owner_id = roster_data.get("owner_id")
        rosters.append(
            Roster(
                roster_id=str(roster_id) if roster_id is not None else "",
                owner_id=str(owner_id) if owner_id is not None else "",
                starters=_normalize_id_list(roster_data.get("starters")),
                players=_normalize_id_list(roster_data.get("players")),
                reserve=_normalize_id_list(roster_data.get("reserve")),
            )
        )
    return rosters


# ---------------------------------------------------------------------------
# Property 11: ID normalization in responses
# ---------------------------------------------------------------------------

class TestProperty11IdNormalizationInResponses:
    """Property 11: every id in the roster JSON response is a string.

    **Validates: Requirements 5.5, 7.8**
    """

    @settings(max_examples=120, deadline=None)
    @given(
        raw_response=rosters_response(),
        include_fraction=st.sampled_from([0.0, 0.5, 1.0]),
    )
    def test_all_response_ids_are_strings(self, raw_response, include_fraction):
        """For ANY rosters payload, the /rosters response has string ids only."""
        client = TestClient(app)
        normalized = _rosters_from_raw(raw_response)
        universe = _build_player_universe(normalized, include_fraction)
        state = {"season": 2025, "week": 8, "season_type": "regular"}

        cms = _patched_client(normalized, universe, state)
        _enter_all(cms)
        try:
            resp = client.get("/api/v1/in-season/league123/rosters")
        finally:
            _exit_all(cms)

        assert resp.status_code == 200
        body = resp.json()

        # Top-level league_id is a string.
        assert isinstance(body["league_id"], str)

        for roster_json in body["rosters"]:
            for value in _collect_response_ids(roster_json):
                assert isinstance(value, str), f"non-string id in response: {value!r}"

    @settings(max_examples=120, deadline=None)
    @given(
        owner_ids=unique_owner_ids,
        include_fraction=st.sampled_from([0.0, 1.0]),
    )
    def test_user_roster_response_ids_are_strings(self, owner_ids, include_fraction):
        """The single-user /roster response also normalizes every id to str."""
        # Build rosters with known unique owners, each with some slot content.
        normalized = []
        for i, owner in enumerate(owner_ids):
            normalized.append(
                Roster(
                    roster_id=str(i + 1),
                    owner_id=str(owner),
                    starters=[str(owner) + "a", "0"],
                    players=[str(owner) + "a", str(owner) + "b"],
                    reserve=[str(owner) + "c"],
                )
            )

        target_owner = str(owner_ids[0])
        universe = _build_player_universe(normalized, include_fraction)
        state = {"season": 2025, "week": 3, "season_type": "regular"}

        client = TestClient(app)
        cms = _patched_client(normalized, universe, state)
        _enter_all(cms)
        try:
            resp = client.get(f"/api/v1/in-season/league123/{target_owner}/roster")
        finally:
            _exit_all(cms)

        assert resp.status_code == 200
        body = resp.json()
        for value in _collect_response_ids(body):
            assert isinstance(value, str)
        assert body["user_id"] == target_owner


# ---------------------------------------------------------------------------
# Property 28: Roster categorization consistency
# ---------------------------------------------------------------------------

class TestProperty28RosterCategorizationConsistency:
    """Property 28: starter/bench/reserve categorization matches Sleeper slots.

    **Validates: Requirements 7.6**
    """

    @settings(max_examples=120, deadline=None)
    @given(
        raw_response=rosters_response(),
        include_fraction=st.sampled_from([0.0, 0.5, 1.0]),
    )
    def test_categorization_partition_matches_slots(
        self, raw_response, include_fraction
    ):
        """For ANY roster, response categories match the normalized slot lists.

        For every roster in the response:
          * starter player_ids == normalized roster.starters (same order)
          * reserve player_ids == normalized roster.reserve (same order)
          * bench player_ids == roster_bench(roster) == players - starters - reserve
          * no bench player is a starter or on reserve
          * every bench player is drawn from the normalized players list
        """
        client = TestClient(app)
        normalized = _rosters_from_raw(raw_response)
        universe = _build_player_universe(normalized, include_fraction)
        state = {"season": 2025, "week": 8, "season_type": "regular"}

        cms = _patched_client(normalized, universe, state)
        _enter_all(cms)
        try:
            resp = client.get("/api/v1/in-season/league123/rosters")
        finally:
            _exit_all(cms)

        assert resp.status_code == 200
        body = resp.json()

        # Response rosters are in the same order as the input rosters.
        assert len(body["rosters"]) == len(normalized)

        for roster_json, roster in zip(body["rosters"], normalized):
            starter_ids = [p["player_id"] for p in roster_json["starters"]]
            bench_ids = [p["player_id"] for p in roster_json["bench"]]
            reserve_ids = [p["player_id"] for p in roster_json["reserve"]]

            expected_bench = roster_bench(roster)

            # Starters/reserve come straight from the Sleeper slot lists.
            assert starter_ids == roster.starters
            assert reserve_ids == roster.reserve

            # Bench is exactly players - starters - reserve (order preserved).
            assert bench_ids == expected_bench

            starters_set = set(roster.starters)
            reserve_set = set(roster.reserve)
            players_set = set(roster.players)

            for pid in bench_ids:
                # No bench player appears in starters or reserve slots.
                assert pid not in starters_set
                assert pid not in reserve_set
                # Every bench player is drawn from the players list.
                assert pid in players_set

            # Bench ∪ (players ∩ starters) ∪ (players ∩ reserve) reconstructs
            # the full players list membership: no players-list id is dropped
            # from all three categories.
            categorized = set(bench_ids) | starters_set | reserve_set
            assert players_set.issubset(categorized)

    @settings(max_examples=120, deadline=None)
    @given(
        raw_response=rosters_response(),
        include_fraction=st.sampled_from([0.0, 1.0]),
    )
    def test_no_player_in_two_categories_via_players_membership(
        self, raw_response, include_fraction
    ):
        """A players-list id never lands in both bench and a slot category.

        Bench is disjoint from starters and reserve by construction; this
        asserts that invariant holds in the actual response payload for every
        player that is part of the roster's ``players`` list.
        """
        client = TestClient(app)
        normalized = _rosters_from_raw(raw_response)
        universe = _build_player_universe(normalized, include_fraction)
        state = {"season": 2025, "week": 1, "season_type": "regular"}

        cms = _patched_client(normalized, universe, state)
        _enter_all(cms)
        try:
            resp = client.get("/api/v1/in-season/league123/rosters")
        finally:
            _exit_all(cms)

        assert resp.status_code == 200
        body = resp.json()

        for roster_json, roster in zip(body["rosters"], normalized):
            bench_ids = set(p["player_id"] for p in roster_json["bench"])
            starter_ids = set(p["player_id"] for p in roster_json["starters"])
            reserve_ids = set(p["player_id"] for p in roster_json["reserve"])

            # Bench is disjoint from both slot categories.
            assert bench_ids.isdisjoint(starter_ids)
            assert bench_ids.isdisjoint(reserve_ids)
