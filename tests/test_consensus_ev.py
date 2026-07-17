"""
Tests for the cross-book consensus work (Kaunitz 2017 + timing gradient):

  - consensus math (src/strategies/consensus.py): per-book devig, overround
    filtering, leave-one-out consensus, min-books guard
  - consensus_ev shadow strategy: fires on a lagging book, silent on a tight
    board, never bets Pinnacle, skips started/soccer games, differs from
    devig_ev on a Pinnacle-outlier board
  - entry_fair stamps commence_time + consensus_fair_prob/consensus_n_books
  - CLV-by-entry-lead-time bucketing (clv_tracker._stamp_entry_lead / get_clv_by_timing)
  - backtest first-crossing dedup + event_id join (scripts/backtest_consensus.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analytics import clv_tracker as ct
from src.analytics.entry_fair import attach_entry_fair, build_indexes
from src.strategies import shadow_strategies as ss
from src.strategies.consensus import (
    draw_team,
    implied,
    is_draw_selection,
    loo_consensus,
    per_book_fair,
)


# ── consensus math ────────────────────────────────────────────────────────────

def test_implied_american():
    assert implied(100) == pytest.approx(0.5)
    assert implied(-110) == pytest.approx(110 / 210)
    assert implied(150) == pytest.approx(100 / 250)
    assert implied(None) is None
    assert implied(0) is None
    assert implied(float("nan")) is None


def test_per_book_fair_devig_and_overround_filter():
    pairs = {
        "FanDuel": (-110, -110),     # overround ~1.048, keep → fair 0.5
        "DraftKings": (-105, -105),  # overround ~1.024, keep → fair 0.5
        "Weird": (500, 500),         # overround ~0.333, DROP (below 0.95)
        "Vigged": (-2000, -2000),    # overround ~1.905, DROP (above 1.25)
        "OneSided": (-120, None),    # missing a side, DROP
    }
    fair = per_book_fair(pairs)
    assert set(fair) == {"FanDuel", "DraftKings"}
    assert fair["FanDuel"] == pytest.approx(0.5, abs=1e-6)
    assert fair["DraftKings"] == pytest.approx(0.5, abs=1e-6)


def test_per_book_fair_favorite_side():
    # -200 home / +170 away: implied 0.667 / 0.370, overround 1.037 (kept)
    fair = per_book_fair({"B": (-200, 170)})
    assert fair["B"] == pytest.approx(implied(-200) / (implied(-200) + implied(170)))


def test_loo_consensus_excludes_and_averages():
    fair = {"A": 0.60, "B": 0.50, "C": 0.52, "D": 0.48}
    res = loo_consensus(fair, exclude="A", min_books=3)
    assert res is not None
    mean, n = res
    assert n == 3
    assert mean == pytest.approx((0.50 + 0.52 + 0.48) / 3)


def test_loo_consensus_min_books_guard():
    fair = {"A": 0.60, "B": 0.50, "C": 0.52}
    # Excluding A leaves 2 books < min_books=3 → None
    assert loo_consensus(fair, exclude="A", min_books=3) is None
    # Without exclusion, 3 books meets the floor
    assert loo_consensus(fair, exclude=None, min_books=3) is not None


# ── consensus_ev shadow strategy ──────────────────────────────────────────────

def _board(rows: list[dict], commence="2099-01-01T00:00:00Z") -> pd.DataFrame:
    """Wide odds board: one row per (game, book). rows = list of
    {book, home_ml, away_ml}, all for a single game HOME vs AWAY."""
    recs = []
    for r in rows:
        recs.append({
            "GameID": "G1", "HomeTeam": "Home", "AwayTeam": "Away",
            "Sportsbook": r["book"],
            "HomeMoneyline": r["home_ml"], "AwayMoneyline": r["away_ml"],
            "CommenceTime": commence,
        })
    return pd.DataFrame(recs)


def test_consensus_ev_fires_on_lagging_book():
    # Four books price Home ~-140 (fair ~0.585). One soft book leaves Away at
    # +190 (implied 0.345) while consensus of the others says Away ~0.415 → +EV.
    df = _board([
        {"book": "FanDuel", "home_ml": -140, "away_ml": 120},
        {"book": "DraftKings", "home_ml": -138, "away_ml": 118},
        {"book": "BetMGM", "home_ml": -142, "away_ml": 122},
        {"book": "Caesars", "home_ml": -140, "away_ml": 120},
        {"book": "SoftBook", "home_ml": -150, "away_ml": 190},  # stale Away price
    ])
    picks = ss.consensus_ev(df, "baseball_mlb")
    away = [p for p in picks if p["direction"] == "AWAY"]
    assert away, "expected a +EV pick on the lagging Away price"
    p = away[0]
    assert p["sportsbook"] == "SoftBook"
    assert p["odds"] == 190
    assert p["edge_pct"] >= ss.CONSENSUS_MIN_EV_PCT
    assert 0.0 < p["model_prob"] < 1.0


def test_consensus_ev_silent_on_tight_board():
    df = _board([
        {"book": "FanDuel", "home_ml": -120, "away_ml": 102},
        {"book": "DraftKings", "home_ml": -120, "away_ml": 100},
        {"book": "BetMGM", "home_ml": -122, "away_ml": 102},
        {"book": "Caesars", "home_ml": -118, "away_ml": 100},
    ])
    assert ss.consensus_ev(df, "baseball_mlb") == []


def test_consensus_ev_never_bets_pinnacle():
    # Pinnacle has the best (highest) Away price, but it's a non-destination
    # book — the pick must never land on it, even if its price would be +EV.
    df = _board([
        {"book": "FanDuel", "home_ml": -140, "away_ml": 118},
        {"book": "DraftKings", "home_ml": -138, "away_ml": 118},
        {"book": "BetMGM", "home_ml": -142, "away_ml": 120},
        {"book": "Pinnacle", "home_ml": -150, "away_ml": 200},  # best but no-bet
    ])
    picks = ss.consensus_ev(df, "baseball_mlb")
    assert all(p["sportsbook"] != "Pinnacle" for p in picks)


def test_consensus_ev_skips_started_game():
    df = _board([
        {"book": "FanDuel", "home_ml": -140, "away_ml": 120},
        {"book": "DraftKings", "home_ml": -138, "away_ml": 118},
        {"book": "BetMGM", "home_ml": -142, "away_ml": 122},
        {"book": "SoftBook", "home_ml": -150, "away_ml": 190},
    ], commence="2000-01-01T00:00:00Z")  # long past
    assert ss.consensus_ev(df, "baseball_mlb") == []


def test_consensus_ev_skips_soccer_without_draw_prices():
    # A 3-way sport whose board carries NO draw prices cannot be devigged
    # honestly — must stay silent (the pre-2026-07-16 blanket skip, now
    # applied per-game only when the draw is genuinely missing).
    df = _board([
        {"book": "FanDuel", "home_ml": -140, "away_ml": 190},
        {"book": "DraftKings", "home_ml": -138, "away_ml": 188},
        {"book": "BetMGM", "home_ml": -142, "away_ml": 192},
    ])
    assert ss.consensus_ev(df, "soccer_fifa_world_cup") == []


# ── 3-way (soccer) consensus ─────────────────────────────────────────────────

def _board3(rows: list[dict], commence="2099-01-01T00:00:00Z") -> pd.DataFrame:
    """3-way board: rows = {book, home_ml, away_ml, draw} for one game."""
    return pd.DataFrame([{
        "GameID": "G1", "HomeTeam": "Home", "AwayTeam": "Away",
        "Sportsbook": r["book"], "HomeMoneyline": r["home_ml"],
        "AwayMoneyline": r["away_ml"], "DrawOdds": r.get("draw"),
        "CommenceTime": commence,
    } for r in rows])


def test_consensus_ev_three_way_no_phantom_edge():
    """The bug the old skip papered over: devig home-vs-away only and the
    missing ~25% draw mass inflates BOTH fair probs → every tight soccer board
    prints fake +EV. Full-simplex devig must stay silent on a tight board."""
    tight = {"home_ml": -105, "away_ml": 290, "draw": 250}
    df = _board3([
        {"book": "FanDuel", **tight},
        {"book": "DraftKings", "home_ml": -108, "away_ml": 285, "draw": 255},
        {"book": "BetMGM", "home_ml": -104, "away_ml": 295, "draw": 245},
        {"book": "Caesars", "home_ml": -106, "away_ml": 290, "draw": 250},
    ])
    # Sanity: a 2-way devig of this board WOULD print phantom EV (~+25%)
    two_way_fair = implied(-105) / (implied(-105) + implied(290))
    assert (two_way_fair / implied(-105) - 1) * 100 > 20
    # Correct 3-way consensus: silent
    assert ss.consensus_ev(df, "soccer_fifa_world_cup") == []


def test_consensus_ev_three_way_fires_on_lagging_book():
    df = _board3([
        {"book": "FanDuel", "home_ml": -105, "away_ml": 290, "draw": 250},
        {"book": "DraftKings", "home_ml": -108, "away_ml": 285, "draw": 255},
        {"book": "BetMGM", "home_ml": -104, "away_ml": 295, "draw": 245},
        {"book": "Caesars", "home_ml": -106, "away_ml": 290, "draw": 250},
        # Soft book still hanging a stale Away price
        {"book": "SoftBook", "home_ml": -120, "away_ml": 400, "draw": 250},
    ])
    picks = ss.consensus_ev(df, "soccer_usa_mls")
    away = [p for p in picks if p["direction"] == "AWAY"]
    assert away, "expected a +EV pick on the stale 3-way Away price"
    p = away[0]
    assert p["sportsbook"] == "SoftBook"
    assert p["odds"] == 400
    # Consensus prob must reflect the draw mass: away fair ≈ 0.22, not ≈ 0.28
    assert p["model_prob"] < 0.26


def test_consensus_ev_three_way_drops_books_missing_draw():
    # Only 2 books quote the full simplex → LOO leaves 1 < MIN_BOOKS → silent,
    # even though 2-way-only books show a juicy (un-devig-able) price.
    df = _board3([
        {"book": "FanDuel", "home_ml": -105, "away_ml": 290, "draw": 250},
        {"book": "DraftKings", "home_ml": -108, "away_ml": 285, "draw": 255},
        {"book": "NoDraw1", "home_ml": -120, "away_ml": 400, "draw": None},
        {"book": "NoDraw2", "home_ml": -115, "away_ml": 380, "draw": None},
    ])
    assert ss.consensus_ev(df, "soccer_usa_mls") == []


def test_parser_carries_draw_odds():
    from src.data.odds_api import _parse_odds_response
    event = {
        "id": "E1", "home_team": "Home FC", "away_team": "Away FC",
        "commence_time": "2099-01-01T00:00:00Z",
        "bookmakers": [{"title": "FanDuel", "last_update": "x", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Home FC", "price": -105},
                {"name": "Away FC", "price": 290},
                {"name": "Draw", "price": 250},
            ]}]}],
    }
    df = _parse_odds_response([event], normalize_names=False)
    assert df.iloc[0]["DrawOdds"] == 250
    assert df.iloc[0]["HomeMoneyline"] == -105


def test_consensus_ev_needs_min_books():
    # Only 3 books quote → LOO leaves 2 < MIN_BOOKS → no pick even if divergent.
    df = _board([
        {"book": "FanDuel", "home_ml": -140, "away_ml": 120},
        {"book": "DraftKings", "home_ml": -138, "away_ml": 118},
        {"book": "SoftBook", "home_ml": -150, "away_ml": 220},
    ])
    assert ss.consensus_ev(df, "baseball_mlb") == []


# ── DRAW as a full third side ────────────────────────────────────────────────

def test_draw_team_key_is_matchup_scoped_and_detected():
    # The packed key must be unique per matchup (a bare "draw" collides) and
    # must be recognised by is_draw_selection so the substring joins skip it.
    key = draw_team("Toronto FC", "CF Montreal")
    assert key == "Draw (Toronto FC @ CF Montreal)"
    assert is_draw_selection(key)
    assert is_draw_selection("draw (x @ y)")
    assert not is_draw_selection("CF Montreal")
    assert not is_draw_selection("Draymond Green")  # starts with "dra", not "draw"


def test_consensus_ev_fires_draw_on_lagging_book():
    # Every book agrees the draw is ~+240 (fair ≈ 0.28) except SoftBook, which
    # still hangs +360. The consensus must price the draw and fire on SoftBook.
    df = _board3([
        {"book": "FanDuel", "home_ml": -105, "away_ml": 290, "draw": 240},
        {"book": "DraftKings", "home_ml": -108, "away_ml": 285, "draw": 245},
        {"book": "BetMGM", "home_ml": -104, "away_ml": 295, "draw": 238},
        {"book": "Caesars", "home_ml": -106, "away_ml": 290, "draw": 242},
        {"book": "SoftBook", "home_ml": -106, "away_ml": 290, "draw": 360},
    ])
    picks = ss.consensus_ev(df, "soccer_usa_mls")
    draws = [p for p in picks if p["direction"] == "DRAW"]
    assert draws, "expected a +EV pick on the stale draw price"
    p = draws[0]
    assert p["sportsbook"] == "SoftBook"
    assert p["odds"] == 360
    assert p["team"] == draw_team("Away", "Home")
    assert is_draw_selection(p["team"])
    # Consensus draw prob is the crowd ~0.28, not SoftBook's implied ~0.22.
    assert 0.25 < p["model_prob"] < 0.31


def test_consensus_ev_draw_silent_on_tight_board():
    # No stale draw → no draw pick (and the packed team key never leaks out).
    df = _board3([
        {"book": "FanDuel", "home_ml": -105, "away_ml": 290, "draw": 250},
        {"book": "DraftKings", "home_ml": -108, "away_ml": 285, "draw": 255},
        {"book": "BetMGM", "home_ml": -104, "away_ml": 295, "draw": 245},
        {"book": "Caesars", "home_ml": -106, "away_ml": 290, "draw": 250},
    ])
    picks = ss.consensus_ev(df, "soccer_usa_mls")
    assert [p for p in picks if p["direction"] == "DRAW"] == []


def test_consensus_ev_no_draw_side_for_two_way_sport():
    # MLB has no draw column → sides stay home/away, never a DRAW pick.
    df = _board([
        {"book": "FanDuel", "home_ml": -140, "away_ml": 120},
        {"book": "DraftKings", "home_ml": -138, "away_ml": 118},
        {"book": "BetMGM", "home_ml": -142, "away_ml": 122},
        {"book": "SoftBook", "home_ml": -150, "away_ml": 220},
    ])
    picks = ss.consensus_ev(df, "baseball_mlb")
    assert all(p["direction"] in ("HOME", "AWAY") for p in picks)


# ── Pinnacle-anchored 3-way (devig_ev twin of consensus_ev) ──────────────────

def test_pinnacle_fair_map_builds_three_way_h2h():
    from src.data.pinnacle_fair import build_fair_prob_map
    df = _board3([
        {"book": "Pinnacle", "home_ml": -105, "away_ml": 290, "draw": 240},
        {"book": "FanDuel", "home_ml": -104, "away_ml": 295, "draw": 238},
    ])
    fair = build_fair_prob_map(df)["G1"]["h2h"]
    assert fair["source"] == "pinnacle"
    assert {"home", "away", "draw"} <= set(fair)
    # Three devigged probs sum to 1.0 and the draw carries real mass.
    assert fair["home"] + fair["away"] + fair["draw"] == pytest.approx(1.0)
    assert 0.25 < fair["draw"] < 0.31


def test_devig_ev_fires_draw_against_pinnacle_anchor():
    # Pinnacle prices the draw fair (~0.28); SoftBook hangs a stale +330 draw.
    df = _board3([
        {"book": "Pinnacle", "home_ml": -105, "away_ml": 290, "draw": 240},
        {"book": "FanDuel", "home_ml": -104, "away_ml": 295, "draw": 238},
        {"book": "DraftKings", "home_ml": -106, "away_ml": 290, "draw": 242},
        {"book": "SoftBook", "home_ml": -106, "away_ml": 290, "draw": 330},
    ])
    picks = ss.devig_ev(df, "soccer_usa_mls")
    draws = [p for p in picks if p["direction"] == "DRAW"]
    assert draws, "Pinnacle-anchored devig_ev should fire on the stale draw"
    p = draws[0]
    assert p["sportsbook"] == "SoftBook"
    assert p["odds"] == 330
    assert p["team"] == draw_team("Away", "Home")
    assert 0.25 < p["model_prob"] < 0.31   # Pinnacle fair, not SoftBook implied


def test_devig_ev_silent_on_tight_three_way_board():
    # No stale side: full-simplex Pinnacle anchor must NOT print phantom EV.
    df = _board3([
        {"book": "Pinnacle", "home_ml": -105, "away_ml": 290, "draw": 240},
        {"book": "FanDuel", "home_ml": -104, "away_ml": 292, "draw": 242},
        {"book": "DraftKings", "home_ml": -106, "away_ml": 288, "draw": 238},
    ])
    assert ss.devig_ev(df, "soccer_usa_mls") == []


def test_devig_ev_skips_three_way_game_without_draw():
    # Draw price genuinely missing → devig_ev must not 2-way devig soccer.
    df = _board([
        {"book": "Pinnacle", "home_ml": -140, "away_ml": 190},
        {"book": "FanDuel", "home_ml": -138, "away_ml": 188},
        {"book": "SoftBook", "home_ml": -150, "away_ml": 260},
    ])
    assert ss.devig_ev(df, "soccer_usa_mls") == []


def test_consensus_diverges_from_pinnacle_anchor():
    """When PINNACLE is the outlier, devig_ev (Pinnacle-anchored) reacts but
    consensus_ev (board-anchored, Pinnacle just one vote) should not chase it —
    the whole point of the second anchor."""
    # Every soft book agrees Home ~-130 (Away ~+110). Pinnacle is the lone
    # outlier calling Away a big favorite. devig_ev anchors on Pinnacle's fair
    # and sees the soft Away prices as +EV; consensus_ev, anchored on the crowd,
    # does not.
    df = _board([
        {"book": "FanDuel", "home_ml": -130, "away_ml": 110},
        {"book": "DraftKings", "home_ml": -130, "away_ml": 110},
        {"book": "BetMGM", "home_ml": -132, "away_ml": 112},
        {"book": "Caesars", "home_ml": -128, "away_ml": 108},
        {"book": "Pinnacle", "home_ml": 250, "away_ml": -300},  # lone outlier
    ])
    cons_picks = ss.consensus_ev(df, "baseball_mlb")
    # The board consensus (excl. destination) is tight around Home -130, so the
    # best soft Away price (+110/-0.476) is NOT +EV vs a ~0.46 Away consensus.
    assert cons_picks == [], "consensus must not chase a lone Pinnacle outlier"


# ── consensus_ev_totals / consensus_ev_spreads ───────────────────────────────

def _totals_board(rows: list[dict], commence="2099-01-01T00:00:00Z") -> pd.DataFrame:
    """rows = {book, total, over, under} for a single game."""
    return pd.DataFrame([{
        "GameID": "G1", "HomeTeam": "Home", "AwayTeam": "Away",
        "Sportsbook": r["book"], "Total": r["total"],
        "OverOdds": r["over"], "UnderOdds": r["under"],
        "CommenceTime": commence,
    } for r in rows])


def test_modal_line_majority_and_tiebreak():
    assert ss._modal_line(pd.Series([8.5, 8.5, 8.5, 9.0])) == 8.5
    # 2-2 tie: 8.5 and 9.5 both appear twice; median 9.0 → equidistant, then
    # the lower line wins deterministically
    assert ss._modal_line(pd.Series([8.5, 8.5, 9.5, 9.5])) == 8.5
    assert ss._modal_line(pd.Series([float("nan")])) is None


def test_consensus_ev_totals_fires_at_modal_line_only():
    df = _totals_board([
        {"book": "FanDuel", "total": 8.5, "over": -110, "under": -110},
        {"book": "DraftKings", "total": 8.5, "over": -112, "under": -108},
        {"book": "BetMGM", "total": 8.5, "over": -110, "under": -110},
        {"book": "Caesars", "total": 8.5, "over": -108, "under": -112},
        {"book": "SoftBook", "total": 8.5, "over": 130, "under": -160},  # stale Over
        # Off-line book with a huge price — must be ignored (different bet)
        {"book": "OffLine", "total": 9.5, "over": 200, "under": -250},
    ])
    picks = ss.consensus_ev_totals(df, "baseball_mlb")
    assert picks, "expected a +EV Over at the modal line"
    p = picks[0]
    assert p["direction"] == "OVER"
    assert p["sportsbook"] == "SoftBook"
    assert p["line"] == 8.5
    assert p["team"] == "OVER 8.5"
    assert all(x["sportsbook"] != "OffLine" for x in picks)


def test_consensus_ev_totals_silent_on_tight_board():
    df = _totals_board([
        {"book": "FanDuel", "total": 8.5, "over": -110, "under": -110},
        {"book": "DraftKings", "total": 8.5, "over": -112, "under": -108},
        {"book": "BetMGM", "total": 8.5, "over": -110, "under": -110},
        {"book": "Caesars", "total": 8.5, "over": -108, "under": -112},
    ])
    assert ss.consensus_ev_totals(df, "baseball_mlb") == []


def _spreads_board(rows: list[dict], commence="2099-01-01T00:00:00Z") -> pd.DataFrame:
    return pd.DataFrame([{
        "GameID": "G1", "HomeTeam": "Home", "AwayTeam": "Away",
        "Sportsbook": r["book"], "HomeSpread": r["line"],
        "HomeSpreadOdds": r["h"], "AwaySpreadOdds": r["a"],
        "CommenceTime": commence,
    } for r in rows])


def test_consensus_ev_spreads_fires_with_signed_line():
    df = _spreads_board([
        {"book": "FanDuel", "line": -1.5, "h": -110, "a": -110},
        {"book": "DraftKings", "line": -1.5, "h": -112, "a": -108},
        {"book": "BetMGM", "line": -1.5, "h": -110, "a": -110},
        {"book": "Caesars", "line": -1.5, "h": -108, "a": -112},
        {"book": "SoftBook", "line": -1.5, "h": -140, "a": 135},  # stale Away
    ])
    picks = ss.consensus_ev_spreads(df, "baseball_mlb")
    away = [p for p in picks if p["direction"] == "AWAY"]
    assert away, "expected a +EV pick on the stale Away spread price"
    p = away[0]
    assert p["market"] == "spread"
    assert p["team"] == "Away"
    assert p["line"] == 1.5          # signed from the picked team's perspective
    assert p["sportsbook"] == "SoftBook"


def test_consensus_ev_spreads_silent_when_thin():
    # Only 3 books at the modal line → LOO leaves 2 < MIN_BOOKS
    df = _spreads_board([
        {"book": "FanDuel", "line": -1.5, "h": -110, "a": -110},
        {"book": "DraftKings", "line": -1.5, "h": -112, "a": -108},
        {"book": "SoftBook", "line": -1.5, "h": -140, "a": 140},
    ])
    assert ss.consensus_ev_spreads(df, "baseball_mlb") == []


# ── entry_fair consensus + commence stamping ─────────────────────────────────

class _FakeBoards:
    def __init__(self, events, age_min=5.0):
        idx = build_indexes(events)
        idx["age_min"] = age_min
        self._idx = idx

    def get(self, sport):
        return self._idx


def _multi_book_event():
    home, away = "Boston Red Sox", "New York Yankees"
    def mk(book, hp, ap):
        return {"title": book, "markets": [
            {"key": "h2h", "outcomes": [
                {"name": home, "price": hp}, {"name": away, "price": ap}]}]}
    return {
        "home_team": home, "away_team": away,
        "commence_time": "2099-06-01T23:05:00Z",
        "bookmakers": [
            mk("Pinnacle", -115, -105),
            mk("DraftKings", -105, -110),
            mk("FanDuel", -108, -104),
        ],
    }


def test_build_indexes_carries_books_and_commence():
    idx = build_indexes([_multi_book_event()])
    rec = idx["ml"]["boston red sox"]
    assert set(rec["books"]) == {"Pinnacle", "DraftKings", "FanDuel"}
    assert rec["commence"] == "2099-06-01T23:05:00Z"
    assert idx["commence"][frozenset({"boston red sox", "new york yankees"})] \
        == "2099-06-01T23:05:00Z"


def test_attach_entry_fair_stamps_consensus_and_commence():
    boards = _FakeBoards([_multi_book_event()])
    snap = {"sport": "mlb", "market": "moneyline", "team": "Boston Red Sox",
            "opening_implied_prob": 0.512}
    assert attach_entry_fair(snap, boards) is True
    assert snap["commence_time"] == "2099-06-01T23:05:00Z"
    assert snap["consensus_n_books"] == 3
    # Consensus = median of each book's own home devig, all near 0.5-0.52
    assert 0.48 < snap["consensus_fair_prob"] < 0.55


def _soccer_3way_event():
    home, away = "CF Montreal", "Toronto FC"
    def mk(book, hp, ap, dp):
        return {"title": book, "markets": [
            {"key": "h2h", "outcomes": [
                {"name": home, "price": hp}, {"name": away, "price": ap},
                {"name": "Draw", "price": dp}]}]}
    return {
        "home_team": home, "away_team": away,
        "commence_time": "2099-06-01T23:05:00Z",
        "bookmakers": [
            mk("Pinnacle", -105, 290, 240),
            mk("DraftKings", -108, 285, 245),
            mk("FanDuel", -104, 295, 238),
        ],
    }


def test_attach_entry_fair_resolves_draw_by_matchup():
    # A DRAW snapshot packs the matchup into `team`; entry_fair must resolve the
    # event by its OWN matchup string, devig the full 3-way, and NOT be fooled
    # by the substring fallback (the packed key contains both team names).
    boards = _FakeBoards([_soccer_3way_event()])
    snap = {"sport": "soccer_usa_mls", "market": "moneyline",
            "team": draw_team("Toronto FC", "CF Montreal"),
            "matchup": "Toronto FC @ CF Montreal",
            "opening_implied_prob": 0.28}
    assert attach_entry_fair(snap, boards) is True
    assert snap["commence_time"] == "2099-06-01T23:05:00Z"
    # Fair draw prob from the 3-way devig sits near the ~0.28 crowd, well below
    # the ~0.42 a broken 2-way (home-vs-away) devig would leave for the draw.
    assert 0.25 < snap["opening_fair_prob"] < 0.32


def test_attach_entry_fair_draw_absent_matchup_returns_false():
    boards = _FakeBoards([_soccer_3way_event()])
    snap = {"sport": "soccer_usa_mls", "market": "moneyline",
            "team": draw_team("Nowhere FC", "Elsewhere FC"),
            "matchup": "Nowhere FC @ Elsewhere FC",
            "opening_implied_prob": 0.28}
    assert attach_entry_fair(snap, boards) is False
    assert "opening_fair_prob" not in snap


# ── entry-lead-time CLV bucketing ────────────────────────────────────────────

def test_stamp_entry_lead_prefers_snapshot_commence():
    snap = {"snapshot_time": "2026-07-14T18:00:00Z",
            "commence_time": "2026-07-14T23:00:00Z"}
    assert ct._stamp_entry_lead(snap, {}) is True
    assert snap["entry_lead_min"] == pytest.approx(300.0)      # 5h early
    # Idempotent: second call changes nothing → False
    assert ct._stamp_entry_lead(snap, {}) is False


def test_stamp_entry_lead_negative_for_in_play():
    snap = {"snapshot_time": "2026-07-14T23:30:00Z",
            "commence_time": "2026-07-14T23:00:00Z"}
    assert ct._stamp_entry_lead(snap, {}) is True
    assert snap["entry_lead_min"] == pytest.approx(-30.0)      # bet after start


def test_stamp_entry_lead_fallback_map_and_bad_commence():
    # No commence on snap → fall back to the closing-archive map by matchup.
    cmap = {frozenset({"away", "home"}): "2026-07-14T23:00:00Z"}
    snap = {"snapshot_time": "2026-07-14T20:00:00Z",
            "matchup": "Away @ Home", "opponent": "Away @ Home"}
    assert ct._stamp_entry_lead(snap, cmap) is True
    assert snap["entry_lead_min"] == pytest.approx(180.0)
    # Unparseable commence → no stamp
    bad = {"snapshot_time": "2026-07-14T20:00:00Z", "commence_time": "not-a-date"}
    assert ct._stamp_entry_lead(bad, {}) is False
    assert "entry_lead_min" not in bad


def test_get_clv_by_timing_buckets(monkeypatch):
    snaps = [
        {"sport": "mlb", "entry_lead_min": 800.0, "clv_novig_pct": 1.0,
         "snapshot_time": "x"},                                  # >12h
        {"sport": "mlb", "entry_lead_min": 120.0, "clv_novig_pct": -0.5,
         "snapshot_time": "x"},                                  # 1-3h
        {"sport": "mlb", "entry_lead_min": 30.0, "clv_raw_pct": 0.2,
         "snapshot_time": "x"},                                  # <1h
        {"sport": "mlb", "entry_lead_min": -10.0, "clv_novig_pct": 0.4,
         "snapshot_time": "x"},                                  # in-play/late
        {"sport": "mlb", "clv_novig_pct": 5.0},                  # no lead → skip
    ]
    monkeypatch.setattr(ct, "_load_snapshots", lambda: snaps)
    out = ct.get_clv_by_timing("mlb")
    assert set(out) == {">12h", "1-3h", "<1h", "in-play/late"}
    assert out[">12h"]["n"] == 1
    assert out[">12h"]["avg_prob_clv_pct"] == pytest.approx(1.0)
    # earliest-entry bucket ordered first
    assert list(out)[0] == ">12h"


# ── backtest join + first-crossing dedup ─────────────────────────────────────

def test_backtest_first_crossing_and_join(tmp_path, monkeypatch):
    import scripts.backtest_consensus as bt

    # Two snapshots of ONE game; the +EV Away price is present in both. The pick
    # must be recorded once (first crossing) and joined to the close by event_id.
    def game(away_price):
        return {
            "id": "EVT1", "home_team": "Home", "away_team": "Away",
            "commence_time": "2026-07-14T23:00:00Z",
            "bookmakers": [
                {"title": "FanDuel", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Home", "price": -140}, {"name": "Away", "price": 118}]}]},
                {"title": "DraftKings", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Home", "price": -138}, {"name": "Away", "price": 118}]}]},
                {"title": "BetMGM", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Home", "price": -142}, {"name": "Away", "price": 120}]}]},
                {"title": "Caesars", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Home", "price": -140}, {"name": "Away", "price": 120}]}]},
                {"title": "SoftBook", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Home", "price": -150}, {"name": "Away", "price": away_price}]}]},
            ],
        }

    hist = tmp_path / "odds_history" / "baseball_mlb"
    hist.mkdir(parents=True)
    import json
    lines = [
        {"ts": "2026-07-14T12:00:00Z", "games": [game(190)]},   # 11h early, +EV
        {"ts": "2026-07-14T20:00:00Z", "games": [game(195)]},   # 3h early, still +EV
    ]
    (hist / "2026-07-14.jsonl").write_text("\n".join(json.dumps(x) for x in lines))

    closing = tmp_path / "closing"
    closing.mkdir()
    (closing / "mlb_2026-07-14.json").write_text(json.dumps([{
        "event_id": "EVT1", "home_team": "Home", "away_team": "Away",
        "commence_time": "2026-07-14T23:00:00Z", "closing_final": True,
        "mins_to_commence": 5.0,
        "BestHomeML": -150, "BestAwayML": 130,   # Away drifted toward the pick
        "all_odds": [
            {"Sportsbook": "Pinnacle", "Market": "h2h",
             "Selection": "Home", "Odds": -145},
            {"Sportsbook": "Pinnacle", "Market": "h2h",
             "Selection": "Away", "Odds": 125},
        ],
    }]))

    monkeypatch.setattr(bt, "ODDS_HISTORY", tmp_path / "odds_history")
    monkeypatch.setattr(bt, "CLOSING_DIR", closing)

    res = bt.run("baseball_mlb", [2.0], None, None, 3)
    rows = res["results"][2.0]
    away_rows = [r for r in rows if r["side"] == "away"]
    assert len(away_rows) == 1, "first-crossing dedup should keep exactly one"
    r = away_rows[0]
    assert r["event_id"] == "EVT1"
    # Entered 11h early (first crossing), not the 3h snapshot
    assert r["lead_min"] == pytest.approx(660.0, abs=1.0)
    assert r["clv_novig_pct"] is not None
    assert r["clv_sharp_pct"] is not None   # Pinnacle close present


def test_backtest_three_way_scores_draw_side(tmp_path, monkeypatch):
    import scripts.backtest_consensus as bt

    def mk(book, hp, ap, dp):
        return {"title": book, "markets": [{"key": "h2h", "outcomes": [
            {"name": "Home", "price": hp}, {"name": "Away", "price": ap},
            {"name": "Draw", "price": dp}]}]}

    # Crowd draw ≈ +240 (fair ~0.28); SoftBook lags at +380 → +EV DRAW pick.
    game = {
        "id": "SOC1", "home_team": "Home", "away_team": "Away",
        "commence_time": "2026-07-17T23:00:00Z",
        "bookmakers": [
            mk("FanDuel", -105, 290, 240),
            mk("DraftKings", -108, 285, 245),
            mk("BetMGM", -104, 295, 238),
            mk("Caesars", -106, 290, 242),
            mk("SoftBook", -106, 290, 380),
        ],
    }
    hist = tmp_path / "odds_history" / "soccer_usa_mls"
    hist.mkdir(parents=True)
    import json
    (hist / "2026-07-17.jsonl").write_text(
        json.dumps({"ts": "2026-07-17T12:00:00Z", "games": [game]}))

    closing = tmp_path / "closing"
    closing.mkdir()
    # Draw drifted in toward the pick (close fair ~0.30 > entry fair ~0.28).
    (closing / "soccer_usa_mls_2026-07-17.json").write_text(json.dumps([{
        "event_id": "SOC1", "home_team": "Home", "away_team": "Away",
        "commence_time": "2026-07-17T23:00:00Z", "closing_final": True,
        "mins_to_commence": 5.0,
        "BestHomeML": -105, "BestAwayML": 290,
        "all_odds": [
            {"Sportsbook": "Pinnacle", "Market": "h2h", "Selection": "Home", "Odds": -110},
            {"Sportsbook": "Pinnacle", "Market": "h2h", "Selection": "Away", "Odds": 285},
            {"Sportsbook": "Pinnacle", "Market": "h2h", "Selection": "Draw", "Odds": 240},
            {"Sportsbook": "FanDuel", "Market": "h2h", "Selection": "Draw", "Odds": 235},
        ],
    }]))

    monkeypatch.setattr(bt, "ODDS_HISTORY", tmp_path / "odds_history")
    monkeypatch.setattr(bt, "CLOSING_DIR", closing)

    res = bt.run("soccer_usa_mls", [2.0], None, None, 3)
    draw_rows = [r for r in res["results"][2.0] if r["side"] == "draw"]
    assert len(draw_rows) == 1, "expected one +EV draw pick joined to the close"
    r = draw_rows[0]
    assert r["event_id"] == "SOC1"
    assert r["clv_novig_pct"] is not None
    assert r["clv_sharp_pct"] is not None
