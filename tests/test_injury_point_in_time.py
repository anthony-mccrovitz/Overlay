"""Injury features must reflect what was KNOWN then, not what is true now.

THE LEAK: every upstream in injury_tracker reports CURRENT status — the NHL
call is literally `/roster/{team}/current`. The per-date cache keeps that honest
going forward, since each day's fetch records what was known that day. But a
request for a PAST date with no cache would fetch today's injuries and file them
under the old date, handing a backtest knowledge it could not have had.

This is the most cited way betting models fool themselves: an injury designation
matching what was CONFIRMED later rather than what was KNOWN at bet time. It
inflates results precisely where the model was supposed to be tested, and it is
undetectable from the output — the backtest just looks good.

An absent feature costs accuracy. A time-travelling one costs the validity of
every evaluation built on it.
"""
from datetime import date, timedelta

import pytest

from src.data import injury_tracker as it


def test_backfill_is_detected_for_past_dates():
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    old = (date.today() - timedelta(days=400)).strftime("%Y%m%d")
    assert it._is_backfill(yesterday)
    assert it._is_backfill(old)


def test_today_is_not_a_backfill():
    """Live use must keep working — this guard is about history, not today."""
    assert not it._is_backfill(date.today().strftime("%Y%m%d"))


def test_nhl_refuses_to_invent_history(monkeypatch):
    """A past date with no cache returns nothing rather than today's roster."""
    calls = []

    def _boom(*a, **k):
        calls.append(a)
        raise AssertionError("hit the network for a historical date")

    monkeypatch.setattr(it, "_load_cache", lambda *a, **k: None)
    monkeypatch.setattr("requests.get", _boom)
    old = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
    assert it.fetch_nhl_injuries(old) == {}
    assert not calls


def test_nba_refuses_to_invent_history(monkeypatch):
    monkeypatch.setattr(it, "_load_cache", lambda *a, **k: None)
    old = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
    assert it.fetch_nba_injuries(old) == {}


def test_a_cached_historical_day_is_still_served(monkeypatch):
    """The guard must not throw away real point-in-time history we DID record.

    A cache entry for an old date is exactly the thing we want: it was written
    on that date, so it holds what was known then.
    """
    monkeypatch.setattr(it, "_load_cache",
                        lambda sport, ds: {"BOS": [{"player": "X", "status": "Out"}],
                                           "_cached_at": 0})
    old = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
    got = it.fetch_nhl_injuries(old)
    assert got == {"BOS": [{"player": "X", "status": "Out"}]}


def test_lineup_adjustment_is_zero_for_uncached_history(monkeypatch):
    """The end-to-end consequence: a historical game gets NO injury adjustment
    rather than one computed from today's injury list."""
    monkeypatch.setattr(it, "_load_cache", lambda *a, **k: None)
    old = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
    assert it.get_lineup_adjustment("BOS", "nhl", old) == 0.0
    assert it.get_lineup_adjustment("Boston Celtics", "nba", old) == 0.0
