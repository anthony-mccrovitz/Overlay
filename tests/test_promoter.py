"""
Tests for the auto-promoter (Step 4) — the decision logic that promotes on a
proven sharp edge and demotes cold live lanes.
"""
from __future__ import annotations

from src.analytics.market_stats import MarketStat
from src.pipeline.promoter import _decide, PromotionAction, PROMOTE_BEAT_MIN


def _stat(roi, n):
    s = MarketStat(sport="x", market="y")
    s.roi, s.n = roi, n
    return s


def _gate(is_candidate=True, sharp_mean=1.5, sharp_beat=60.0, sharp_n=200,
          mean=1.5, n=200):
    return {"is_candidate": is_candidate, "sharp_mean": sharp_mean,
            "sharp_beat_pct": sharp_beat, "sharp_n": sharp_n, "mean": mean, "n": n}


class TestPromote:
    def test_promotes_when_all_pass(self):
        rec, _ = _decide("incubating", _gate(), _stat(roi=5.0, n=60))
        assert rec == "live"

    def test_no_promote_without_candidate(self):
        rec, _ = _decide("incubating", _gate(is_candidate=False), _stat(5.0, 60))
        assert rec == "incubating"

    def test_no_promote_if_beats_book_but_not_sharp(self):
        # positive vs best price, negative vs the sharp close → mirage, hold.
        rec, _ = _decide("incubating", _gate(sharp_mean=-0.5), _stat(5.0, 60))
        assert rec == "incubating"

    def test_no_promote_if_sharp_beat_too_low(self):
        rec, _ = _decide("incubating", _gate(sharp_beat=PROMOTE_BEAT_MIN - 5), _stat(5.0, 60))
        assert rec == "incubating"

    def test_no_promote_if_roi_negative(self):
        rec, _ = _decide("incubating", _gate(), _stat(roi=-2.0, n=60))
        assert rec == "incubating"

    def test_no_promote_if_sample_too_small(self):
        rec, _ = _decide("incubating", _gate(), _stat(roi=5.0, n=5))
        assert rec == "incubating"


class TestDemote:
    def test_demotes_live_on_negative_roi(self):
        rec, reason = _decide("live", None, _stat(roi=-8.0, n=50))
        assert rec == "incubating" and "cold" in reason

    def test_demotes_live_on_negative_sharp_clv(self):
        rec, _ = _decide("live", _gate(sharp_mean=-1.0, sharp_n=50), _stat(roi=1.0, n=50))
        assert rec == "incubating"

    def test_demotes_live_on_confluence_below_floor(self):
        # ROI -40% (n=13) AND sharp CLV -2.5 (n=15): both below the single floor
        # of 30, but agreement demotes.
        rec, reason = _decide("live", _gate(sharp_mean=-2.5, sharp_n=15), _stat(roi=-40.0, n=13))
        assert rec == "incubating" and "both ways" in reason

    def test_holds_live_when_positive(self):
        rec, _ = _decide("live", _gate(), _stat(roi=8.0, n=50))
        assert rec == "live"

    def test_does_not_demote_on_thin_sample(self):
        # 10 settled picks isn't enough to yank a live lane.
        rec, _ = _decide("live", None, _stat(roi=-20.0, n=10))
        assert rec == "live"


class TestAction:
    def test_kind_classification(self):
        assert PromotionAction("x", "y", "incubating", "live", "").kind == "promote"
        assert PromotionAction("x", "y", "live", "incubating", "").kind == "demote"
        assert PromotionAction("x", "y", "live", "live", "").kind == "hold"
