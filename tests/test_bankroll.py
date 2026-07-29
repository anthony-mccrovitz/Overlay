"""Tests for the MONEY ledger.

This module settles real dollars, so the bar is higher than for the lab: a bad
auto-grade join silently books a win that never happened. The matcher tests
below are mostly about what must NOT match.
"""
import pytest

from src.tracking import bankroll as bk


def _bet(**kw):
    base = {"date": "2026-07-28", "sport": "mlb", "market": "total",
            "direction": "UNDER", "line": 8.5, "odds": -110,
            "stake_dollars": 6.0, "result": None}
    base.update(kw)
    return base


def _lab(**kw):
    base = {"date": "2026-07-28", "sport": "mlb", "market": "total",
            "direction": "UNDER", "line": 8.5, "result": "win",
            "pick_id": "lab_1", "team": None, "matchup": "A @ B"}
    base.update(kw)
    return base


class TestPayout:
    def test_underdog_win(self):
        assert bk.payout(6.0, 105, True) == pytest.approx(6.30)

    def test_favourite_win(self):
        assert bk.payout(6.0, -113, True) == pytest.approx(5.3097, abs=1e-3)

    def test_loss_returns_negative_stake(self):
        assert bk.payout(6.0, 105, False) == -6.0


class TestAutogradeMatching:
    def test_settles_from_lab_twin(self):
        bets, n = bk.autograde([_bet()], [_lab(result="win")])
        assert n == 1
        assert bets[0]["result"] == "win"
        assert bets[0]["profit_dollars"] == pytest.approx(5.45, abs=0.01)
        assert bets[0]["graded_via"] == "lab:lab_1"

    def test_different_line_never_inherits(self):
        """UNDER 8.5 and UNDER 9.0 are different bets — the classic way a
        naive join books a phantom win."""
        bets, n = bk.autograde([_bet(line=8.5)], [_lab(line=9.0)])
        assert n == 0
        assert bets[0]["result"] is None

    def test_opposite_side_never_inherits(self):
        bets, n = bk.autograde([_bet(direction="OVER")], [_lab(direction="UNDER")])
        assert n == 0

    def test_different_date_never_inherits(self):
        bets, n = bk.autograde([_bet(date="2026-07-27")], [_lab(date="2026-07-28")])
        assert n == 0

    def test_ungraded_lab_pick_is_ignored(self):
        bets, n = bk.autograde([_bet()], [_lab(result=None)])
        assert n == 0

    def test_already_settled_bet_is_left_alone(self):
        bet = _bet(result="loss", profit_dollars=-6.0)
        bets, n = bk.autograde([bet], [_lab(result="win")])
        assert n == 0
        assert bets[0]["profit_dollars"] == -6.0

    def test_push_books_zero_not_a_payout(self):
        bets, n = bk.autograde([_bet()], [_lab(result="push")])
        assert n == 1
        assert bets[0]["profit_dollars"] == 0.0

    def test_moneyline_matches_on_team(self):
        bet = _bet(market="moneyline", direction="WIN", line=None,
                   team="New York Mets", odds=150)
        lab = _lab(market="moneyline", direction="WIN", line=None,
                   team="New York Mets", result="win")
        bets, n = bk.autograde([bet], [lab])
        assert n == 1
        assert bets[0]["profit_dollars"] == pytest.approx(9.0)

    def test_wrong_team_never_inherits(self):
        bet = _bet(market="moneyline", direction="WIN", line=None, team="New York Mets")
        lab = _lab(market="moneyline", direction="WIN", line=None,
                   team="Atlanta Braves", matchup="Atlanta Braves @ Chicago Cubs")
        bets, n = bk.autograde([bet], [lab])
        assert n == 0


class TestSummary:
    def test_dollars_only(self):
        bets = [
            _bet(result="win",  profit_dollars=6.30, odds=105),
            _bet(result="loss", profit_dollars=-6.0, line=9.0),
            _bet(result="push", profit_dollars=0.0,  line=9.5),
        ]
        s = bk.summary(bets, start=308.0)
        assert s["wins"] == 1 and s["losses"] == 1 and s["pushes"] == 1
        assert s["balance"] == pytest.approx(308.30)
        assert s["profit"] == pytest.approx(0.30)
        assert s["staked"] == pytest.approx(12.0)   # push excluded from staked

    def test_open_bets_count_as_at_risk_not_profit(self):
        bets = [_bet(result=None, stake_dollars=10.0)]
        s = bk.summary(bets, start=308.0)
        assert s["open"] == 1
        assert s["at_risk"] == pytest.approx(10.0)
        assert s["balance"] == pytest.approx(308.0)
        assert s["n_settled"] == 0

    def test_empty_ledger_is_flat(self):
        s = bk.summary([], start=308.0)
        assert s["balance"] == 308.0 and s["roi_pct"] == 0.0


class TestByLane:
    def test_groups_dollars_by_sport_market(self):
        bets = [
            _bet(result="win",  profit_dollars=6.30),
            _bet(result="loss", profit_dollars=-6.0, line=9.0),
            _bet(result="win",  profit_dollars=9.0, market="moneyline",
                 line=None, team="Mets"),
        ]
        lanes = {(l["sport"], l["market"]): l for l in bk.by_lane(bets)}
        assert lanes[("mlb", "total")]["profit"] == pytest.approx(0.30)
        assert lanes[("mlb", "total")]["n"] == 2
        assert lanes[("mlb", "moneyline")]["profit"] == pytest.approx(9.0)
