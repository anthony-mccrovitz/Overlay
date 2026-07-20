"""
tests/test_polymarket_fills.py — maker fill + adverse-selection measurement.

The maker thesis says: rest inside the bid, pay no fee, capture the spread.
It is only true if orders actually fill, and if fills are not concentrated in
the cases where the counterparty knew more. This module is what makes that
falsifiable, so the invariants below are about NOT flattering the strategy:

  - a fill requires the price to actually trade down to the limit
  - only the window the order was live counts (posted → kickoff); a price that
    touched the limit BEFORE the order existed is not a fill
  - drift after a fill is reported with its sign intact, so being picked off
    is visible rather than averaged away

Run: python3 -m pytest tests/test_polymarket_fills.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from scripts.polymarket_fills import evaluate, summarize


def _pick(limit=0.39, recorded="2026-07-20T12:00:00+00:00",
          start="2026-07-20T18:00:00+00:00", fair=0.42, ev=7.7, **over):
    p = {"pick_id": "polymarket_ev__x", "team": "Boston Red Sox",
         "sport": "baseball_mlb", "date": "2026-07-20",
         "poly_limit": limit, "recorded_at": recorded,
         "poly_game_start": start, "model_prob": fair, "edge_pct": ev}
    p.update(over)
    return p


def _hist(points):
    """[(hours_after_noon, price)] → history rows."""
    base = 1784548800  # 2026-07-20T12:00:00Z
    return [{"t": base + int(h * 3600), "p": p} for h, p in points]


class TestFillDetection:
    def test_price_reaching_limit_is_a_fill(self):
        r = evaluate(_pick(limit=0.39), _hist([(0, 0.42), (1, 0.39), (2, 0.41)]))
        assert r["filled"] is True
        assert r["minutes_to_fill"] == 60.0

    def test_price_never_reaching_limit_is_no_fill(self):
        r = evaluate(_pick(limit=0.39), _hist([(0, 0.42), (1, 0.40), (2, 0.41)]))
        assert r["filled"] is False
        assert r["minutes_to_fill"] is None

    def test_touching_the_limit_exactly_fills(self):
        r = evaluate(_pick(limit=0.40), _hist([(0, 0.42), (1, 0.40)]))
        assert r["filled"] is True

    def test_price_before_the_order_existed_is_not_a_fill(self):
        """A dip that happened BEFORE the order was posted is not a fill —
        counting it would silently inflate the fill rate with hindsight."""
        r = evaluate(_pick(limit=0.39, recorded="2026-07-20T14:00:00+00:00"),
                     _hist([(0, 0.35), (1, 0.36), (3, 0.44), (4, 0.45)]))
        assert r["filled"] is False

    def test_price_after_kickoff_is_ignored(self):
        """In-play prices are not available to a pregame resting order."""
        r = evaluate(_pick(limit=0.39), _hist([(1, 0.44), (7, 0.20)]))
        assert r["filled"] is False

    def test_unusable_pick_returns_none(self):
        assert evaluate(_pick(limit=None), _hist([(1, 0.30)])) is None
        assert evaluate(_pick(), []) is None
        assert evaluate(_pick(recorded=None), _hist([(1, 0.30)])) is None


class TestDriftSign:
    def test_drift_positive_when_market_moves_toward_us(self):
        r = evaluate(_pick(limit=0.39), _hist([(1, 0.39), (2, 0.45)]))
        assert r["filled"] is True
        assert r["post_fill_drift"] == pytest.approx(0.06)

    def test_drift_negative_when_picked_off(self):
        """Filled at 0.39, market closed at 0.30 — the fill was information,
        not a gift. This must surface as a negative number, never abs()."""
        r = evaluate(_pick(limit=0.39), _hist([(1, 0.39), (2, 0.30)]))
        assert r["post_fill_drift"] == pytest.approx(-0.09)

    def test_no_drift_reported_without_a_fill(self):
        r = evaluate(_pick(limit=0.20), _hist([(1, 0.44)]))
        assert r["post_fill_drift"] is None


class TestSummary:
    def _rows(self, specs):
        return [{"filled": f, "post_fill_drift": d, "claimed_ev_pct": e,
                 "minutes_to_fill": 10 if f else None} for f, d, e in specs]

    def test_fill_rate_and_drift(self):
        s = summarize(self._rows([(True, -0.02, 5.0), (True, -0.04, 7.0),
                                  (False, None, 9.0)]))
        assert s["n"] == 3 and s["n_filled"] == 2
        assert s["fill_rate_pct"] == pytest.approx(66.7)
        assert s["mean_post_fill_drift"] == pytest.approx(-0.03)

    def test_separates_ev_of_filled_from_unfilled(self):
        """If the best-looking edges never fill, paper EV is a mirage — the
        summary has to make that visible side by side."""
        s = summarize(self._rows([(True, 0.01, 2.0), (False, None, 20.0)]))
        assert s["claimed_ev_filled"] == pytest.approx(2.0)
        assert s["claimed_ev_unfilled"] == pytest.approx(20.0)
        assert s["claimed_ev_filled"] < s["claimed_ev_unfilled"]

    def test_empty_is_safe(self):
        s = summarize([])
        assert s["n"] == 0 and s["fill_rate_pct"] is None
