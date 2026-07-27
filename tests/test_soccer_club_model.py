"""
Regression tests for the club soccer model (MLS, Liga MX).

Locks in the fix for the phantom-edge bug where club fixtures were priced by the
national-team model and every game got an identical team-blind price. These
tests load the persisted club pickles (no network) and assert the model now
(a) prices only roster teams, (b) differentiates teams, and (c) applies a real
home-field edge.
"""
from __future__ import annotations

import pytest

from src.data.soccer_club_data import (
    LEAGUE_ROSTERS,
    normalize_club_team_name,
)
from src.models.soccer_club_model import SoccerClubModel

LEAGUES = ["soccer_usa_mls", "soccer_mexico_ligamx"]


def _load(key: str) -> SoccerClubModel:
    m = SoccerClubModel(key)
    if not m.model_path.exists():
        pytest.skip(f"club model {key} not fitted (run validate_soccer_club.py)")
    return m.load()


@pytest.mark.parametrize("key", LEAGUES)
def test_roster_teams_priceable(key):
    m = _load(key)
    for team in list(LEAGUE_ROSTERS[key])[:6]:
        # pick any two distinct roster teams
        other = next(t for t in LEAGUE_ROSTERS[key] if t != team)
        assert m.can_price(team, other) is True


@pytest.mark.parametrize("key", LEAGUES)
def test_non_roster_team_unpriceable(key):
    m = _load(key)
    roster = list(LEAGUE_ROSTERS[key])
    assert m.can_price("Some Random FC", roster[0]) is False
    assert m.can_price(roster[0], "Not A Real Team") is False


def test_teams_are_differentiated():
    """The whole bug was identical prices for every fixture. Distinct matchups
    must now yield distinct probabilities."""
    m = _load("soccer_mexico_ligamx")
    order = sorted(m.elo_ratings.items(), key=lambda x: x[1], reverse=True)
    strong, weak = order[0][0], order[-1][0]
    mid = order[len(order) // 2][0]
    r1 = m.matchup(strong, weak, neutral=False)
    r2 = m.matchup(mid, weak, neutral=False)
    assert abs(r1["home_win"] - r2["home_win"]) > 0.03, "matchups not differentiated"
    # strong team at home beats a weak team more often than a mid team does
    assert r1["home_win"] > r2["home_win"]


@pytest.mark.parametrize("key", LEAGUES)
def test_home_advantage_applies(key):
    """γ must boost a real home side (neutral=False) and vanish on neutral."""
    m = _load(key)
    order = sorted(m.elo_ratings.items(), key=lambda x: x[1], reverse=True)
    a, b = order[3][0], order[4][0]  # two near-equal sides
    home = m.matchup(a, b, neutral=False)
    neutral = m.matchup(a, b, neutral=True)
    assert home["home_win"] > neutral["home_win"], "home edge not applied"


@pytest.mark.parametrize("key", LEAGUES)
def test_probabilities_normalized(key):
    m = _load(key)
    order = sorted(m.elo_ratings.items(), key=lambda x: x[1], reverse=True)
    r = m.matchup(order[0][0], order[-1][0], neutral=False)
    # matchup() rounds each outcome to 4 decimals, so the sum can differ from 1
    # by up to ~5e-4 — a 1e-6 bar is impossible for rounded probabilities.
    assert abs(r["home_win"] + r["draw"] + r["away_win"] - 1.0) < 1e-3


def test_market_anchoring_shrinks_edges():
    """find_edges must pull the model toward the de-vigged book so the reported
    edge is a fraction (ANCHOR_MODEL_WEIGHT) of the raw model-vs-market gap —
    this is what keeps a young rating model from manufacturing phantom edges."""
    m = _load("soccer_mexico_ligamx")
    order = sorted(m.elo_ratings.items(), key=lambda x: x[1], reverse=True)
    strong, weak = order[0][0], order[-1][0]
    event = {
        "home_team": strong, "away_team": weak, "neutral": False,
        "bookmakers": [{
            "title": "Pinnacle",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": strong, "price": -110},
                {"name": weak, "price": 400},
                {"name": "Draw", "price": 300},
            ]}],
        }],
    }
    edges = m.find_edges([event], min_edge_pct=-100.0)
    assert edges, "expected at least one moneyline lean"
    for e in edges:
        # anchored prob sits strictly between the raw model prob and the book.
        raw, anchored, novig = e["model_prob_raw"], e["model_prob"], e["implied_prob"]
        if abs(raw - novig) > 1e-6:
            lo, hi = sorted((raw, novig))
            assert lo - 1e-9 <= anchored <= hi + 1e-9, "anchored prob not between model and market"
        # only moneyline for clubs
        assert e["market"] == "moneyline"


def test_unpriceable_fixture_yields_no_edges():
    m = _load("soccer_usa_mls")
    event = {
        "home_team": "Some Random FC", "away_team": "Toronto FC", "neutral": False,
        "bookmakers": [{"title": "DK", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Some Random FC", "price": 150},
            {"name": "Toronto FC", "price": 160},
            {"name": "Draw", "price": 230}]}]}],
    }
    assert m.find_edges([event], min_edge_pct=-100.0) == []


def test_name_normalization():
    # ESPN variants must resolve to the canonical Odds API form.
    assert normalize_club_team_name("LAFC") == "Los Angeles FC"
    assert normalize_club_team_name("Tigres UANL") == "Tigres"
    assert normalize_club_team_name("CF Montréal") == "CF Montreal"
    assert normalize_club_team_name("Santos") == "Santos Laguna"
    # unknown passes through unchanged
    assert normalize_club_team_name("Toronto FC") == "Toronto FC"
