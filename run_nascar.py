"""
NASCAR Cup Series Daily Picks Pipeline — ChefTonyBets

Fetches outrights (win/top-5/matchups) for the upcoming Cup Series race
and runs the unified motorsport simulation engine to find edges.

Output: output/picks/auto_racing_nascar_cup_series/YYYYMMDD/picks.json

Run:
    python3 run_nascar.py
    python3 run_nascar.py --refresh
    python3 run_nascar.py --date 20260525
    python3 run_nascar.py --n-sim 100000
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

from src.models.motorsport_engine import get_engine, DRIVER_RATINGS
from src.data.odds_api import MY_BOOKS_PARAM
from src.tracking.schema import normalize_pick
from src.config.models import is_live, shadow_stake

import requests

API_BASE  = "https://api.the-odds-api.com/v4"
SPORT_KEY = "auto_racing_nascar_cup_series"
PNL_FILE  = Path("data/pnl/picks.json")
CACHE_DIR = Path("data/cache/odds")


def fetch_race_odds(sport: str = SPORT_KEY, refresh: bool = False) -> list[dict]:
    key   = os.environ.get("ODDS_API_KEY")
    cache = CACHE_DIR / f"{sport}_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not refresh and cache.exists():
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 3600:  # 1-hour cache for race odds
            with open(cache) as f:
                return json.load(f)

    if not key:
        print(f"  [{sport}] No ODDS_API_KEY — using cached data.")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []

    try:
        resp = requests.get(
            f"{API_BASE}/sports/{sport}/odds",
            params={
                "apiKey":     key,
                "regions":    "us,us2",
                "markets":    "outrights",
                "oddsFormat": "american",
                "bookmakers": MY_BOOKS_PARAM,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        print(f"  [{sport}] Fetched {len(data)} event(s) from The Odds API.")
        return data
    except Exception as e:
        print(f"  [{sport}] API error: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


def _extract_entry_list(events: list[dict]) -> list[str]:
    """Pull unique driver names from outrights outcomes."""
    drivers: set[str] = set()
    for event in events:
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") in ("outrights", "winner"):
                    for o in market.get("outcomes", []):
                        name = o.get("name", "").strip()
                        if name:
                            drivers.add(name)
    return sorted(drivers)


def _auto_log_picks(edges: list[dict], game_date: date, sport: str) -> int:
    if not edges:
        return 0

    pnl_data: dict = {}
    if PNL_FILE.exists():
        try:
            pnl_data = json.loads(PNL_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pnl_data = {}
    picks = pnl_data.get("picks", [])
    existing_ids = {p.get("pick_id") for p in picks if isinstance(p, dict)}

    now   = datetime.now(timezone.utc).isoformat()
    added = 0

    for e in edges:
        raw = {
            "date":        game_date.isoformat(),
            "sport":       sport,
            "market":      e.get("market", "outrights"),
            "direction":   "WIN",
            "team":        e.get("driver", e.get("team", "")),
            "matchup":     e.get("matchup", ""),
            "odds":        e.get("odds", -110),
            "line":        None,
            "sportsbook":  e.get("sportsbook", ""),
            "model_prob":  e.get("model_prob"),
            "edge_pct":    e.get("edge_pct"),
            "stake":       shadow_stake(sport, "outrights"),
            "card_pick":   is_live(sport, "outrights"),
            "result":      None,
            "profit":      None,
            "recorded_at": now,
        }
        norm = normalize_pick(raw)
        pid  = norm.get("pick_id")
        if pid and pid in existing_ids:
            continue
        picks.append(norm)
        if pid:
            existing_ids.add(pid)
        added += 1

    pnl_data["picks"] = picks
    PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
    PNL_FILE.write_text(json.dumps(pnl_data, indent=2))
    return added


def run_motorsport(args: argparse.Namespace) -> int:
    sport    = getattr(args, "sport", SPORT_KEY) or SPORT_KEY
    n_sim    = getattr(args, "n_sim", 50_000)
    refresh  = getattr(args, "refresh", False)
    min_edge = getattr(args, "min_edge", 3.0)
    date_str = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    game_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    today_str = game_date.strftime("%Y%m%d")

    series_label = {
        "auto_racing_nascar_cup_series": "NASCAR Cup Series",
        "auto_racing_indycar_series":    "NTT IndyCar Series",
        "auto_racing_formula_one":       "Formula 1",
    }.get(sport, sport)

    print(f"\n{'='*60}")
    print(f"  {series_label} — Race Picks")
    print(f"  {game_date.strftime('%B %d, %Y')}  |  n_sim={n_sim:,}")
    print(f"{'='*60}")

    # 1. Fetch odds
    events = fetch_race_odds(sport=sport, refresh=refresh)
    if not events:
        print(f"  No {series_label} odds found. Race may not be scheduled.")
        return 0

    print(f"\n  {len(events)} race event(s) available.")
    for ev in events:
        ct = ev.get("commence_time", "")
        print(f"    {ev.get('sport_title', series_label)}  {ct[:10]}")

    # 2. Extract driver field
    entry_list = _extract_entry_list(events)
    if not entry_list:
        print("  No driver names found in odds data.")
        return 0

    print(f"\n  Field: {len(entry_list)} driver(s)")
    known = [d for d in entry_list if any(
        d in DRIVER_RATINGS and any(k in DRIVER_RATINGS.get(d, {}) for k in ("nascar","indycar","f1"))
        for _ in [1]
    )]
    print(f"  Known Elo: {len(known)}/{len(entry_list)} drivers")

    # 3. Run simulation
    print(f"\n  Running Monte Carlo simulation ({n_sim:,} races)...")
    engine = get_engine(sport)
    sim    = engine.simulate(entry_list, n_sim=n_sim)
    summary = sim.summary()

    # Show top-10 by win probability
    ranked = sorted(summary.items(), key=lambda x: x[1]["win"], reverse=True)
    print(f"\n  Top-10 win probabilities:")
    for driver, stats in ranked[:10]:
        print(
            f"    {driver:30s}  win={stats['win']:.3f}  "
            f"top5={stats['top5']:.3f}  top10={stats['top10']:.3f}  "
            f"dnf={stats['dnf']:.3f}"
        )

    # 4. Find edges
    edges = engine.find_edges(entry_list, events, n_sim=n_sim, min_edge_pct=min_edge)

    if not edges:
        print(f"\n  No edges ≥ {min_edge}% found.")
    else:
        print(f"\n  Found {len(edges)} edge(s):")
        for e in edges[:10]:
            print(
                f"    {e['driver']:30s}  edge={e['edge_pct']:+.1f}%  "
                f"odds={e['odds']:+d}  model={e['model_prob']:.1%}  "
                f"top5={e['top5']:.1%}  [{e['sportsbook']}]"
            )

    # Pinnacle disagreement guard
    try:
        from src.betting.value_bets import flag_high_edge_picks
        high_edge = flag_high_edge_picks(edges, threshold_pct=8.0)
        if high_edge:
            print(f"\n  WARNING: {len(high_edge)} pick(s) with edge >8% — verify Elo is current:")
            for e in high_edge:
                print(f"    {e['driver']}  edge={e['edge_pct']:+.1f}%")
    except Exception:
        pass

    # 5. Save output
    out_dir = Path("output/picks") / sport / today_str
    out_dir.mkdir(parents=True, exist_ok=True)

    picks_path = out_dir / "picks.json"
    picks_path.write_text(json.dumps(edges, indent=2, default=str))
    print(f"\n  Picks saved → {picks_path}")

    sim_summary_path = out_dir / "sim_summary.json"
    sim_summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"  Sim summary → {sim_summary_path}")

    # 6. Auto-log
    added = _auto_log_picks(edges, game_date, sport)
    if added:
        print(f"  Logged {added} pick(s) to PnL.")

    # 7. CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} motorsport pick(s)")
    except Exception as err:
        print(f"  [CLV snapshot] {err}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Motorsport race picks pipeline")
    parser.add_argument("--sport",    type=str, default=SPORT_KEY,
                        help="Odds API sport key (default: NASCAR Cup)")
    parser.add_argument("--n-sim",   type=int, default=50_000,
                        help="Monte Carlo simulation count (default: 50000)")
    parser.add_argument("--min-edge", type=float, default=3.0,
                        help="Minimum edge %% to report (default: 3.0)")
    parser.add_argument("--date",    type=str, help="Date YYYYMMDD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    args = parser.parse_args()
    sys.exit(run_motorsport(args))
