"""
Tests for the per-league SoccerModel adapters — each league is its own model
with its own registry cell, gated and validated independently.
"""
from __future__ import annotations

from src.config.models import _key, model_status
from src.models.pick_model import PickModel, SportContext, finalize_picks
from src.models.adapters.soccer_model import SoccerModel, SOCCER_LEAGUES, league_label


class _FakeClub:
    def find_edges(self, events, min_edge_pct=4.0, host_nations=None):
        return [{
            "sport": "soccer", "market": "moneyline",
            "direction": "Guadalajara", "team": "Guadalajara",
            "matchup": "FC Juárez @ Guadalajara", "odds": -181,
            "model_prob": 0.66, "edge_pct": 5.2, "sportsbook": "Pinnacle",
            "exp_total": 2.9,
        }]


def _model(monkeypatch, league):
    m = SoccerModel(league)
    monkeypatch.setattr(m, "_load", lambda: _FakeClub())
    return m


def test_one_model_per_league():
    # Each league is a distinct adapter with its own short-label sport.
    ligamx = SoccerModel("soccer_mexico_ligamx")
    mls = SoccerModel("soccer_usa_mls")
    assert isinstance(ligamx, PickModel)
    assert ligamx.sport == "mexico_ligamx" and ligamx.key == ("mexico_ligamx", "moneyline")
    assert mls.sport == "usa_mls" and mls.key == ("usa_mls", "moneyline")


def test_league_label_matches_registry_key():
    # The adapter's sport must equal how _key folds the league, so the registry
    # cell and gate line up 1:1.
    for lg in SOCCER_LEAGUES:
        assert league_label(lg) == _key(lg, "moneyline")[0]


def test_each_league_has_its_own_registry_cell():
    # Liga MX and MLS resolve to separate registry entries (own verdicts).
    assert model_status("soccer_mexico_ligamx", "moneyline") == "incubating"
    assert model_status("soccer_usa_mls", "moneyline") == "incubating"
    assert _key("soccer_mexico_ligamx", "m")[0] != _key("soccer_usa_mls", "m")[0]


def test_reads_its_own_league_events(monkeypatch):
    m = _model(monkeypatch, "soccer_mexico_ligamx")
    ctx = SportContext(date="2026-07-26", extras={"events": [{"home_team": "x"}]})
    raw = m.generate_picks(ctx)
    assert len(raw) == 1
    assert raw[0].sport == "soccer_mexico_ligamx"   # full key kept for the ledger
    assert raw[0].team == "Guadalajara" and raw[0].odds == -181


def test_no_events_yields_nothing(monkeypatch):
    m = _model(monkeypatch, "soccer_usa_mls")
    assert m.generate_picks(SportContext(date="2026-07-26")) == []


def test_round_trip_stays_shadow_half_unit(monkeypatch):
    m = _model(monkeypatch, "soccer_mexico_ligamx")
    ctx = SportContext(date="2026-07-26", extras={"events": [{"home_team": "x"}]})
    p = finalize_picks(m.generate_picks(ctx), "2026-07-26")[0]
    assert p["card_pick"] is False
    assert p["stake"] == 0.5
    assert p["sport"] == "soccer_mexico_ligamx"     # league preserved in ledger
    assert p["raw_edge_pct"] == 5.2                 # claim pinned
    assert p["edge_pct"] <= 5.2                     # gate shrinks it
