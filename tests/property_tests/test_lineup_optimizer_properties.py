"""Property-based tests for ``src.services.lineup_optimizer``.

Validates the universal correctness properties of the lineup slot assignment
solver against Hypothesis-generated rosters and league configurations:

- Property 4  — Lineup optimality: the Hungarian assignment's total expected
  points is never worse than a greedy baseline (fill each slot in order with
  the highest-scoring eligible unused player).
- Property 5  — Lineup eligibility: every assigned (player, slot) pair respects
  ``eligible_positions(slot)``; no player is assigned twice; the result length
  equals ``len(starting_slots(roster_positions))``.
- Property 6  — Exclusion correctness: ``apply_exclusions`` drops exactly the
  on-bye / OUT / DOUBTFUL / IR / TAXI players and retains every
  QUESTIONABLE/healthy player unchanged.
- Empty slot handling: with fewer eligible players than slots (or none eligible
  for a slot), those slots come back ``None`` and no exception is raised.

Unit tests (specific examples / edge cases) live separately in task 9.2; this
module covers the universal invariants only.

Performance note: ``linear_sum_assignment`` is exact but the cost matrix grows
with (players x (slots + players)). Generated sizes are kept small (<= ~14
players, <= ~10 slots) and every property runs at 200 Hypothesis examples,
comfortably above the 100-iteration bar in the design.

**Validates: Requirements 6.9, 6.10, 6.3, 6.4, 6.5, 6.11**
"""

from typing import List, Optional, Sequence

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.services.lineup_optimizer import (
    EXCLUDED_INJURY_STATUSES,
    EXCLUDED_ROSTER_STATUSES,
    FLEX_ELIGIBILITY,
    OptimizerPlayer,
    apply_exclusions,
    assign_lineup,
    eligible_positions,
    starting_slots,
)

# Positions the solver reasons about in start/sit (per task scope: QB/RB/WR/TE).
POSITIONS = ("QB", "RB", "WR", "TE")

# Named starting slots plus the flex-type slots the solver knows about. These
# are the only slot names a league config can draw from for these properties.
NAMED_SLOTS = ("QB", "RB", "WR", "TE")
FLEX_SLOTS = tuple(FLEX_ELIGIBILITY.keys())
STARTING_SLOT_CHOICES = NAMED_SLOTS + FLEX_SLOTS
NON_STARTING_SLOT_CHOICES = ("BN", "IR", "TAXI")

# Injury / roster status pools for the exclusion property. Deliberately mixes
# excluded statuses with retained ones (QUESTIONABLE, healthy/None).
INJURY_STATUSES = (None, "", "QUESTIONABLE", "OUT", "DOUBTFUL", "questionable", "out")
ROSTER_STATUSES = (None, "", "active", "IR", "TAXI", "ir", "taxi")


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_scores = st.floats(
    min_value=-50.0, max_value=60.0, allow_nan=False, allow_infinity=False
)


@st.composite
def _eligible_player(draw, idx):
    """A post-exclusion player: a position and an expected-points score.

    Health/bye fields are left at their eligible defaults — the optimality /
    eligibility properties assume exclusions have already been applied.
    """
    return OptimizerPlayer(
        player_id=f"p{idx}",
        position=draw(st.sampled_from(POSITIONS)),
        expected_points=draw(_scores),
    )


@st.composite
def _eligible_roster(draw):
    """A list of eligible players with unique ids."""
    n = draw(st.integers(min_value=0, max_value=14))
    return [draw(_eligible_player(i)) for i in range(n)]


@st.composite
def _roster_positions(draw):
    """A league roster_positions array mixing starting and bench slots."""
    n = draw(st.integers(min_value=0, max_value=10))
    return draw(
        st.lists(
            st.sampled_from(STARTING_SLOT_CHOICES + NON_STARTING_SLOT_CHOICES),
            min_size=n,
            max_size=n,
        )
    )


@st.composite
def _raw_player(draw, idx):
    """A player with arbitrary health/bye/roster status for the exclusion test."""
    return OptimizerPlayer(
        player_id=f"p{idx}",
        position=draw(st.sampled_from(POSITIONS)),
        expected_points=draw(_scores),
        on_bye=draw(st.booleans()),
        injury_status=draw(st.sampled_from(INJURY_STATUSES)),
        roster_status=draw(st.sampled_from(ROSTER_STATUSES)),
    )


@st.composite
def _raw_roster(draw):
    n = draw(st.integers(min_value=0, max_value=16))
    return [draw(_raw_player(i)) for i in range(n)]


# ---------------------------------------------------------------------------
# Baselines / helpers used by the properties
# ---------------------------------------------------------------------------

def _total(assignment: Sequence[Optional[OptimizerPlayer]]) -> float:
    """Sum of expected points over all non-None assigned players."""
    return sum(p.expected_points for p in assignment if p is not None)


def _greedy_assignment(
    players: Sequence[OptimizerPlayer], roster_positions: Sequence[str]
) -> List[Optional[OptimizerPlayer]]:
    """Fill each slot in order with the highest-scoring eligible unused player.

    A plausible-but-suboptimal heuristic: it never reconsiders an earlier slot,
    so it can strand a double-eligible player. Only players with positive
    expected points are worth starting (a dummy "sit" always scores 0), matching
    the solver's freedom to bench a net-negative player. This is the baseline
    Property 4 says the Hungarian solver must never underperform.
    """
    slots = starting_slots(roster_positions)
    used = set()
    result: List[Optional[OptimizerPlayer]] = [None] * len(slots)
    for j, slot in enumerate(slots):
        allowed = eligible_positions(slot)
        best = None
        best_idx = None
        for i, player in enumerate(players):
            if i in used:
                continue
            if player.position not in allowed:
                continue
            if player.expected_points <= 0:
                continue  # benching (0) beats starting a negative scorer
            if best is None or player.expected_points > best.expected_points:
                best = player
                best_idx = i
        if best is not None:
            result[j] = best
            used.add(best_idx)
    return result


# ===========================================================================
# Property 4 — Lineup optimality
# ===========================================================================

@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(players=_eligible_roster(), roster_positions=_roster_positions())
def test_assignment_never_worse_than_greedy(players, roster_positions):
    """Property 4: the solver's total expected points is >= a greedy baseline.

    The Hungarian (max-weight bipartite matching) solution is globally optimal,
    so for ANY roster and ANY slot config it must score at least as high as the
    order-dependent greedy fill.

    **Validates: Requirements 6.9**
    """
    optimal = assign_lineup(players, roster_positions)
    greedy = _greedy_assignment(players, roster_positions)

    # A tiny epsilon absorbs floating-point noise in the two summations.
    assert _total(optimal) >= _total(greedy) - 1e-9, (
        f"Hungarian total {_total(optimal)} < greedy {_total(greedy)}"
    )


# ===========================================================================
# Property 5 — Lineup eligibility
# ===========================================================================

@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(players=_eligible_roster(), roster_positions=_roster_positions())
def test_assignment_respects_eligibility_and_uniqueness(players, roster_positions):
    """Property 5: every assigned player is position-eligible for its slot, no
    player is assigned twice, and the result aligns to the starting slots.

    **Validates: Requirements 6.8, 6.10**
    """
    slots = starting_slots(roster_positions)
    result = assign_lineup(players, roster_positions)

    # Length aligns exactly to the real starting slots (order + duplicates).
    assert len(result) == len(slots)

    assigned_ids = []
    for slot, player in zip(slots, result):
        if player is None:
            continue
        # Position eligibility.
        assert player.position in eligible_positions(slot), (
            f"{player.position} not eligible for slot {slot}"
        )
        assigned_ids.append(player.player_id)

    # No duplicate player assignment.
    assert len(assigned_ids) == len(set(assigned_ids)), "a player was started twice"

    # Every assigned player came from the input pool.
    input_ids = {p.player_id for p in players}
    assert set(assigned_ids) <= input_ids


# ===========================================================================
# Property 6 — Exclusion correctness
# ===========================================================================

@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(players=_raw_roster())
def test_exclusions_drop_exactly_the_ineligible(players):
    """Property 6: apply_exclusions removes exactly on_bye / OUT / DOUBTFUL /
    IR / TAXI players and keeps every other (QUESTIONABLE or healthy) player,
    unchanged and in order.

    **Validates: Requirements 6.3, 6.4, 6.5, 6.11**
    """
    result = apply_exclusions(players)
    result_ids = [p.player_id for p in result]

    def should_exclude(p: OptimizerPlayer) -> bool:
        if p.on_bye:
            return True
        if (p.injury_status or "").upper() in EXCLUDED_INJURY_STATUSES:
            return True
        if (p.roster_status or "").upper() in EXCLUDED_ROSTER_STATUSES:
            return True
        return False

    expected = [p for p in players if not should_exclude(p)]
    expected_ids = [p.player_id for p in expected]

    # Exactly the right players survive, in original order.
    assert result_ids == expected_ids

    # No excluded condition slipped through.
    for p in result:
        assert not p.on_bye
        assert (p.injury_status or "").upper() not in EXCLUDED_INJURY_STATUSES
        assert (p.roster_status or "").upper() not in EXCLUDED_ROSTER_STATUSES

    # Retained players are the same objects (full-weight, unchanged).
    retained_by_id = {p.player_id: p for p in result}
    for p in expected:
        kept = retained_by_id[p.player_id]
        assert kept is p
        assert kept.expected_points == p.expected_points

    # QUESTIONABLE players specifically are never dropped.
    for p in players:
        if (p.injury_status or "").upper() == "QUESTIONABLE" and not p.on_bye \
                and (p.roster_status or "").upper() not in EXCLUDED_ROSTER_STATUSES:
            assert p.player_id in retained_by_id


# ===========================================================================
# Empty slot handling
# ===========================================================================

@st.composite
def _restricted_roster(draw):
    """Players drawn from a limited position set, to force unfillable slots."""
    allowed = draw(st.lists(st.sampled_from(POSITIONS), min_size=1, max_size=2,
                            unique=True))
    n = draw(st.integers(min_value=0, max_value=6))
    return [
        OptimizerPlayer(
            player_id=f"p{i}",
            position=draw(st.sampled_from(allowed)),
            expected_points=draw(_scores),
        )
        for i in range(n)
    ]


@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(players=_restricted_roster(), roster_positions=_roster_positions())
def test_empty_slots_are_none_and_no_exception(players, roster_positions):
    """Empty slot handling: when there aren't enough eligible players for every
    slot (or none eligible for a given slot), those slots are None and the call
    never raises.

    **Validates: Requirements 6.9**
    """
    result = assign_lineup(players, roster_positions)  # must not raise
    slots = starting_slots(roster_positions)

    assert len(result) == len(slots)

    # Number of filled slots can never exceed the number of players available.
    filled = [p for p in result if p is not None]
    assert len(filled) <= len(players)

    # A slot with zero eligible players in the pool must be None.
    for slot, player in zip(slots, result):
        pool = [p for p in players if p.position in eligible_positions(slot)]
        if not pool:
            assert player is None
