"""The alarm must be loud when blind, and silent when there is nothing wrong.

Two failure modes, opposite in shape, that both end with the pipeline unwatched:

  1. GREEN WHEN BLIND. `chef.py monitor` exited 0 whenever it could not reach the
     Odds API — a missing key, a blown quota or an upstream outage rendered as
     "✓ ALL GREEN — every in-season market producing". The one state where you
     know nothing looked exactly like the state where everything is fine.

  2. RED WHEN FINE. The monitor demanded daily output from lanes we had
     deliberately RETIRED (mlb/pitcher_strikeouts, nhl/puck_line) and treated the
     Odds API's `active` flag as "in season" — which flags icehockey_nhl in July,
     two months before its first game. Every day it reported four or five gaps
     that were not gaps. Noise on that scale is worse than no alarm, because it
     trains you to skim past the real one sitting in the same list.

The delivery bug those alarms died in is covered by the alert canary; this file
covers the verdict itself.
"""
import argparse
import importlib
from datetime import date, timedelta

import pytest

chef = importlib.import_module("chef")


def _run(monkeypatch, **env):
    """Run the monitor with a controlled environment; return (exit_code, text)."""
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    lines: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(map(str, a))))
    code = chef.cmd_monitor(argparse.Namespace(soft=False))
    return code, "\n".join(lines)


def test_unknown_alone_makes_the_run_red(monkeypatch):
    """The decision rule, isolated: zero gaps + one blind spot must still be RED.

    Tested against a stubbed _monitor_run rather than the live record, because
    the real repo almost always has SOME gap — which means an end-to-end
    assertion on the exit code passes whether or not `unknown` is honoured, and
    would sail straight past a revert of this very rule.
    """
    monkeypatch.setattr(chef, "_monitor_run",
                        lambda emit=print: (0, ["could not reach the Odds API"]))
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert chef.cmd_monitor(argparse.Namespace(soft=False)) != 0, (
        "monitor exited 0 with zero gaps but an unrunnable check — "
        "a blind alarm is not an all-clear"
    )


def test_clean_run_is_still_green(monkeypatch):
    """The converse: no gaps and no blind spots must NOT be red."""
    monkeypatch.setattr(chef, "_monitor_run", lambda emit=print: (0, []))
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert chef.cmd_monitor(argparse.Namespace(soft=False)) == 0


def test_missing_api_key_is_reported_as_unrunnable(monkeypatch):
    """End-to-end: no key must produce an explicit UNKNOWN, never a green tick."""
    code, out = _run(monkeypatch, ODDS_API_KEY=None)
    assert "COULD NOT BE RUN" in out
    assert "ALL GREEN" not in out, "reported ALL GREEN without being able to check anything"
    assert code != 0


def test_soft_flag_still_suppresses_exit_code(monkeypatch):
    """--soft stays report-only, so local/manual runs don't fail a shell."""
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert chef.cmd_monitor(argparse.Namespace(soft=True)) == 0


class _FakeResp:
    def __init__(self, payload, status=200, remaining="5000"):
        self._p, self.status_code, self.ok = payload, status, status == 200
        # The monitor reads the credit header to detect an exhausted quota, so a
        # stub without one makes every call look broken and silently collapses
        # these tests into "nothing was evaluated" — vacuously green.
        self.headers = {"x-requests-remaining": remaining}

    def json(self):
        return self._p


def _fake_odds_api(monkeypatch):
    """Simulate the Odds API: MLB playing tomorrow, NHL's next game 60 days out.

    Needed because with no API key the monitor evaluates NO lane at all, so any
    assertion about which lanes it complains about is vacuously true — that is
    exactly how the first version of the retired-lane test below passed against
    a deliberate reintroduction of the bug.
    """
    soon = (date.today() + timedelta(days=1)).isoformat() + "T00:00:00Z"
    far = (date.today() + timedelta(days=60)).isoformat() + "T00:00:00Z"

    def fake_get(url, params=None, timeout=None, **kw):
        if url.endswith("/v4/sports"):
            return _FakeResp([{"key": "baseball_mlb", "active": True},
                              {"key": "icehockey_nhl", "active": True}])
        if "baseball_mlb/events" in url:
            return _FakeResp([{"id": "1", "commence_time": soon}])
        if "icehockey_nhl/events" in url:
            return _FakeResp([{"id": "2", "commence_time": far}])
        return _FakeResp([])

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setenv("ODDS_API_KEY", "test-key")


def test_retired_lanes_are_not_expected_to_produce(monkeypatch):
    """A lane we chose to kill must never be reported as having gone dark.

    Failure mode 2. mlb/pitcher_strikeouts is retired, but the monitor kept a
    hand-maintained market list that still demanded daily picks from it — so it
    reported a lane we killed on purpose as broken, every single day.
    """
    from src.config.models import MODELS, model_status
    retired_mlb = [m for (s, m) in MODELS
                   if s == "mlb" and model_status(s, m) == "retired"]
    assert retired_mlb, "expected retired MLB lanes in the registry"

    _fake_odds_api(monkeypatch)
    lines: list[str] = []
    chef._monitor_run(lines.append)
    dark = [ln for ln in lines if "not producing" in ln]
    assert any("MLB" in ln for ln in lines), "MLB should have been evaluated"

    for market in retired_mlb:
        assert not any(market in ln for ln in dark), (
            f"retired lane 'mlb/{market}' reported as DARK — the monitor's "
            f"expectations have drifted from the registry again"
        )


def test_out_of_season_sport_is_not_expected_to_produce(monkeypatch):
    """A league on its summer break must not be reported as dark.

    The Odds API marks icehockey_nhl `active` in July because next season's board
    is already posted. Trusting that flag meant three NHL lanes were reported
    DARK every day from June onward — noise that sat in the same list as the real
    findings and taught the whole report to be skimmed.
    """
    _fake_odds_api(monkeypatch)
    lines: list[str] = []
    chef._monitor_run(lines.append)
    assert not any("NHL" in ln and "not producing" in ln for ln in lines), (
        "NHL reported as DARK while its next game is 60 days away — the season "
        "test is trusting the API's `active` flag again instead of real fixtures"
    )


def test_capture_gate_ignores_games_that_have_not_happened_yet(monkeypatch):
    """The capture gate must measure a SETTLED window.

    Closing lines are archived minutes before start, so today's picks have no
    close yet by design. Counting them as misses made WNBA read 42% when its
    real settled rate was 96% — an alarm firing about games not yet played.
    """
    lines: list[str] = []
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    chef._monitor_run(lines.append)
    header = [ln for ln in lines if "Closing-line capture" in ln]
    assert header, "capture gate did not run"

    # The window must end at least a couple of days in the past.
    end = header[0].split("ending")[1].split(")")[0].strip()
    assert end < date.today().isoformat(), (
        f"capture gate window ends {end}, which includes unplayed games"
    )


def test_monitor_run_and_cmd_monitor_agree(monkeypatch):
    """The heartbeat reads _monitor_run; the alarm reads cmd_monitor.

    If these ever diverge, the digest you read daily and the alarm that pages you
    would disagree about whether the pipeline is healthy — and the friendly one
    would be the one you believe.
    """
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    sink: list[str] = []
    issues, unknown = chef._monitor_run(sink.append)

    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    code = chef.cmd_monitor(argparse.Namespace(soft=False))
    assert (code != 0) == bool(issues or unknown)
