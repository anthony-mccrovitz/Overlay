"""Tests for the live draft assistant.

A cheat sheet tells you who is best. The assistant has to answer the question
you actually face on a 60-second clock: of the players you want, which one will
still be there next time? Everything here protects that reasoning.
"""
import pytest

from src.fantasy.draft import (
    BENCH_DECAY, DraftState, need_multiplier, recommend, roster_counts,
    survival_probability,
)
from src.fantasy.valuation import PlayerValue


def _pv(pid, pos, vorp, adp=None):
    return PlayerValue(player_id=pid, name=pid, position=pos, team="X",
                       vorp=vorp, raw_vorp=vorp, adp=adp)


class TestSnakeOrder:
    def test_slot_ten_of_twelve_picks_back_to_back_at_the_turn(self):
        """Anthony drafts 10th in a 12-team snake, so picks 10 and 15 are five
        apart. That is the whole strategy at this slot: plan in pairs."""
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=10, picks_made=0)
        assert st.my_next_picks(4) == [10, 15, 34, 39]

    def test_slot_one_waits_a_full_round(self):
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=1, picks_made=0)
        assert st.my_next_picks(3) == [1, 24, 25]

    def test_past_picks_are_not_offered(self):
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=10, picks_made=20)
        assert all(p >= 21 for p in st.my_next_picks(3))


class TestSurvival:
    def test_early_adp_will_not_last(self):
        assert survival_probability(20, picks_until_next=22, current_pick=10) < 0.10

    def test_late_adp_will_last(self):
        assert survival_probability(90, picks_until_next=22, current_pick=10) > 0.90

    def test_survival_falls_as_the_wait_grows(self):
        near = survival_probability(40, 5, 10)
        far = survival_probability(40, 40, 10)
        assert near > far

    def test_unknown_adp_is_assumed_mostly_available(self):
        """A player with no ADP is deep enough that nobody is racing us."""
        assert survival_probability(None, 20, 10) > 0.5


class TestRosterNeed:
    def test_starters_are_full_value(self):
        assert need_multiplier("RB", have=1, starters_needed={"RB": 2}) == 1.0

    def test_bench_value_decays(self):
        """Raw VORP says a 4th RB is as good as a 1st. He cannot be started."""
        # have == need means starters are full, so the NEXT one is bench.
        m1 = need_multiplier("RB", have=2, starters_needed={"RB": 2})
        m3 = need_multiplier("RB", have=4, starters_needed={"RB": 2})
        assert 1.0 > m1 > m3
        assert m1 == BENCH_DECAY[0]
        assert m3 == BENCH_DECAY[2]

    def test_need_stops_the_board_hammering_one_position(self):
        """In a 2WR league RBs top the board; without a need multiplier the
        assistant would recommend RB with every single pick."""
        board = [_pv(f"rb{i}", "RB", 100 - i, adp=i + 1) for i in range(6)]
        board += [_pv(f"wr{i}", "WR", 80 - i, adp=20 + i) for i in range(6)]
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=1,
                        picks_made=30, my_players=["rb0", "rb1", "rb2", "rb3"])
        recs = recommend(board, st, {"RB": 2, "WR": 2}, top=3)
        assert recs[0].value.position == "WR"


class TestRecommendation:
    def test_taken_players_are_excluded(self):
        board = [_pv("a", "RB", 100, adp=1), _pv("b", "RB", 90, adp=2)]
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=1,
                        picks_made=1, taken={"a"})
        recs = recommend(board, st, {"RB": 2})
        assert [r.value.player_id for r in recs] == ["b"]

    def test_urgency_promotes_the_player_who_will_not_last(self):
        """Two near-equal players: take the one who disappears, get the other
        next round. This is the difference between ranking and drafting."""
        board = [_pv("gone", "RB", 100, adp=11), _pv("stays", "RB", 102, adp=95)]
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=10, picks_made=9)
        recs = recommend(board, st, {"RB": 2})
        assert recs[0].value.player_id == "gone"
        assert "won't last" in recs[0].reason

    def test_imputed_note_is_surfaced(self):
        """A rookie valued off market consensus must say so on the clock."""
        v = _pv("rook", "RB", 50, adp=21)
        v.note = "ROOKIE — market value"
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=10, picks_made=9)
        recs = recommend([v], st, {"RB": 2})
        assert "ROOKIE" in recs[0].reason

    def test_roster_counts_only_counts_my_players(self):
        board = [_pv("a", "RB", 10), _pv("b", "WR", 10)]
        counts = roster_counts(["a"], {v.player_id: v for v in board})
        assert counts["RB"] == 1 and counts["WR"] == 0
