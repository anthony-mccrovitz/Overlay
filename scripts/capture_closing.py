#!/usr/bin/env python3
"""
Per-game closing-line capture daemon.

Designed to run every 2 minutes via cron. For each upcoming game starting
within the next [3, 10] minutes, fetches that event's current odds and
appends to data/clv/closing/{sport}_{date}.json.

Captures regardless of whether picks were posted — every game's closing
line is archived for later CLV analysis on any pick we ever take on it.

Idempotent: once an event has been captured (by event_id), subsequent runs
skip it. To force a re-capture (e.g., line moved late), pass --force.

Usage:
    python3 scripts/capture_closing.py                # MLB + NBA
    python3 scripts/capture_closing.py --sport mlb
    python3 scripts/capture_closing.py --window 5     # ±5 min around tipoff
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make project root importable when run as a script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.odds_api import fetch_events_list, fetch_event_odds  # noqa: E402


CLOSING_DIR = ROOT / "data" / "clv" / "closing"
LOG_FILE = ROOT / "logs" / "capture_closing.log"

SPORTS = {
    "mlb":    "baseball_mlb",
    "nba":    "basketball_nba",
    "nhl":    "icehockey_nhl",
    "wnba":   "basketball_wnba",
    "soccer": "soccer_fifa_world_cup",
    "tennis": "tennis_atp_french_open",
    "pga":    "golf_pga_championship",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load_archive(sport_key: str, date_str: str) -> list[dict]:
    path = CLOSING_DIR / f"{sport_key}_{date_str}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return []


def _save_archive(sport_key: str, date_str: str, records: list[dict]) -> None:
    CLOSING_DIR.mkdir(parents=True, exist_ok=True)
    path = CLOSING_DIR / f"{sport_key}_{date_str}.json"
    path.write_text(json.dumps(records, indent=2))


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def _within_window(commence_iso: str, lo_min: float, hi_min: float) -> bool:
    """Return True if commence_iso is between [now+lo_min, now+hi_min]."""
    try:
        ct = datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    delta_min = (ct - _now_utc()).total_seconds() / 60.0
    return lo_min <= delta_min <= hi_min


def capture_sport(
    sport_key: str,
    odds_api_sport: str,
    lo_min: float,
    hi_min: float,
    force: bool,
) -> int:
    """Capture closing odds for any game in the [lo_min, hi_min] window."""
    events = fetch_events_list(sport=odds_api_sport, refresh=True)
    if not events:
        return 0

    today_str = _now_utc().date().isoformat()
    archive = _load_archive(sport_key, today_str)
    captured_ids = {r.get("event_id") for r in archive}

    captured_now = 0
    for ev in events:
        ev_id = ev.get("id")
        if not ev_id:
            continue
        if ev_id in captured_ids and not force:
            continue
        if not _within_window(ev.get("commence_time", ""), lo_min, hi_min):
            continue

        try:
            odds_df = fetch_event_odds(
                event_id=ev_id,
                sport=odds_api_sport,
                markets="h2h,spreads,totals",
                refresh=True,
            )
        except Exception as e:
            _log(f"  ERROR fetching {sport_key} event {ev_id}: {e}")
            continue

        if odds_df is None or odds_df.empty:
            continue

        # Pull the best (most favorable) ML for each side from the DataFrame
        ml_rows = odds_df[odds_df["Market"] == "h2h"]
        home_ml = away_ml = None
        home_book = away_book = None
        if not ml_rows.empty:
            for _, r in ml_rows.iterrows():
                sel = str(r.get("Selection", ""))
                price = r.get("Odds")
                book = str(r.get("Sportsbook", ""))
                if sel == ev.get("home_team"):
                    if home_ml is None or price > home_ml:
                        home_ml, home_book = price, book
                elif sel == ev.get("away_team"):
                    if away_ml is None or price > away_ml:
                        away_ml, away_book = price, book

        record = {
            "event_id":      ev_id,
            "sport":         odds_api_sport,
            "home_team":     ev.get("home_team"),
            "away_team":     ev.get("away_team"),
            "commence_time": ev.get("commence_time"),
            "captured_at":   _now_utc().isoformat(),
            "BestHomeML":    int(home_ml) if home_ml is not None else None,
            "BestAwayML":    int(away_ml) if away_ml is not None else None,
            "HomeBook":      home_book,
            "AwayBook":      away_book,
            "all_odds":      odds_df.to_dict(orient="records"),
        }
        # If forcing re-capture, replace the existing entry
        if force and ev_id in captured_ids:
            archive = [r for r in archive if r.get("event_id") != ev_id]

        archive.append(record)
        captured_now += 1
        matchup = f"{ev.get('away_team')} @ {ev.get('home_team')}"
        _log(f"  ✓ {sport_key.upper()} closing captured: {matchup} (event {ev_id[:8]})")

    if captured_now > 0:
        _save_archive(sport_key, today_str, archive)

    return captured_now


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=list(SPORTS.keys()) + ["all"], default="all")
    ap.add_argument("--window", type=float, default=5.0,
                    help="Capture games starting within ±window/2 minutes (default 5 → 2.5-7.5 min)")
    ap.add_argument("--force", action="store_true",
                    help="Re-capture even if event already in archive")
    args = ap.parse_args()

    half = args.window / 2.0
    lo, hi = 5.0 - half, 5.0 + half  # capture window centered ~5 min before first pitch

    sports_to_run = list(SPORTS.keys()) if args.sport == "all" else [args.sport]
    total = 0
    for sk in sports_to_run:
        odds_sport = SPORTS[sk]
        n = capture_sport(sk, odds_sport, lo, hi, args.force)
        total += n

    if total == 0:
        # Quiet run when nothing in window — keeps logs clean
        sys.exit(0)
    _log(f"  Total events captured this run: {total}")


if __name__ == "__main__":
    main()
