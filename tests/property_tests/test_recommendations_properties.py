"""Property-based tests for the in-season start/sit recommendations endpoint.

Exercises two design properties of the ``in-season-matchup-recommendations``
feature end-to-end through ``GET /api/v1/in-season/{league_id}/{user_id}/
recommendations`` with a ``fastapi.testclient.TestClient``:

- **Property 24: Optimal lineup flag accuracy** — For ANY generated roster +
  projections + ``roster_positions``, the response's ``optimal_lineup_set`` is
  ``True`` IFF the computed optimal lineup fills every real starting slot (no
  ``None`` slot), and ``False`` when any starting slot cannot be filled (not
  enough eligible players) or there are no starting slots. The expected flag is
  derived independently from the generated inputs via the lineup optimizer
  (``apply_exclusions`` + ``assign_lineup``), mirroring the enrichment the
  endpoint does in ``_build_optimizer_players``, and asserted equal to the
  endpoint's flag.
  **Validates: Requirements 8.10**

- **Property 17: Error response safety** — For arbitrary inputs that trigger
  expected error paths (missing league -> no rosters -> 404; missing target
  user -> 404; projections pending -> no projections -> 503), the endpoint
  returns the proper HTTP status with a JSON body carrying a string ``detail``,
  and NEVER returns 500 or leaks a stack trace / traceback text for these
  expected conditions.
  **Validates: Requirements 8.11**

Design note on example budget:
    Each example drives a real ``TestClient`` request, heavier than a pure
    in-process property. We keep ``max_examples`` at 120 (>= the 100-iteration
    guideline) and bound the generated roster to <= 20 players and the league
    to <= 12 starting slots so every example stays fast while still exercising
    flex eligibility, exclusions (bye / OUT / DOUBTFUL / reserve-IR),
    missing-projection fallbacks, and empty / over-subscribed slot sets.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

from src.api.main import app
from src.data_sources.sleeper_client import Roster
from src.services.lineup_optimizer import (
    OptimizerPlayer,
    apply_exclusions,
    assign_lineup,
    starting_slots,
)


# ---------------------------------------------------------------------------
# Shared player-id space + strategies
# ---------------------------------------------------------------------------

LEAGUE_ID = "league123"
USER_ID = "owner1"

# Positions the player universe may assign. UNKNOWN is included because the
# endpoint falls back to "UNKNOWN" for players missing a position, and such a
# player is eligible only for a (nonexistent) "UNKNOWN" slot -> effectively
# benchable, which the independently-derived flag must also account for.
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# Starting slots the league may use (named + flex variants). BN/IR/TAXI are
# non-starting and filtered by starting_slots().
STARTING_SLOT_CHOICES = [
    "QB", "RB", "WR", "TE", "K", "DEF",
    "FLEX", "SUPER_FLEX", "REC_FLEX", "WRRB_FLEX",
]

BENCH_SLOT_CHOICES = ["BN", "IR", "TAXI"]

# Injury statuses the universe may report. OUT/DOUBTFUL exclude; QUESTIONABLE
# stays in the pool; None is healthy.
INJURY_STATUSES = [None, "QUESTIONABLE", "OUT", "DOUBTFUL", "IR"]


@st.composite
def player_entries(draw):
    """Generate a list of (player_id, universe_entry) with unique ids.

    Each entry mirrors the shape ``_build_optimizer_players`` reads from the
    player universe: first/last name, position, team, injury_status.
    """
    n = draw(st.integers(min_value=0, max_value=20))
    entries = []
    for i in range(n):
        pid = f"p{i}"
        position = draw(st.sampled_from(POSITIONS + ["UNKNOWN"]))
        injury = draw(st.sampled_from(INJURY_STATUSES))
        # team "FA" is the endpoint's fallback; include it plus a real team.
        team = draw(st.sampled_from(["KC", "SF", "BUF", "FA"]))
        entries.append(
            (
                pid,
                {
                    "first_name": "First",
                    "last_name": f"Last{i}",
                    "position": position,
                    "team": team,
                    "injury_status": injury,
                },
            )
        )
    return entries


@st.composite
def roster_positions_strategy(draw):
    """Generate a league ``roster_positions`` array (starters + bench slots)."""
    starters = draw(st.lists(st.sampled_from(STARTING_SLOT_CHOICES), max_size=12))
    bench = draw(st.lists(st.sampled_from(BENCH_SLOT_CHOICES), max_size=6))
    combined = list(starters) + list(bench)
    draw(st.randoms()).shuffle(combined)
    return combined


@st.composite
def scenario(draw):
    """Generate a full recommendations scenario.

    Returns a dict describing the universe, the target roster's slot lists,
    the projections map, and the league ``roster_positions`` — everything the
    endpoint and the independent flag derivation both consume.
    """
    entries = draw(player_entries())
    universe = {pid: data for pid, data in entries}
    all_ids = [pid for pid, _ in entries]

    # Reserve subset (these get roster_status="IR" in the endpoint).
    reserve = draw(
        st.lists(st.sampled_from(all_ids), unique=True, max_size=len(all_ids))
    ) if all_ids else []

    # Sleeper empty-slot sentinels ("0") may appear in players; the endpoint
    # skips them. Mix some in to exercise that path.
    players = list(all_ids)
    if draw(st.booleans()):
        players = players + ["0"]
        draw(st.randoms()).shuffle(players)

    # Projections: a subset of ids get a float; others are absent (endpoint
    # treats absent as 0.0 expected points).
    projected_ids = draw(
        st.lists(st.sampled_from(all_ids), unique=True, max_size=len(all_ids))
    ) if all_ids else []
    projections = {
        pid: draw(st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False))
        for pid in projected_ids
    }

    roster_positions = draw(roster_positions_strategy())

    return {
        "universe": universe,
        "players": players,
        "reserve": reserve,
        "projections": projections,
        "roster_positions": roster_positions,
    }


# ---------------------------------------------------------------------------
# Independent derivation of the expected optimal_lineup_set flag
# ---------------------------------------------------------------------------

def _build_optimizer_players_ref(players, reserve, universe, projections):
    """Reimplementation of main._build_optimizer_players for cross-checking.

    Kept intentionally independent so the property validates the endpoint's
    behaviour rather than trivially reusing its code path. Mirrors the
    enrichment rules: skip "0" sentinels, position/team fallbacks, reserve ->
    IR roster_status, absent projection -> 0.0 expected points.
    """
    reserve_set = {str(pid) for pid in reserve}
    optimizer_players = []
    for pid in players:
        pid = str(pid)
        if pid == "0":
            continue
        data = universe.get(pid) or {}
        position = data.get("position") or "UNKNOWN"
        injury = data.get("injury_status")
        roster_status = "IR" if pid in reserve_set else None
        pts = projections.get(pid)
        optimizer_players.append(
            OptimizerPlayer(
                player_id=pid,
                position=position,
                expected_points=float(pts) if pts is not None else 0.0,
                on_bye=False,
                injury_status=injury,
                roster_status=roster_status,
            )
        )
    return optimizer_players


def _expected_optimal_flag(scn):
    """Derive the expected optimal_lineup_set for a scenario.

    Returns (has_players, expected_flag). When there are no optimizer players
    the endpoint short-circuits to False; otherwise the flag is True IFF every
    real starting slot is filled by the assignment.
    """
    opt_players = _build_optimizer_players_ref(
        scn["players"], scn["reserve"], scn["universe"], scn["projections"]
    )
    if not opt_players:
        return False, False

    eligible = apply_exclusions(opt_players)
    slots = starting_slots(scn["roster_positions"])
    assignment = assign_lineup(eligible, scn["roster_positions"])
    expected = bool(slots) and all(a is not None for a in assignment)
    return True, expected


# ---------------------------------------------------------------------------
# Patching harness
# ---------------------------------------------------------------------------

def _patches(
    *,
    rosters,
    universe,
    projections,
    roster_positions,
    state=None,
):
    """Patch every external symbol the recommendations endpoint touches."""
    state = state or {"season": 2025, "week": 8, "season_type": "regular"}
    league_info = {"roster_positions": roster_positions}
    return [
        patch("src.api.main.sleeper_client.get_league_rosters", return_value=rosters),
        patch("src.api.main.sleeper_client.get_nfl_state", return_value=state),
        patch("src.api.main.sleeper_client.get_scoring_format", return_value="ppr"),
        patch("src.api.main.sleeper_client.get_league_info", return_value=league_info),
        # Feed the generated universe as the enrichment source. Use a non-empty
        # sentinel when the universe is empty so _load_in_season_players does
        # not raise 500 on empty data (it only cares that the dict is truthy).
        patch(
            "src.api.main._load_in_season_players",
            return_value=universe if universe else {"__sentinel__": {}},
        ),
        patch("src.api.main._load_week_projections", return_value=projections),
        patch("src.api.main._get_matchup_grade_service", return_value=None),
    ]


def _enter_all(cms):
    for cm in cms:
        cm.__enter__()


def _exit_all(cms):
    for cm in reversed(cms):
        cm.__exit__(None, None, None)


def _target_roster(scn):
    return Roster(
        roster_id="1",
        owner_id=USER_ID,
        starters=[],
        players=list(scn["players"]),
        reserve=list(scn["reserve"]),
    )


# ---------------------------------------------------------------------------
# Property 24: Optimal lineup flag accuracy
# ---------------------------------------------------------------------------

class TestProperty24OptimalLineupFlagAccuracy:
    """Property 24: ``optimal_lineup_set`` matches the independently derived flag.

    **Validates: Requirements 8.10**
    """

    @settings(max_examples=120, deadline=None)
    @given(scn=scenario())
    def test_flag_matches_independent_derivation(self, scn):
        """For ANY roster + projections + slots, the endpoint flag is correct.

        The flag must be True IFF every starting slot in the optimal assignment
        is filled; False otherwise (including the no-slots and empty-roster
        cases). We also assert the flag is never True while a slot is empty.
        """
        has_players, expected_flag = _expected_optimal_flag(scn)

        rosters = [_target_roster(scn)]
        # When there are no projections at all the endpoint returns 503, which
        # is a different property; guarantee a non-empty projections map by
        # always providing at least one entry when the roster has real players.
        projections = dict(scn["projections"])
        real_ids = [p for p in scn["players"] if p != "0"]
        if real_ids and not projections:
            projections[real_ids[0]] = 1.0

        cms = _patches(
            rosters=rosters,
            universe=scn["universe"],
            projections=projections if real_ids else {"__force__": 1.0},
            roster_positions=scn["roster_positions"],
        )
        _enter_all(cms)
        try:
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/in-season/{LEAGUE_ID}/{USER_ID}/recommendations"
            )
        finally:
            _exit_all(cms)

        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Recompute the expected flag against the projections actually sent
        # (we may have injected one to avoid the 503 path).
        scn_sent = dict(scn)
        scn_sent["projections"] = projections
        _, expected_flag = _expected_optimal_flag(scn_sent)

        assert body["optimal_lineup_set"] == expected_flag, (
            f"flag mismatch: endpoint={body['optimal_lineup_set']} "
            f"expected={expected_flag} slots={starting_slots(scn['roster_positions'])}"
        )

        # Cross-check the invariant directly against the response rows: if the
        # flag is True, every real starting slot must be occupied by a START
        # row, so the number of START rows equals the number of starting slots.
        slots = starting_slots(scn["roster_positions"])
        start_rows = [r for r in body["recommendations"] if r["recommendation"] == "START"]
        if body["optimal_lineup_set"]:
            assert len(start_rows) == len(slots)
            assert len(slots) > 0
        # A START row always carries a non-null slot label; SIT rows never do.
        for r in body["recommendations"]:
            if r["recommendation"] == "START":
                assert r["slot"] is not None
            else:
                assert r["slot"] is None

    @settings(max_examples=60, deadline=None)
    @given(
        entries=player_entries(),
        roster_positions=roster_positions_strategy(),
    )
    def test_empty_roster_flag_is_false(self, entries, roster_positions):
        """A roster with no startable players yields optimal_lineup_set=False.

        We force an empty optimizer pool by giving the roster only the "0"
        sentinel (skipped) so the endpoint hits its empty-roster short circuit.
        """
        universe = {pid: data for pid, data in entries}
        rosters = [
            Roster(
                roster_id="1",
                owner_id=USER_ID,
                starters=[],
                players=["0"],  # only the empty-slot sentinel -> no real players
                reserve=[],
            )
        ]
        cms = _patches(
            rosters=rosters,
            universe=universe,
            projections={"__force__": 1.0},  # non-empty -> avoid 503 path
            roster_positions=roster_positions,
        )
        _enter_all(cms)
        try:
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/in-season/{LEAGUE_ID}/{USER_ID}/recommendations"
            )
        finally:
            _exit_all(cms)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["optimal_lineup_set"] is False
        assert body["recommendations"] == []


# ---------------------------------------------------------------------------
# Property 17: Error response safety
# ---------------------------------------------------------------------------

def _assert_clean_error(resp, allowed_status):
    """Assert an error response is a proper JSON error, not a leaked 500."""
    assert resp.status_code in allowed_status, resp.text
    assert resp.status_code != 500
    body = resp.json()
    assert "detail" in body
    assert isinstance(body["detail"], str)
    assert body["detail"]  # non-empty
    # Never leak internal traceback markers to the client.
    lowered = body["detail"].lower()
    assert "traceback" not in lowered
    assert "internal server error" not in lowered


class TestProperty17ErrorResponseSafety:
    """Property 17: expected error paths return clean 404/503 JSON, never 500.

    **Validates: Requirements 8.11**
    """

    @settings(max_examples=120, deadline=None)
    @given(
        league_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=12,
        ),
        user_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=12,
        ),
    )
    def test_missing_league_returns_404(self, league_id, user_id):
        """No rosters for the league -> 404 with a string detail, never 500."""
        cms = _patches(
            rosters=[],  # empty -> league not found
            universe={"__sentinel__": {}},
            projections={"__force__": 1.0},
            roster_positions=["QB", "RB", "BN"],
        )
        _enter_all(cms)
        try:
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/in-season/{league_id}/{user_id}/recommendations"
            )
        finally:
            _exit_all(cms)

        _assert_clean_error(resp, allowed_status={404})

    @settings(max_examples=120, deadline=None)
    @given(
        owner_ids=st.lists(
            st.integers(min_value=1, max_value=10_000),
            min_size=1,
            max_size=8,
            unique=True,
        ),
        missing_owner=st.integers(min_value=10_001, max_value=20_000),
    )
    def test_missing_user_returns_404(self, owner_ids, missing_owner):
        """League exists but target user has no roster -> 404, never 500."""
        rosters = [
            Roster(
                roster_id=str(i + 1),
                owner_id=str(owner),
                starters=[],
                players=[f"p{owner}"],
                reserve=[],
            )
            for i, owner in enumerate(owner_ids)
        ]
        cms = _patches(
            rosters=rosters,
            universe={f"p{owner_ids[0]}": {"position": "RB", "team": "KC"}},
            projections={"__force__": 1.0},
            roster_positions=["QB", "RB", "BN"],
        )
        _enter_all(cms)
        try:
            client = TestClient(app)
            # missing_owner is guaranteed outside owner_ids' range.
            resp = client.get(
                f"/api/v1/in-season/{LEAGUE_ID}/{missing_owner}/recommendations"
            )
        finally:
            _exit_all(cms)

        _assert_clean_error(resp, allowed_status={404})

    @settings(max_examples=120, deadline=None)
    @given(scn=scenario())
    def test_pending_projections_returns_503(self, scn):
        """Projections pending (empty map) -> 503 with a string detail, never 500.

        The league and target roster exist, so the only expected failure is the
        projections-pending branch regardless of the generated roster shape.
        """
        rosters = [_target_roster(scn)]
        cms = _patches(
            rosters=rosters,
            universe=scn["universe"],
            projections={},  # pending -> 503
            roster_positions=scn["roster_positions"],
        )
        _enter_all(cms)
        try:
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/in-season/{LEAGUE_ID}/{USER_ID}/recommendations"
            )
        finally:
            _exit_all(cms)

        _assert_clean_error(resp, allowed_status={503})


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
