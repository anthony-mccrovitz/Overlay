"""
tests/test_line_clv_scoring.py — Line-market CLV scoring guard (plan item X4).

X4 asked to "extend CLV capture beyond moneyline." Investigation showed the
capture + scoring for spreads / totals / F5 totals already exist and work — the
apparent gap (F5 totals showed 0 populated) was a historical back-score gap for a
shadow market, not a scoring defect. These tests pin the scoring math so the
line-CLV path can't silently regress: a totals/F5 pick that got a better number
than the close must score positive line CLV, direction-aware.

Run: python3 -m pytest tests/test_line_clv_scoring.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analytics.clv_tracker import _score_total


def _snap(direction, open_line, odds=-110, imp=0.524):
    return {"market": "total", "direction": direction, "opening_line": open_line,
            "opening_odds": odds, "opening_implied_prob": imp,
            "opponent": "Texas Rangers @ St. Louis Cardinals"}


class TestTotalLineCLV:
    def test_under_beats_close_when_line_drops(self):
        # Took UNDER 4.5, closed 3.5 -> UNDER got the higher (easier) number? No:
        # UNDER wants a HIGHER bar. Closed lower (3.5) => our 4.5 was easier => +1.0.
        res = _score_total(_snap("UNDER", 4.5), {"line": 3.5, "over": -110, "under": -110})
        assert res is not None
        assert res["line_clv"] == 1.0
        assert res["beat_close"] is True

    def test_over_beats_close_when_line_rises(self):
        # Took OVER 3.5, closed 4.5 => our lower bar was easier => +1.0.
        res = _score_total(_snap("OVER", 3.5), {"line": 4.5, "over": -110, "under": -110})
        assert res["line_clv"] == 1.0
        assert res["beat_close"] is True

    def test_under_loses_when_line_rises(self):
        res = _score_total(_snap("UNDER", 3.5), {"line": 4.5, "over": -110, "under": -110})
        assert res["line_clv"] == -1.0
        assert res["beat_close"] is False

    def test_same_line_falls_back_to_price_clv(self):
        # Line unchanged -> CLV decided on price. Better closing price => beat.
        res = _score_total(_snap("UNDER", 3.5, imp=0.40),
                           {"line": 3.5, "over": 120, "under": -140})
        assert res["line_clv"] == 0.0
        assert res["price_clv_pct"] is not None

    def test_missing_direction_returns_none(self):
        # A snapshot with no usable direction/line must not fabricate CLV.
        assert _score_total({"market": "total"}, {"line": 3.5, "over": -110, "under": -110}) is None

    def test_f5_scores_like_a_total(self):
        # F5 totals reuse the totals scorer; a real archived F5 line must score.
        res = _score_total(
            {"market": "f5_total", "direction": "UNDER", "opening_line": 3.5,
             "opening_odds": -110, "opening_implied_prob": 0.524,
             "opponent": "Texas Rangers @ St. Louis Cardinals"},
            {"line": 3.5, "over": -116.0, "under": 101.0})
        assert res is not None and "line_clv" in res
