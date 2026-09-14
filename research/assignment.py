"""Lineup slot assignment: exclusions, eligibility, and optimal matching.

Given a roster of scored players and a league's roster_positions array, picks
which player starts in which slot to maximize total expected points. This is
a maximum-weight bipartite matching problem (players x slots), solved exactly
with scipy.optimize.linear_sum_assignment — never a greedy fill, so it can't
get stuck starting a mediocre FLEX-only player over a double-eligible one that
was needed to fill a named slot.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

import numpy as np
from scipy.optimize import linear_sum_assignment

# Roster slots that are never "starting" lineup slots.
NON_STARTING_SLOTS = {"BN", "IR", "TAXI"}

# Injury statuses that keep a player out of the eligible pool entirely.
# QUESTIONABLE is deliberately absent — those players stay in the pool at
# full weight (see apply_exclusions docstring).
EXCLUDED_INJURY_STATUSES = {"OUT", "DOUBTFUL"}

# Roster statuses (distinct from injury status) that exclude a player.
EXCLUDED_ROSTER_STATUSES = {"IR", "TAXI"}

# Flex-type slots and the positions eligible to fill them. Named slots
# (QB/RB/WR/TE/K/DEF/...) aren't listed here — they fall back to matching
# their own position exactly (see `eligible_positions`).
FLEX_ELIGIBILITY: Dict[str, Set[str]] = {
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "REC_FLEX": {"WR", "TE"},
    "WRRB_FLEX": {"WR", "RB"},
}

# A cost the solver will never prefer over leaving a slot empty (a dummy
# column costs 0). Must be much larger than any realistic |expected_points|.
_INELIGIBLE_COST = 1e6


@dataclass
class LineupPlayer:
    """A single player as seen by the assignment solver.

    Only the fields the solver and its tests need — the caller's richer
    prediction-log row carries everything else.
    """

    player_id: str
    position: str
    expected_points: float
    on_bye: bool = False
    injury_status: Optional[str] = None
    roster_status: Optional[str] = None
    is_questionable: bool = field(init=False, default=False)

    def __post_init__(self):
        self.is_questionable = (self.injury_status or "").upper() == "QUESTIONABLE"


def starting_slots(roster_positions: Sequence[str]) -> List[str]:
    """Filter a league's roster_positions array down to real starting slots.

    Drops BN/IR/TAXI; preserves order and duplicates (e.g. two "RB" slots
    stay two separate slots).
    """
    return [slot for slot in roster_positions if slot not in NON_STARTING_SLOTS]


def eligible_positions(slot: str) -> Set[str]:
    """Positions allowed to fill a given slot.

    Flex-type slots (FLEX/SUPER_FLEX/REC_FLEX/WRRB_FLEX) come from
    FLEX_ELIGIBILITY; any other slot name (QB/RB/WR/TE/K/DEF/...) matches
    only its own position.
    """
    return FLEX_ELIGIBILITY.get(slot, {slot})


def apply_exclusions(players: Sequence[LineupPlayer]) -> List[LineupPlayer]:
    """Drop players who cannot be started this week.

    Excluded: on bye, injury status OUT or DOUBTFUL, roster status IR or
    TAXI. QUESTIONABLE players are kept in the pool at full expected-points
    weight — `is_questionable` is set for callers that want to flag it in
    the UI/log, but it does not affect eligibility or weighting here.
    """
    excluded = []
    for player in players:
        if player.on_bye:
            continue
        if (player.injury_status or "").upper() in EXCLUDED_INJURY_STATUSES:
            continue
        if (player.roster_status or "").upper() in EXCLUDED_ROSTER_STATUSES:
            continue
        excluded.append(player)
    return excluded


def assign_lineup(
    players: Sequence[LineupPlayer],
    roster_positions: Sequence[str],
) -> List[Optional[LineupPlayer]]:
    """Assign players to starting slots to maximize total expected points.

    `players` should already have exclusions applied (see apply_exclusions) —
    this function does no health/bye filtering of its own, only eligibility.

    Solved as a maximum-weight bipartite matching: rows are players, columns
    are starting slots plus one dummy "sit" column per player (cost 0), so
    the solver is always free to bench a player rather than force them into
    a slot they're ineligible for, or into a slot where they'd score less
    than nothing. Real slot columns cost -expected_points when the player is
    eligible for that slot, or a very large cost otherwise (never chosen).

    Args:
        players: Eligible players (post-exclusion) to consider starting.
        roster_positions: The league's raw roster_positions array; BN/IR/TAXI
            are filtered out internally via `starting_slots`.

    Returns:
        A list aligned to `starting_slots(roster_positions)` (same order,
        same duplicates), each entry either the assigned LineupPlayer or
        None if no eligible player was left for that slot.
    """
    slots = starting_slots(roster_positions)
    n_slots = len(slots)
    n_players = len(players)

    if n_slots == 0:
        return []
    if n_players == 0:
        return [None] * n_slots

    n_cols = n_slots + n_players  # real slots + one dummy "sit" column per player
    cost = np.zeros((n_players, n_cols))
    for i, player in enumerate(players):
        for j, slot in enumerate(slots):
            if player.position in eligible_positions(slot):
                cost[i, j] = -player.expected_points
            else:
                cost[i, j] = _INELIGIBLE_COST
        # cost[i, n_slots:] stays 0 — the dummy "sit" columns.

    row_idx, col_idx = linear_sum_assignment(cost)

    result: List[Optional[LineupPlayer]] = [None] * n_slots
    for r, c in zip(row_idx, col_idx):
        if c < n_slots and cost[r, c] < _INELIGIBLE_COST:
            result[c] = players[r]
    return result
