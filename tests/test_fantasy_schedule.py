"""Tests for bye weeks and position-specific strength of schedule.

Both decide leagues and almost nobody in a casual league checks them. Byes are
exact — the schedule is public, so three starters resting in the same week is a
game lost in September for a reason chosen in August. Playoff SOS is measured
rather than guessed: Sleeper tracks what each defense actually gave up to each
position.
"""
import pytest

from src.fantasy.draft import DraftState, bye_conflict, recommend
from src.fantasy.schedule import ScheduleView
from src.fantasy.valuation import PlayerValue


def _view():
    return ScheduleView(
        byes={"AAA": 7, "BBB": 7, "CCC": 9},
        opp={"AAA": {15: "SOFT", 16: "SOFT", 17: "HARD"},
             "BBB": {15: "HARD", 16: "HARD", 17: "HARD"}},
        allowed={"SOFT": {"RB": 30.0}, "HARD": {"RB": 12.0}},
        league_avg={"RB": 21.0},
    )


class TestStrengthOfSchedule:
    def test_soft_playoff_slate_scores_above_one(self):
        v = _view()
        assert v.playoff_sos("AAA", "RB") > 1.0

    def test_hard_playoff_slate_scores_below_one(self):
        v = _view()
        assert v.playoff_sos("BBB", "RB") < 1.0

    def test_relative_to_league_average_not_raw(self):
        """A raw points-allowed number means nothing without the league baseline."""
        v = _view()
        assert v.playoff_sos("BBB", "RB") == pytest.approx(12.0 / 21.0, abs=0.01)

    def test_unknown_team_returns_none(self):
        assert _view().playoff_sos("ZZZ", "RB") is None

    def test_unknown_position_returns_none(self):
        assert _view().playoff_sos("AAA", "DEF") is None

    def test_playoff_opponents_are_listed(self):
        assert _view().playoff_opponents("AAA") == ["SOFT", "SOFT", "HARD"]


def _pv(pid, pos, vorp, bye=None, adp=None):
    return PlayerValue(player_id=pid, name=pid, position=pos, team="X",
                       vorp=vorp, raw_vorp=vorp, bye=bye, adp=adp)


class TestByeConflict:
    def _board(self):
        return {p.player_id: p for p in [
            _pv("rb1", "RB", 100, bye=7), _pv("rb2", "RB", 90, bye=7),
            _pv("wr1", "WR", 80, bye=7), _pv("wr2", "WR", 70, bye=9),
        ]}

    def test_counts_only_matching_byes(self):
        b = self._board()
        n = bye_conflict(b["wr1"], ["rb1", "rb2", "wr2"], b, {"RB": 2, "WR": 2})
        assert n == 2

    def test_no_bye_data_is_not_a_conflict(self):
        b = self._board()
        assert bye_conflict(_pv("x", "RB", 50), ["rb1"], b, {"RB": 2}) == 0

    def test_stacking_is_penalised_in_the_recommendation(self):
        """Two on a bye is a warning; a third should actively cost the player
        ground against an equal alternative."""
        board = [_pv("clash", "WR", 100, bye=7, adp=30),
                 _pv("clean", "WR", 100, bye=12, adp=30),
                 _pv("a", "RB", 90, bye=7), _pv("b", "RB", 90, bye=7)]
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=10,
                        picks_made=30, my_players=["a", "b"])
        recs = recommend(board, st, {"RB": 2, "WR": 2})
        top = recs[0].value
        assert top.player_id == "clean"
        clash = next(r for r in recs if r.value.player_id == "clash")
        assert "bye 7" in clash.reason

    def test_playoff_schedule_is_surfaced_not_scored(self):
        """SOS informs a close call; it must never be folded into VORP, because
        defenses change between seasons more than offenses do."""
        easy = _pv("easy", "RB", 100, adp=30); easy.playoff_sos = 1.12
        hard = _pv("hard", "RB", 100, adp=30); hard.playoff_sos = 0.88
        st = DraftState(draft_id="d", teams=12, rounds=14, my_slot=10, picks_made=9)
        recs = {r.value.player_id: r for r in recommend([easy, hard], st, {"RB": 2})}
        assert recs["easy"].adjusted == pytest.approx(recs["hard"].adjusted)
        assert "easy playoffs" in recs["easy"].reason
        assert "hard playoffs" in recs["hard"].reason
