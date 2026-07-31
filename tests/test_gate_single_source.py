"""One promotion gate, one answer, every surface.

THE BUG. The scoreboard printed '✅ READY — clears gate, EV proven' for
usa_mls/moneyline while `chef.py promote usa_mls moneyline` refused the same
lane. Three gate implementations had accreted: model_standard.
clears_promotion_gate (the documented one), cmd_promote's pre-rework
200-snapshot CLV rule, and the scoreboard's inline partial copy — which
skipped the independence check, the exact check usa_mls fails (46 rows from 4
days, 63% on one). A green checkmark the real gate contradicts is worse than
no scoreboard: someone bets on it.

Same disease, same cure as `models._key`: decide in ONE place, delegate
everywhere, and pin it with tests that fail when a copy grows back.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import chef


def _ev(n=46, mean=13.0, significant=True, n_needed=None, t=2.3):
    return SimpleNamespace(n=n, mean_ev_pct=mean, significant=significant,
                           n_needed=n_needed, t=t)


def _gate(monkeypatch, ok: bool, why: str):
    calls: list[tuple] = []

    def fake(sport, market):
        calls.append((sport, market))
        return ok, why
    # Both call sites import lazily from the source module, so patch the source.
    monkeypatch.setattr("src.config.model_standard.clears_promotion_gate", fake)
    return calls


# ── the scoreboard verdict ───────────────────────────────────────────────────
def test_ready_requires_the_real_gate(monkeypatch):
    """The exact shape of the bug: a lane that passes every LOCAL pre-check
    (EV floor, ROI, n, even 'significant') but fails the gate's independence
    check must not read READY — it must print the gate's own reason."""
    calls = _gate(monkeypatch, False,
                  "EV +13.00% on n=46 but only 4 distinct day(s) — clustered")
    v = chef._scoreboard_verdict("incubating", _ev(), True,
                                 "usa_mls", "moneyline", 30, 1.0)
    assert "READY" not in v
    assert "4 distinct" in v, "the gate's reason must surface, not a local guess"
    assert calls == [("usa_mls", "moneyline")]


def test_ready_when_the_gate_passes(monkeypatch):
    _gate(monkeypatch, True, "EV +3.02% on n=215, ROI +8.9%, t=+3.38 SIGNIFICANT")
    v = chef._scoreboard_verdict("incubating", _ev(n=215, mean=3.0), True,
                                 "mlb", "total", 30, 1.0)
    assert "READY" in v


def test_lanes_failing_local_prechecks_never_pay_for_a_gate_call(monkeypatch):
    """The pre-checks are a strict subset of the gate, so a local fail is
    final — and the gate must not be called for it (it is expensive per lane)."""
    calls = _gate(monkeypatch, True, "should never be consulted")
    v1 = chef._scoreboard_verdict("incubating", _ev(n=5), True, "x", "y", 30, 1.0)
    v2 = chef._scoreboard_verdict("incubating", _ev(mean=-2.0), True, "x", "y", 30, 1.0)
    v3 = chef._scoreboard_verdict("incubating", _ev(), False, "x", "y", 30, 1.0)
    assert "building" in v1 and "negative EV" in v2 and "ROI" in v3
    assert calls == [], "no READY candidate, no gate call"


def test_live_and_paused_states_bypass_the_gate(monkeypatch):
    calls = _gate(monkeypatch, False, "irrelevant")
    assert "promoted" in chef._scoreboard_verdict("live", None, False, "x", "y", 30, 1.0)
    assert "held" in chef._scoreboard_verdict("paused", None, False, "x", "y", 30, 1.0)
    assert calls == []


# ── the promote command ──────────────────────────────────────────────────────
def _promote_args(sport="usa_mls", market="moneyline"):
    return SimpleNamespace(sport=sport, market=market, tier=None, min_n=None)


def test_promote_refuses_when_the_gate_refuses(monkeypatch, capsys):
    _gate(monkeypatch, False, "only 4 distinct day(s) — clustered")
    writes: list = []
    monkeypatch.setattr("src.config.models.set_promotion",
                        lambda *a, **k: writes.append(a))
    rc = chef.cmd_promote(_promote_args())
    out = capsys.readouterr().out
    assert rc == 1
    assert "REFUSED" in out and "4 distinct" in out
    assert writes == [], "a refused promotion must write nothing"


def test_promote_promotes_when_the_gate_passes(monkeypatch, capsys):
    _gate(monkeypatch, True, "EV +9.99% on n=99, ROI +5.0%, t=+2.50 SIGNIFICANT")
    writes: list = []
    monkeypatch.setattr("src.config.models.set_promotion",
                        lambda *a, **k: writes.append((a, k)))
    rc = chef.cmd_promote(_promote_args())
    out = capsys.readouterr().out
    assert rc == 0
    assert "PROMOTED" in out
    assert len(writes) == 1
    _a, kw = writes[0]
    assert "EV +9.99%" in kw["evidence"]["gate"], \
        "the gate's summary line is the recorded evidence"


def test_promote_and_scoreboard_share_one_gate(monkeypatch, capsys):
    """The invariant itself: with the gate forced to one answer, both surfaces
    must give that answer. This is what was false before the fix."""
    _gate(monkeypatch, False, "clustered sample — refused by THE gate")
    monkeypatch.setattr("src.config.models.set_promotion",
                        lambda *a, **k: pytest.fail("must not promote"))
    rc = chef.cmd_promote(_promote_args())
    v = chef._scoreboard_verdict("incubating", _ev(), True,
                                 "usa_mls", "moneyline", 30, 1.0)
    assert rc == 1
    assert "READY" not in v
    assert "refused by THE gate" in v
    assert "refused by THE gate" in capsys.readouterr().out
