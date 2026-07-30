"""One quota check, and acknowledgements that expire.

Two fixes for the same root problem: an alarm nobody can act on stops being read.

QUOTA. One exhausted key produced seven red runs across three workflows on
2026-07-30, each showing a different symptom — capture exited 0 having archived
nothing, odds_snapshot died on a raw 401 traceback, market-scan printed a clear
message. The check now lives in one module so every credit-spending script
reports the same cause the same way.

ACKNOWLEDGEMENTS. The monitor had four findings whose code fixes had ALREADY
landed and which could not clear for two weeks, because the gate measures a 14-day
settled window. Left alone it would have been red every day while nothing was
wrong and nothing could be done — the same place twelve unread red days came
from, reached from the opposite direction. Acknowledged gaps are still PRINTED;
they just don't turn the run red, and they EXPIRE.
"""
from datetime import date, timedelta

import pytest

import chef
from src.data.quota import preflight_quota, LOW_WATER


class _Resp:
    def __init__(self, remaining=None, status=200, text=""):
        self.status_code, self.text = status, text
        self.ok = status == 200
        self.headers = {} if remaining is None else {"x-requests-remaining": str(remaining)}

    def json(self):
        return []


def _patch(monkeypatch, resp):
    import requests
    monkeypatch.setenv("ODDS_API_KEY", "k")
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp)


def test_exhausted_quota_blocks(monkeypatch):
    _patch(monkeypatch, _Resp(remaining=0))
    ok, why = preflight_quota(log=lambda *a: None)
    assert not ok and "EXHAUSTED" in why


def test_rejected_key_blocks(monkeypatch):
    _patch(monkeypatch, _Resp(status=401, text="unauthorized"))
    ok, _ = preflight_quota(log=lambda *a: None)
    assert not ok


def test_healthy_quota_proceeds(monkeypatch):
    _patch(monkeypatch, _Resp(remaining=5000))
    ok, _ = preflight_quota(log=lambda *a: None)
    assert ok


def test_low_quota_warns_but_proceeds(monkeypatch):
    """A thin budget is a warning, not a stop — a partial slate beats none."""
    _patch(monkeypatch, _Resp(remaining=LOW_WATER - 1))
    msgs = []
    ok, _ = preflight_quota(log=msgs.append)
    assert ok and any("remaining" in m for m in msgs)


def test_network_failure_does_not_block(monkeypatch):
    """An unreachable preflight must not stop a run that might otherwise work."""
    import requests
    monkeypatch.setenv("ODDS_API_KEY", "k")
    def boom(*a, **k):
        raise ConnectionError("dns")
    monkeypatch.setattr(requests, "get", boom)
    ok, _ = preflight_quota(log=lambda *a: None)
    assert ok


def test_capture_delegates_rather_than_copying():
    """capture_closing must not carry its own copy — that divergence is what
    made one root cause look like three different failures."""
    import inspect
    from scripts import capture_closing as cc
    src = inspect.getsource(cc._preflight_quota)
    assert "src.data.quota" in src
    assert "x-requests-remaining" not in src, "re-implemented the check locally"


# ── acknowledgements ────────────────────────────────────────────────────────

def test_live_acknowledgement_suppresses_red():
    today = date(2026, 8, 1)
    assert chef._ack("capture", "brazil_campeonato", today) is not None


def test_expired_acknowledgement_stops_suppressing():
    """The escape hatch must not become permanent cover."""
    today = date(2027, 1, 1)
    assert chef._ack("capture", "brazil_campeonato", today) is None


def test_every_acknowledgement_has_a_reason_and_an_expiry():
    for key, rec in chef.ACKNOWLEDGED_GAPS.items():
        assert rec.get("why"), f"{key} has no stated reason"
        assert rec.get("expires"), f"{key} never expires — that is permanent cover"
        assert rec.get("since"), f"{key} is undated"
        assert len(rec["why"]) > 40, f"{key}'s reason is too thin to audit"


def test_acknowledgements_are_not_open_ended():
    """Nothing may be acknowledged more than ~90 days out. An acknowledgement is
    a wait for data, not a decision to stop looking."""
    for key, rec in chef.ACKNOWLEDGED_GAPS.items():
        span = (date.fromisoformat(rec["expires"]) - date.fromisoformat(rec["since"])).days
        assert 0 < span <= 90, f"{key} acknowledged for {span}d — too long to be a wait"


def test_unknown_gap_is_not_acknowledged():
    assert chef._ack("capture", "some_new_league", date(2026, 8, 1)) is None
