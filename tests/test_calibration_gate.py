"""
tests/test_calibration_gate.py — Edge honesty gate (plan item X1).

Pins the invariants that stop overconfident models from manufacturing phantom
edges: a claimed edge is shrunk to what has historically materialized, trusted
segments shrink by their realization factor, unproven segments are magnitude-
capped, and the schema wires it in for PENDING picks only (graded picks and the
public record are never rewritten).

Run: python3 -m pytest tests/test_calibration_gate.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.analytics.calibration_gate as cg
from src.tracking.schema import normalize_pick


def _seed_table(monkeypatch, table: dict):
    """Force the module cache to a known table (no disk / no picks.json)."""
    monkeypatch.setattr(cg, "_table_cache", table)


class TestKFactor:
    def test_zero_when_no_edge_materialized(self):
        # claimed +43pp, realized negative -> k floors at 0
        assert cg._k_from(200, 43.0, -9.0) == 0.0

    def test_full_when_realized_meets_claim(self):
        assert cg._k_from(200, 5.0, 6.0) == 1.0   # capped at 1

    def test_partial_realization(self):
        assert cg._k_from(200, 20.0, 12.0) == 0.6

    def test_tiny_claim_is_not_touched(self):
        # A model claiming ~no edge shouldn't be shrunk on noise.
        assert cg._k_from(200, 0.2, -5.0) == 1.0


class TestCalibrateEdge:
    def test_trusted_segment_shrinks_by_k(self, monkeypatch):
        _seed_table(monkeypatch, {"tennis::total": {
            "n": 150, "claimed_pp": 32.0, "realized_pp": -9.0, "k": 0.0}})
        assert cg.calibrate_edge("tennis_atp_wimbledon", "total", 43.5) == 0.0

    def test_trusted_good_segment_survives(self, monkeypatch):
        _seed_table(monkeypatch, {"mlb::total": {
            "n": 195, "claimed_pp": 4.8, "realized_pp": 6.7, "k": 1.0}})
        assert cg.calibrate_edge("mlb", "total", 4.8) == 4.8

    def test_unproven_segment_is_capped(self, monkeypatch):
        _seed_table(monkeypatch, {})   # unknown segment
        # 30pp claim on an unknown market is capped to HARD_CAP
        assert cg.calibrate_edge("newsport", "total", 30.0) == cg.HARD_CAP

    def test_unproven_with_partial_evidence_shrinks_then_caps(self, monkeypatch):
        # n between PARTIAL_N and MIN_TRUST, clearly overconfident -> k applied
        _seed_table(monkeypatch, {"wnba::total": {
            "n": 67, "claimed_pp": 13.4, "realized_pp": -13.5, "k": 0.0}})
        assert cg.calibrate_edge("wnba", "total", 14.9) == 0.0

    def test_negative_edge_preserved_under_cap(self, monkeypatch):
        _seed_table(monkeypatch, {})
        assert cg.calibrate_edge("newsport", "spread", -20.0) == -cg.HARD_CAP


class TestSchemaIntegration:
    def test_pending_phantom_edge_is_shrunk_and_decarded(self, monkeypatch):
        _seed_table(monkeypatch, {"tennis::total": {
            "n": 150, "claimed_pp": 32.0, "realized_pp": -9.0, "k": 0.0}})
        p = normalize_pick({
            "sport": "tennis_atp_wimbledon", "market": "total", "team": "OVER 22.5",
            "date": "2026-07-20", "odds": -110, "model_prob": 0.72,
            "edge_pct": 43.5, "stake": 1.0, "card_pick": True, "result": None})
        assert p["raw_edge_pct"] == 43.5
        assert p["edge_pct"] == 0.0
        assert p["card_pick"] is False
        assert p["stake"] == 0.0

    def test_graded_pick_is_frozen(self, monkeypatch):
        _seed_table(monkeypatch, {"tennis::total": {
            "n": 150, "claimed_pp": 32.0, "realized_pp": -9.0, "k": 0.0}})
        g = normalize_pick({
            "sport": "tennis_atp_wimbledon", "market": "total", "team": "OVER 22.5",
            "date": "2026-06-20", "odds": -110, "model_prob": 0.72,
            "edge_pct": 43.5, "stake": 1.0, "card_pick": False,
            "result": "loss", "profit": -1.0})
        assert g["edge_pct"] == 43.5   # untouched — record must not be rewritten

    def test_renormalize_is_idempotent(self, monkeypatch):
        _seed_table(monkeypatch, {"tennis::total": {
            "n": 150, "claimed_pp": 32.0, "realized_pp": -9.0, "k": 0.0}})
        one = normalize_pick({
            "sport": "tennis_atp_wimbledon", "market": "total", "team": "OVER 22.5",
            "date": "2026-07-20", "odds": -110, "model_prob": 0.72,
            "edge_pct": 43.5, "stake": 1.0, "card_pick": True, "result": None})
        two = normalize_pick(one)
        assert two["raw_edge_pct"] == 43.5 and two["edge_pct"] == one["edge_pct"]

    def test_proven_market_still_makes_card(self, monkeypatch):
        _seed_table(monkeypatch, {"mlb::total": {
            "n": 195, "claimed_pp": 4.8, "realized_pp": 6.7, "k": 1.0}})
        m = normalize_pick({
            "sport": "mlb", "market": "total", "team": "UNDER 8.5",
            "date": "2026-07-20", "odds": -110, "model_prob": 0.58,
            "edge_pct": 4.8, "stake": 1.0, "card_pick": True, "result": None})
        assert m["edge_pct"] == 4.8 and m["card_pick"] is True
