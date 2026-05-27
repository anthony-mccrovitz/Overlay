#!/usr/bin/env python3
"""
scripts/night_pipeline.py — Night picks pipeline (9:30 PM ET)

Runs the night before to:
  1. Fetch opening odds for tomorrow's MLB, NBA, NHL, WNBA games
  2. Generate picks flagged with bet_status (ready | wait_for_trigger)
  3. Store opening line snapshot in data/timing/open_lines_{date}.json
  4. Print a "BET NOW" vs "HOLD" summary so you know what to place tonight

Usage:
    python3 scripts/night_pipeline.py              # tomorrow's slate
    python3 scripts/night_pipeline.py --date 20260527
    python3 scripts/night_pipeline.py --sport mlb   # single sport

Cron (9:30 PM ET = 01:30 UTC):
    30 1 * * * cd /path/to/march-madness && python3 scripts/night_pipeline.py >> logs/night.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TIMING_DIR  = ROOT / "data" / "timing"
OPEN_DIR    = TIMING_DIR / "open_lines"
LOG_DIR     = ROOT / "logs"

TIMING_DIR.mkdir(parents=True, exist_ok=True)
OPEN_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Sports that run in the night pipeline (open lines night before)
NIGHT_SPORTS = ["mlb", "nba", "nhl", "wnba"]

# Sports that run morning-of (not worth generating night before)
MORNING_SPORTS = ["tennis", "soccer"]

# Sports with weekly cadence (not daily)
WEEKLY_SPORTS = ["pga", "ufc", "nascar"]


def tomorrow_str() -> str:
    """Return tomorrow's date as YYYYMMDD string."""
    return (date.today() + timedelta(days=1)).strftime("%Y%m%d")


def run_sport_picks(sport: str, date_str: str) -> int:
    """Run picks generation for a sport. Returns exit code."""
    sport_cmd_map = {
        "mlb":   [sys.executable, str(ROOT / "predict.py"), "--daily", "--sport", "mlb", "--date", date_str],
        "nba":   [sys.executable, str(ROOT / "run_nba.py"), "--date", date_str],
        "nhl":   [sys.executable, str(ROOT / "run_nhl.py"), "--date", date_str],
        "wnba":  [sys.executable, str(ROOT / "run_wnba.py"), "--date", date_str],
    }
    cmd = sport_cmd_map.get(sport)
    if not cmd:
        print(f"  ⚠  No command configured for sport: {sport}")
        return 1
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def snapshot_open_lines(sport: str, date_str: str) -> dict:
    """
    Fetch current odds for tomorrow's games and store as opening line snapshot.
    Returns dict of {event_id: {home, away, sport, open_odds, open_time}}.
    """
    import os
    try:
        from src.data.odds_api import fetch_odds
    except ImportError:
        print(f"  ⚠  Could not import odds_api for {sport} open line snapshot")
        return {}

    sport_key_map = {
        "mlb":  "baseball_mlb",
        "nba":  "basketball_nba",
        "nhl":  "icehockey_nhl",
        "wnba": "basketball_wnba",
    }
    sport_key = sport_key_map.get(sport, sport)
    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        print(f"  ⚠  No ODDS_API_KEY — skipping open line snapshot for {sport}")
        return {}

    try:
        odds_data = fetch_odds(sport_key, api_key)
    except Exception as e:
        print(f"  ⚠  Could not fetch odds for {sport}: {e}")
        return {}

    open_time = datetime.now(timezone.utc).isoformat()
    snapshots = {}
    for game in odds_data or []:
        event_id = game.get("id", "")
        home = game.get("home_team", "")
        away = game.get("away_team", "")

        # Pull best available moneyline odds from first bookmaker
        home_odds, away_odds = None, None
        for bm in game.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                if mkt.get("key") == "h2h":
                    for outcome in mkt.get("outcomes", []):
                        if outcome.get("name") == home:
                            home_odds = outcome.get("price")
                        elif outcome.get("name") == away:
                            away_odds = outcome.get("price")
                    break
            if home_odds:
                break

        snapshots[event_id] = {
            "sport":       sport_key,
            "home":        home,
            "away":        away,
            "home_odds":   home_odds,
            "away_odds":   away_odds,
            "open_time":   open_time,
            "game_time":   game.get("commence_time", ""),
        }

    # Save snapshot
    out_path = OPEN_DIR / f"{sport}_{date_str}_open.json"
    with open(out_path, "w") as f:
        json.dump(snapshots, f, indent=2)
    print(f"  💾 Open line snapshot → {out_path.name} ({len(snapshots)} games)")
    return snapshots


def load_picks_for_date(date_str: str) -> list[dict]:
    """Load all card picks for a given date from picks.json."""
    pnl = ROOT / "data" / "pnl" / "picks.json"
    if not pnl.exists():
        return []
    try:
        raw = json.loads(pnl.read_text())
        picks = raw if isinstance(raw, list) else raw.get("picks", [])
    except Exception:
        return []

    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return [p for p in picks if p.get("card_pick") and
            str(p.get("date", "")).startswith(date_fmt)]


def print_bet_status(date_str: str, sports: list[str]) -> None:
    """Print a BET NOW vs HOLD summary for picks on a given date."""
    from scripts.timing_config import get_timing

    picks = load_picks_for_date(date_str)
    if not picks:
        print(f"  ℹ  No card picks found for {date_str} yet (run after picks generate)")
        return

    sep = "─" * 64
    date_fmt = datetime.strptime(date_str, "%Y%m%d").strftime("%B %d, %Y")
    print(f"\n  {'═'*64}")
    print(f"  BET STATUS — {date_fmt}")
    print(f"  {'═'*64}")

    by_sport: dict[str, list[dict]] = {}
    for p in picks:
        s = p.get("sport", "unknown")
        by_sport.setdefault(s, []).append(p)

    for sport, sport_picks in sorted(by_sport.items()):
        cfg = get_timing(sport)
        bet_ready   = cfg.get("bet_ready", "open")
        trig_mkts   = cfg.get("trigger_markets", [])
        trig_type   = cfg.get("trigger_type")
        notes       = cfg.get("notes", "")

        print(f"\n  {sport.upper()}")
        print(f"  {sep}")

        for p in sport_picks:
            market   = p.get("market", "")
            team     = p.get("team", "")
            odds     = p.get("odds", 0)
            edge     = p.get("edge_pct", 0)
            odds_str = f"+{odds}" if odds > 0 else str(odds)

            # Determine bet status
            needs_trigger = (
                bet_ready == "trigger" or
                (bet_ready == "split" and market in trig_mkts) or
                ("all" in trig_mkts)
            )

            if needs_trigger and trig_type:
                status = f"⏳ HOLD — wait for {trig_type}"
            else:
                status = "✅ BET NOW"

            print(f"    {status:<30}  {team[:28]:<28}  {odds_str:<6}  edge {edge:.1f}%")

        if notes:
            print(f"\n  📌 {notes}")

    print(f"\n  {'═'*64}\n")


def run(date_str: str, sports: list[str]) -> None:
    """Main pipeline: generate picks + snapshot open lines for given sports/date."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sep = "═" * 60
    print(f"\n  {sep}")
    print(f"  NIGHT PIPELINE — {date_str}  (run at {now})")
    print(f"  {sep}\n")

    for sport in sports:
        print(f"  ▸ [{sport.upper()}] Generating picks for {date_str}...")
        rc = run_sport_picks(sport, date_str)
        if rc != 0:
            print(f"  ✗ {sport.upper()} picks failed or no games\n")
        else:
            print(f"  ✓ {sport.upper()} picks done\n")

        print(f"  ▸ [{sport.upper()}] Snapshotting opening lines...")
        snapshot_open_lines(sport, date_str)
        print()

    # Print bet status summary
    print_bet_status(date_str, sports)

    print(f"  Night pipeline complete. Check logs/night.log for details.")
    print(f"  Run 'python3 chef.py gates' before game time to check triggers.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Night picks pipeline")
    parser.add_argument("--date",  default=tomorrow_str(), help="YYYYMMDD target date (default: tomorrow)")
    parser.add_argument("--sport", default=None, help="Single sport to run (default: all night sports)")
    args = parser.parse_args()

    sports = [args.sport] if args.sport else NIGHT_SPORTS
    run(args.date, sports)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()
