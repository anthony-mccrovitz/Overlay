"""
WNBA Daily Picks Pipeline — Overlay

Generates picks for today's WNBA slate and saves to:
    output/picks/basketball_wnba/YYYYMMDD/picks.json

Run:
    python3 run_wnba.py
    python3 run_wnba.py --refresh     # force-refresh odds cache
    python3 run_wnba.py --date 20260515
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from src.models.wnba_model import find_wnba_edges
from src.data.odds_api import MY_BOOKS_PARAM
from src.tracking.schema import normalize_pick, make_pick_id
from src.config.models import is_live, shadow_stake

import requests

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "basketball_wnba"
CACHE_DIR = Path("data/cache/odds")
PNL_FILE = Path("data/pnl/picks.json")


# ─────────────────────────── Odds fetch ──────────────────────────────────────

def fetch_wnba_odds(refresh: bool = False) -> list[dict]:
    """Fetch today's WNBA odds from The Odds API."""
    key = os.environ.get("ODDS_API_KEY")
    cache = CACHE_DIR / "basketball_wnba_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not refresh and cache.exists():
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 1800:
            with open(cache) as f:
                return json.load(f)

    if not key:
        print("  [wnba] No ODDS_API_KEY — using cached data.")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []

    try:
        resp = requests.get(
            f"{API_BASE}/sports/{SPORT}/odds",
            params={
                "apiKey": key,
                "regions": "us,us2",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
                "bookmakers": MY_BOOKS_PARAM,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        print(f"  [wnba] Fetched {len(data)} events from The Odds API.")
        return data
    except Exception as e:
        print(f"  [wnba] API error: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


# ─────────────────────────── PnL auto-log ────────────────────────────────────

def _auto_log_wnba_picks(edges: list[dict], game_date: date) -> int:
    """Log WNBA picks to pnl/picks.json. Returns number of new picks added."""
    if not edges:
        return 0

    from src.tracking.schema import append_picks_safe

    existing_ids: set[str] = set()
    now     = datetime.now(timezone.utc).isoformat()
    entries: list[dict] = []

    for e in edges:
        market = e.get("market", "total")
        raw = {
            "date":        game_date.isoformat(),
            "sport":       "basketball_wnba",
            "market":      market,
            "direction":   e.get("direction", ""),
            "team":        e.get("team", ""),
            "matchup":     e.get("matchup", ""),
            "odds":        e.get("odds", -110),
            "line":        e.get("line"),
            "sportsbook":  e.get("sportsbook", ""),
            "model_prob":  e.get("model_prob"),
            "edge_pct":    e.get("edge_pct"),
            "stake":       shadow_stake("wnba", market),
            "card_pick":   is_live("wnba", market),
            "result":      None,
            "profit":      None,
            "recorded_at": now,
        }
        norm = normalize_pick(raw)
        pid = norm.get("pick_id")
        if pid and pid in existing_ids:
            continue
        entries.append(norm)
        if pid:
            existing_ids.add(pid)

    PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
    return append_picks_safe(PNL_FILE, entries)


# ─────────────────────────── Main ────────────────────────────────────────────

def run_wnba(args: argparse.Namespace) -> int:
    date_str = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    refresh = getattr(args, "refresh", False)
    game_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    today_str = game_date.strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print(f"  WNBA Picks — {game_date.strftime('%B %d, %Y')}")
    print(f"{'='*60}")

    # 1. Fetch odds
    events = fetch_wnba_odds(refresh=refresh)
    if not events:
        print("  No WNBA events found. Season may be dark or no odds posted yet.")
        return 0

    # Keep only games on this slate date. The odds feed returns the next N
    # upcoming games regardless of date; comparing in ET keeps late-night games
    # (e.g. 02:00 UTC = 10 PM ET) on the right calendar day and prevents future
    # games from leaking onto today's card on an off-day.
    from src.data.slate import filter_to_slate
    today_events = filter_to_slate(events, game_date)

    if not today_events:
        print(f"  No WNBA games scheduled for {today_str}.")
        return 0

    print(f"\n  {len(today_events)} game(s) on slate:")
    for ev in today_events:
        print(f"    {ev.get('away_team')} @ {ev.get('home_team')}")

    # 2. Find edges
    print("\n  Running WNBA model...")
    edges = find_wnba_edges(today_events)

    if not edges:
        print("  No edges meet threshold today.")
    else:
        print(f"\n  Found {len(edges)} edge(s):")
        for e in edges[:10]:
            print(
                f"    {e['team']:30s}  {e['market']:8s}  "
                f"edge={e['edge_pct']:+.1f}%  "
                f"odds={e['odds']:+d}  [{e['sportsbook']}]"
            )

    # 3. Save output
    out_dir = Path("output/picks/basketball_wnba") / today_str
    out_dir.mkdir(parents=True, exist_ok=True)
    picks_path = out_dir / "picks.json"
    picks_path.write_text(json.dumps(edges, indent=2))
    print(f"\n  Picks saved → {picks_path}")

    # 4. Generate platform captions
    if edges:
        try:
            from src.output.captions_platform import write_platform_captions
            cap_picks = [
                {
                    "team":       e.get("team", ""),
                    "matchup":    e.get("matchup", ""),
                    "market":     e.get("market", "total"),
                    "direction":  e.get("direction", ""),
                    "odds":       e.get("odds", -110),
                    "best_odds":  e.get("odds", -110),
                    "sportsbook": e.get("sportsbook", ""),
                    "edge_pct":   float(e.get("edge_pct", 0) or 0),
                }
                for e in edges
            ]
            paths = write_platform_captions(cap_picks, "basketball_wnba", game_date)
            for platform, path in paths.items():
                print(f"  Caption [{platform}] → {path}")
        except Exception as _ce:
            print(f"  [captions] {_ce}")

    # 5. Auto-log to pnl (PAUSED: WNBA market is in shadow/incubating status)
    # 0-8 on spreads; all markets thin. Track output JSON for CLV but don't log to record.
    print("  [PAUSED] WNBA picks not logged to pnl (shadow tracking only).")

    # 6. CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} WNBA pick(s)")
    except Exception as _clv_err:
        print(f"  [CLV snapshot] {_clv_err}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WNBA daily picks pipeline")
    parser.add_argument("--date", help="Target date YYYYMMDD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    args = parser.parse_args()
    sys.exit(run_wnba(args))
