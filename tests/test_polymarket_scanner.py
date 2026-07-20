"""
Polymarket-vs-Pinnacle scanner tests — all network mocked.

The scanner's contract: only emit when Polymarket's TRUE entry cost
(best ask + 2% fee, never the mid) is under Pinnacle's devigged fair prob by
the shared 2% EV bar, with picks shaped so the existing CLV pipeline scores
them for free (Odds-API team name, American odds, market=moneyline).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.polymarket import FEE_RATE, PolyMarket   # noqa: E402
from scripts.polymarket_scanner import (                # noqa: E402
    log_polymarket_picks,
    prob_to_american,
    scan_sport,
    team_matches,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _pm(question="Yankees vs. Red Sox", outcomes=("New York Yankees", "Boston Red Sox"),
        bid=0.55, ask=0.58, liquidity=5000.0, tokens=("tok0", "tok1"), **over):
    raw = {"outcomes": json.dumps(list(outcomes))}
    kw = dict(
        market_id="m1", question=question, category="sports",
        yes_prob=round((bid + ask) / 2, 4), no_prob=round(1 - (bid + ask) / 2, 4),
        volume_usd=10000.0, liquidity_usd=liquidity, end_date=None, active=True,
        url="https://polymarket.com/event/x", token_ids=list(tokens),
        best_bid=bid, best_ask=ask, raw=raw,
    )
    kw.update(over)
    return PolyMarket(**kw)


def _board(home="New York Yankees", away="Boston Red Sox",
           pin_home=-150, pin_away=130, sport_rows=None):
    """Odds board with a Pinnacle row so build_fair_prob_map gets a sharp anchor."""
    rows = sport_rows or [
        {"GameID": "g1", "HomeTeam": home, "AwayTeam": away, "Sportsbook": "Pinnacle",
         "HomeMoneyline": pin_home, "AwayMoneyline": pin_away,
         "CommenceTime": "2026-07-19T23:00:00Z"},
        {"GameID": "g1", "HomeTeam": home, "AwayTeam": away, "Sportsbook": "FanDuel",
         "HomeMoneyline": -145, "AwayMoneyline": 125,
         "CommenceTime": "2026-07-19T23:00:00Z"},
    ]
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _no_clob(monkeypatch):
    """No CLOB network: default to 'no live book' so entry_cost uses the Gamma
    snapshot. Individual tests override with a fake book."""
    import scripts.polymarket_scanner as sc
    monkeypatch.setattr(sc, "fetch_order_book", lambda *a, **k: None)
    yield


# ── unit: odds + costs + matching ────────────────────────────────────────────

class TestHelpers:
    def test_prob_to_american(self):
        assert prob_to_american(0.25) == 300
        assert prob_to_american(0.60) == -150
        assert prob_to_american(0.50) == -100

    def test_entry_cost_uses_ask_plus_fee_not_mid(self):
        pm = _pm(bid=0.36, ask=0.40)     # mid 0.38
        cost = pm.entry_cost("yes")
        assert cost == pytest.approx(0.40 + FEE_RATE * 0.60)   # 0.412
        assert cost > pm.yes_prob        # strictly worse than the mid

    def test_entry_cost_no_side_uses_one_minus_bid(self):
        pm = _pm(bid=0.36, ask=0.40)
        cost_no = pm.entry_cost("no")
        px = 1 - 0.36
        assert cost_no == pytest.approx(px + FEE_RATE * (1 - px))

    def test_entry_cost_prefers_live_book(self):
        pm = _pm(bid=0.36, ask=0.40)
        cost = pm.entry_cost("yes", book={"best_bid": 0.30, "best_ask": 0.33})
        assert cost == pytest.approx(0.33 + FEE_RATE * 0.67)

    def test_team_matches(self):
        assert team_matches("Yankees", "New York Yankees")
        assert team_matches("New York Yankees", "New York Yankees")
        assert team_matches("McGregor", "Conor McGregor")
        assert not team_matches("Yankees", "Boston Red Sox")
        # generic tokens alone never match
        assert not team_matches("New", "New York Yankees")
        assert not team_matches("City", "Kansas City Royals")


# ── scan_sport behavior ──────────────────────────────────────────────────────

class TestScanSport:
    def test_fires_when_poly_cheaper_than_fair(self):
        # Pinnacle -150/+130 → fair home ≈ 0.593. Poly ask 0.55 → cost 0.559
        # → EV ≈ +6.1% ≥ 2% → fire on the home team.
        pm = _pm(bid=0.53, ask=0.55)
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        assert len(picks) >= 1
        p = next(x for x in picks if x["team"] == "New York Yankees")
        assert p["sportsbook"] == "Polymarket"
        assert p["market"] == "moneyline"
        assert p["edge_pct"] > 2.0
        assert p["odds"] == prob_to_american(p["poly_cost"])
        assert isinstance(p["odds"], int)

    def test_silent_when_cost_above_fair(self):
        # Poly ask 0.62 → cost 0.628 > fair 0.593 → no YES edge; away side ask
        # is 1-bid=0.40 → cost .412 vs fair away 0.407 → +EV? 0.407/0.412-1 =
        # -1.2% < 2% → silent both sides.
        pm = _pm(bid=0.60, ask=0.62)
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        assert picks == []

    def test_two_outcome_market_prices_each_side_off_own_token(self, monkeypatch):
        import scripts.polymarket_scanner as sc
        books = {
            "tok0": {"best_bid": 0.53, "best_ask": 0.55},   # home cheap
            "tok1": {"best_bid": 0.44, "best_ask": 0.46},
        }
        monkeypatch.setattr(sc, "fetch_order_book", lambda t, **k: books.get(t))
        pm = _pm()
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        teams = {p["team"] for p in picks}
        assert "New York Yankees" in teams          # 0.593/0.559 → +6%
        assert "Boston Red Sox" not in teams        # 0.407/0.471 → −13%

    def test_yes_no_market_maps_no_to_opponent(self):
        # "Will the Red Sox win?" YES=away team; NO=Yankees ML.
        # YES ask 0.50 → cost 0.51 vs fair away 0.407 → −20% (silent).
        # NO cost = 1−bid = 0.52 → 0.5296 vs fair home 0.593 → +12% (fires).
        pm = _pm(question="Will the Boston Red Sox win?",
                 outcomes=("Yes", "No"), bid=0.48, ask=0.50)
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        assert [p["team"] for p in picks] == ["New York Yankees"]

    def test_draw_sport_skips_no_side_and_two_outcome_markets(self):
        board = _board(home="Club América", away="Chivas Guadalajara",
                       pin_home=-120, pin_away=250)
        # Yes/No in a draw sport: only YES side may fire
        pm_yesno = _pm(question="Will Club América win?", outcomes=("Yes", "No"),
                       bid=0.42, ask=0.44)
        picks = scan_sport("soccer_mexico_ligamx", board, [pm_yesno], "2026-07-19")
        assert all(p["team"] == "Club América" for p in picks)
        # 2-outcome team market in a draw sport: ambiguous draw semantics → skip
        pm_teams = _pm(question="América vs Chivas",
                       outcomes=("Club América", "Chivas Guadalajara"),
                       bid=0.30, ask=0.32)
        assert scan_sport("soccer_mexico_ligamx", board, [pm_teams], "2026-07-19") == []

    def test_unmatched_and_thin_markets_skipped(self):
        unmatched = _pm(question="Will the Lakers win?",
                        outcomes=("Yes", "No"), bid=0.10, ask=0.12)
        thin = _pm(bid=0.10, ask=0.12, liquidity=50.0)
        picks = scan_sport("baseball_mlb", _board(), [unmatched, thin], "2026-07-19")
        assert picks == []

    def test_derivative_markets_never_priced_as_moneylines(self):
        # A spread contract at spread-market prices vs full-game ML fair is a
        # category error, not an edge (first live scan printed +62% on these).
        spread = _pm(question="Spread: New York Yankees (-1.5)",
                     bid=0.40, ask=0.42)
        spread.raw["sportsMarketType"] = "spreads"
        spread.raw["line"] = -1.5
        f5 = _pm(question="New York Yankees winning after 5 innings?",
                 outcomes=("Yes", "No"), bid=0.40, ask=0.42)   # no smt field
        prop = _pm(question="Aaron Judge: Home Runs O/U 0.5",
                   outcomes=("Over", "Under"), bid=0.30, ask=0.32)
        picks = scan_sport("baseball_mlb", _board(), [spread, f5, prop], "2026-07-19")
        assert picks == []
        # …while an explicit moneyline-typed market still fires
        ml = _pm(bid=0.53, ask=0.55)
        ml.raw["sportsMarketType"] = "moneyline"
        assert scan_sport("baseball_mlb", _board(), [ml], "2026-07-19")

    def test_wrong_date_game_never_matches_todays_board(self):
        # Tomorrow's "Liberty vs. Wings" contract must not attach to today's
        # Wings game (this printed a phantom +62% on the first live scan).
        pm = _pm(question="New York Liberty vs. New York Yankees",
                 outcomes=("New York Liberty", "New York Yankees"),
                 bid=0.40, ask=0.42)
        pm.game_start_time = "2026-07-20T23:00:00Z"       # tomorrow
        assert scan_sport("baseball_mlb", _board(), [pm], "2026-07-19") == []
        # …and even with today's start time, a market whose two outcomes span
        # DIFFERENT games (one team not on today's board) is skipped.
        pm2 = _pm(question="New York Liberty vs. New York Yankees",
                  outcomes=("New York Liberty", "New York Yankees"),
                  bid=0.40, ask=0.42)
        pm2.game_start_time = "2026-07-19T23:00:00Z"
        assert scan_sport("baseball_mlb", _board(), [pm2], "2026-07-19") == []

    def test_todays_game_start_time_passes(self):
        pm = _pm(bid=0.53, ask=0.55)
        pm.game_start_time = "2026-07-19 23:00:00+00"     # Gamma's space format
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        assert any(p["team"] == "New York Yankees" for p in picks)

    def test_ambiguous_doubleheader_skipped(self):
        rows = []
        for gid in ("g1", "g2"):   # same matchup twice = doubleheader
            rows.append({"GameID": gid, "HomeTeam": "New York Yankees",
                         "AwayTeam": "Boston Red Sox", "Sportsbook": "Pinnacle",
                         "HomeMoneyline": -150, "AwayMoneyline": 130,
                         "CommenceTime": "2026-07-19T23:00:00Z"})
        pm = _pm(bid=0.40, ask=0.42)
        picks = scan_sport("baseball_mlb", _board(sport_rows=rows), [pm], "2026-07-19")
        assert picks == []


# ── logging tail ─────────────────────────────────────────────────────────────

class TestLogging:
    def _pick(self):
        return {
            "sport": "baseball_mlb", "market": "moneyline", "direction": "WIN",
            "team": "New York Yankees", "matchup": "Boston Red Sox @ New York Yankees",
            "odds": -128, "sportsbook": "Polymarket", "model_prob": 0.593,
            "edge_pct": 6.1, "poly_market_id": "m1", "poly_cost": 0.559,
            "poly_question": "Yankees vs. Red Sox",
        }

    def test_logged_shape_and_dedup(self, tmp_path, monkeypatch):
        import scripts.polymarket_scanner as sc
        monkeypatch.setattr(sc, "PICKS_FILE", tmp_path / "picks.json")
        monkeypatch.setattr("src.analytics.clv_tracker.snapshot_from_pnl",
                            lambda *a, **k: 0)

        added = log_polymarket_picks([self._pick()], "2026-07-19")
        assert added == 1
        stored = json.loads((tmp_path / "picks.json").read_text())["picks"][0]
        assert stored["strategy"] == "polymarket_ev"
        assert stored["pick_id"].startswith("polymarket_ev__mlb_")   # namespaced + canonical sport
        assert stored["card_pick"] is False and stored["stake"] == 0.0
        assert stored["sportsbook"] == "Polymarket"
        assert stored["poly_market_id"] == "m1"                      # extras survive
        # second run: same pick dedups
        assert log_polymarket_picks([self._pick()], "2026-07-19") == 0
