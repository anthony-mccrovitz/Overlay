"""
Tests for the SoccerModel adapter (first grid expansion) — proves the
Dixon-Coles engine plugs into the factory, preserves league identity in the
ledger, and stays shadow through the gate.
"""
from __future__ import annotations

from src.models.pick_model import PickModel, SportContext, finalize_picks
from src.models.adapters.soccer_model import SoccerModel


class _FakeClub:
    """Stand-in for a fitted club model: find_edges returns canned edges."""
    def find_edges(self, events, min_edge_pct=4.0, host_nations=None):
        return [{
            "sport": "soccer", "market": "moneyline",
            "direction": "Guadalajara", "team": "Guadalajara",
            "matchup": "FC Juárez @ Guadalajara", "odds": -181,
            "model_prob": 0.66, "edge_pct": 5.2, "sportsbook": "Pinnacle",
            "exp_total": 2.9,
        }]


def _model(monkeypatch, leagues):
    m = SoccerModel(leagues=leagues)
    monkeypatch.setattr(m, "_model_for", lambda league: _FakeClub())
    return m


def test_is_a_pickmodel():
    assert isinstance(SoccerModel(), PickModel)
    assert SoccerModel().key == ("soccer", "moneyline")


def test_no_events_yields_nothing(monkeypatch):
    m = _model(monkeypatch, ["soccer_mexico_ligamx"])
    assert m.generate_picks(SportContext(date="2026-07-26")) == []


def test_maps_edges_and_preserves_league(monkeypatch):
    league = "soccer_mexico_ligamx"
    m = _model(monkeypatch, [league])
    ctx = SportContext(date="2026-07-26",
                       extras={"events_by_league": {league: [{"home_team": "x"}]}})
    raw = m.generate_picks(ctx)
    assert len(raw) == 1
    rp = raw[0]
    assert rp.sport == league           # league identity kept for the ledger
    assert rp.market == "moneyline"
    assert rp.team == "Guadalajara" and rp.odds == -181 and rp.edge == 5.2


def test_iterates_multiple_leagues(monkeypatch):
    ls = ["soccer_mexico_ligamx", "soccer_usa_mls"]
    m = _model(monkeypatch, ls)
    ctx = SportContext(date="2026-07-26", extras={"events_by_league": {
        ls[0]: [{"home_team": "a"}], ls[1]: [{"home_team": "b"}]}})
    assert len(m.generate_picks(ctx)) == 2


def test_round_trip_stays_shadow(monkeypatch):
    league = "soccer_mexico_ligamx"
    m = _model(monkeypatch, [league])
    ctx = SportContext(date="2026-07-26",
                       extras={"events_by_league": {league: [{"home_team": "x"}]}})
    picks = finalize_picks(m.generate_picks(ctx), "2026-07-26")
    assert len(picks) == 1
    p = picks[0]
    # Soccer moneyline is an incubating registry lane → never card, always 0.5u.
    assert p["card_pick"] is False
    assert p["stake"] == 0.5
    assert p["sport"] == league          # league preserved through normalize
    # The calibration gate shrinks the claimed 5.2% edge to what soccer moneyline
    # historically realizes (~0); the raw claim is pinned for the record.
    assert p["raw_edge_pct"] == 5.2
    assert p["edge_pct"] <= 5.2
