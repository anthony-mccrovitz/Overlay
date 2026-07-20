"""
tests/test_polymarket_readiness.py — the gate that stands between the
experiment and real money.

This module decides PROMOTE / RETIRE / WAIT. If its logic is wrong in the
permissive direction it green-lights betting on an unproven strategy; if it is
wrong in the strict direction the experiment never concludes. The invariants
below are therefore about the DISTINCTIONS it must never blur:

  - "failed" vs "not yet": a gate can only fail conclusively once it has the
    sample to say so, otherwise every experiment RETIREs on day one
  - protocol versions must not pool: rules changed mid-flight means the old
    picks answer a different question
  - PROMOTE requires every gate, not most of them

Run: python3 -m pytest tests/test_polymarket_readiness.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import scripts.polymarket_readiness as rd
from src.config import polymarket_protocol as PROTO


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Redirect the module at temp files so nothing touches real data."""
    picks, snaps, out = (tmp_path / "picks.json", tmp_path / "snaps.json",
                         tmp_path / "out.json")
    picks.write_text(json.dumps({"picks": []}))
    snaps.write_text(json.dumps({"snapshots": []}))
    monkeypatch.setattr(rd, "PICKS_FILE", picks)
    monkeypatch.setattr(rd, "SNAPSHOTS_FILE", snaps)
    monkeypatch.setattr(rd, "OUT_FILE", out)

    def _write(picks_rows=(), snap_rows=()):
        picks.write_text(json.dumps({"picks": list(picks_rows)}))
        snaps.write_text(json.dumps({"snapshots": list(snap_rows)}))
    return _write


def _pick(**over):
    p = {"strategy": "polymarket_ev", "poly_protocol": PROTO.PROTOCOL_VERSION,
         "date": "2026-07-20", "team": "X", "market": "moneyline"}
    p.update(over)
    return p


def _snap(clv=1.0, **over):
    s = {"strategy": "polymarket_ev", "clv_pct": clv, "market": "moneyline",
         "date": "2026-07-20", "team": "X"}
    s.update(over)
    return s


class TestVerdictLogic:
    def test_empty_experiment_waits(self, store):
        store()
        assert rd.evaluate()["verdict"] == "WAIT"

    def test_negative_clv_below_sample_is_not_retire(self, store):
        """The distinction that matters most: losing early is NOT failing.
        Without this, one bad night ends the experiment."""
        store(snap_rows=[_snap(clv=-9.0) for _ in range(10)])
        assert rd.evaluate()["verdict"] == "WAIT"

    def test_negative_clv_at_full_sample_is_retire(self, store):
        store(snap_rows=[_snap(clv=-2.0)
                         for _ in range(PROTO.VERDICT_MIN_SCORED)])
        assert rd.evaluate()["verdict"] == "RETIRE"

    def test_positive_clv_alone_does_not_promote(self, store):
        """CLV passing while ANCHOR and FILLS are open must still WAIT —
        PROMOTE requires every gate."""
        store(snap_rows=[_snap(clv=3.0)
                         for _ in range(PROTO.VERDICT_MIN_SCORED)])
        out = rd.evaluate()
        assert out["verdict"] == "WAIT"
        assert not all(g["pass"] for g in out["gates"])

    def test_drawdown_breach_retires_regardless_of_sample(self, store, monkeypatch):
        store()
        monkeypatch.setattr(rd, "evaluate", rd.evaluate)  # keep real fn
        import scripts.paper_trader as pt
        monkeypatch.setattr(pt, "run", lambda **k: {
            "max_drawdown": PROTO.BANKROLL_USD * (PROTO.MAX_DRAWDOWN_FRAC + 0.05)})
        assert rd.evaluate()["verdict"] == "RETIRE"


class TestProtocolIsolation:
    def test_picks_from_another_protocol_are_not_counted(self, store):
        """Rules changed mid-flight means those picks answered a different
        question. Pooling them would launder a fitted sample into the verdict."""
        store(picks_rows=[_pick(poly_protocol="v0") for _ in range(50)])
        assert rd.evaluate()["n_logged"] == 0

    def test_current_protocol_picks_count(self, store):
        store(picks_rows=[_pick() for _ in range(50)])
        assert rd.evaluate()["n_logged"] == 50


class TestUnfilledExcluded:
    def test_unfilled_snapshots_do_not_reach_the_verdict(self, store):
        store(snap_rows=[_snap(clv=5.0, poly_filled=False) for _ in range(20)])
        assert rd.evaluate()["n_scored"] == 0

    def test_filled_and_unchecked_both_count(self, store):
        store(snap_rows=[_snap(clv=5.0, poly_filled=True),
                         _snap(clv=5.0)])          # unchecked
        assert rd.evaluate()["n_scored"] == 2


class TestAnchorCalibration:
    def test_small_buckets_are_ignored_not_reported_as_fine(self, store):
        """A 3-sample bucket must not be presented as evidence the anchor works."""
        store(picks_rows=[_pick(date=f"d{i}", result="win", direction="WIN")
                          for i in range(3)],
              snap_rows=[_snap(date=f"d{i}", direction="WIN",
                               opening_fair_sharp=0.5) for i in range(3)])
        anchor = rd.evaluate()["anchor"]
        assert anchor["n"] == 3
        assert anchor["buckets"] == []      # below the 25-sample floor

    def test_well_calibrated_anchor_reports_small_gap(self, store):
        # 40 picks at a 0.5 fair, 20 wins — exactly calibrated.
        picks = [_pick(date=f"d{i}", direction="WIN",
                       result="win" if i < 20 else "loss") for i in range(40)]
        snaps = [_snap(date=f"d{i}", direction="WIN", opening_fair_sharp=0.55)
                 for i in range(40)]
        store(picks_rows=picks, snap_rows=snaps)
        anchor = rd.evaluate()["anchor"]
        assert anchor["buckets"], "40 samples should clear the floor"
        assert anchor["worst_gap"] == pytest.approx(0.05, abs=0.02)

    def test_miscalibrated_anchor_shows_a_large_gap(self, store):
        """If Pinnacle says 55% and reality is 10%, the anchor is unfit and
        every edge measured against it is measurement error."""
        picks = [_pick(date=f"d{i}", direction="WIN",
                       result="win" if i < 4 else "loss") for i in range(40)]
        snaps = [_snap(date=f"d{i}", direction="WIN", opening_fair_sharp=0.55)
                 for i in range(40)]
        store(picks_rows=picks, snap_rows=snaps)
        assert rd.evaluate()["anchor"]["worst_gap"] > PROTO.ANCHOR_MAX_MISCALIBRATION
