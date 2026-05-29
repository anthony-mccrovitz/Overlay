"""Weekly sports calendar — prints what leagues are active the coming week.

Run manually or add to weekly_audit.py.
    python3 scripts/weekly_sports_calendar.py

Checks live schedules via Odds API and prints a clean summary.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Sport metadata: key → (display name, typical season window, notes)
SPORTS = {
    "baseball_mlb":          ("MLB",          (4, 11), "Daily — 15 games/night"),
    "basketball_nba":        ("NBA",          (10, 6), "Playoffs run Apr–Jun"),
    "basketball_wnba":       ("WNBA",         (5, 9),  "May–Sep"),
    "icehockey_nhl":         ("NHL",          (10, 6), "Playoffs run Apr–Jun"),
    "soccer_spain_la_liga":  ("La Liga",      (8, 5),  ""),
    "soccer_germany_bundesliga": ("Bundesliga",(8, 5),  ""),
    "soccer_italy_serie_a":  ("Serie A",      (8, 5),  ""),
    "soccer_usa_mls":        ("MLS",          (2, 11), ""),
    "soccer_fifa_world_cup": ("World Cup",    (6, 7),  "2026 — Jun/Jul"),
    "tennis_atp_french_open":("Roland-Garros",(5, 6),  "May 25–Jun 8"),
    "golf_pga":              ("PGA Tour",     (1, 8),  "Majors: Apr/May/Jul/Aug"),
}

def _in_season(key: str, today: date) -> bool:
    _, (start_m, end_m), _ = SPORTS[key]
    m = today.month
    if start_m <= end_m:
        return start_m <= m <= end_m
    return m >= start_m or m <= end_m


def _check_live_events(sport_key: str, lookahead_days: int = 7) -> int:
    """Return count of events found via Odds API in the next N days."""
    try:
        from src.data.odds_api import fetch_events_list
        events = fetch_events_list(sport=sport_key, days_ahead=lookahead_days)
        return len(events) if events is not None else 0
    except Exception:
        return -1  # -1 = couldn't check


def run() -> None:
    today      = date.today()
    week_end   = today + timedelta(days=6)
    print(f"\n{'='*58}")
    print(f"  WEEKLY SPORTS CALENDAR  {today.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}")
    print(f"{'='*58}")

    active, inactive = [], []
    for key, (name, _, notes) in SPORTS.items():
        in_season = _in_season(key, today)
        count     = _check_live_events(key) if in_season else 0
        if in_season and count != 0:
            active.append((name, count, notes, key))
        else:
            inactive.append((name, notes))

    print("\n✅ ACTIVE THIS WEEK")
    print(f"  {'Sport':<20} {'Events':>7}  Notes")
    print(f"  {'-'*48}")
    for name, count, notes, key in sorted(active, key=lambda x: -x[1]):
        count_str = f"~{count}" if count > 0 else "checking..."
        from src.config.models import model_tier, model_status
        sport_clean = key.replace("baseball_","").replace("basketball_","").replace("icehockey_","")
        if "soccer" in sport_clean: sport_clean = "soccer"
        if "tennis" in sport_clean: sport_clean = "tennis"
        if "golf" in sport_clean:   sport_clean = "pga"
        ml_status  = model_status(sport_clean, "moneyline")
        tot_status = model_status(sport_clean, "total")
        model_str  = ""
        if ml_status  == "live": model_str += "ML✅ "
        if tot_status == "live": model_str += "TOT✅"
        print(f"  {name:<20} {count_str:>7}  {notes}  {model_str}")

    print("\n⏸  OFF-SEASON / NO EVENTS")
    for name, notes in inactive:
        print(f"  {name:<20}  {notes}")

    print(f"\n{'='*58}\n")


if __name__ == "__main__":
    run()
