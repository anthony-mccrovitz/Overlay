#!/usr/bin/env python3
"""
One-off backfill: grade pending NBA v1 player props (market="prop") from ESPN
boxscores. The v1 NBA props pipeline died with the season; these picks from
the 2026 playoffs (May 27 – Jun 1) never had a grader that could reach back
past Odds API's 3-day score window.

Game lookup: pick matchup across pick date ±1 on ESPN's scoreboard (slate
dates from that era can be a day off — pre-PR-#62 UTC drift). If the game is
found but the player has no stats row, the pick is VOIDED (scratch/DNP). If
the game itself can't be found, the pick stays pending — unless
--void-phantoms is passed AND all three scoreboard fetches succeeded, in
which case the matchup provably never happened and the pick is voided with a
void_reason.

Usage: python3 scripts/backfill_nba_props.py [--dry-run] [--void-phantoms]
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grade  # noqa: E402
from scripts.grade_backlog import _norm, _matchup_teams  # noqa: E402

# prop_market → (ESPN boxscore label, parser)
_STAT_LABELS = {
    "player_rebounds": ("REB", int),
    "player_assists":  ("AST", int),
    "player_steals":   ("STL", int),
    "player_points":   ("PTS", int),
    "player_threes":   ("3PT", lambda v: int(v.split("-")[0])),  # "3-7" → 3 made
}

_UA = {"User-Agent": "Mozilla/5.0"}
_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


def _scoreboard(day: str) -> list[dict] | None:
    """None = fetch FAILED. [] = fetched fine, no games. The distinction is
    load-bearing: --void-phantoms must never mistake an ESPN outage for
    'this game never existed' and void real picks."""
    try:
        r = requests.get(f"{_BASE}/scoreboard", params={"dates": day}, headers=_UA, timeout=12)
        return r.json().get("events", []) if r.status_code == 200 else None
    except Exception:
        return None


def _player_stats(event_id: str) -> dict[str, dict[str, int]]:
    """{player_name_lower: {prop_market: value}} from the game summary."""
    try:
        r = requests.get(f"{_BASE}/summary", params={"event": event_id}, headers=_UA, timeout=15)
        if r.status_code != 200:
            return {}
        box = r.json().get("boxscore", {})
    except Exception:
        return {}

    out: dict[str, dict[str, int]] = {}
    for team_block in box.get("players", []):
        for stat_group in team_block.get("statistics", []):
            labels = stat_group.get("labels", [])
            for ath in stat_group.get("athletes", []):
                name = ath.get("athlete", {}).get("displayName", "")
                stats = ath.get("stats", [])
                if not name or len(stats) != len(labels):
                    continue  # DNP rows have empty stats
                row = dict(zip(labels, stats))
                entry = out.setdefault(_norm(name), {})
                for market, (label, parse) in _STAT_LABELS.items():
                    if label in row:
                        try:
                            entry[market] = parse(row[label])
                        except (ValueError, IndexError):
                            pass
    return out


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    void_phantoms = "--void-phantoms" in sys.argv
    data = grade._load()
    pending = [
        p for p in data["picks"]
        if p.get("sport") in ("nba", "basketball_nba")
        and p.get("market") == "prop"
        and p.get("result") in (None, "pending")
        and p.get("prop_market") in _STAT_LABELS
        and p.get("odds") is not None
    ]
    if not pending:
        print("No pending NBA v1 props.")
        return
    print(f"{len(pending)} pending NBA props (dry_run={dry_run})")

    events_by_day: dict[str, list[dict]] = {}
    stats_cache: dict[str, dict] = {}
    graded = unresolved = 0

    for p in sorted(pending, key=lambda x: x["date"]):
        away, home = _matchup_teams(p)
        d = datetime.strptime(p["date"].replace("-", ""), "%Y%m%d")
        event = None
        for off in (-1, 0, 1):
            day = (d + timedelta(days=off)).strftime("%Y%m%d")
            if day not in events_by_day:
                events_by_day[day] = _scoreboard(day)
            for ev in events_by_day[day] or []:
                comp = (ev.get("competitions") or [{}])[0]
                if not comp.get("status", {}).get("type", {}).get("completed"):
                    continue
                sides = {c.get("homeAway"): _norm(c.get("team", {}).get("displayName", ""))
                         for c in comp.get("competitors", [])}
                if sides.get("away") == away and sides.get("home") == home:
                    event = ev
                    break
            if event:
                break

        player = _norm(p.get("player", ""))
        market = p["prop_market"]
        if not event or not player:
            # Phantom check: we have completed scoreboards for the whole ±1
            # window and the away@home pairing appears on none of them. These
            # are slate-date-bug era cross-joins (e.g. "Knicks @ Spurs" in
            # May) — the game never happened, so the pick can never settle.
            window_days = [(d + timedelta(days=off)).strftime("%Y%m%d") for off in (-1, 0, 1)]
            # None = fetch failed. A failed board means "unknown", never "phantom".
            boards_fetched = all(events_by_day.get(day) is not None for day in window_days)
            if void_phantoms and boards_fetched and player:
                p["result"], p["profit"] = "void", 0.0
                p["resulted_at"] = datetime.now(timezone.utc).isoformat()
                p["void_reason"] = "phantom matchup — game not on ESPN scoreboard date ±1"
                graded += 1
                print(f"  ⚫ VOID-PHANTOM {p['date']} {market:16} {p.get('player','?'):<22} ({p.get('matchup','')})")
                continue
            print(f"  ⚫ UNRESOLVED {p['date']} {market:16} {p.get('player','?'):<22} ({p.get('matchup','')})")
            unresolved += 1
            continue

        eid = event.get("id")
        if eid not in stats_cache:
            stats_cache[eid] = _player_stats(eid)
        stats = stats_cache[eid]

        actual = None
        for name, entry in stats.items():
            if market in entry and (player == name or player in name or name in player):
                actual = entry[market]
                break

        line = float(p.get("line") or 0)
        direction = (p.get("direction") or "OVER").upper()
        odds = float(p["odds"])
        stake = float(p.get("stake") or 1.0)
        now = datetime.now(timezone.utc).isoformat()

        if actual is None:
            # Player in neither boxscore roster with stats — scratched/DNP → void
            p["result"], p["profit"], p["resulted_at"] = "void", 0.0, now
            graded += 1
            print(f"  ⚫ VOID {p['date']} {market:16} {p.get('player'):<22} (no stats — DNP)")
            continue

        if actual == line:
            p["result"], p["profit"] = "push", 0.0
        else:
            won = (actual > line) if direction == "OVER" else (actual < line)
            p["result"] = "win" if won else "loss"
            p["profit"] = round(grade._profit(stake, odds, won), 4)
        p["resulted_at"] = now
        graded += 1
        icon = {"win": "🟢", "loss": "🔴", "push": "⬜"}[p["result"]]
        print(f"  {icon} {p['result'].upper():4} {p['date']} {market:16} "
              f"{p.get('player'):<22} {direction} {line}  →  {p['profit']:+.2f}u  ({actual})")

    print(f"\nGraded {graded}, unresolved {unresolved}")
    if dry_run:
        print("Dry run — nothing saved.")
        return
    grade._save(data)
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
    except Exception as e:
        print(f"[stats] {e}")
    print("Saved.")


if __name__ == "__main__":
    main()
