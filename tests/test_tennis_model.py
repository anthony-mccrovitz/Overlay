"""
Tests for the rebuilt tennis engine (2026-07-13):
  - name normalization between tennis-data.co.uk and Odds API formats
  - 538 K-decay, rank prior, Elo building on synthetic matches
  - confidence gating + market anchor (sparse players can never show an edge)
  - best-of routing (ATP slams = BO5)
  - grading math (winner match, games totals, retirement void)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data import tennis_data as td
from src.data.tennis_data import (
    build_ratings, elo_from_rank, elo_win_prob,
    norm_odds_name, norm_td_name,
)
from src.data.tennis_results import _games_total, find_result


# ── name normalization ───────────────────────────────────────────────────────

@pytest.mark.parametrize("odds_name,td_name", [
    ("Jannik Sinner", "Sinner J."),
    ("Felix Auger-Aliassime", "Auger-Aliassime F."),
    ("Alex De Minaur", "De Minaur A."),
    ("Novak Djokovic", "Djokovic N."),
])
def test_name_formats_meet(odds_name, td_name):
    assert norm_odds_name(odds_name) == norm_td_name(td_name)


def test_accents_stripped():
    assert norm_odds_name("Novák Djokovič") == norm_td_name("Djokovic N.")


# ── priors and K decay ───────────────────────────────────────────────────────

def test_rank_prior_monotonic():
    assert elo_from_rank(1) > elo_from_rank(10) > elo_from_rank(100) > elo_from_rank(None)
    assert elo_from_rank(1) == pytest.approx(2250.0)
    assert elo_from_rank(None) == 1450.0


def test_k_decays_with_matches():
    k = lambda m: td._K_NUM / ((m + td._K_OFF) ** td._K_SHAPE)
    assert k(0) > k(50) > k(300)
    assert k(0) == pytest.approx(250 / 5 ** 0.4)


# ── Elo building ─────────────────────────────────────────────────────────────

def _frame(rows):
    return pd.DataFrame(rows)


def test_build_ratings_updates_and_skips_walkovers():
    m = _frame([
        {"Winner": "Sinner J.", "Loser": "Zverev A.", "Surface": "Grass",
         "WRank": 1, "LRank": 3, "Comment": "Completed", "Date": "2026-07-12"},
        {"Winner": "Sinner J.", "Loser": "Ghost G.", "Surface": "Grass",
         "WRank": 1, "LRank": 500, "Comment": "Walkover", "Date": "2026-07-13"},
    ])
    r = build_ratings(m)
    sinner, zverev = r["sinner j"], r["zverev a"]
    assert sinner["overall"] > 1500 > zverev["overall"]
    assert sinner["grass"] > 1500
    assert sinner["hard"] == 1500.0            # surface untouched
    assert sinner["matches"] == 1              # walkover didn't count
    assert "ghost g" not in r
    assert sinner["rank"] == 1.0


def test_unknown_player_is_1500_not_1750():
    td._ratings_mem = {"atp": {}, "wta": {}}
    try:
        elo, m = td.get_rating_info("Totally Unknown", "hard", "atp")
        assert elo == 1500.0 and m == 0
    finally:
        td._ratings_mem = None


def test_sparse_player_shrinks_to_rank_prior():
    td._ratings_mem = {"atp": {
        # 2 matches of observed 1900 Elo, ranked #200 → estimate must sit
        # far closer to the rank prior than to the observed rating
        "fresh f": {"overall": 1900.0, "clay": 1900.0, "hard": 1900.0,
                    "grass": 1900.0, "matches": 2, "rank": 200},
    }, "wta": {}}
    try:
        elo, m = td.get_rating_info("Frank Fresh", "hard", "atp")
        prior = elo_from_rank(200)
        assert m == 2
        assert abs(elo - prior) < abs(elo - 1900.0)
    finally:
        td._ratings_mem = None


# ── model: confidence gate + market anchor ───────────────────────────────────

def _fake_event(p_home_price=-150, p_away_price=130):
    return {
        "home_team": "Player Alpha", "away_team": "Player Beta",
        "bookmakers": [
            {"title": "Pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Player Alpha", "price": -160},
                {"name": "Player Beta", "price": 140},
            ]}]},
            {"title": "DraftKings", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Player Alpha", "price": p_home_price},
                {"name": "Player Beta", "price": p_away_price},
            ]}]},
        ],
    }


def test_sparse_players_produce_no_edges(monkeypatch):
    from src.models import tennis_model as tm
    monkeypatch.setattr(tm, "get_rating_info", lambda n, s, t: (1500.0, 0))
    model = tm.TennisModel(surface="grass", tour="atp")
    assert model.confidence("Player Alpha", "Player Beta") == 0.0
    # even a +2000 longshot price shows no edge: final prob IS the market
    edges = model.find_edges([_fake_event(p_away_price=2000)], min_edge_pct=4.0)
    assert edges == []


def test_known_players_capped_edges(monkeypatch):
    from src.models import tennis_model as tm
    ratings = {"player alpha": (2100.0, 300), "player beta": (1600.0, 300)}
    monkeypatch.setattr(tm, "get_rating_info",
                        lambda n, s, t: ratings[n.lower()])
    model = tm.TennisModel(surface="grass", tour="atp")
    w = model.confidence("Player Alpha", "Player Beta")
    assert w == 0.5                      # capped: market never outweighed
    edges = model.find_edges([_fake_event()], min_edge_pct=0.1)
    assert all(e["edge_pct"] <= tm.MAX_EDGE_PCT for e in edges)
    assert all(e["sportsbook"] != "Pinnacle" for e in edges)
    for e in edges:
        assert "model_weight" in e and "market_fair" in e


# ── best-of routing ──────────────────────────────────────────────────────────

def test_bo5_only_for_atp_slams():
    import run_tennis as rt
    assert rt._bo_for("tennis_atp_wimbledon", None) == 5
    assert rt._bo_for("tennis_wta_wimbledon", None) == 3
    assert rt._bo_for("tennis_atp_halle_open", None) == 3
    assert rt._bo_for("tennis_atp_wimbledon", 3) == 3   # explicit override wins
    assert rt._tour_for("tennis_wta_wimbledon") == "wta"


# ── grading math ─────────────────────────────────────────────────────────────

class _Row:
    def __init__(self, **kw):
        for i in range(1, 6):
            setattr(self, f"W{i}", kw.get(f"W{i}", float("nan")))
            setattr(self, f"L{i}", kw.get(f"L{i}", float("nan")))


def test_games_total_from_set_scores():
    # Sinner d. Zverev 6-7 7-6 6-3 → 35 games
    row = _Row(W1=6, L1=7, W2=7, L2=6, W3=6, L3=3)
    assert _games_total(row) == 35.0
    assert _games_total(_Row()) is None


def test_find_result_window_and_retirement():
    idx = {
        frozenset({"sinner j", "zverev a"}): [
            {"date": date(2026, 7, 12), "winner_key": "sinner j",
             "games": 35.0, "completed": True},
        ],
        frozenset({"osaka n", "kostyuk m"}): [
            {"date": date(2026, 7, 9), "winner_key": "osaka n",
             "games": 11.0, "completed": False},   # retirement
        ],
    }
    r = find_result(idx, "Jannik Sinner", "Alexander Zverev", date(2026, 7, 12))
    assert r and r["winner_key"] == "sinner j" and r["games"] == 35.0
    # ±1 day window
    assert find_result(idx, "Jannik Sinner", "Alexander Zverev", date(2026, 7, 13))
    assert find_result(idx, "Jannik Sinner", "Alexander Zverev", date(2026, 7, 15)) is None
    # retirement flagged not-completed (grader voids the total)
    r2 = find_result(idx, "Naomi Osaka", "Marta Kostyuk", date(2026, 7, 9))
    assert r2 and r2["completed"] is False
