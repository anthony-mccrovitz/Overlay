"""
Tests for the MlbF5TotalsModel adapter — first-5-innings totals through the
common PickModel gate. The real edge logic (find_f5_edges) is stubbed; these
prove the adapter builds SP inputs from matchups and translates output faithfully.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.models.pick_model import PickModel, SportContext, finalize_picks
from src.models.adapters.mlb_f5_totals_model import MlbF5TotalsModel


def _matchup(home, away, h_era=3.5, a_era=4.5, h_k9=9.0, a_k9=8.0):
    return SimpleNamespace(
        home_team=SimpleNamespace(name=home),
        away_team=SimpleNamespace(name=away),
        home_pitcher=SimpleNamespace(era=h_era, k_per_9=h_k9),
        away_pitcher=SimpleNamespace(era=a_era, k_per_9=a_k9),
    )


_EDGE = {
    "market": "f5_total", "direction": "UNDER", "line": 4.5,
    "matchup": "Seattle Mariners @ Oakland Athletics",
    "team": "F5 UNDER 4.5 (Seattle Mariners @ Oakland Athletics)",
    "model_prob": 0.61, "edge_pct": 6.2, "odds": -115,
    "book": "FanDuel", "projected_total": 3.9,
}


def _model(monkeypatch, edges):
    m = MlbF5TotalsModel()
    captured = {}

    def _fake(inputs, game_date=None, min_edge=0.08):
        captured["inputs"] = inputs
        captured["min_edge"] = min_edge
        return edges

    monkeypatch.setattr(
        "src.models.adapters.mlb_f5_totals_model.find_f5_edges", _fake
    )
    return m, captured


def test_is_a_pick_model():
    m = MlbF5TotalsModel()
    assert isinstance(m, PickModel)
    assert m.key == ("mlb", "f5_total")


def test_no_matchups_yields_nothing():
    assert MlbF5TotalsModel().generate_picks(SportContext(date="2026-07-27")) == []


def test_builds_sp_inputs_from_matchups(monkeypatch):
    m, captured = _model(monkeypatch, [])
    ctx = SportContext(date="2026-07-27", matchups=[_matchup("Oakland Athletics", "Seattle Mariners")])
    m.generate_picks(ctx)
    inp = captured["inputs"][0]
    assert inp["home_team"] == "Oakland Athletics"
    assert inp["home_sp_era"] == 3.5 and inp["away_sp_era"] == 4.5
    assert inp["home_sp_k9"] == 9.0 and inp["away_sp_k9"] == 8.0
    assert captured["min_edge"] == 0.08


def test_translates_edge_to_rawpick(monkeypatch):
    m, _ = _model(monkeypatch, [_EDGE])
    ctx = SportContext(date="2026-07-27", matchups=[_matchup("Oakland Athletics", "Seattle Mariners")])
    raw = m.generate_picks(ctx)
    assert len(raw) == 1
    rp = raw[0]
    assert rp.sport == "mlb" and rp.market == "f5_total"
    assert rp.direction == "UNDER" and rp.odds == -115
    assert rp.team == "F5 UNDER 4.5 (Seattle Mariners @ Oakland Athletics)"
    assert rp.edge == 6.2 and rp.sportsbook == "FanDuel"


def test_round_trip_through_gate(monkeypatch):
    m, _ = _model(monkeypatch, [_EDGE])
    ctx = SportContext(date="2026-07-27", matchups=[_matchup("Oakland Athletics", "Seattle Mariners")])
    p = finalize_picks(m.generate_picks(ctx), "2026-07-27")[0]
    assert p["market"] == "f5_total"
    assert p["team"] == "F5 UNDER 4.5 (Seattle Mariners @ Oakland Athletics)"
    assert p["raw_edge_pct"] == 6.2     # claim pinned
    assert p["edge_pct"] <= 6.2         # gate shrinks it
