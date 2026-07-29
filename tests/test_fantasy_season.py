"""Tests for the in-season tools and the draft simulator.

The draft is one day; the season is fourteen weeks and most leagues are decided
after it. Every function here answers the same question — what is a player worth
to THIS roster for the games that remain — which is why none of them can be
evaluated on a ranking alone.
"""
import pytest

from src.fantasy.draft import positional_run, run_alert
from src.fantasy.season import evaluate_trade, faab_bid, start_sit
from src.fantasy.simulate import lineup_value, simulate_opening
from src.fantasy.valuation import PlayerValue


def mk(pid, pos, vorp, team="X", bye=None, adp=None):
    return PlayerValue(player_id=pid, name=pid, position=pos, team=team,
                       vorp=vorp, raw_vorp=vorp, bye=bye, adp=adp)


NEED = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
ROSTER_POS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN"]


class TestFaab:
    def _roster(self):
        return [mk("rb1", "RB", 90), mk("rb2", "RB", 40),
                mk("wr1", "WR", 80), mk("wr2", "WR", 30)]

    def test_a_player_who_cannot_start_is_worth_nothing(self):
        """The mistake that loses FAAB leagues: bidding on a name. A back who
        would be your third adds nothing to a lineup that starts two."""
        bid = faab_bid(mk("x", "RB", 20), self._roster(), NEED, budget_left=100)
        assert bid.dollars == 0
        assert "would not crack" in bid.reason

    def test_bid_scales_with_the_upgrade(self):
        small = faab_bid(mk("s", "RB", 50), self._roster(), NEED, 100)
        big = faab_bid(mk("b", "RB", 95), self._roster(), NEED, 100)
        assert big.dollars > small.dollars > 0

    def test_bid_shrinks_late_in_the_season(self):
        """Budget is non-renewable; the same upgrade in week 12 buys fewer weeks
        than in week 2."""
        early = faab_bid(mk("b", "RB", 95), self._roster(), NEED, 100, weeks_left=14)
        late = faab_bid(mk("b", "RB", 95), self._roster(), NEED, 100, weeks_left=3)
        assert early.dollars > late.dollars

    def test_never_bids_the_whole_budget(self):
        bid = faab_bid(mk("god", "RB", 500), self._roster(), NEED, 100)
        assert bid.dollars < 100

    def test_empty_starting_slot_counts_as_full_upgrade(self):
        roster = [mk("rb1", "RB", 90)]          # only one RB, need two
        bid = faab_bid(mk("new", "RB", 60), roster, NEED, 100)
        assert bid.upgrade == pytest.approx(60.0)


class TestTrades:
    def _roster(self):
        return [mk("rb1", "RB", 90), mk("rb2", "RB", 60), mk("rb3", "RB", 55),
                mk("wr1", "WR", 70), mk("wr2", "WR", 25), mk("te1", "TE", 30)]

    def test_consolidation_is_valued_correctly(self):
        """Two players who become your RB3 and RB4 are worth almost nothing;
        counting raw value on both sides is how people lose 2-for-1s."""
        v = evaluate_trade(self._roster(), give=[mk("rb3", "RB", 55)],
                           get=[mk("elite", "WR", 95)], starters_needed=NEED)
        assert v.delta > 0
        assert "ACCEPT" in v.verdict

    def test_quantity_for_quality_is_flagged(self):
        v = evaluate_trade(self._roster(), give=[mk("rb1", "RB", 90)],
                           get=[mk("a", "RB", 50), mk("b", "RB", 48)],
                           starters_needed=NEED)
        assert v.delta < 0
        assert any("take on bodies" in n for n in v.notes)

    def test_neutral_trade_is_not_oversold(self):
        v = evaluate_trade(self._roster(), give=[mk("wr2", "WR", 25)],
                           get=[mk("x", "WR", 27)], starters_needed=NEED)
        assert "neutral" in v.verdict

    def test_equal_value_swap_is_correctly_neutral(self):
        """Trading a 55-VORP flex RB for a 55-VORP WR changes nothing: the
        receiver he displaces simply slides into the flex. Raw totals are equal
        AND the lineup is equal, and the tool must say so rather than inventing
        a gain."""
        v = evaluate_trade(self._roster(), give=[mk("rb3", "RB", 55)],
                           get=[mk("wrX", "WR", 55)], starters_needed=NEED)
        assert v.delta == pytest.approx(0.0)

    def test_upgrading_a_weak_starting_slot_reads_positive(self):
        """The roster's soft spot is WR2 at 25. Turning a spare RB into a real
        receiver moves the lineup even though the roster total barely changes."""
        v = evaluate_trade(self._roster(), give=[mk("rb3", "RB", 55)],
                           get=[mk("wrX", "WR", 72)], starters_needed=NEED)
        assert v.delta > 0


class _View:
    opp = {"AAA": {5: "SOFT"}, "BBB": {5: "HARD"}, "CCC": {}}
    allowed = {"SOFT": {"RB": 32.0}, "HARD": {"RB": 12.0}}
    league_avg = {"RB": 22.0}


class TestStartSit:
    def test_good_matchup_ranks_higher_all_else_equal(self):
        res = start_sit([mk("a", "RB", 50, team="AAA"), mk("b", "RB", 50, team="BBB")],
                        week=5, view=_View(), starters_needed=NEED)
        assert res[0].player.player_id == "a"

    def test_matchup_cannot_override_a_large_talent_gap(self):
        """The most common start/sit error is benching a stud because the
        matchup looks hard."""
        res = start_sit([mk("stud", "RB", 90, team="BBB"), mk("scrub", "RB", 40, team="AAA")],
                        week=5, view=_View(), starters_needed=NEED)
        assert res[0].player.player_id == "stud"

    def test_bye_week_player_cannot_start(self):
        res = start_sit([mk("c", "RB", 90, team="CCC")], week=5,
                        view=_View(), starters_needed=NEED)
        assert res[0].verdict.startswith("BYE")

    def test_verdicts_respect_starting_slots(self):
        players = [mk(f"rb{i}", "RB", 90 - i * 10, team="AAA") for i in range(4)]
        res = start_sit(players, week=5, view=_View(), starters_needed=NEED)
        assert sum(1 for r in res if r.verdict == "START") == NEED["RB"]


class TestRunDetection:
    def test_a_run_is_flagged(self):
        board = {f"p{i}": mk(f"p{i}", "RB", 50) for i in range(8)}
        picks = [{"player_id": f"p{i}"} for i in range(5)]
        assert "RUN" in (run_alert(positional_run(picks, board)) or "")

    def test_a_mixed_board_is_not_a_run(self):
        board = {"a": mk("a", "RB", 1), "b": mk("b", "WR", 1),
                 "c": mk("c", "TE", 1), "d": mk("d", "QB", 1)}
        picks = [{"player_id": x} for x in ("a", "b", "c", "d")]
        assert run_alert(positional_run(picks, board)) is None


class TestSimulator:
    def test_lineup_value_ignores_unstartable_depth(self):
        """A fourth running back contributes nothing to a lineup that starts
        two plus a flex."""
        two = [mk("a", "RB", 100), mk("b", "RB", 90)]
        four = two + [mk("c", "RB", 80), mk("d", "RB", 70)]
        v2 = lineup_value(two, ROSTER_POS)
        v4 = lineup_value(four, ROSTER_POS)
        assert v4 > v2                       # flex absorbs the third
        assert v4 - v2 == pytest.approx(80)  # but NOT the fourth

    def test_simulation_is_deterministic_for_a_seed(self):
        board = [mk(f"p{i}", ["RB", "WR", "TE", "QB"][i % 4], 200 - i, adp=i + 1)
                 for i in range(120)]
        a = simulate_opening(board, ("RB", "RB"), 10, 12, 8, ROSTER_POS, trials=15)
        b = simulate_opening(board, ("RB", "RB"), 10, 12, 8, ROSTER_POS, trials=15)
        assert a.mean_starter_vorp == b.mean_starter_vorp

    def test_opening_is_actually_honoured(self):
        board = [mk(f"rb{i}", "RB", 200 - i, adp=i + 1) for i in range(40)]
        board += [mk(f"wr{i}", "WR", 190 - i, adp=i + 1) for i in range(40)]
        r = simulate_opening(board, ("WR", "WR"), 1, 12, 4, ROSTER_POS, trials=5)
        assert r.example[0].endswith("(WR)")
