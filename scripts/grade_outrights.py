#!/usr/bin/env python3
"""
Auto-grade outright markets (NASCAR / F1 / IndyCar / PGA golf) using the ESPN
public scoreboard API. No API key required.

Runs daily at 9 AM after picks are logged. If a race or tournament finished
yesterday (or earlier and still ungraded), it pulls the winner from ESPN and
calls grade.py --winner automatically.

Idempotent — skips sports with no ungraded outright picks.

Usage:
    python3 scripts/grade_outrights.py
    python3 scripts/grade_outrights.py --dry-run
    python3 scripts/grade_outrights.py --sport nascar
    python3 scripts/grade_outrights.py --days-back 7
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"

# ESPN API endpoints per sport
ESPN_ENDPOINTS: dict[str, str] = {
    "nascar":  "https://site.api.espn.com/apis/site/v2/sports/racing/nascar-cup/scoreboard",
    "f1":      "https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard",
    "indycar": "https://site.api.espn.com/apis/site/v2/sports/racing/indycar/scoreboard",
    "pga":     "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard",
}

# Maps grade.py --sport flag to picks.json sport field values
SPORT_FIELDS: dict[str, tuple[str, ...]] = {
    "nascar":  ("auto_racing_nascar_cup_series",),
    "f1":      ("auto_racing_formula_one",),
    "indycar": ("auto_racing_indycar_series",),
    "pga":     ("golf_pga_championship", "golf_masters_tournament_winner",
                 "golf_us_open_winner", "golf_the_open_championship_winner"),
}


def _load_picks() -> list[dict]:
    if not PICKS_FILE.exists():
        return []
    try:
        data = json.loads(PICKS_FILE.read_text())
        return data.get("picks", []) if isinstance(data, dict) else data
    except (json.JSONDecodeError, OSError):
        return []


def _ungraded_outright_picks(picks: list[dict], sport: str, since_date: str) -> list[dict]:
    fields = SPORT_FIELDS.get(sport, ())
    return [
        p for p in picks
        if p.get("sport") in fields
        and p.get("result") is None
        and (p.get("date") or "") >= since_date
        and p.get("market") in ("outrights", "winner", None, "")
    ]


def _fetch_espn_winner(sport: str) -> tuple[str | None, str | None]:
    """
    Call ESPN scoreboard API and return (winner_name, event_date_YYYYMMDD).
    Returns (None, None) if no completed event found or API unavailable.
    """
    url = ESPN_ENDPOINTS.get(sport)
    if not url:
        return None, None

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [ESPN/{sport}] API error: {e}")
        return None, None

    events = data.get("events") or data.get("competitions") or []

    # Handle golf scoreboard (different structure)
    if sport == "pga":
        return _parse_golf_winner(data)

    for event in events:
        status = (event.get("status") or {}).get("type", {})
        completed = status.get("completed", False) or status.get("name") == "STATUS_FINAL"
        if not completed:
            continue

        competitions = event.get("competitions", [event])
        for comp in competitions:
            competitors = comp.get("competitors", [])
            winner = next(
                (c for c in competitors if c.get("winner") or c.get("order") == 1
                 or (c.get("statistics") or [{}])[0].get("value") == "1"),
                None,
            )
            if winner:
                name = (winner.get("athlete") or {}).get("displayName") or winner.get("displayName") or ""
                event_date = (event.get("date") or "")[:10].replace("-", "")
                if name:
                    return name, event_date or None

    return None, None


def _parse_golf_winner(data: dict) -> tuple[str | None, str | None]:
    """Parse PGA Tour ESPN scoreboard — golf has a different JSON shape."""
    # Golf scoreboard uses 'leaders' or competitor list sorted by position
    events = data.get("events", [])
    for event in events:
        status = (event.get("status") or {}).get("type", {})
        completed = status.get("completed", False)
        if not completed:
            continue

        competitions = event.get("competitions", [])
        for comp in competitions:
            competitors = comp.get("competitors", [])
            # Sort by score (lowest = winner in stroke play)
            # ESPN encodes position in competitor.status or competitor.order
            for comp_entry in competitors:
                pos = comp_entry.get("status", {}).get("position", {}).get("id") or comp_entry.get("order")
                if pos == 1 or pos == "1":
                    name = (comp_entry.get("athlete") or {}).get("displayName") or ""
                    event_date = (event.get("date") or "")[:10].replace("-", "")
                    if name:
                        return name, event_date or None

    return None, None


def _run_grader(sport: str, date_str: str, winner: str, dry_run: bool) -> bool:
    cmd = [
        sys.executable, str(ROOT / "grade.py"),
        "--sport", sport,
        "--date", date_str,
        "--winner", winner,
    ]
    print(f"  {'[DRY RUN] Would run' if dry_run else 'Running'}: {' '.join(cmd)}")
    if dry_run:
        return True

    try:
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"  [grade/{sport}] exit {result.returncode}: {result.stderr[:300]}")
            return False
        if result.stdout.strip():
            print(result.stdout.strip()[-500:])
        return True
    except subprocess.TimeoutExpired:
        print(f"  [grade/{sport}] TIMEOUT")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Print what would happen, no writes")
    ap.add_argument("--sport", choices=list(ESPN_ENDPOINTS.keys()), help="Restrict to one sport")
    ap.add_argument("--days-back", type=int, default=3, help="Look back N days for ungraded picks (default 3)")
    args = ap.parse_args()

    since = (date.today() - timedelta(days=args.days_back)).strftime("%Y-%m-%d")
    sports = [args.sport] if args.sport else list(ESPN_ENDPOINTS.keys())

    all_picks = _load_picks()
    graded_count = 0

    for sport in sports:
        pending = _ungraded_outright_picks(all_picks, sport, since)
        if not pending:
            print(f"  [{sport.upper()}] No ungraded outright picks since {since} — skipping.")
            continue

        dates_needed = sorted({p["date"] for p in pending})
        print(f"\n  [{sport.upper()}] {len(pending)} ungraded pick(s) across {len(dates_needed)} date(s): {dates_needed}")

        winner, event_date = _fetch_espn_winner(sport)
        if not winner:
            print(f"  [{sport.upper()}] ESPN returned no completed event — grading skipped.")
            print(f"  To grade manually: python3 grade.py --sport {sport} --date YYYYMMDD --winner \"Name\"")
            continue

        print(f"  [{sport.upper()}] ESPN winner: {winner}  (event date: {event_date or 'unknown'})")

        # Grade each ungraded date that matches
        for date_str in dates_needed:
            compact = date_str.replace("-", "")
            # Only grade if event date matches or we don't know event date
            if event_date and compact not in (event_date, date_str.replace("-", "")):
                # Allow ±1 day for timezone edge cases
                try:
                    pick_d  = datetime.strptime(date_str, "%Y-%m-%d").date()
                    event_d = datetime.strptime(event_date, "%Y%m%d").date()
                    if abs((pick_d - event_d).days) > 1:
                        print(f"  [{sport.upper()}] Skipping {date_str} — event date {event_date} too far off.")
                        continue
                except ValueError:
                    pass

            ok = _run_grader(sport, compact, winner, args.dry_run)
            if ok:
                graded_count += 1

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"\n[{ts}] grade_outrights done — {graded_count} sport/date combos graded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
