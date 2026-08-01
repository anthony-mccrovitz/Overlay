"""Three ways the evidence base was quietly corrupting itself.

The gate that decides whether a lane bets real money reads three things: the
entry price, the set of picks, and the closing line. Each had a defect that
made the record LOOK complete while being wrong, and none of the three raised
so much as a warning.

  1. A pick with no captured price was snapshotted at implied 0.5 — even money,
     a price nobody quoted — because `_odds_to_implied(0)` returns 0.5. 467 such
     rows, 86 with an invented clv_ev_pct averaging +5.37%, enough to flip
     mlb/moneyline from −0.36% to +0.07% and read as an edge.
  2. `pick_id` did not identify the GAME, so two games sharing a total line
     deduped each other away: 90 picks lost (64 totals, 26 moneylines), on the
     lane betting real money.
  3. A mid-run 401 made the odds client return a stale cached board, which
     capture then archived with closing_final=True — a pre-game price recorded
     forever as the close.

The shared lesson, and why these are one file: each bug produced a plausible
number instead of an error. Absent evidence must read as absent.
"""
from __future__ import annotations

import json

import pytest

from src.tracking.schema import append_picks_safe, make_pick_id, _game_slug


# ── 1. no entry price → no snapshot ─────────────────────────────────────────
def test_pick_without_a_price_is_not_snapshotted(tmp_path, monkeypatch, capsys):
    """A snapshot's whole purpose is entry-vs-close. With no entry there is
    nothing to compare, and 0.5 is a fabrication, not a fallback."""
    from src.analytics import clv_tracker

    from datetime import date as _date

    picks_file = tmp_path / "picks.json"
    picks_file.write_text(json.dumps([
        {"team": "Priced Team", "odds": -110, "market": "moneyline",
         "matchup": "A @ Priced Team", "sport": "mlb"},
        {"team": "Unpriced Team", "odds": 0, "market": "moneyline",
         "matchup": "B @ Unpriced Team", "sport": "mlb"},
    ]))

    monkeypatch.setattr(clv_tracker, "_load_snapshots", lambda: [])
    saved: list = []
    monkeypatch.setattr(clv_tracker, "_save_snapshots", lambda s: saved.extend(s))

    n = clv_tracker.snapshot_opening_lines(picks_file, "baseball_mlb",
                                           _date(2026, 8, 1))

    teams = {s["team"] for s in saved}
    assert "Priced Team" in teams
    assert "Unpriced Team" not in teams, \
        "a pick with no price was snapshotted — at implied 0.5, a made-up number"
    assert n == 1
    # And the gap must be REPORTED. A silent skip is the same disease.
    assert "no entry price" in capsys.readouterr().out


def test_fabricated_half_price_rows_are_refused_as_lane_evidence():
    """The 467 rows already on disk cannot be unwritten, so the READ side has
    to reject them: a row with no opening_odds never counts toward a lane."""
    from src.analytics.ev_gate import _usable_ev

    good = {"clv_ev_pct": 2.0, "opening_odds": -110,
            "opening_implied_prob": 0.524, "closing_implied_prob": 0.540}
    fabricated = {"clv_ev_pct": 5.37, "opening_odds": 0,
                  "opening_implied_prob": 0.5, "closing_implied_prob": 0.54}

    assert _usable_ev(good) == pytest.approx(2.0)
    assert _usable_ev(fabricated) is None, \
        "an invented even-money entry price still counts as evidence"


# ── 2. pick_id must identify the game ───────────────────────────────────────
def test_two_games_with_the_same_total_line_get_different_ids():
    a = make_pick_id("mlb", "2026-08-01", "OVER 7.5", "total", "over",
                     game="Texas Rangers @ Houston Astros")
    b = make_pick_id("mlb", "2026-08-01", "OVER 7.5", "total", "over",
                     game="Chicago Cubs @ San Diego Padres")
    assert a != b, "two different games share one pick_id — one will be dropped"


def test_same_city_teams_do_not_collapse():
    """A city-only slug would make Yankees and Mets the same game."""
    assert _game_slug("New York Yankees @ Chicago Cubs") != \
           _game_slug("New York Mets @ Chicago Cubs")
    assert _game_slug("Chicago White Sox @ Detroit Tigers") != \
           _game_slug("Chicago Cubs @ Detroit Tigers")


def test_doubleheader_moneylines_both_survive(tmp_path):
    """Two games, same team, same day — the classic silent drop."""
    ledger = tmp_path / "picks.json"
    ledger.write_text(json.dumps({"picks": []}))

    def pick(matchup):
        return {"date": "2026-08-01", "sport": "mlb", "market": "total",
                "direction": "OVER", "team": "OVER 7.5", "line": 7.5,
                "matchup": matchup, "odds": -110, "stake": 1.0,
                "card_pick": False, "result": None}

    added = append_picks_safe(ledger, [pick("Texas Rangers @ Houston Astros"),
                                       pick("Chicago Cubs @ San Diego Padres")])
    rows = json.loads(ledger.read_text())["picks"]
    assert added == 2 and len(rows) == 2, \
        "the second game was silently discarded as a duplicate"


def test_relogging_the_same_bet_is_still_deduped(tmp_path):
    """The fix must not turn idempotent re-logging into duplicate rows."""
    ledger = tmp_path / "picks.json"
    ledger.write_text(json.dumps({"picks": []}))
    p = {"date": "2026-08-01", "sport": "mlb", "market": "total",
         "direction": "OVER", "team": "OVER 7.5", "line": 7.5,
         "matchup": "Texas Rangers @ Houston Astros", "odds": -110,
         "stake": 1.0, "card_pick": False, "result": None}

    assert append_picks_safe(ledger, [p]) == 1
    assert append_picks_safe(ledger, [dict(p)]) == 0
    assert len(json.loads(ledger.read_text())["picks"]) == 1


def test_a_real_collision_is_reported_not_swallowed(tmp_path, capsys):
    """Legacy ids (minted before the game qualifier) can still collide. When
    they do, it is data loss and must print — silence is what let 90 picks
    disappear unnoticed."""
    ledger = tmp_path / "picks.json"
    ledger.write_text(json.dumps({"picks": []}))

    def legacy(matchup):
        return {"pick_id": "mlb_20260801_over-7-5_total_over",   # pre-fix id
                "date": "2026-08-01", "sport": "mlb", "market": "total",
                "direction": "OVER", "team": "OVER 7.5", "line": 7.5,
                "matchup": matchup, "odds": -110, "stake": 1.0,
                "card_pick": False, "result": None}

    append_picks_safe(ledger, [legacy("Texas Rangers @ Houston Astros")])
    capsys.readouterr()
    append_picks_safe(ledger, [legacy("Chicago Cubs @ San Diego Padres")])

    out = capsys.readouterr().out
    assert "DROPPED" in out and "collision" in out.lower(), \
        "a pick was dropped for a different game with no warning"


# ── 3. a quota failure is not a board ───────────────────────────────────────
def test_quota_failure_raises_instead_of_serving_a_stale_board(tmp_path, monkeypatch):
    """THE ARCHIVE BUG. capture_closing calls fetch_event_odds twice per event
    with the same markets string, so both share one cache file: the pre-game
    call writes it, and the closing call (refresh=True) would get a 401,
    silently receive that ~70-minute-old board, and archive it as the close.
    """
    from src.data import odds_api
    from src.data.odds_api import OddsAPIUnavailable

    cache = tmp_path / "cached_board.json"
    cache.write_text(json.dumps({"bookmakers": [], "id": "evt1"}))
    monkeypatch.setattr(odds_api, "_cache_path", lambda *a, **k: cache)
    monkeypatch.setattr(odds_api, "_get_api_key", lambda: "key")

    class Resp:
        status_code = 401
        def json(self): return {}
        def raise_for_status(self): raise AssertionError("should not reach")

    monkeypatch.setattr(odds_api.requests, "get", lambda *a, **k: Resp())

    with pytest.raises(OddsAPIUnavailable):
        odds_api.fetch_event_odds(event_id="evt1", sport="baseball_mlb",
                                  markets="h2h", refresh=True)


def test_event_gone_from_the_board_is_still_an_ordinary_empty_answer(tmp_path, monkeypatch):
    """404 means the event is finished/postponed/never priced — a real answer,
    not an outage. It must NOT fail the capture run."""
    from src.data import odds_api

    cache = tmp_path / "c.json"
    monkeypatch.setattr(odds_api, "_cache_path", lambda *a, **k: cache)
    monkeypatch.setattr(odds_api, "_get_api_key", lambda: "key")

    class Resp:
        status_code = 404
        def json(self): return {}
        def raise_for_status(self): raise AssertionError("should not reach")

    monkeypatch.setattr(odds_api.requests, "get", lambda *a, **k: Resp())
    df = odds_api.fetch_event_odds(event_id="evt1", sport="baseball_mlb",
                                   markets="h2h", refresh=True)
    assert df.empty
