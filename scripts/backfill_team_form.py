#!/usr/bin/env python3
"""Backfill team_form snapshots onto historical MLB picks.

Phase 2 helper: takes any MLB pick that's missing `team_form` and tries to
reconstruct what the form snapshot WOULD have looked like on the pick's date.

This lets us start Phase 3 analysis sooner (4 weeks of data already exists,
not 4 weeks from now).

The MLB Stats API supports historical date ranges, so this is well-defined.

Usage:
    python3 scripts/backfill_team_form.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"

sys.path.insert(0, str(ROOT))

from src.data.mlb_stats import (  # noqa: E402
    get_team_form, _cached_get, API_BASE, fetch_team_stats,
)


def _fetch_team_pairs_for_date(d: date) -> list[tuple[int, str, int, str]]:
    """Return list of (home_id, home_name, away_id, away_name) for all games on `d`.

    Unlike get_todays_matchups, this includes Final games — needed for backfill.
    """
    try:
        data = _cached_get(
            f"backfill_schedule_{d.isoformat()}",
            f"{API_BASE}/schedule",
            {"sportId": 1, "date": d.isoformat()},
            max_age_s=604800,  # week — historical schedules don't change
        )
    except Exception:
        return []
    out = []
    for de in data.get("dates", []):
        for g in de.get("games", []):
            home = g.get("teams", {}).get("home", {}).get("team", {})
            away = g.get("teams", {}).get("away", {}).get("team", {})
            if home.get("id") and away.get("id"):
                out.append((home["id"], home.get("name",""),
                            away["id"], away.get("name","")))
    return out


def _load() -> dict:
    return json.loads(PICKS_FILE.read_text())


def _save(data: dict) -> None:
    PICKS_FILE.write_text(json.dumps(data, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Backfill at most N picks (for testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change without writing")
    ap.add_argument("--since", default="2026-05-01",
                    help="Only backfill picks on or after this date (default 2026-05-01)")
    args = ap.parse_args()

    data = _load()
    picks = data.get("picks", data) if isinstance(data, dict) else data
    if isinstance(data, list):
        # bare-list legacy format — wrap to write back uniformly
        picks = data
        data = {"picks": picks}

    targets = [
        p for p in picks
        if (p.get("sport") or "").lower() in ("mlb", "baseball_mlb")
        and (p.get("date") or "") >= args.since
        and not p.get("team_form")
    ]
    print(f"[backfill] {len(targets)} MLB picks missing team_form (since {args.since})")

    if args.limit:
        targets = targets[: args.limit]
        print(f"[backfill] limiting to first {len(targets)}")

    # Group by date so we only fetch the matchup list once per day
    by_date: dict[str, list[dict]] = defaultdict(list)
    for p in targets:
        by_date[p["date"]].append(p)

    # Season baselines — used as the fallback context in each snapshot
    try:
        season_stats = fetch_team_stats()
    except Exception:
        season_stats = {}

    filled = 0
    failed = 0
    for d_str, day_picks in sorted(by_date.items()):
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        pairs = _fetch_team_pairs_for_date(d)
        if not pairs:
            print(f"  [{d_str}] no games found")
            failed += len(day_picks)
            continue

        # Build snapshot per game
        snap_by_team: dict[str, dict] = {}
        for home_id, home_name, away_id, away_name in pairs:
            home_7  = get_team_form(home_id, as_of=d, lookback_days=7)
            home_15 = get_team_form(home_id, as_of=d, lookback_days=15)
            away_7  = get_team_form(away_id, as_of=d, lookback_days=7)
            away_15 = get_team_form(away_id, as_of=d, lookback_days=15)
            if not any([home_7, home_15, away_7, away_15]):
                continue
            home_stat = season_stats.get(home_id)
            away_stat = season_stats.get(away_id)
            snap = {
                "home": {
                    "team_id": home_id,
                    "season_rs_per_g": round(home_stat.rs_per_game, 2) if home_stat else None,
                    "season_ra_per_g": round(home_stat.ra_per_game, 2) if home_stat else None,
                    "form_7d":  home_7,
                    "form_15d": home_15,
                },
                "away": {
                    "team_id": away_id,
                    "season_rs_per_g": round(away_stat.rs_per_game, 2) if away_stat else None,
                    "season_ra_per_g": round(away_stat.ra_per_game, 2) if away_stat else None,
                    "form_7d":  away_7,
                    "form_15d": away_15,
                },
                "snapshot_date": d.isoformat(),
                "backfilled":    True,
            }
            snap_by_team[home_name.lower()] = snap
            snap_by_team[away_name.lower()] = snap

        day_filled = 0
        for p in day_picks:
            team = (p.get("team") or "").lower()
            matchup = (p.get("matchup") or "").lower()
            snap = (snap_by_team.get(team)
                    or snap_by_team.get(matchup.split("@")[0].strip())
                    or snap_by_team.get(matchup.split("@")[-1].strip()))
            if snap:
                p["team_form"] = snap
                day_filled += 1
        filled += day_filled
        print(f"  [{d_str}] {day_filled}/{len(day_picks)} filled")
        time.sleep(0.2)  # be nice to MLB Stats API

    print(f"\n[backfill] filled {filled}, failed {failed}, untouched {len(targets) - filled - failed}")

    if not args.dry_run and filled > 0:
        _save(data)
        print(f"[backfill] wrote {PICKS_FILE}")
    elif args.dry_run:
        print("[backfill] DRY RUN — no changes written")

    return 0


if __name__ == "__main__":
    sys.exit(main())
