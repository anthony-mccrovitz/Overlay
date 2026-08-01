"""
Tests for the auto-promoter (Step 4) — the decision logic that promotes on a
proven sharp edge and demotes cold live lanes.
"""
from __future__ import annotations

import pytest

from src.analytics.market_stats import MarketStat
from src.pipeline.promoter import _decide, PromotionAction


def _stat(roi, n):
    s = MarketStat(sport="x", market="y")
    s.roi, s.n = roi, n
    return s


def _gate(is_candidate=True, sharp_mean=1.5, sharp_beat=60.0, sharp_n=200,
          mean=1.5, n=200):
    return {"is_candidate": is_candidate, "sharp_mean": sharp_mean,
            "sharp_beat_pct": sharp_beat, "sharp_n": sharp_n, "mean": mean, "n": n}


class TestPromote:
    """Promotion is DELEGATED, so these test delegation, not thresholds.

    Until 2026-08-01 this class asserted the promoter's own criterion — sharp
    beat >= 55%, positive sharp mean, ROI on n>=30. That criterion was retired
    on 2026-07-30 when the gate moved to EV vs the close (beat-close correlated
    -0.153 with realised ROI; EV +0.494), and the promoter never followed. So
    these tests kept passing while asserting the wrong rule — a test suite
    guarding a copy is how the copy survives.

    The thresholds now live in ONE place and are tested there
    (tests/test_model_standard.py); tests/test_gate_single_source.py pins that
    every surface, including this one, asks that place.
    """

    def _force_gate(self, monkeypatch, ok: bool, why: str = "forced"):
        monkeypatch.setattr("src.config.model_standard.clears_promotion_gate",
                            lambda s, m: (ok, why))

    def test_promotes_when_the_gate_passes(self, monkeypatch):
        self._force_gate(monkeypatch, True, "EV +4.10% on n=216")
        rec, why = _decide("incubating", _gate(), _stat(roi=5.0, n=60), "mlb", "total")
        assert rec == "live" and "EV +4.10%" in why

    def test_holds_when_the_gate_refuses(self, monkeypatch):
        self._force_gate(monkeypatch, False, "clustered sample")
        rec, why = _decide("incubating", _gate(), _stat(roi=5.0, n=60), "usa_mls", "moneyline")
        assert rec == "incubating" and "clustered sample" in why

    def test_gaudy_local_evidence_cannot_override_the_gate(self, monkeypatch):
        """The failure this prevents: a lane that beats the close 71% of the
        time on 500 picks with +25% ROI still does not promote if the gate
        refuses it — that combination is exactly what a clustered, repriced
        sample looks like from here."""
        self._force_gate(monkeypatch, False, "only 4 distinct days")
        rec, _ = _decide("incubating",
                         _gate(sharp_beat=71.0, sharp_mean=2.5, n=500),
                         _stat(roi=25.0, n=500), "usa_mls", "moneyline")
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
