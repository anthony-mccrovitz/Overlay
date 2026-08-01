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


# ── the auto-promoter (the surface this test file missed) ────────────────────
def test_auto_promoter_delegates_to_the_gate(monkeypatch):
    """The third copy, found 2026-08-01.

    src/pipeline/promoter.py carried the PRE-2026-07-30 criterion — beat-close
    >= 55%, positive sharp mean, ROI on n>=30 — with no EV floor and no
    independence check. `--apply` writes status=live to promotions.json, which
    the registry reads, which makes that lane's picks card_pick=True. So the
    divergence was not cosmetic like the scoreboard's: it could spend money on
    a lane `chef.py promote` refuses.

    This file existed and still missed it, because it only knew about the two
    surfaces that had already bitten. Hence: assert the DELEGATION, not just
    the agreement of the surfaces we happen to remember.
    """
    from src.pipeline import promoter

    calls = _gate(monkeypatch, False, "clustered sample — refused by THE gate")
    st = SimpleNamespace(roi=25.0, n=500, pnl=125.0)   # gaudy ROI, big sample
    row = {"is_candidate": True, "sharp_mean": 2.5, "sharp_beat_pct": 71.0,
           "mean": 2.5, "n": 500}                      # and it beats the close

    rec, why = promoter._decide("incubating", row, st, "usa_mls", "moneyline")

    assert calls == [("usa_mls", "moneyline")], \
        "the promoter decided without asking the gate"
    assert rec == "incubating", \
        "promoter promoted a lane THE gate refuses — the divergence is back"
    assert "refused by THE gate" in why


def test_auto_promoter_promotes_when_the_gate_passes(monkeypatch):
    """The other direction: delegation must not become a blanket refusal."""
    from src.pipeline import promoter

    _gate(monkeypatch, True, "EV +4.10% on n=216, ROI +9.0%, t=+3.49 SIGNIFICANT")
    st = SimpleNamespace(roi=9.0, n=216, pnl=19.4)
    rec, why = promoter._decide("incubating", {"is_candidate": True}, st,
                                "mlb", "total")
    assert rec == "live"
    assert "EV +4.10%" in why


def test_promoter_carries_no_private_promotion_thresholds():
    """Structural: promotion constants in this module are how the copy grew
    back last time. Demotion keeps its own (it only removes risk)."""
    import inspect
    from src.pipeline import promoter

    code = "\n".join(line.split("#", 1)[0]
                     for line in inspect.getsource(promoter).splitlines())
    for banned in ("PROMOTE_BEAT_MIN", "PROMOTE_ROI_MIN_N"):
        assert banned not in code, (
            f"{banned} is back in promoter.py — promotion thresholds belong to "
            "model_standard, which is the only module allowed to decide")
