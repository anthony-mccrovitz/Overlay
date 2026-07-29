"""Tests for the MARKET track (+EV line shop).

The headline test is TestThreeWayDevig: soccer moneylines are Home/Draw/Away,
and de-vigging a draw against a single opponent inflates its fair probability
enormously. The first live run of this scanner surfaced 403 "edges", nearly all
of them draws at +100% to +254% EV. Same class of bug as the Polymarket draw
incident. It must never regress.
"""
import pytest

from src.strategies import line_shop_scanner as ls


def _book(key, markets):
    return {"key": key, "markets": markets}


def _h2h(outcomes):
    return {"key": "h2h", "outcomes": [{"name": n, "price": p} for n, p in outcomes]}


def _totals(point, over, under):
    return {"key": "totals", "outcomes": [
        {"name": "Over", "price": over, "point": point},
        {"name": "Under", "price": under, "point": point},
    ]}


class TestOddsMath:
    def test_implied_symmetric_pair_overrounds(self):
        # -110/+110 is an exact inverse pair and sums to 1.0 — no vig. A real
        # two-sided book price (-110 both ways) carries the overround.
        assert ls.implied(-110) + ls.implied(110) == pytest.approx(1.0)
        assert ls.implied(-110) + ls.implied(-110) > 1.0

    def test_ev_zero_at_fair_price(self):
        # +100 is decimal 2.0; a true 50% shot is exactly break-even.
        assert ls.ev_pct(0.5, 100) == pytest.approx(0.0, abs=1e-9)

    def test_ev_is_return_on_stake_not_probability_gap(self):
        """A 5-point probability edge is worth far more on a longshot than on a
        favourite. The old line_shop reported the flat gap and understated this."""
        longshot = ls.ev_pct(0.25, 400)   # fair 20% priced at 400 (implied 20%)
        assert longshot == pytest.approx(25.0)

    def test_kelly_zero_when_no_edge(self):
        assert ls.kelly_fraction(0.5, 100) == pytest.approx(0.0)


class TestThreeWayDevig:
    """Soccer h2h is 3-way. Regression guard for the +254% phantom draws."""

    EVENT = {
        "home_team": "Club A", "away_team": "Club B",
        "bookmakers": [
            _book("pinnacle", [_h2h([("Club A", -110), ("Draw", 260), ("Club B", 300)])]),
            _book("fanduel",  [_h2h([("Club A", -105), ("Draw", 280), ("Club B", 310)])]),
        ],
    }

    def test_draw_fair_prob_uses_all_three_outcomes(self):
        table = ls._collect(self.EVENT)
        sel = ("moneyline", "Draw", None)
        fair, source, _ = ls.fair_probability(sel, table)
        assert source == "pinnacle"
        # Raw implied of +260 is ~27.8%. A correct 3-way de-vig lands BELOW that
        # (overround > 1); the 2-way bug pushed it far above.
        assert 0.20 < fair < ls.implied(260)

    def test_siblings_returns_both_other_outcomes(self):
        table = ls._collect(self.EVENT)
        sibs = ls._siblings(("moneyline", "Draw", None), table)
        assert len(sibs) == 2
        assert {s[1] for s in sibs} == {"Club A", "Club B"}

    def test_no_phantom_draw_edge(self):
        """FanDuel's +280 draw against Pinnacle's +260 is a small real edge, not
        a triple-digit one."""
        rows = ls.scan_event(self.EVENT, "soccer_test", min_ev=0.0)
        draws = [r for r in rows if r["selection"] == "Draw"]
        assert draws, "expected the draw to be priced"
        assert all(r["ev_pct"] < 15.0 for r in draws), \
            f"phantom draw edge returned: {[r['ev_pct'] for r in draws]}"

    def test_probabilities_sum_to_one(self):
        table = ls._collect(self.EVENT)
        total = sum(ls.fair_probability(("moneyline", n, None), table)[0]
                    for n in ("Club A", "Draw", "Club B"))
        assert total == pytest.approx(1.0, abs=1e-9)


class TestTwoWayDevig:
    EVENT = {
        "home_team": "Home", "away_team": "Away",
        "bookmakers": [
            _book("pinnacle", [_h2h([("Home", -120), ("Away", 110)])]),
            _book("fanduel",  [_h2h([("Home", -115), ("Away", 125)])]),
        ],
    }

    def test_pair_sums_to_one(self):
        table = ls._collect(self.EVENT)
        a = ls.fair_probability(("moneyline", "Home", None), table)[0]
        b = ls.fair_probability(("moneyline", "Away", None), table)[0]
        assert a + b == pytest.approx(1.0, abs=1e-9)

    def test_soft_book_beating_sharp_is_flagged(self):
        rows = ls.scan_event(self.EVENT, "test", min_ev=0.5)
        assert any(r["selection"] == "Away" and r["book"] == "FanDuel" for r in rows)

    def test_pinnacle_is_never_a_bet_destination(self):
        rows = ls.scan_event(self.EVENT, "test", min_ev=-100.0)
        assert all(r["book_key"] != "pinnacle" for r in rows)


class TestLineIdentity:
    def test_totals_at_different_lines_never_pair(self):
        """UNDER 8.5 and OVER 9.0 are not two sides of one market. Pairing them
        is how a scanner invents edges out of a half-run of line movement."""
        event = {"home_team": "H", "away_team": "A", "bookmakers": [
            _book("pinnacle", [_totals(8.5, -105, -115)]),
            _book("fanduel",  [_totals(9.0, -110, -110)]),
        ]}
        table = ls._collect(event)
        sibs = ls._siblings(("total", "Under", 8.5), table)
        assert all(s[2] == 8.5 for s in sibs)

    def test_incomplete_book_excluded_from_consensus(self):
        """A book pricing only one side can't be de-vigged; including it would
        treat its vigged price as a fair probability."""
        event = {"home_team": "H", "away_team": "A", "bookmakers": [
            _book("fanduel",  [_h2h([("H", -110), ("A", -110)])]),
            _book("betmgm",   [{"key": "h2h", "outcomes": [{"name": "H", "price": 200}]}]),
        ]}
        table = ls._collect(event)
        # Only 1 complete book < MIN_CONSENSUS_BOOKS, so no fair is produced.
        assert ls.fair_probability(("moneyline", "H", None), table) is None


class TestEvCeiling:
    def test_absurd_edge_is_dropped_and_recorded(self):
        event = {"home_team": "H", "away_team": "A", "bookmakers": [
            _book("pinnacle", [_h2h([("H", -400), ("A", 300)])]),
            # +550 stays inside MAX_ODDS so the ceiling, not the odds filter,
            # is what rejects it.
            _book("fanduel",  [_h2h([("H", -400), ("A", 550)])]),
        ]}
        rejected = []
        rows = ls.scan_event(event, "test", min_ev=1.0, rejected=rejected)
        assert all(r["ev_pct"] <= ls.MAX_EV_PCT for r in rows)
        assert rejected and rejected[0]["ev_pct"] > ls.MAX_EV_PCT


class TestPickShape:
    def test_logged_pick_is_shadow_and_tagged(self):
        row = {"sport": "mlb", "market": "total", "selection": "Under",
               "line": 8.5, "matchup": "A @ H", "book": "FanDuel",
               "book_key": "fanduel", "odds": -105, "fair_prob": 0.55,
               "ev_pct": 3.2, "fair_source": "pinnacle"}
        pick = ls.to_pick(row, "2026-07-29")
        assert pick["card_pick"] is False
        assert pick["strategy"] == "line_shop"
        assert pick["stake"] == 0.0
        assert "8.5" in pick["pick_id"] and "fanduel" in pick["pick_id"]
