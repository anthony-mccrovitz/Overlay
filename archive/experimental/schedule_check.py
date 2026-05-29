#!/usr/bin/env python3
"""
scripts/schedule_check.py — Schedule validation guard for all sports pipelines.

Queries live schedules before running picks generation.
Returns True if games exist for the sport/date, False if the sport should be skipped.

Usage:
    from scripts.schedule_check import has_games, get_game_count, validate_and_log

    if not has_games("nba", "2026-05-27"):
        print("No NBA games today — skipping")
        sys.exit(0)
"""
from __future__ import annotations

import sys
import requests
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── ESPN league slugs for soccer ──────────────────────────────────────────────
SOCCER_LEAGUES = {
    "soccer_epl":           "eng.1",
    "soccer_spain_la_liga": "esp.1",
    "soccer_italy_serie_a": "ita.1",
    "soccer_france_ligue_one": "fra.1",
    "soccer_germany_bundesliga": "ger.1",
    "soccer_usa_mls":       "usa.1",
}


def _date_str(d: str | date | None) -> str:
    if d is None:
        return date.today().strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    # accept YYYYMMDD or YYYY-MM-DD
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _espn_game_count(sport: str, league: str, date_str: str) -> int:
    """Return number of ESPN scoreboard events for a sport/league/date."""
    ymd = date_str.replace("-", "")
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
    try:
        r = requests.get(url, params={"dates": ymd}, timeout=8)
        r.raise_for_status()
        return len(r.json().get("events", []))
    except Exception:
        return -1   # -1 = network error, don't block pipeline


def _mlb_game_count(date_str: str) -> int:
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str},
            timeout=8,
        )
        r.raise_for_status()
        dates = r.json().get("dates", [])
        return sum(len(d.get("games", [])) for d in dates)
    except Exception:
        return -1


def _nhl_game_count(date_str: str) -> int:
    try:
        r = requests.get(
            f"https://api-web.nhle.com/v1/schedule/{date_str}", timeout=8
        )
        r.raise_for_status()
        week = r.json().get("gameWeek", [])
        for day in week:
            if day.get("date") == date_str:
                return len(day.get("games", []))
        return 0
    except Exception:
        return -1


def _soccer_game_count(date_str: str) -> int:
    """Total games across all tracked soccer leagues for a date."""
    total = 0
    for league_slug in SOCCER_LEAGUES.values():
        n = _espn_game_count("soccer", league_slug, date_str)
        if n > 0:
            total += n
    return total


# ── Public API ─────────────────────────────────────────────────────────────────

def get_game_count(sport: str, check_date: str | date | None = None) -> int:
    """
    Return the number of games scheduled for a sport on a date.
    Returns -1 if the check failed (network error) — treat as 'unknown, proceed'.
    """
    d = _date_str(check_date)
    sport = sport.lower().strip()

    if sport == "mlb":
        return _mlb_game_count(d)
    elif sport == "nba":
        return _espn_game_count("basketball", "nba", d)
    elif sport == "nhl":
        return _nhl_game_count(d)
    elif sport == "wnba":
        return _espn_game_count("basketball", "wnba", d)
    elif sport in ("soccer", "soccer_all") or sport.startswith("soccer_"):
        return _soccer_game_count(d)
    elif sport == "tennis":
        # ATP/WTA schedules not easily available; don't block
        return -1
    elif sport == "pga":
        # PGA tournament check is handled in run_pga.py already
        return -1
    elif sport in ("ufc", "mma"):
        # UFC card check is handled in run_ufc.py already
        return -1
    elif sport == "nascar":
        # Race week check is handled in run_nascar.py already
        return -1
    else:
        return -1   # unknown sport → don't block


def has_games(sport: str, check_date: str | date | None = None) -> bool:
    """
    Returns True if the sport has games on this date (or check failed → benefit of doubt).
    Returns False ONLY when we definitively confirmed 0 games.
    """
    n = get_game_count(sport, check_date)
    if n == -1:
        return True   # network error — don't block pipeline, log below
    return n > 0


def validate_and_log(sport: str, check_date: str | date | None = None) -> bool:
    """
    Validate schedule and print a clear log line.
    Returns False and prints a skip message if no games found.
    Call at the top of every run_*.py picks script.

    Example:
        if not validate_and_log("nba"):
            sys.exit(0)
    """
    d = _date_str(check_date)
    n = get_game_count(sport, d)

    sport_label = sport.upper().replace("_", " ")

    if n == 0:
        print(f"  ⛔  {sport_label} — 0 games on {d}. Skipping picks generation.")
        print(f"       (No games confirmed via live schedule API)")
        return False
    elif n == -1:
        print(f"  ⚠   {sport_label} — schedule check failed (network). Proceeding anyway.")
        return True
    else:
        print(f"  ✅  {sport_label} — {n} game{'s' if n != 1 else ''} confirmed on {d}. Running picks.")
        return True


# ── CLI for testing ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check game schedule for a sport/date")
    parser.add_argument("sport", nargs="?", default="all",
                        help="Sport to check (mlb/nba/nhl/wnba/soccer) or 'all'")
    parser.add_argument("--date", default=None, help="Date YYYY-MM-DD or YYYYMMDD (default: today)")
    args = parser.parse_args()

    check_date = args.date or date.today().strftime("%Y-%m-%d")

    sports = (
        ["mlb", "nba", "nhl", "wnba", "soccer"]
        if args.sport == "all"
        else [args.sport]
    )

    print(f"\nSchedule check for {_date_str(check_date)}\n")
    for s in sports:
        n = get_game_count(s, check_date)
        status = "✅" if n > 0 else ("⛔" if n == 0 else "⚠ ")
        count = str(n) if n >= 0 else "check failed"
        print(f"  {status}  {s.upper():<10}  {count} games")
    print()
