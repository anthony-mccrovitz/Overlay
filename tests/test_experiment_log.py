"""
Tests for the experiment log — the model-tuning ledger's core logic:
the confidence-signal test (is there real signal to tune?) and the
profitability-first triage call (never cut a moneymaker).
"""
from __future__ import annotations

import json

from src.analytics.experiment_log import (
    _confidence_signal, _triage_call, record, history,
)


def _picks(pairs):
    """pairs: list of (model_prob, result) → graded pick dicts."""
    return [{"model_prob": mp, "result": r, "odds": -110} for mp, r in pairs]


def test_confidence_signal_needs_thirty():
    sig = _confidence_signal(_picks([(0.6, "win")] * 20))
    assert sig.verdict == "insufficient-data"


def test_confidence_signal_detects_real_signal():
    # Win rate rises sharply with confidence → real, tunable signal.
    lo = [(0.50, "loss")] * 25 + [(0.50, "win")] * 5    # 17% WR
    hi = [(0.80, "win")] * 25 + [(0.80, "loss")] * 5     # 83% WR
    sig = _confidence_signal(_picks(lo + hi))
    assert sig.verdict == "real-signal"
    assert sig.spread > 0


def test_confidence_signal_flat_on_noise():
    # ~50% across the whole confidence range → no discriminating signal.
    pairs = [(0.50 + i * 0.003, "win" if i % 2 else "loss") for i in range(90)]
    sig = _confidence_signal(_picks(pairs))
    assert sig.verdict == "flat"


def test_confidence_signal_inverted_when_backwards():
    # High confidence loses, low confidence wins → model is backwards.
    lo = [(0.50, "win")] * 25 + [(0.50, "loss")] * 5     # 83% WR (low conf)
    hi = [(0.80, "loss")] * 25 + [(0.80, "win")] * 5     # 17% WR (high conf)
    sig = _confidence_signal(_picks(lo + hi))
    assert sig.verdict == "inverted"
    assert sig.spread < 0


def test_triage_never_cuts_a_profitable_lane():
    # Even with an ugly (inverted) confidence read, a +ROI lane is KEEP, not cut.
    assert _triage_call(roi=10.7, clv=0.1, signal="inverted").startswith("KEEP")
    assert _triage_call(roi=20.1, clv=None, signal="flat").startswith("KEEP")


def test_triage_tunes_signal_losers_and_cuts_dead_ones():
    assert _triage_call(roi=-9.7, clv=-0.2, signal="real-signal").startswith("TUNE")
    assert _triage_call(roi=-6.1, clv=-0.6, signal="flat").startswith("CUT")
    assert _triage_call(roi=-11.1, clv=1.1, signal="flat").startswith("TUNE")  # beats close
    assert _triage_call(roi=None, clv=None, signal="insufficient-data").startswith("WAIT")


def test_record_and_history_round_trip(tmp_path, monkeypatch):
    import src.analytics.experiment_log as xl
    pnl = tmp_path / "picks.json"
    graded = _picks([(0.6, "win"), (0.55, "loss")] * 20)
    for p, i in zip(graded, range(len(graded))):
        p.update(sport="mlb", market="nrfi", date="2026-07-27", pick_id=f"p{i}")
    pnl.write_text(json.dumps({"picks": graded}))
    monkeypatch.setattr(xl, "_EXPERIMENTS_DIR", tmp_path / "experiments")
    snap = xl.record("mlb", "nrfi", "baseline", note="test", pnl_file=pnl)
    assert snap.tag == "baseline" and snap.n == 40
    hist = xl.history("mlb", "nrfi")
    assert len(hist) == 1 and hist[0]["tag"] == "baseline"
