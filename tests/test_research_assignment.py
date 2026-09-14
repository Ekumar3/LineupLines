"""Tests for research/assignment.py — exclusions, eligibility, and lineup matching."""

from research.assignment import LineupPlayer, apply_exclusions, assign_lineup, eligible_positions, starting_slots

ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN", "BN"]


def test_starting_slots_drops_bench_ir_taxi():
    assert starting_slots(["QB", "BN", "RB", "IR", "WR", "TAXI"]) == ["QB", "RB", "WR"]


def test_eligible_positions_named_slot_matches_only_itself():
    assert eligible_positions("QB") == {"QB"}
    assert eligible_positions("TE") == {"TE"}


def test_eligible_positions_flex_variants():
    assert eligible_positions("FLEX") == {"RB", "WR", "TE"}
    assert eligible_positions("SUPER_FLEX") == {"QB", "RB", "WR", "TE"}
    assert eligible_positions("REC_FLEX") == {"WR", "TE"}
    assert eligible_positions("WRRB_FLEX") == {"WR", "RB"}


def test_flex_picks_highest_expected_eligible_player():
    slots = ["RB", "WR", "TE", "FLEX"]
    players = [
        LineupPlayer("rb_a", "RB", 12.0),  # best RB -> RB slot
        LineupPlayer("rb_b", "RB", 9.0),   # 2nd-best RB -> should win FLEX
        LineupPlayer("wr_a", "WR", 11.0),  # best WR -> WR slot
        LineupPlayer("wr_b", "WR", 7.0),
        LineupPlayer("te_a", "TE", 6.0),   # best TE -> TE slot
        LineupPlayer("te_b", "TE", 5.0),
    ]
    lineup = assign_lineup(players, slots)

    assert [p.player_id for p in lineup] == ["rb_a", "wr_a", "te_a", "rb_b"]


def test_bye_player_is_never_assigned():
    players = [
        LineupPlayer("rb_bye", "RB", 100.0, on_bye=True),  # huge score, but on bye
        LineupPlayer("rb_ok", "RB", 5.0),
    ]
    pool = apply_exclusions(players)
    lineup = assign_lineup(pool, ["RB", "BN"])

    assigned_ids = {p.player_id for p in lineup if p is not None}
    assert "rb_bye" not in assigned_ids
    assert lineup[0] is not None and lineup[0].player_id == "rb_ok"


def test_out_and_doubtful_are_excluded_but_questionable_is_not():
    players = [
        LineupPlayer("out1", "RB", 30.0, injury_status="OUT"),
        LineupPlayer("doubtful1", "RB", 30.0, injury_status="DOUBTFUL"),
        LineupPlayer("questionable1", "RB", 10.0, injury_status="QUESTIONABLE"),
    ]
    pool = apply_exclusions(players)
    ids = {p.player_id for p in pool}
    assert ids == {"questionable1"}
    assert pool[0].is_questionable is True


def test_ir_and_taxi_roster_status_are_excluded():
    players = [
        LineupPlayer("ir1", "WR", 30.0, roster_status="IR"),
        LineupPlayer("taxi1", "WR", 30.0, roster_status="TAXI"),
        LineupPlayer("active1", "WR", 5.0, roster_status="ACTIVE"),
    ]
    pool = apply_exclusions(players)
    assert {p.player_id for p in pool} == {"active1"}


def test_fewer_healthy_eligible_players_than_slots_leaves_slot_empty():
    # Two RB slots, only one healthy eligible RB.
    players = [LineupPlayer("rb1", "RB", 12.0)]
    lineup = assign_lineup(players, ["RB", "RB"])

    assert lineup[0] is not None and lineup[0].player_id == "rb1"
    assert lineup[1] is None


def test_negative_expected_points_leaves_slot_empty_rather_than_start_a_net_negative():
    players = [LineupPlayer("bust", "RB", -3.0)]
    lineup = assign_lineup(players, ["RB"])
    assert lineup[0] is None


def test_no_players_returns_all_none_slots():
    lineup = assign_lineup([], ["QB", "RB", "RB"])
    assert lineup == [None, None, None]
