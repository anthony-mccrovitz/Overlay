"""
Tests for the vig-consistent CLV build:

  - entry-side devig math (src/analytics/entry_fair.py)
  - board indexing + attach_entry_fair (moneyline 2/3-way, totals exact-line)
  - stale-opener signal (entry_ev_vs_fair_pct)
  - strategy verdicts under the 300-bet rule + metric preference ladder
  - entry-hour / entry-edge / catalyst bucketing (clv_tracker reports)
  - devig_ev_totals shadow strategy (same-line guard, EV threshold)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analytics import clv_tracker as ct
from src.analytics.entry_fair import (
    _devig,
    _odds_to_implied,
    attach_entry_fair,
    build_indexes,
)


# ── entry-side devig math ─────────────────────────────────────────────────────

def test_devig_two_way_symmetric():
    # -110/-110 is a symmetric market: fair prob is exactly 0.5
    assert _devig(-110, -110) == pytest.approx(0.5)


def test_devig_two_way_favorite():
    # -150 vs +130: raw 0.6 vs 0.4348 → fair = 0.6 / 1.0348
    assert _devig(-150, 130) == pytest.approx(0.6 / (0.6 + 100 / 230))


def test_devig_three_way_sums_to_one():
    sides = [(-105, 260, 250), (260, -105, 250), (250, 260, -105)]
    total = sum(_devig(p, a, b) for p, a, b in sides)
    assert total == pytest.approx(1.0)


def test_devig_strips_vig():
    # Sum of raw implieds > 1 (the vig); sum of fair probs == 1
    raw_sum = _odds_to_implied(-120) + _odds_to_implied(-105)
    assert raw_sum > 1.0
    assert _devig(-120, -105) + _devig(-105, -120) == pytest.approx(1.0)


# ── board indexing + attach_entry_fair ───────────────────────────────────────

def _fake_event(home="Boston Red Sox", away="New York Yankees"):
    """Two books: Pinnacle (-115/-105) and a soft book with a better home price."""
    return {
        "home_team": home,
        "away_team": away,
        "bookmakers": [
            {"title": "Pinnacle", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": home, "price": -115},
                    {"name": away, "price": -105},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -110, "point": 8.5},
                    {"name": "Under", "price": -110, "point": 8.5},
                ]},
            ]},
            {"title": "DraftKings", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": home, "price": -105},   # best home price
                    {"name": away, "price": -110},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": 100, "point": 8.5},   # best over
                    {"name": "Under", "price": -120, "point": 8.5},
                ]},
            ]},
        ],
    }


class _FakeBoards:
    """Stands in for EntryBoards: same .get(sport) contract, no disk."""

    def __init__(self, events, age_min=5.0):
        idx = build_indexes(events)
        idx["age_min"] = age_min
        self._idx = idx

    def get(self, sport):
        return self._idx


def test_build_indexes_best_and_pinnacle():
    idx = build_indexes([_fake_event()])
    rec = idx["ml"]["boston red sox"]
    # Best price = highest American odds for the bettor
    assert rec["best"]["boston red sox"] == -105
    assert rec["best"]["new york yankees"] == -105
    assert rec["pin"]["boston red sox"] == -115
    # Totals indexed by unordered team pair and exact line
    tot = idx["totals"][frozenset({"new york yankees", "boston red sox"})]
    assert tot[8.5]["over_best"] == 100
    assert tot[8.5]["over_pin"] == -110


def test_attach_entry_fair_moneyline():
    boards = _FakeBoards([_fake_event()])
    snap = {
        "sport": "mlb", "market": "moneyline", "team": "Boston Red Sox",
        "opening_odds": -105,
        "opening_implied_prob": _odds_to_implied(-105),
    }
    assert attach_entry_fair(snap, boards) is True
    # Fair from best both sides: -105 (DK home) vs -105 (Pinnacle away) → 0.5
    assert snap["opening_fair_prob"] == pytest.approx(0.5, abs=1e-6)
    # Pinnacle-only fair: -115 vs -105 → 0.53488/1.04703
    pin_fair = _devig(-115, -105)
    assert snap["opening_fair_sharp"] == pytest.approx(pin_fair, abs=1e-6)
    # Stale-opener signal: sharp fair vs our raw entry implied
    exp_ev = (pin_fair / _odds_to_implied(-105) - 1.0) * 100
    assert snap["entry_ev_vs_fair_pct"] == pytest.approx(exp_ev, abs=0.01)
    assert snap["entry_overround"] > 1.0
    assert snap["entry_board_age_min"] == 5.0


def test_attach_entry_fair_moneyline_partial_name():
    boards = _FakeBoards([_fake_event()])
    snap = {"sport": "mlb", "market": "moneyline", "team": "Red Sox",
            "opening_implied_prob": _odds_to_implied(-105)}
    assert attach_entry_fair(snap, boards) is True
    assert snap["opening_fair_prob"] == pytest.approx(0.5, abs=1e-6)


def test_attach_entry_fair_total_exact_line_only():
    boards = _FakeBoards([_fake_event()])
    base = {
        "sport": "mlb", "market": "total", "direction": "OVER",
        "opponent": "New York Yankees @ Boston Red Sox",
        "opening_odds": 100, "opening_implied_prob": 0.5,
    }
    hit = dict(base, opening_line=8.5)
    assert attach_entry_fair(hit, boards) is True
    # over best +100 vs under best -110 → fair = .5 / (.5 + .5238)
    assert hit["opening_fair_prob"] == pytest.approx(0.5 / (0.5 + _odds_to_implied(-110)))
    # A different line is a different bet — must NOT attach
    miss = dict(base, opening_line=9.0)
    assert attach_entry_fair(miss, boards) is False
    assert "opening_fair_prob" not in miss


def test_attach_entry_fair_unsupported_market():
    boards = _FakeBoards([_fake_event()])
    snap = {"sport": "mlb", "market": "pitcher_strikeouts", "team": "whoever"}
    assert attach_entry_fair(snap, boards) is False


def test_attach_entry_fair_three_way_draw():
    ev = {
        "home_team": "Arsenal", "away_team": "Chelsea",
        "bookmakers": [{"title": "Pinnacle", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Arsenal", "price": -105},
                {"name": "Chelsea", "price": 260},
                {"name": "Draw", "price": 250},
            ]},
        ]}],
    }
    boards = _FakeBoards([ev])
    snap = {"sport": "soccer_epl", "market": "moneyline", "team": "Arsenal",
            "opening_implied_prob": _odds_to_implied(-105)}
    assert attach_entry_fair(snap, boards) is True
    # 3-way devig must include the draw mass
    assert snap["opening_fair_prob"] == pytest.approx(_devig(-105, 260, 250))
    assert snap["opening_draw_odds"] == 250


# ── metric preference ladder + strategy verdicts ─────────────────────────────

def test_best_prob_clv_prefers_novig_then_raw():
    assert ct._best_prob_clv(
        {"clv_novig_pct": 1.0, "clv_raw_pct": 2.0, "clv_pct": -3.0}) == 1.0
    assert ct._best_prob_clv({"clv_raw_pct": 2.0, "clv_pct": -3.0}) == 2.0
    assert ct._best_prob_clv({"clv_pct": -3.0}) == -3.0
    assert ct._best_prob_clv({}) is None


def test_strategy_verdicts_300_bet_rule():
    assert ct._strategy_verdict(50, 5.0, 80.0).startswith("SHADOW (need")
    assert ct._strategy_verdict(300, 0.8, 55.0).startswith("PROMOTE")
    assert ct._strategy_verdict(300, 0.8, 40.0).startswith("SHADOW")   # outlier-driven
    assert ct._strategy_verdict(300, -1.2, 40.0).startswith("RETIRE")
    assert ct._strategy_verdict(300, -0.1, 48.0).startswith("SHADOW")  # flat


def test_get_clv_by_strategy_uses_ladder(monkeypatch):
    snaps = (
        # devig_ev: novig present and positive — the raw/legacy noise must not leak in
        [{"strategy": "devig_ev", "clv_novig_pct": 1.5,
          "clv_raw_pct": -9.0, "clv_pct": -9.0}] * 4
        # model: legacy only
        + [{"clv_pct": -2.0}] * 2
    )
    monkeypatch.setattr(ct, "_load_snapshots", lambda: snaps)
    out = ct.get_clv_by_strategy()
    assert out["devig_ev"]["avg_clv_pct"] == pytest.approx(1.5)
    assert out["devig_ev"]["avg_clv_novig_pct"] == pytest.approx(1.5)
    assert out["devig_ev"]["beat_close_pct"] == 100.0
    assert out["model"]["avg_clv_pct"] == pytest.approx(-2.0)
    assert "verdict" in out["devig_ev"]


# ── entry-hour / entry-edge / catalyst buckets ───────────────────────────────

def test_get_clv_by_entry_hour(monkeypatch):
    snaps = [
        {"snapshot_time": "2026-07-10T04:30:00+00:00", "clv_novig_pct": 1.0},
        {"snapshot_time": "2026-07-10T05:59:00+00:00", "clv_novig_pct": -0.5},
        {"snapshot_time": "2026-07-10T14:00:00+00:00", "line_clv": 0.5,
         "beat_close": True},
        {"snapshot_time": None, "clv_novig_pct": 99.0},          # no timestamp → dropped
        {"snapshot_time": "2026-07-10T04:00:00+00:00"},          # unscored → dropped
    ]
    monkeypatch.setattr(ct, "_load_snapshots", lambda: snaps)
    out = ct.get_clv_by_entry_hour()
    assert out["03-06"]["n"] == 2
    assert out["03-06"]["avg_prob_clv_pct"] == pytest.approx(0.25)
    assert out["03-06"]["beat_pct"] == 50.0
    assert out["12-15"]["avg_line_clv"] == pytest.approx(0.5)
    assert out["12-15"]["beat_pct"] == 100.0
    assert "09-12" not in out


def test_get_clv_by_entry_edge_bands(monkeypatch):
    snaps = [
        {"entry_ev_vs_fair_pct": 3.0, "clv_novig_pct": 2.0},   # stale opener band
        {"entry_ev_vs_fair_pct": 3.5, "clv_novig_pct": 1.0},
        {"entry_ev_vs_fair_pct": -1.0, "clv_novig_pct": -2.0},  # paid fair or worse
        {"entry_ev_vs_fair_pct": 10.0},                          # no CLV yet → dropped
        {"clv_novig_pct": 5.0},                                  # no entry signal → dropped
    ]
    monkeypatch.setattr(ct, "_load_snapshots", lambda: snaps)
    out = ct.get_clv_by_entry_edge()
    stale = out["2-5% (stale opener)"]
    assert stale["n"] == 2
    assert stale["avg_clv"] == pytest.approx(1.5)
    assert stale["beat_pct"] == 100.0
    assert out["≤0% (paid fair or worse)"]["avg_clv"] == pytest.approx(-2.0)
    assert ">5% (very stale)" not in out


def test_get_clv_by_catalyst_split(monkeypatch):
    snaps = [
        {"catalyst": "weather", "clv_novig_pct": 1.0},
        {"catalyst": "lineup,park", "clv_novig_pct": 3.0},
        {"clv_novig_pct": -1.0},
        {"catalyst": None, "line_clv": -0.5, "beat_close": False},
    ]
    monkeypatch.setattr(ct, "_load_snapshots", lambda: snaps)
    out = ct.get_clv_by_catalyst()
    assert out["catalyst"]["avg_clv"] == pytest.approx(2.0)
    assert out["no_catalyst"]["avg_clv"] == pytest.approx(-1.0)
    assert out["no_catalyst"]["avg_line_clv"] == pytest.approx(-0.5)


def test_derive_catalyst_tags():
    assert ct._derive_catalyst({"weather_context": "wind out 15mph",
                                "model_agreement": True}) == "weather,model_agreement"
    assert ct._derive_catalyst({"strategy": "devig_ev"}) == "stale_opener"
    assert ct._derive_catalyst({"strategy": "devig_ev_totals"}) == "stale_opener"
    assert ct._derive_catalyst({"model_agreement": False}) is None


# ── devig_ev_totals shadow strategy ──────────────────────────────────────────

def _totals_df(commence="2099-01-01T00:00:00Z"):
    rows = [
        # Pinnacle -110/-110 at 9.0 → fair over = 0.5
        {"GameID": "g1", "HomeTeam": "Reds", "AwayTeam": "Cubs",
         "Sportsbook": "Pinnacle", "OverOdds": -110, "UnderOdds": -110,
         "Total": 9.0, "CommenceTime": commence},
        # Soft book at the SAME line, over +115 → EV = .5/.4651 - 1 = +7.5%
        {"GameID": "g1", "HomeTeam": "Reds", "AwayTeam": "Cubs",
         "Sportsbook": "DraftKings", "OverOdds": 115, "UnderOdds": -125,
         "Total": 9.0, "CommenceTime": commence},
        # Different line (8.5): looks like huge EV but is a DIFFERENT bet — excluded
        {"GameID": "g1", "HomeTeam": "Reds", "AwayTeam": "Cubs",
         "Sportsbook": "FanDuel", "OverOdds": 150, "UnderOdds": -170,
         "Total": 8.5, "CommenceTime": commence},
    ]
    return pd.DataFrame(rows)


def test_devig_ev_totals_emits_stale_over():
    from src.strategies.shadow_strategies import devig_ev_totals
    picks = devig_ev_totals(_totals_df(), "baseball_mlb")
    assert len(picks) == 1
    p = picks[0]
    assert p["market"] == "total"
    assert p["direction"] == "OVER"
    assert p["line"] == 9.0
    assert p["odds"] == 115           # same-line best, NOT the 8.5 +150
    assert p["sportsbook"] == "DraftKings"
    assert p["edge_pct"] == pytest.approx(7.5, abs=0.1)
    assert p["model_prob"] == pytest.approx(0.5)


def test_devig_ev_totals_skips_started_games():
    from src.strategies.shadow_strategies import devig_ev_totals
    picks = devig_ev_totals(_totals_df(commence="2020-01-01T00:00:00Z"),
                            "baseball_mlb")
    assert picks == []


def test_devig_ev_totals_no_fair_line_no_picks():
    from src.strategies.shadow_strategies import devig_ev_totals
    df = _totals_df()
    df["Total"] = float("nan")
    assert devig_ev_totals(df, "baseball_mlb") == []


def test_devig_ev_totals_registered():
    from src.strategies.shadow_strategies import STRATEGIES
    assert "devig_ev_totals" in STRATEGIES
