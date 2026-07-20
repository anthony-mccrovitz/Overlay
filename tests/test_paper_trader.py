"""
tests/test_paper_trader.py — virtual ledger for the Polymarket pilot.

The ledger exists so the $112 can be validated without being spent. That only
works if it refuses to flatter itself, so the invariants here are the ones
that keep it honest:

  - a maker order that never filled is not a trade and earns nothing
  - a maker order not yet checked is not silently assumed filled
  - payouts use the contract's real shape (each share pays $1), not odds math
  - the significance number tells the truth about how little n=11 means

Run: python3 -m pytest tests/test_paper_trader.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from scripts.paper_trader import _significance, fill_price, settle


def _pick(result="win", mode="take", cost=0.189, fair=0.199, **over):
    p = {"pick_id": "polymarket_ev__x", "date": "2026-07-20",
         "team": "Seattle Storm", "sport": "wnba", "result": result,
         "poly_entry_mode": mode, "poly_taker_cost": cost, "poly_cost": cost,
         "model_prob": fair}
    p.update(over)
    return p


class TestFillPrice:
    def test_taker_prefers_size_aware_cost(self):
        """Top-of-book cost is a lie once the stake exceeds the top rung."""
        p = _pick(poly_taker_cost=0.189, poly_taker_cost_at_size=0.205)
        cost, conf = fill_price(p)
        assert cost == 0.205
        assert "high" in conf

    def test_taker_falls_back_to_top_of_book(self):
        assert fill_price(_pick())[0] == 0.189

    def test_maker_unfilled_has_no_price(self):
        cost, why = fill_price(_pick(mode="make", poly_filled=False))
        assert cost is None
        assert "never filled" in why

    def test_maker_unchecked_is_not_assumed_filled(self):
        """Silence is not a fill. Assuming otherwise is how a paper ledger
        starts reporting profits it never could have earned."""
        cost, why = fill_price(_pick(mode="make"))
        assert cost is None
        assert "not checked" in why

    def test_maker_filled_is_flagged_low_confidence(self):
        cost, conf = fill_price(_pick(mode="make", poly_filled=True))
        assert cost == 0.189
        assert "low" in conf


class TestSettlement:
    def test_win_pays_one_dollar_per_share(self):
        # $4.48 at 0.189 → 23.7 shares → $23.70 back on a win.
        r = settle(_pick(result="win"), 4.48)
        assert r["shares"] == pytest.approx(23.70, abs=0.01)
        assert r["pnl"] == pytest.approx(19.22, abs=0.02)

    def test_loss_costs_exactly_the_stake(self):
        assert settle(_pick(result="loss"), 4.48)["pnl"] == pytest.approx(-4.48)

    def test_push_and_void_are_flat(self):
        assert settle(_pick(result="push"), 4.48)["pnl"] == 0.0
        assert settle(_pick(result="void"), 4.48)["pnl"] == 0.0

    def test_unsettled_pick_is_skipped(self):
        assert settle(_pick(result=None), 4.48) is None

    def test_unfilled_maker_never_books_a_result(self):
        """Even a WINNING pick earns nothing if the order never traded."""
        assert settle(_pick(result="win", mode="make", poly_filled=False), 4.48) is None

    def test_expected_pnl_is_edge_times_stake(self):
        r = settle(_pick(cost=0.189, fair=0.199), 4.48)
        assert r["expected_pnl"] == pytest.approx(4.48 * (0.199 / 0.189 - 1), abs=1e-3)
        assert r["expected_pnl"] == pytest.approx(0.237, abs=0.01)


class TestSignificance:
    def test_longshot_edge_needs_a_huge_sample(self):
        """The number that should stop anyone reading a losing week as failure.

        A +5.3% edge on a ~20% shot carries an SD of ~2.1 units per bet, so
        realised P&L cannot separate it from zero until thousands of bets have
        settled. CLV is the only usable signal before then.
        """
        sig = _significance([{"fair": 0.199, "cost": 0.189}])
        assert sig["mean_edge_per_unit"] == pytest.approx(0.053, abs=0.005)
        assert sig["sd_per_unit"] == pytest.approx(2.11, abs=0.05)
        assert sig["n_for_2sigma"] > 5000

    def test_coin_flip_edge_needs_far_fewer(self):
        """Same edge on an even-money market is enormously cheaper to prove —
        variance, not edge size, sets the sample you need."""
        sig = _significance([{"fair": 0.55, "cost": 0.52}])
        assert sig["n_for_2sigma"] < _significance(
            [{"fair": 0.199, "cost": 0.189}])["n_for_2sigma"]

    def test_no_edge_returns_no_target(self):
        assert _significance([{"fair": 0.40, "cost": 0.50}])["n_for_2sigma"] is None

    def test_empty_is_safe(self):
        assert _significance([]) == {}


class TestImpossibleCosts:
    """A binary contract pays exactly $1, so a cost outside (0, 1) is corrupt
    data rather than a bad trade. Before this guard, a cost of 1.5 booked
    pnl=-1.49 on a WINNING pick — a loss reported on a win."""

    @pytest.mark.parametrize("cost", [1.5, 1.0, 0.0, -0.1])
    def test_impossible_costs_are_rejected(self, cost):
        assert settle(_pick(result="win", cost=cost), 4.48) is None

    def test_normal_cost_still_settles(self):
        assert settle(_pick(result="win", cost=0.5), 4.48)["pnl"] == pytest.approx(4.48)
