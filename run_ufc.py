"""
UFC Daily Picks Pipeline — ChefTonyBets

Fetches moneyline odds for upcoming UFC/UFC Fight Night cards and runs
the Glicko-2 + style matchup simulator to find edges.

Output: output/picks/mma_mixed_martial_arts/YYYYMMDD/picks.json

Run:
    python3 run_ufc.py
    python3 run_ufc.py --refresh
    python3 run_ufc.py --date 20260607
    python3 run_ufc.py --main-card        # 5-round rules for all fights
    python3 run_ufc.py --n-sim 100000
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

from src.models.ufc_model import get_ufc_model
from src.data.odds_api import MY_BOOKS_PARAM
from src.tracking.schema import normalize_pick
from src.config.models import is_live, shadow_stake

import requests

API_BASE  = "https://api.the-odds-api.com/v4"
SPORT_KEY = "mma_mixed_martial_arts"
PNL_FILE  = Path("data/pnl/picks.json")
CACHE_DIR = Path("data/cache/odds")


def fetch_ufc_odds(refresh: bool = False) -> list[dict]:
    key   = os.environ.get("ODDS_API_KEY")
    cache = CACHE_DIR / f"{SPORT_KEY}_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not refresh and cache.exists():
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 3600:
            with open(cache) as f:
                return json.load(f)

    if not key:
        print(f"  [UFC] No ODDS_API_KEY — using cached data.")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []

    try:
        resp = requests.get(
            f"{API_BASE}/sports/{SPORT_KEY}/odds",
            params={
                "apiKey":     key,
                "regions":    "us,us2",
                "markets":    "h2h",
                "oddsFormat": "american",
                "bookmakers": MY_BOOKS_PARAM,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        print(f"  [UFC] Fetched {len(data)} fight(s) from The Odds API.")
        return data
    except Exception as e:
        print(f"  [UFC] API error: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


def _auto_log_picks(edges: list[dict], game_date: date, sport: str) -> int:
    if not edges:
        return 0

    from src.tracking.schema import append_picks_safe

    existing_ids: set[str] = set()
    now     = datetime.now(timezone.utc).isoformat()
    entries: list[dict] = []

    for e in edges:
        raw = {
            "date":        game_date.isoformat(),
            "sport":       sport,
            "market":      "moneyline",
            "direction":   "WIN",
            "team":        e.get("fighter", e.get("team", "")),
            "matchup":     e.get("matchup", ""),
            "odds":        e.get("odds", -110),
            "line":        None,
            "sportsbook":  e.get("sportsbook", ""),
            "model_prob":  e.get("model_prob"),
            "edge_pct":    e.get("edge_pct"),
            "stake":       shadow_stake(sport, "moneyline"),
            "card_pick":   is_live(sport, "moneyline"),
            "result":      None,
            "profit":      None,
            "recorded_at": now,
        }
        norm = normalize_pick(raw)
        pid  = norm.get("pick_id")
        if pid and pid in existing_ids:
            continue
        entries.append(norm)
        if pid:
            existing_ids.add(pid)

    PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
    return append_picks_safe(PNL_FILE, entries)


def run_ufc(args: argparse.Namespace) -> int:
    n_sim      = getattr(args, "n_sim", 50_000)
    refresh    = getattr(args, "refresh", False)
    main_card  = getattr(args, "main_card", False)
    min_edge   = getattr(args, "min_edge", 3.0)
    date_str   = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    game_date  = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    today_str  = game_date.strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print(f"  UFC MMA — Fight Picks")
    print(f"  {game_date.strftime('%B %d, %Y')}  |  n_sim={n_sim:,}")
    print(f"{'='*60}")

    # 1. Fetch odds
    events = fetch_ufc_odds(refresh=refresh)
    if not events:
        print("  No UFC odds found. No card may be scheduled.")
        return 0

    # Filter to today (or next upcoming)
    today_events = []
    for ev in events:
        ct = ev.get("commence_time", "")
        if not ct:
            continue
        try:
            edate = datetime.fromisoformat(ct.replace("Z", "+00:00")).strftime("%Y%m%d")
            if edate == today_str:
                today_events.append(ev)
        except ValueError:
            pass

    if not today_events:
        # Show next card
        upcoming = []
        for ev in events:
            ct = ev.get("commence_time", "")
            try:
                edt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if edt > datetime.now(timezone.utc):
                    upcoming.append((edt, ev))
            except ValueError:
                pass
        upcoming.sort(key=lambda x: x[0])
        print(f"\n  No UFC fights today.")
        if upcoming[:5]:
            print(f"  Next bouts:")
            for dt, ev in upcoming[:5]:
                print(f"    {dt.strftime('%Y-%m-%d')}  {ev.get('away_team')} vs {ev.get('home_team')}")
        return 0

    n_rounds = 5 if main_card else 3
    print(f"\n  {len(today_events)} fight(s) on slate (n_rounds={n_rounds}):")
    for ev in today_events:
        print(f"    {ev.get('away_team')} vs {ev.get('home_team')}")

    # 2. Run model
    print(f"\n  Running UFC fight simulator...")
    model = get_ufc_model()
    edges = model.find_edges(
        today_events,
        n_sim=n_sim,
        min_edge_pct=min_edge,
        is_main_card=main_card,
    )

    if not edges:
        print(f"  No edges ≥ {min_edge}% found.")
        # Print all model probs
        print("\n  Model probabilities (all fights):")
        for ev in today_events:
            home = ev.get("home_team", "")
            away = ev.get("away_team", "")
            sim  = model.simulate_fight(home, away, n_rounds=n_rounds, n_sim=5000)
            print(f"    {away:28s} vs {home:28s}  {away[:16]}={sim.win_prob(away):.1%}")
    else:
        print(f"\n  Found {len(edges)} edge(s):")
        for e in edges[:10]:
            print(
                f"    {e['fighter']:28s}  edge={e['edge_pct']:+.1f}%  "
                f"odds={e['odds']:+d}  model={e['model_prob']:.1%}  "
                f"KO={e['ko_tko']:.1%}  sub={e['submission']:.1%}  [{e['sportsbook']}]"
            )

    # Unknown-fighter warning
    unknown_edges = [e for e in edges if e.get("data_quality") == "unknown_fighter"]
    if unknown_edges:
        print(f"\n  WARNING: {len(unknown_edges)} edge(s) from unknown fighter(s) — model has no Glicko data, treat as low confidence:")
        for e in unknown_edges[:5]:
            print(f"    {e['fighter']}  edge={e['edge_pct']:+.1f}%  matchup={e['matchup']}")

    # Pinnacle guard
    try:
        from src.betting.value_bets import flag_high_edge_picks
        high_edge = flag_high_edge_picks(edges, threshold_pct=8.0)
        if high_edge:
            print(f"\n  WARNING: {len(high_edge)} pick(s) with edge >8% — verify fighter ratings are current:")
            for e in high_edge:
                print(f"    {e['fighter']}  edge={e['edge_pct']:+.1f}%")
    except Exception:
        pass

    # 3. Save output
    out_dir = Path("output/picks") / SPORT_KEY / today_str
    out_dir.mkdir(parents=True, exist_ok=True)
    picks_path = out_dir / "picks.json"
    picks_path.write_text(json.dumps(edges, indent=2, default=str))
    print(f"\n  Picks saved → {picks_path}")

    # 4. Auto-log
    added = _auto_log_picks(edges, game_date, SPORT_KEY)
    if added:
        print(f"  Logged {added} pick(s) to PnL.")

    # 5. CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} UFC pick(s)")
    except Exception as err:
        print(f"  [CLV snapshot] {err}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UFC picks pipeline")
    parser.add_argument("--n-sim",     type=int,   default=50_000)
    parser.add_argument("--min-edge",  type=float, default=3.0)
    parser.add_argument("--date",      type=str,   help="Date YYYYMMDD (default: today)")
    parser.add_argument("--refresh",   action="store_true")
    parser.add_argument("--main-card", action="store_true",
                        help="Use 5-round rules for all fights (main card mode)")
    args = parser.parse_args()
    sys.exit(run_ufc(args))
