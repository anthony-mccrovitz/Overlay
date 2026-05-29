"""
NHL Daily Picks Pipeline — ChefTonyBets

Generates picks for today's NHL playoff slate and saves to:
    output/picks/icehockey_nhl/YYYYMMDD/picks.json

Run:
    python3 run_nhl.py
    python3 run_nhl.py --refresh     # force-refresh odds cache
    python3 run_nhl.py --date 20260424
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

import requests

from src.data.nhl_stats import fetch_today_schedule, get_team_goalie, fetch_goalie_stats
from src.models.nhl_model import find_nhl_edges, project_game

API_BASE = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path("data/cache/odds")
_PNL_FILE = Path("data/pnl/picks.json")
SPORT_KEY = "icehockey_nhl"
OUT_SPORT  = "icehockey_nhl"


def fetch_nhl_odds(refresh: bool = False) -> list[dict]:
    """Fetch today's NHL odds from The Odds API."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("  ⚠  No ODDS_API_KEY in env. Using cached data.")
        cache = CACHE_DIR / f"{SPORT_KEY}_latest.json"
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []

    cache = CACHE_DIR / f"{SPORT_KEY}_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache.exists() and not refresh:
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 1800:
            with open(cache) as f:
                return json.load(f)

    try:
        resp = requests.get(
            f"{API_BASE}/sports/{SPORT_KEY}/odds",
            params={
                "apiKey": key,
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
                "bookmakers": "pinnacle,draftkings,fanduel,betmgm,betrivers,caesars,bet365",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  ✓  Live NHL odds fetched. API requests remaining: {remaining}")
        return data
    except Exception as e:
        print(f"  [run_nhl] Odds fetch error: {e}")
        cache_path = CACHE_DIR / f"{SPORT_KEY}_latest.json"
        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)
        return []


def _format_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%I:%M %p ET")
    except Exception:
        return iso


def _auto_log_picks(picks: list[dict], game_date: date) -> int:
    """Log NHL picks to data/pnl/picks.json. card_pick driven by models.py registry."""
    if not picks:
        return 0

    from src.tracking.schema import append_picks_safe
    from src.config.models import is_live, shadow_stake, is_card_pick

    existing_ids: set[str] = set()
    date_str = game_date.isoformat()
    now_ts = datetime.now(timezone.utc).isoformat()
    added = 0
    nhl_entries: list[dict] = []

    for pick in picks:
        team_slug = pick["team"].lower().replace(" ", "-").replace(".", "")[:20]
        market_slug = pick["market"].replace("_", "-")
        direction_slug = pick["direction"].lower().replace(" ", "-").replace(".", "")
        pick_id = f"nhl_{date_str.replace('-','')}_{team_slug}_{market_slug}_{direction_slug}"

        if pick_id in existing_ids:
            continue

        market = pick["market"]
        entry = {
            "pick_id":       pick_id,
            "date":          date_str,
            "sport":         "nhl",
            "market":        market,
            "direction":     pick["direction"],
            "team":          pick["team"],
            "matchup":       pick["matchup"],
            "odds":          pick["odds"],
            "line":          pick.get("line"),
            "sportsbook":    pick.get("sportsbook", "DraftKings"),
            "model_prob":    pick["model_prob"],
            "edge_pct":      pick["edge_pct"],
            "proj_total":    pick.get("proj_total"),
            "stake":         shadow_stake("nhl", market),
            "card_pick":     is_card_pick("nhl", market, pick.get("edge_pct")),
            "result":        None,
            "profit":        None,
            "recorded_at":   now_ts,
            "resulted_at":   None,
            "model_version": "v1_logreg_20260514",
        }
        nhl_entries.append(entry)
        existing_ids.add(pick_id)
        added += 1

    if nhl_entries:
        _PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
        append_picks_safe(_PNL_FILE, nhl_entries)

    return added


def _print_picks(picks: list[dict], game_date: date) -> None:
    W = 72
    print(f"\n  {'═'*W}")
    print(f"  NHL PICKS — {game_date.strftime('%A %B %d, %Y').upper()}")
    print(f"  {'─'*W}")
    print(f"  {'MATCHUP / BET':<36} {'ODDS':>5}  {'EDGE':>5}  {'PROJ':>5}  MARKET")
    print(f"  {'─'*W}")

    for p in picks:
        matchup_short = p["matchup"][:36]
        proj = f"{p['proj_total']:.1f}" if p.get("proj_total") else "—"
        market_label = {
            "moneyline": "ML",
            "puck_line":  f"PL {p.get('line','')}",
            "total":      f"TOT {p.get('line','')}",
        }.get(p["market"], p["market"])
        print(
            f"  {p['team'][:30]:<30} {p['odds']:>+5}  "
            f"{p['edge_pct']:>+4.1f}%  {proj:>5}  {market_label}"
        )
        print(f"    ↳ {matchup_short}")
        if p.get("notes"):
            print(f"    ↳ {p['notes'][-1]}")
        print()

    print(f"  {'─'*W}")
    print(f"  {len(picks)} edge(s) found  |  NHL Playoffs  |  min edge: 8%")
    print(f"  {'═'*W}\n")


def main(refresh: bool = False, target_date: str | None = None) -> None:
    if target_date:
        game_date = date(int(target_date[:4]), int(target_date[4:6]), int(target_date[6:]))
    else:
        game_date = date.today()

    today = game_date.strftime("%Y%m%d")
    out_dir = Path(f"output/picks/{OUT_SPORT}/{today}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  [NHL] Generating picks for {game_date.isoformat()}")

    # ── Schedule guard: skip if no NHL games today ─────────────────────────────
    try:
        from scripts.schedule_check import validate_and_log
        if not validate_and_log("nhl", game_date.isoformat()):
            return
    except Exception as _sce:
        print(f"  ⚠  Schedule check skipped ({_sce})")
    # ──────────────────────────────────────────────────────────────────────────

    # Fetch schedule
    schedule = fetch_today_schedule(game_date)
    if schedule:
        print(f"  ✓  {len(schedule)} NHL game(s) on the slate today")
    else:
        print("  ℹ  No NHL games found for today (off-day or API unavailable)")

    # Fetch odds
    odds_data = fetch_nhl_odds(refresh=refresh)
    if not odds_data:
        print("  ⚠  No NHL odds available. Check cache or ODDS_API_KEY.")
        return

    print(f"  ✓  {len(odds_data)} game(s) with odds from API")

    # Find edges
    picks = find_nhl_edges(odds_data, game_date=game_date.isoformat())

    # Print summary
    if picks:
        _print_picks(picks, game_date)
    else:
        print("  ℹ  No NHL edges found above 4% threshold today.")
        print("     (Playoff lines are efficient — fewer soft spots than regular season)")

    # Generate projections for all games (even without edges)
    all_teams_data = None
    try:
        from src.data.nhl_stats import fetch_team_stats
        all_teams_data = fetch_team_stats(game_type=3) or fetch_team_stats(game_type=2)
    except Exception:
        pass

    projections = []
    for game in odds_data:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        if not home or not away:
            continue
        try:
            proj = project_game(
                away_team=away,
                home_team=home,
                all_teams=all_teams_data,
            )
            projections.append({
                "matchup": f"{away} @ {home}",
                "commence": game.get("commence_time", ""),
                "time_et": _format_time(game.get("commence_time", "")),
                **proj,
            })
        except Exception as e:
            print(f"  [projection] {away} @ {home}: {e}")

    # Save picks.json
    picks_out = {
        "date": game_date.isoformat(),
        "sport": "nhl",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "picks": picks,
        "projections": projections,
    }
    with open(out_dir / "picks.json", "w") as f:
        json.dump(picks_out, f, indent=2)
    print(f"  ✓  Saved {len(picks)} picks + {len(projections)} projections → {out_dir}/picks.json")

    # Log to pnl
    n_logged = _auto_log_picks(picks, game_date)
    if n_logged:
        print(f"  ✓  Auto-logged {n_logged} pick(s) to data/pnl/picks.json")

    # Print slate overview
    if projections:
        W = 72
        print(f"\n  {'═'*W}")
        print(f"  NHL SLATE — {game_date.strftime('%B %d').upper()}")
        print(f"  {'─'*W}")
        print(f"  {'MATCHUP':<38} {'PROJ':>5}  {'HW%':>5}  {'TIME'}")
        print(f"  {'─'*W}")
        for p in projections:
            matchup = p["matchup"][:38]
            print(
                f"  {matchup:<38} {p['total_exp_goals']:>5.1f}  "
                f"{p['home_win_prob']:>4.0%}  {p.get('time_et','')}"
            )
        print(f"  {'═'*W}\n")

    # Update public stats
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
    except Exception as e:
        print(f"  [stats] {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NHL Picks Pipeline")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    parser.add_argument("--date", type=str, default=None, help="Date YYYYMMDD")
    args = parser.parse_args()
    main(refresh=args.refresh, target_date=args.date)
