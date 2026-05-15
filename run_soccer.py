"""
World Cup / International Soccer Daily Picks Pipeline — ChefTonyBets

Generates picks for today's international soccer slate and saves to:
    output/picks/soccer_fifa_world_cup/YYYYMMDD/picks.json

Odds source: The Odds API — sport key 'soccer_fifa_world_cup'
Model: Dixon-Coles with time-decay weighting (trained on WC/Euros 2014-2024)

Run:
    python3 run_soccer.py
    python3 run_soccer.py --refresh       # force-refresh odds cache
    python3 run_soccer.py --date 20260611 # specific date
    python3 run_soccer.py --fit           # retrain model before running
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

from src.models.soccer_model import SoccerModel, MODEL_PATH
from src.data.odds_api import MY_BOOKS_PARAM
from src.tracking.schema import normalize_pick
from src.config.models import is_live, shadow_stake

import requests

API_BASE  = "https://api.the-odds-api.com/v4"
SPORT_KEY = "soccer_fifa_world_cup"
CACHE_DIR = Path("data/cache/odds")
PNL_FILE  = Path("data/pnl/picks.json")


# ─────────────────────────── Odds fetch ──────────────────────────────────────

def fetch_soccer_odds(refresh: bool = False) -> list[dict]:
    """Fetch World Cup odds from The Odds API."""
    key = os.environ.get("ODDS_API_KEY")
    cache = CACHE_DIR / f"{SPORT_KEY}_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not refresh and cache.exists():
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 1800:
            with open(cache) as f:
                return json.load(f)

    if not key:
        print("  [soccer] No ODDS_API_KEY — using cached data.")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []

    try:
        resp = requests.get(
            f"{API_BASE}/sports/{SPORT_KEY}/odds",
            params={
                "apiKey":      key,
                "regions":     "us,us2",
                "markets":     "h2h,totals",
                "oddsFormat":  "american",
                "bookmakers":  MY_BOOKS_PARAM,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        print(f"  [soccer] Fetched {len(data)} events from The Odds API.")
        return data
    except Exception as e:
        print(f"  [soccer] API error: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


# ─────────────────────────── PnL auto-log ────────────────────────────────────

def _auto_log_picks(edges: list[dict], game_date: date) -> int:
    """Log soccer picks to pnl/picks.json. Returns number of new picks added."""
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
            "sport":       "soccer_fifa_world_cup",
            "market":      market,
            "direction":   e.get("direction", ""),
            "team":        e.get("team", ""),
            "matchup":     e.get("matchup", ""),
            "odds":        e.get("odds", -110),
            "line":        e.get("line"),
            "sportsbook":  e.get("sportsbook", ""),
            "model_prob":  e.get("model_prob"),
            "edge_pct":    e.get("edge_pct"),
            "stake":       shadow_stake("soccer", market),
            "card_pick":   is_live("soccer", market),
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


# ─────────────────────────── Main ────────────────────────────────────────────

def run_soccer(args: argparse.Namespace) -> int:
    date_str = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    refresh  = getattr(args, "refresh", False)
    do_fit   = getattr(args, "fit", False)
    game_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    today_str = game_date.strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print(f"  World Cup Soccer Picks — {game_date.strftime('%B %d, %Y')}")
    print(f"{'='*60}")

    # 1. Load or fit model
    model = SoccerModel()
    if do_fit or not MODEL_PATH.exists():
        print("\n  [soccer] Fitting Dixon-Coles model...")
        model.fit(min_year=2010, verbose=True)
    else:
        try:
            model.load()
            age_days = (date.today() - model.fitted_on).days
            print(f"\n  [soccer] Model loaded (fitted {age_days}d ago, {len(model.teams)} teams).")
            if age_days > 7:
                print("  [soccer] Model is >7 days old. Run with --fit to retrain.")
        except FileNotFoundError:
            print("  [soccer] No saved model — fitting now...")
            model.fit(min_year=2010, verbose=True)

    # 2. Fetch odds
    events = fetch_soccer_odds(refresh=refresh)
    if not events:
        print("  No soccer events found. Tournament may not have started or no odds posted.")
        return 0

    # Filter to today's games
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
        # Show upcoming games in the next 7 days so we know what's coming
        upcoming = []
        for ev in events:
            ct = ev.get("commence_time", "")
            if not ct:
                continue
            try:
                edate = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                if edate > datetime.now(timezone.utc):
                    upcoming.append((edate, ev))
            except ValueError:
                pass
        upcoming.sort(key=lambda x: x[0])

        print(f"\n  No games scheduled for {today_str}.")
        if upcoming[:5]:
            print("  Next games:")
            for dt, ev in upcoming[:5]:
                print(f"    {dt.strftime('%Y-%m-%d %H:%M UTC')}  {ev.get('away_team')} @ {ev.get('home_team')}")
        return 0

    print(f"\n  {len(today_events)} game(s) on slate:")
    for ev in today_events:
        print(f"    {ev.get('away_team')} @ {ev.get('home_team')}")

    # 3. Find edges
    print("\n  Running Dixon-Coles model...")
    edges = model.find_edges(today_events, min_edge_pct=4.0)

    if not edges:
        print("  No edges meet threshold today.")
        # Show model projections regardless
        print("\n  Model projections (no edge):")
        for ev in today_events:
            home = ev.get("home_team", "")
            away = ev.get("away_team", "")
            try:
                m = model.matchup(home, away, neutral=True)
                print(
                    f"    {away:20s} @ {home:20s}  "
                    f"{m['home_win']:.1%}/{m['draw']:.1%}/{m['away_win']:.1%}  "
                    f"exp={m['exp_total']:.2f}"
                )
            except Exception:
                pass
    else:
        print(f"\n  Found {len(edges)} edge(s):")
        for e in edges[:10]:
            print(
                f"    {e['team']:30s}  {e['market']:10s}  "
                f"edge={e['edge_pct']:+.1f}%  "
                f"odds={e['odds']:+d}  [{e['sportsbook']}]"
            )

    # Pinnacle disagreement guard: flag any edge >8% for manual review
    try:
        from src.betting.value_bets import flag_high_edge_picks
        high_edge = flag_high_edge_picks(edges, threshold_pct=8.0)
        if high_edge:
            print(f"\n  ⚠  MANUAL REVIEW: {len(high_edge)} pick(s) with edge >8%:")
            for e in high_edge:
                print(f"    {e['team']}  edge={e['edge_pct']:+.1f}%  — verify line not stale")
    except Exception:
        pass

    # 4. Save output
    out_dir = Path("output/picks/soccer_fifa_world_cup") / today_str
    out_dir.mkdir(parents=True, exist_ok=True)
    picks_path = out_dir / "picks.json"
    picks_path.write_text(json.dumps(edges, indent=2, default=str))
    print(f"\n  Picks saved → {picks_path}")

    # 5. Auto-log to PnL
    added = _auto_log_picks(edges, game_date)
    if added:
        print(f"  Logged {added} pick(s) to PnL.")

    # 6. CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} soccer pick(s)")
    except Exception as _clv_err:
        print(f"  [CLV snapshot] {_clv_err}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="World Cup soccer picks pipeline")
    parser.add_argument("--date",    type=str, help="Slate date YYYYMMDD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    parser.add_argument("--fit",     action="store_true", help="Retrain Dixon-Coles model")
    args = parser.parse_args()
    sys.exit(run_soccer(args))
