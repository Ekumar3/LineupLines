"""Unit tests for src/services/lineup_optimizer.py.

Covers exclusion logic, optimal (non-greedy) slot assignment, position
eligibility, empty slots, and the starting_slots / eligible_positions helpers.
"""

from src.services.lineup_optimizer import (
    FLEX_ELIGIBILITY,
    OptimizerPlayer,
    apply_exclusions,
    assign_lineup,
    eligible_positions,
    starting_slots,
)


# --- Exclusion logic (Requirement 6.2) ---------------------------------------


class TestApplyExclusions:
    def test_on_bye_is_excluded(self):
        players = [
            OptimizerPlayer("bye_rb", "RB", 50.0, on_bye=True),
            OptimizerPlayer("active_rb", "RB", 4.0),
        ]
        pool = apply_exclusions(players)
        assert {p.player_id for p in pool} == {"active_rb"}

    def test_injury_out_and_doubtful_are_excluded(self):
        players = [
            OptimizerPlayer("out1", "WR", 40.0, injury_status="OUT"),
            OptimizerPlayer("doubtful1", "WR", 40.0, injury_status="DOUBTFUL"),
            OptimizerPlayer("healthy1", "WR", 6.0),
        ]
        pool = apply_exclusions(players)
        assert {p.player_id for p in pool} == {"healthy1"}

    def test_roster_status_ir_and_taxi_are_excluded(self):
        players = [
            OptimizerPlayer("ir1", "TE", 40.0, roster_status="IR"),
            OptimizerPlayer("taxi1", "TE", 40.0, roster_status="TAXI"),
            OptimizerPlayer("active1", "TE", 5.0, roster_status="ACTIVE"),
        ]
        pool = apply_exclusions(players)
        assert {p.player_id for p in pool} == {"active1"}

    def test_questionable_is_kept_at_full_value_with_flag_set(self):
        players = [
            OptimizerPlayer("q1", "RB", 15.0, injury_status="QUESTIONABLE"),
        ]
        pool = apply_exclusions(players)
        assert len(pool) == 1
        kept = pool[0]
        assert kept.player_id == "q1"
        # Full expected-points weight is preserved (not discounted).
        assert kept.expected_points == 15.0
        assert kept.is_questionable is True

    def test_mixed_roster_keeps_only_startable_players(self):
        players = [
            OptimizerPlayer("bye", "QB", 30.0, on_bye=True),
            OptimizerPlayer("out", "RB", 30.0, injury_status="OUT"),
            OptimizerPlayer("doubtful", "RB", 30.0, injury_status="DOUBTFUL"),
            OptimizerPlayer("ir", "WR", 30.0, roster_status="IR"),
            OptimizerPlayer("taxi", "WR", 30.0, roster_status="TAXI"),
            OptimizerPlayer("quest", "WR", 20.0, injury_status="QUESTIONABLE"),
            OptimizerPlayer("healthy", "TE", 10.0),
        ]
        pool = apply_exclusions(players)
        assert {p.player_id for p in pool} == {"quest", "healthy"}

    def test_injury_status_matching_is_case_insensitive(self):
        players = [
            OptimizerPlayer("out_lower", "RB", 20.0, injury_status="out"),
            OptimizerPlayer("ok", "RB", 5.0),
        ]
        pool = apply_exclusions(players)
        assert {p.player_id for p in pool} == {"ok"}


# --- Optimal assignment beats greedy (Requirement 6.7) -----------------------


class TestOptimalAssignmentBeatsGreedy:
    def test_dual_eligible_high_scorer_not_wasted_in_flex(self):
        # Slots: one RB, one WR, one FLEX.
        # A greedy "fill named slots first" pass would place the single best RB
        # (rb_star, 25) into the RB slot, the single WR into WR, then be forced
        # to fill FLEX with the leftover weak RB (rb_weak, 3) -> total 25+8+3=36.
        #
        # The optimal solution keeps rb_star for FLEX is NOT better here; the
        # real trap is the reverse: a strong WR that a greedy fill would strand.
        # Construct a case where greedy named-first is strictly worse.
        slots = ["RB", "WR", "FLEX"]
        players = [
            OptimizerPlayer("rb_only", "RB", 20.0),   # only eligible for RB/FLEX
            OptimizerPlayer("wr_strong", "WR", 18.0),  # WR/FLEX
            OptimizerPlayer("wr_weak", "WR", 4.0),     # WR/FLEX
        ]
        lineup = assign_lineup(players, slots)

        total = sum(p.expected_points for p in lineup if p is not None)
        # Optimal: rb_only -> RB(20), wr_strong -> WR(18), wr_weak -> FLEX(4) = 42
        assert total == 42.0
        assigned = {p.player_id for p in lineup if p is not None}
        assert assigned == {"rb_only", "wr_strong", "wr_weak"}

    def test_greedy_flex_first_would_be_suboptimal(self):
        # Classic greedy trap: if FLEX were filled first with the single highest
        # scorer overall, a named slot could be left starved.
        # Slots: TE, FLEX. Players: one elite TE (eligible TE and FLEX) and one
        # WR (FLEX only among these slots).
        # Greedy-by-score fills FLEX with te_elite (22), leaving TE slot only
        # te_backup... but here there's no te_backup, so TE would go empty and
        # wr would be benched -> greedy total 22.
        # Optimal: te_elite -> TE(22), wr -> FLEX(15) = 37.
        slots = ["TE", "FLEX"]
        players = [
            OptimizerPlayer("te_elite", "TE", 22.0),
            OptimizerPlayer("wr", "WR", 15.0),
        ]
        lineup = assign_lineup(players, slots)

        total = sum(p.expected_points for p in lineup if p is not None)
        assert total == 37.0
        assert lineup[0].player_id == "te_elite"  # TE slot
        assert lineup[1].player_id == "wr"         # FLEX slot

    def test_two_rb_slots_plus_flex_picks_best_three_eligible(self):
        slots = ["RB", "RB", "WR", "FLEX"]
        players = [
            OptimizerPlayer("rb1", "RB", 14.0),
            OptimizerPlayer("rb2", "RB", 12.0),
            OptimizerPlayer("rb3", "RB", 10.0),
            OptimizerPlayer("wr1", "WR", 11.0),
            OptimizerPlayer("wr2", "WR", 2.0),
        ]
        lineup = assign_lineup(players, slots)

        total = sum(p.expected_points for p in lineup if p is not None)
        # Best achievable: rb1(14)+rb2(12) in RB slots, wr1(11) in WR,
        # rb3(10) in FLEX = 47 (rb3 beats wr2 for the flex spot).
        assert total == 47.0
        flex_player = lineup[3]
        assert flex_player is not None and flex_player.player_id == "rb3"


# --- Position eligibility respected (Requirement 6.8) ------------------------


class TestPositionEligibility:
    def test_flex_accepts_rb_wr_te_but_not_qb(self):
        slots = ["FLEX"]
        qb = OptimizerPlayer("qb1", "QB", 30.0)
        lineup = assign_lineup([qb], slots)
        # QB is ineligible for FLEX -> slot stays empty.
        assert lineup[0] is None

        for pos in ("RB", "WR", "TE"):
            lineup = assign_lineup([OptimizerPlayer(f"{pos}1", pos, 10.0)], ["FLEX"])
            assert lineup[0] is not None and lineup[0].position == pos

    def test_super_flex_accepts_qb(self):
        lineup = assign_lineup([OptimizerPlayer("qb1", "QB", 25.0)], ["SUPER_FLEX"])
        assert lineup[0] is not None and lineup[0].player_id == "qb1"

    def test_direct_qb_slot_accepts_only_qb(self):
        rb = OptimizerPlayer("rb1", "RB", 30.0)
        lineup = assign_lineup([rb], ["QB"])
        assert lineup[0] is None  # RB can't fill a QB slot

        qb = OptimizerPlayer("qb1", "QB", 5.0)
        lineup = assign_lineup([qb], ["QB"])
        assert lineup[0] is not None and lineup[0].player_id == "qb1"

    def test_no_player_assigned_to_ineligible_slot(self):
        slots = ["QB", "RB", "WR", "TE", "FLEX"]
        players = [
            OptimizerPlayer("qb1", "QB", 20.0),
            OptimizerPlayer("rb1", "RB", 15.0),
            OptimizerPlayer("wr1", "WR", 12.0),
            OptimizerPlayer("te1", "TE", 8.0),
            OptimizerPlayer("rb2", "RB", 7.0),
        ]
        lineup = assign_lineup(players, slots)
        for slot, player in zip(slots, lineup):
            if player is not None:
                assert player.position in eligible_positions(slot)


# --- Empty slots -------------------------------------------------------------


class TestEmptySlots:
    def test_slot_with_no_eligible_player_is_none(self):
        # Only a WR available for a QB + WR lineup -> QB slot empty.
        players = [OptimizerPlayer("wr1", "WR", 10.0)]
        lineup = assign_lineup(players, ["QB", "WR"])
        assert lineup[0] is None
        assert lineup[1] is not None and lineup[1].player_id == "wr1"

    def test_more_slots_than_eligible_players_leaves_extras_none(self):
        players = [OptimizerPlayer("rb1", "RB", 9.0)]
        lineup = assign_lineup(players, ["RB", "RB"])
        assert lineup[0] is not None and lineup[0].player_id == "rb1"
        assert lineup[1] is None

    def test_no_players_returns_all_none(self):
        lineup = assign_lineup([], ["QB", "RB", "WR"])
        assert lineup == [None, None, None]


# --- starting_slots / eligible_positions helpers (Requirement 6.8) -----------


class TestStartingSlots:
    def test_drops_bn_ir_taxi(self):
        roster = ["QB", "BN", "RB", "IR", "WR", "TAXI", "FLEX"]
        assert starting_slots(roster) == ["QB", "RB", "WR", "FLEX"]

    def test_preserves_order_and_duplicate_slots(self):
        roster = ["RB", "RB", "WR", "WR", "WR", "BN", "BN"]
        assert starting_slots(roster) == ["RB", "RB", "WR", "WR", "WR"]

    def test_empty_when_all_non_starting(self):
        assert starting_slots(["BN", "IR", "TAXI"]) == []


class TestEligiblePositions:
    def test_named_slot_matches_only_itself(self):
        assert eligible_positions("QB") == {"QB"}
        assert eligible_positions("RB") == {"RB"}
        assert eligible_positions("K") == {"K"}
        assert eligible_positions("DEF") == {"DEF"}

    def test_flex_variants_match_eligibility_table(self):
        assert eligible_positions("FLEX") == {"RB", "WR", "TE"}
        assert eligible_positions("SUPER_FLEX") == {"QB", "RB", "WR", "TE"}
        assert eligible_positions("REC_FLEX") == {"WR", "TE"}
        assert eligible_positions("WRRB_FLEX") == {"WR", "RB"}

    def test_matches_flex_eligibility_constant(self):
        for slot, positions in FLEX_ELIGIBILITY.items():
            assert eligible_positions(slot) == positions
