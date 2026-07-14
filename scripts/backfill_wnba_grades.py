#!/usr/bin/env python3
"""
One-off backfill: grade pending WNBA picks stuck since mid-June.

Why they're stuck: picks were written with sport="wnba" while the grader
matched "basketball_wnba" (fixed in grade.py), and many pre-PR-#62 picks
carry the wrong slate date (UTC drift) — the game actually happened the
day after the pick's date.

Strategy: for each pending pick, look up the game by its *matchup* (away @
home pair) on ESPN's scoreboard across pick date −1 / +0 / +1. A matchup
that appears on more than one of those days is ambiguous and left pending.
Settling uses grade._settle_game_pick — the same logic as nightly grading.

Usage: python3 scripts/backfill_wnba_grades.py [--dry-run]
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grade  # noqa: E402


def _norm(s: str) -> str:
    return s.lower().strip()


def _find_game(matchup: str, team: str, boards: list[tuple[str, dict]]):
    """Locate a game across the fetched boards. Returns (date, game_info) or None.

    Match by away/home pair from the matchup field; fall back to single-team
    match for totals picks whose matchup may be missing. Ambiguous (found on
    multiple days) → None.
    """
    away, home = None, None
    if "@" in matchup:
        away, home = (_norm(x) for x in matchup.split("@", 1))

    hits = []
    for day, games in boards:
        seen_ids = set()
        for info in games.values():
            gid = (info["away"], info["home"])
            if gid in seen_ids:
                continue
            seen_ids.add(gid)
            g_away, g_home = _norm(info["away"]), _norm(info["home"])
            if away and home:
                if (g_away == away or away in g_away or g_away in away) and \
                   (g_home == home or home in g_home or g_home in home):
                    hits.append((day, info))
            elif team:
                t = _norm(team)
                if t in (g_away, g_home):
                    hits.append((day, info))
    if len(hits) == 1:
        return hits[0]
    return None


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    today = datetime.now().strftime("%Y%m%d")

    data = grade._load()
    pending = [
        p for p in data["picks"]
        if p.get("sport") in ("wnba", "basketball_wnba")
        and p.get("result") in (None, "pending")
        and p.get("odds") is not None
        and p.get("date", "").replace("-", "") < today
    ]
    if not pending:
        print("No pending WNBA picks before today.")
        return

    print(f"{len(pending)} pending WNBA picks to backfill (dry_run={dry_run})")

    # Fetch each needed scoreboard date once (pick date ±1 day)
    need_dates: set[str] = set()
    for p in pending:
        d = datetime.strptime(p["date"].replace("-", ""), "%Y%m%d")
        for off in (-1, 0, 1):
            ds = (d + timedelta(days=off)).strftime("%Y%m%d")
            if ds < today:
                need_dates.add(ds)

    boards_by_date: dict[str, dict] = {}
    for ds in sorted(need_dates):
        boards_by_date[ds] = grade._fetch_scores_espn("basketball_wnba", ds)
    print(f"Fetched {len(boards_by_date)} ESPN scoreboard dates.")

    graded = skipped = 0
    profit = 0.0
    for p in sorted(pending, key=lambda x: x["date"]):
        d = datetime.strptime(p["date"].replace("-", ""), "%Y%m%d")
        window = []
        for off in (-1, 0, 1):
            ds = (d + timedelta(days=off)).strftime("%Y%m%d")
            if ds in boards_by_date:
                window.append((ds, boards_by_date[ds]))

        hit = _find_game(p.get("matchup", ""), p.get("team", ""), window)
        if hit is None:
            print(f"  ⚫ UNRESOLVED {p['date']} {p.get('market','?'):9} {p.get('team','?'):<26} ({p.get('matchup','no matchup')})")
            skipped += 1
            continue

        game_day, info = hit
        result = grade._settle_game_pick(p, info)
        if result is None:
            print(f"  ⚠️  unknown market {p.get('market')} — skipped")
            skipped += 1
            continue
        graded += 1
        profit += p.get("profit") or 0.0
        icon = {"win": "🟢", "loss": "🔴", "push": "⬜"}[result]
        note = "" if game_day == p["date"].replace("-", "") else f"  [game on {game_day}]"
        print(f"  {icon} {result.upper():4} {p['date']} {p.get('market','?'):9} "
              f"{p.get('team','?'):<26} {p.get('profit', 0):+.2f}u{note}")

    print(f"\nGraded {graded}, unresolved {skipped}, net profit {profit:+.2f}u")
    if dry_run:
        print("Dry run — nothing saved.")
        return
    grade._save(data)
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
        print("Saved picks.json and refreshed public stats.")
    except Exception as e:
        print(f"Saved picks.json; stats refresh failed: {e}")


if __name__ == "__main__":
    main()
