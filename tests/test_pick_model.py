"""
Tests for the PickModel framework (the factory's first brick).

Covers the contract, the gate (finalize_picks), and the reference adapter
(MlbTotalsModel) — proving a model's raw output becomes a canonical pick that
matches the exact conventions the live pipeline already writes.
"""
from __future__ import annotations

import pandas as pd

from src.config.models import is_card_pick
from src.models.pick_model import PickModel, RawPick, SportContext, finalize_picks
from src.models.adapters.mlb_totals_model import MlbTotalsModel
from src.tracking.schema import make_pick_id, validate_pick


DATE = "2026-07-26"


def _totals_raw(edge, line=7.5, direction="OVER", odds=100):
    return RawPick(
        sport="mlb", market="total", direction=direction, odds=odds,
        matchup="Colorado Rockies @ Milwaukee Brewers", line=line,
        model_prob=0.7599, edge=edge, sportsbook="BetRivers",
    )


class TestGate:
    def test_canonical_shape_matches_pipeline(self):
        picks = finalize_picks([_totals_raw(edge=2.0)], DATE)
        assert len(picks) == 1
        p = picks[0]
        # Exact conventions the live ledger uses for a totals pick.
        assert p["team"] == "OVER 7.5"
        assert p["direction"] == "OVER"
        assert p["line"] == 7.5
        assert p["market"] == "total"
        assert p["raw_edge_pct"] == 2.0        # the claimed native run-edge is pinned
        assert p["edge_pct"] <= 2.0            # calibration gate may shrink the stored edge
        assert p["odds"] == 100
        assert p["pick_id"] == make_pick_id("mlb", DATE, "OVER 7.5", "total", "OVER")
        assert p["pick_id"] == "mlb_20260726_over-7-5_total_over"
        assert validate_pick(p) == []          # no missing canonical fields

    def test_card_gate_respects_edge_threshold(self):
        # mlb total is a live model with a 1.0–2.0 run card BAND: the profitable
        # edge band per the backtest. Below 1.0 = noise, above 2.0 = untrusted
        # big-disagreement tail — both held as shadow.
        low = finalize_picks([_totals_raw(edge=0.5)], DATE)[0]   # below band
        inband = finalize_picks([_totals_raw(edge=1.5)], DATE)[0]  # in band
        high = finalize_picks([_totals_raw(edge=3.5)], DATE)[0]  # above band
        assert low["card_pick"] is False       # 0.5 < 1.0 → shadow
        assert inband["card_pick"] is True      # 1.0 ≤ 1.5 ≤ 2.0 → card
        assert high["card_pick"] is False       # 3.5 > 2.0 → shadow
        # Gate matches the registry's own is_card_pick decision.
        assert low["card_pick"] == is_card_pick("mlb", "total", 0.5)
        assert inband["card_pick"] == is_card_pick("mlb", "total", 1.5)
        assert high["card_pick"] == is_card_pick("mlb", "total", 3.5)

    def test_unbettable_pick_is_dropped(self):
        assert finalize_picks([_totals_raw(edge=2.0, odds=0)], DATE) == []

    def test_stake_is_flat_unit_for_mlb(self):
        p = finalize_picks([_totals_raw(edge=2.0)], DATE)[0]
        assert p["stake"] == 1.0


class TestAdapterContract:
    def test_is_a_pickmodel(self):
        m = MlbTotalsModel()
        assert isinstance(m, PickModel)
        assert m.key == ("mlb", "total")

    def test_empty_context_yields_nothing(self):
        assert MlbTotalsModel().generate_picks(SportContext(date=DATE)) == []

    def test_maps_model_edges_to_rawpicks(self, monkeypatch):
        fake_edges = [{
            "home_team": "Milwaukee Brewers", "away_team": "Colorado Rockies",
            "predicted_total": 9.5, "market_line": 7.5, "edge_runs": 2.0,
            "direction": "OVER", "best_odds": 100, "sportsbook": "BetRivers",
            "model_prob": 0.7599, "weather_context": "",
        }]
        monkeypatch.setattr(
            "src.models.adapters.mlb_totals_model.find_totals_edges",
            lambda *a, **k: fake_edges,
        )
        ctx = SportContext(date=DATE, odds_df=pd.DataFrame({"x": [1]}))
        raw = MlbTotalsModel().generate_picks(ctx)
        assert len(raw) == 1
        rp = raw[0]
        assert rp.market == "total" and rp.direction == "OVER"
        assert rp.line == 7.5 and rp.edge == 2.0 and rp.odds == 100
        assert rp.matchup == "Colorado Rockies @ Milwaukee Brewers"
        assert rp.extras["proj_total"] == 9.5

        # And the full round-trip: adapter → gate → canonical pick.
        p = finalize_picks(raw, DATE)[0]
        assert p["team"] == "OVER 7.5"
        assert p["card_pick"] is True  # 2.0-run edge sits at the top of the 1.0–2.0 band
