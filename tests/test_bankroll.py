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


# ── the game itself must match (found 2026-08-01) ───────────────────────────
def _game_bet(matchup, line=8.5, direction="OVER"):
    return {"pick_id": "personal_x", "date": "2026-08-01", "sport": "mlb",
            "market": "total", "direction": direction, "team": f"{direction} {line}",
            "line": line, "matchup": matchup, "odds": 105, "stake_dollars": 6.70,
            "result": None}


def _game_lab(matchup, result, line=8.5, direction="OVER"):
    return {"pick_id": f"mlb_20260801_{direction.lower()}_{line}_{matchup[:6]}",
            "date": "2026-08-01", "sport": "mlb", "market": "total",
            "direction": direction, "team": f"{direction} {line}", "line": line,
            "matchup": matchup, "result": result}


def test_real_bet_never_inherits_another_games_result():
    """A total's `team` is "OVER 8.5" — the same string in every game on the
    slate that has that number. Date, sport, market, direction, line and team
    can therefore ALL agree between two different games, and the autograder
    used to take the first such lab pick it found. That writes a real dollar
    loss from a game the owner never bet on.
    """
    from src.tracking.bankroll import autograde

    bets = [_game_bet("Texas Rangers @ Houston Astros")]
    lab = [_game_lab("Chicago Cubs @ San Diego Padres", "loss")]  # same line, other game
    graded, n = autograde(bets, lab)

    assert n == 0, "a bet was graded from a different game's result"
    assert graded[0]["result"] is None
    assert graded[0].get("profit_dollars") is None


def test_real_bet_still_grades_from_its_own_game():
    """The fix must not break the thing it protects: the right game still settles."""
    from src.tracking.bankroll import autograde

    bets = [_game_bet("Texas Rangers @ Houston Astros")]
    lab = [_game_lab("Chicago Cubs @ San Diego Padres", "loss"),
           _game_lab("Texas Rangers @ Houston Astros", "win")]
    graded, n = autograde(bets, lab)

    assert n == 1
    assert graded[0]["result"] == "win"
    assert graded[0]["profit_dollars"] > 0


def test_bet_without_a_matchup_still_falls_back_to_the_team_test():
    """Older rows carry no matchup; they must not become ungradable."""
    from src.tracking.bankroll import autograde

    bet = _game_bet("Texas Rangers @ Houston Astros")
    bet.pop("matchup")
    graded, n = autograde([bet], [_game_lab("Texas Rangers @ Houston Astros", "win")])
    assert n == 1 and graded[0]["result"] == "win"
