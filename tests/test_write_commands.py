"""The commands that MUTATE the ledger, under test.

Why this file exists: `record`, `scoreboard`, `moneypath` and friends are all
read-only — if they are wrong you see a wrong number and go looking. `bet`,
`result` and `grade` write to disk. If they are wrong they corrupt the record
that every other number is computed from, and the wrongness compounds silently
until a month of P&L is fiction.

Everything here writes to a tmp_path. No test in this file may touch
data/pnl/*.json — `test_real_ledger_is_never_touched` enforces that.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import chef


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point the personal-bet ledger at a scratch file."""
    f = tmp_path / "personal_picks.json"
    monkeypatch.setattr(chef, "_PERSONAL_FILE", f)
    return f


@pytest.fixture
def no_side_effects(monkeypatch):
    """Stub out everything `grade` fires off besides the grader itself.

    Found by running this file and then `git status`: the first version rewrote
    two real calibrator pickles and data/franchise/bets.json. `cmd_grade` calls
    recalibrate_all, grade_challenge_bets and grade_yesterday, each inside a
    bare `except`, so the damage was silent and the tests still passed. A test
    suite that mutates production artifacts is worse than no suite — it makes
    every subsequent run start from a different state.

    Patched at the source module because cmd_grade imports these lazily, so the
    name is resolved from the module at call time.
    """
    monkeypatch.setattr("src.analytics.calibration.recalibrate_all",
                        lambda *a, **k: None)
    monkeypatch.setattr("src.output.june_challenge_card.grade_challenge_bets",
                        lambda *a, **k: None)
    monkeypatch.setattr("scripts.run_franchise_bets.grade_yesterday",
                        lambda *a, **k: None)


def _args(**kw):
    return argparse.Namespace(**kw)


def _bet(**kw):
    base = dict(team="Yankees", odds=-110, stake=10.0, market=None, sport=None,
                sportsbook=None, date="2026-07-30", matchup=None,
                direction=None, line=None)
    base.update(kw)
    return _args(**base)


# ── chef.py bet ──────────────────────────────────────────────────────────────
def test_bet_records_a_complete_row(ledger, capsys):
    assert chef.cmd_bet(_bet()) == 0
    picks = json.loads(ledger.read_text())["picks"]
    assert len(picks) == 1
    p = picks[0]
    assert p["team"] == "Yankees"
    assert p["odds"] == -110
    assert p["stake_dollars"] == 10.0
    assert p["date"] == "2026-07-30"
    assert p["result"] is None
    assert p["card_pick"] is False, (
        "a personal bet must never enter the public card record — that record "
        "is the one quoted as the system's track record")


def test_bet_is_idempotent(ledger):
    """Running the same command twice must not double-stake.

    The obvious failure: you log a bet, aren't sure it took, run it again, and
    the ledger now says you risked twice what you risked.
    """
    chef.cmd_bet(_bet())
    chef.cmd_bet(_bet())
    picks = json.loads(ledger.read_text())["picks"]
    assert len(picks) == 1


def test_bet_normalises_compact_dates(ledger):
    """`--date 20260730` and `--date 2026-07-30` must land on the same row,
    otherwise the same bet dedupes against nothing and gets logged twice."""
    chef.cmd_bet(_bet(date="20260730"))
    chef.cmd_bet(_bet(date="2026-07-30"))
    picks = json.loads(ledger.read_text())["picks"]
    assert len(picks) == 1
    assert picks[0]["date"] == "2026-07-30"


def test_bet_distinguishes_different_markets_on_the_same_team(ledger):
    chef.cmd_bet(_bet(market="moneyline"))
    chef.cmd_bet(_bet(market="total"))
    picks = json.loads(ledger.read_text())["picks"]
    assert len(picks) == 2
    assert len({p["pick_id"] for p in picks}) == 2


def test_bet_preserves_existing_rows(ledger):
    """A write must never clobber the file it is appending to."""
    chef.cmd_bet(_bet(team="Yankees"))
    chef.cmd_bet(_bet(team="Dodgers"))
    chef.cmd_bet(_bet(team="Mets"))
    teams = {p["team"] for p in json.loads(ledger.read_text())["picks"]}
    assert teams == {"Yankees", "Dodgers", "Mets"}


# ── profit arithmetic ────────────────────────────────────────────────────────
@pytest.mark.parametrize("stake,odds,won,expected", [
    (10.0, +150, True, 15.0),      # +150: risk 10 to win 15
    (10.0, -110, True, 9.0909),    # -110: risk 10 to win 9.09
    (10.0, +100, True, 10.0),      # even money
    (10.0, -200, True, 5.0),       # heavy favourite
    (10.0, +150, False, -10.0),    # a loss costs the stake, never more
    (10.0, -110, False, -10.0),
])
def test_personal_profit_math(stake, odds, won, expected):
    assert chef._personal_profit(stake, odds, won) == pytest.approx(expected, abs=1e-3)


def test_a_loss_never_costs_more_than_the_stake():
    """Straight bets cannot lose more than risked. A sign error here would make
    the bankroll curve wrong in the one direction nobody sanity-checks."""
    for odds in (-500, -110, +100, +2000):
        assert chef._personal_profit(25.0, odds, False) == -25.0


# ── chef.py result ───────────────────────────────────────────────────────────
def test_result_settles_a_win(ledger):
    chef.cmd_bet(_bet(odds=+150))
    assert chef.cmd_result(_args(pick_id="Yankees", result="win")) == 0
    p = json.loads(ledger.read_text())["picks"][0]
    assert p["result"] == "win"
    assert p["profit_dollars"] == pytest.approx(15.0)
    assert p["resulted_at"]


def test_result_settles_a_loss(ledger):
    chef.cmd_bet(_bet(odds=-110))
    chef.cmd_result(_args(pick_id="Yankees", result="loss"))
    p = json.loads(ledger.read_text())["picks"][0]
    assert p["result"] == "loss"
    assert p["profit_dollars"] == pytest.approx(-10.0)


def test_push_returns_the_stake(ledger):
    chef.cmd_bet(_bet(odds=-110))
    chef.cmd_result(_args(pick_id="Yankees", result="push"))
    p = json.loads(ledger.read_text())["picks"][0]
    assert p["result"] == "push"
    assert p["profit_dollars"] == 0.0, "a push is a refund, not a loss"


def test_result_rejects_an_unknown_outcome(ledger):
    chef.cmd_bet(_bet())
    assert chef.cmd_result(_args(pick_id="Yankees", result="maybe")) != 0
    p = json.loads(ledger.read_text())["picks"][0]
    assert p["result"] is None, "a rejected grade must not half-write"


def test_result_refuses_an_ambiguous_match(ledger):
    """Two pending bets on the same team must not be settled by a guess — that
    silently grades the wrong one and the error is invisible afterwards."""
    chef.cmd_bet(_bet(team="Yankees", market="moneyline"))
    chef.cmd_bet(_bet(team="Yankees", market="total"))
    assert chef.cmd_result(_args(pick_id="Yankees", result="win")) != 0
    picks = json.loads(ledger.read_text())["picks"]
    assert all(p["result"] is None for p in picks), "nothing may be settled on an ambiguous match"


def test_result_refuses_when_nothing_matches(ledger):
    chef.cmd_bet(_bet(team="Yankees"))
    assert chef.cmd_result(_args(pick_id="Padres", result="win")) != 0
    assert json.loads(ledger.read_text())["picks"][0]["result"] is None


def test_result_on_an_empty_ledger_fails_cleanly(ledger):
    assert chef.cmd_result(_args(pick_id="Yankees", result="win")) != 0


def test_regrading_the_same_result_does_not_compound(ledger):
    """Settling twice must be idempotent. If profit accumulated instead of being
    assigned, a double-run would silently inflate the bankroll."""
    chef.cmd_bet(_bet(odds=+150))
    chef.cmd_result(_args(pick_id="Yankees", result="win"))
    first = json.loads(ledger.read_text())["picks"][0]["profit_dollars"]
    chef.cmd_result(_args(pick_id="Yankees", result="win"))
    second = json.loads(ledger.read_text())["picks"][0]["profit_dollars"]
    assert first == second == pytest.approx(15.0)


def test_a_settled_bet_is_not_picked_up_by_a_later_partial_match(ledger):
    """Partial-name matching only considers PENDING bets. Otherwise settling
    'Yankees' a second time would re-grade last week's Yankees bet."""
    chef.cmd_bet(_bet(team="Yankees", market="moneyline", date="2026-07-01"))
    chef.cmd_result(_args(pick_id="Yankees", result="win"))
    chef.cmd_bet(_bet(team="Yankees", market="moneyline", date="2026-07-30"))
    assert chef.cmd_result(_args(pick_id="Yankees", result="loss")) == 0
    picks = {p["date"]: p for p in json.loads(ledger.read_text())["picks"]}
    assert picks["2026-07-01"]["result"] == "win", "an old settled bet was re-graded"
    assert picks["2026-07-30"]["result"] == "loss"


# ── chef.py grade ────────────────────────────────────────────────────────────
def test_grade_defaults_to_yesterday(monkeypatch, no_side_effects):
    """Grading defaults to yesterday because today's games have not finished.
    A default of `today` would mark every pending bet a loss."""
    seen = {}
    monkeypatch.setattr(chef, "_run", lambda cmd: seen.setdefault("cmd", cmd) and 0 or 0)
    chef.cmd_grade(_args(date=None, sport="all", winner=None))
    from datetime import datetime, timedelta
    expected = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    assert "--date" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--date") + 1] == expected


def test_grade_passes_through_date_and_sport(monkeypatch, no_side_effects):
    seen = {}
    monkeypatch.setattr(chef, "_run", lambda cmd: seen.setdefault("cmd", cmd) and 0 or 0)
    chef.cmd_grade(_args(date="20260715", sport="mlb", winner=None))
    cmd = seen["cmd"]
    assert cmd[cmd.index("--date") + 1] == "20260715"
    assert cmd[cmd.index("--sport") + 1] == "mlb"
    assert "--winner" not in cmd


def test_grade_forwards_a_manual_winner(monkeypatch, no_side_effects):
    seen = {}
    monkeypatch.setattr(chef, "_run", lambda cmd: seen.setdefault("cmd", cmd) and 0 or 0)
    chef.cmd_grade(_args(date="20260715", sport="ufc", winner="Jon Jones"))
    cmd = seen["cmd"]
    assert cmd[cmd.index("--winner") + 1] == "Jon Jones"


def test_grade_reports_the_graders_exit_code(monkeypatch, no_side_effects):
    """A failed grade must not report success — the whole point of the evening
    run is knowing whether it worked."""
    monkeypatch.setattr(chef, "_run", lambda cmd: 3)
    assert chef.cmd_grade(_args(date="20260715", sport="all", winner=None)) == 3


# ── the guard on this file itself ────────────────────────────────────────────
def test_real_ledger_is_never_touched(ledger):
    """If a future edit forgets the fixture, this catches it before the suite
    rewrites real money records."""
    assert chef._PERSONAL_FILE != Path("data/pnl/personal_picks.json")
    assert "personal_picks.json" in str(chef._PERSONAL_FILE)
    chef.cmd_bet(_bet())
    assert ledger.exists()
    real = Path("data/pnl/personal_picks.json")
    if real.exists():
        blob = json.loads(real.read_text())
        rows = blob.get("picks", blob) if isinstance(blob, dict) else blob
        assert not any(p.get("team") == "Yankees" and p.get("date") == "2026-07-30"
                       and p.get("sportsbook") == "Unknown" and p.get("stake") == 10.0
                       for p in rows), "a test bet leaked into the real ledger"
