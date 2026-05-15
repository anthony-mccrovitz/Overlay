"""
Tennis Daily Picks Pipeline — ChefTonyBets

Generates picks for today's tennis slate using surface-specific Elo + Markov chain.
Default tournament: Roland-Garros (clay). Automatically detects surface from sport key.

Output: output/picks/tennis_atp_french_open/YYYYMMDD/picks.json

Run:
    python3 run_tennis.py
    python3 run_tennis.py --surface clay           # force surface
    python3 run_tennis.py --best-of 5              # Grand Slam final rounds
    python3 run_tennis.py --date 20260526
    python3 run_tennis.py --sport tennis_atp_wimbledon  # grass
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

from src.models.tennis_model import TennisModel
from src.data.odds_api import MY_BOOKS_PARAM
from src.tracking.schema import normalize_pick
from src.config.models import is_live

import requests

API_BASE = "https://api.the-odds-api.com/v4"
PNL_FILE = Path("data/pnl/picks.json")
CACHE_DIR = Path("data/cache/odds")

# Odds API sport keys for major tennis events
TENNIS_SPORTS = {
    "tennis_atp_french_open":    "clay",
    "tennis_atp_wimbledon":      "grass",
    "tennis_atp_us_open":        "hard",
    "tennis_atp_australian_open": "hard",
    "tennis_wta_french_open":    "clay",
    "tennis_wta_wimbledon":      "grass",
    "tennis_wta_us_open":        "hard",
    "tennis_wta_australian_open": "hard",
}

# Active tournament — Roland-Garros starts May 25, 2026
DEFAULT_SPORT = "tennis_atp_french_open"


def fetch_tennis_odds(sport: str, refresh: bool = False) -> list[dict]:
    """Fetch tennis match odds from The Odds API."""
    key = os.environ.get("ODDS_API_KEY")
    cache = CACHE_DIR / f"{sport}_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not refresh and cache.exists():
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 1800:
            with open(cache) as f:
                return json.load(f)

    if not key:
        print(f"  [tennis] No ODDS_API_KEY — using cached data.")
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
        print(f"  [tennis] Fetched {len(data)} matches from The Odds API.")
        return data
    except Exception as e:
        print(f"  [tennis] API error: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


def _auto_log_picks(edges: list[dict], game_date: date, sport: str) -> int:
    """Log tennis picks to pnl/picks.json. Returns number added."""
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

    now = datetime.now(timezone.utc).isoformat()
    added = 0

    for e in edges:
        market = e.get("market", "moneyline")
        raw = {
            "date":        game_date.isoformat(),
            "sport":       sport,
            "market":      market,
            "direction":   e.get("direction", ""),
            "team":        e.get("team", ""),
            "matchup":     e.get("matchup", ""),
            "odds":        e.get("odds", -110),
            "line":        None,
            "sportsbook":  e.get("sportsbook", ""),
            "model_prob":  e.get("model_prob"),
            "edge_pct":    e.get("edge_pct"),
            "stake":       1.0,
            "card_pick":   is_live("tennis", market),
            "result":      None,
            "profit":      None,
            "recorded_at": now,
        }
        norm = normalize_pick(raw)
        pid = norm.get("pick_id")
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


def run_tennis(args: argparse.Namespace) -> int:
    sport   = getattr(args, "sport", DEFAULT_SPORT) or DEFAULT_SPORT
    surface = getattr(args, "surface", None) or TENNIS_SPORTS.get(sport, "clay")
    best_of = getattr(args, "best_of", 3)
    refresh = getattr(args, "refresh", False)
    date_str = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    game_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    today_str = game_date.strftime("%Y%m%d")

    tournament = sport.replace("tennis_atp_", "").replace("tennis_wta_", "").replace("_", " ").title()

    print(f"\n{'='*60}")
    print(f"  Tennis Picks — {tournament} ({surface.capitalize()})")
    print(f"  {game_date.strftime('%B %d, %Y')}  |  Best of {best_of}")
    print(f"{'='*60}")

    # 1. Fetch odds
    events = fetch_tennis_odds(sport, refresh=refresh)
    if not events:
        print(f"  No {tournament} odds found. Tournament may not be active.")
        return 0

    # Filter to today
    today_events = []
    for ev in events:
        ct = ev.get("commence_time", "")
        if not ct:
            continue
        try:
            event_date = datetime.fromisoformat(ct.replace("Z", "+00:00")).strftime("%Y%m%d")
            if event_date == today_str:
                today_events.append(ev)
        except ValueError:
            pass

    if not today_events:
        upcoming = []
        for ev in events:
            ct = ev.get("commence_time", "")
            try:
                edate = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if edate > datetime.now(timezone.utc):
                    upcoming.append((edate, ev))
            except ValueError:
                pass
        upcoming.sort(key=lambda x: x[0])

        print(f"\n  No matches scheduled for {today_str}.")
        if upcoming[:5]:
            print(f"  Next {tournament} matches:")
            for dt, ev in upcoming[:5]:
                print(f"    {dt.strftime('%Y-%m-%d %H:%M UTC')}  {ev.get('away_team')} vs {ev.get('home_team')}")
        return 0

    print(f"\n  {len(today_events)} match(es) on slate:")
    for ev in today_events:
        print(f"    {ev.get('away_team')} vs {ev.get('home_team')}")

    # 2. Run model
    print(f"\n  Running tennis model ({surface} surface)...")
    model = TennisModel(surface=surface)
    edges = model.find_edges(today_events, surface=surface, best_of=best_of)

    if not edges:
        print("  No edges meet threshold today.")
        print("\n  Model probabilities (no edge):")
        for ev in today_events:
            home = ev.get("home_team", "")
            away = ev.get("away_team", "")
            p = model.match_win_prob(home, away, best_of=best_of)
            print(f"    {away:30s} vs {home:30s}  home={p:.1%}")
    else:
        print(f"\n  Found {len(edges)} edge(s):")
        for e in edges[:10]:
            print(
                f"    {e['team']:30s}  edge={e['edge_pct']:+.1f}%  "
                f"odds={e['odds']:+d}  model={e['model_prob']:.1%}  [{e['sportsbook']}]"
            )

    # 3. Save output
    out_dir = Path("output/picks") / sport / today_str
    out_dir.mkdir(parents=True, exist_ok=True)
    picks_path = out_dir / "picks.json"
    picks_path.write_text(json.dumps(edges, indent=2, default=str))
    print(f"\n  Picks saved → {picks_path}")

    # 4. Auto-log
    added = _auto_log_picks(edges, game_date, sport)
    if added:
        print(f"  Logged {added} pick(s) to PnL.")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tennis picks pipeline")
    parser.add_argument("--sport",   type=str, default=DEFAULT_SPORT,
                        help=f"Odds API sport key (default: {DEFAULT_SPORT})")
    parser.add_argument("--surface", type=str, choices=["clay", "hard", "grass"],
                        help="Court surface (auto-detected from sport key if omitted)")
    parser.add_argument("--best-of", type=int, default=3, choices=[3, 5],
                        help="Match format: 3 or 5 sets (default 3)")
    parser.add_argument("--date",    type=str, help="Slate date YYYYMMDD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    args = parser.parse_args()
    sys.exit(run_tennis(args))
