"""
Soccer Daily Picks Pipeline — ChefTonyBets

Generates picks for today's soccer slate across all active leagues and saves to:
    output/picks/<sport_key>/YYYYMMDD/picks.json

Priority league order (Dixon-Coles edge strongest in mid-tier leagues):
    EPL, La Liga, Serie A, Bundesliga, Ligue 1, Championship, World Cup

Odds source: The Odds API
Model: Rolling Elo + 2-param Poisson (v2, Dixon-Coles)

Run:
    python3 run_soccer.py
    python3 run_soccer.py --refresh            # force-refresh odds cache
    python3 run_soccer.py --date 20260611      # specific date
    python3 run_soccer.py --fit                # retrain model before running
    python3 run_soccer.py --league epl         # single league only
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

from src.models.soccer_model_v2 import SoccerModelV2, load_or_fit_model_v2
from src.data.odds_api import MY_BOOKS_PARAM
from src.tracking.schema import normalize_pick
from src.config.models import is_live, shadow_stake

import requests

API_BASE  = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path("data/cache/odds")
PNL_FILE  = Path("data/pnl/picks.json")

# League priority order. Dixon-Coles edge is strongest in mid-tier leagues
# (Championship, Ligue 1, Serie A) where books price less efficiently than EPL.
# World Cup included for the June 2026 tournament.
SOCCER_LEAGUES: list[tuple[str, str]] = [
    ("soccer_epl",                          "EPL"),
    ("soccer_spain_la_liga",                "La Liga"),
    ("soccer_italy_serie_a",                "Serie A"),
    ("soccer_germany_bundesliga",           "Bundesliga"),
    ("soccer_france_ligue_one",             "Ligue 1"),
    ("soccer_uefa_champs_league",           "Champions League"),
    ("soccer_usa_mls",                      "MLS"),
    ("soccer_mexico_ligamx",                "Liga MX"),
    ("soccer_england_championship",         "Championship"),
    ("soccer_conmebol_copa_libertadores",   "Copa Libertadores"),
    ("soccer_fifa_world_cup",               "World Cup"),     # Active June 2026
]

# Short alias → sport key (for --league flag)
_LEAGUE_ALIASES: dict[str, str] = {
    "epl":              "soccer_epl",
    "laliga":           "soccer_spain_la_liga",
    "seriea":           "soccer_italy_serie_a",
    "bundesliga":       "soccer_germany_bundesliga",
    "ligue1":           "soccer_france_ligue_one",
    "ucl":              "soccer_uefa_champs_league",
    "championsleague":  "soccer_uefa_champs_league",
    "mls":              "soccer_usa_mls",
    "ligamx":           "soccer_mexico_ligamx",
    "mexico":           "soccer_mexico_ligamx",
    "championship":     "soccer_england_championship",
    "libertadores":     "soccer_conmebol_copa_libertadores",
    "worldcup":         "soccer_fifa_world_cup",
    "wc":               "soccer_fifa_world_cup",
}


# ─────────────────────────── Odds fetch ──────────────────────────────────────

def fetch_soccer_odds(sport_key: str, refresh: bool = False) -> list[dict]:
    """Fetch soccer odds for a specific league from The Odds API."""
    key = os.environ.get("ODDS_API_KEY")
    cache = CACHE_DIR / f"{sport_key}_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not refresh and cache.exists():
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 1800:
            with open(cache) as f:
                return json.load(f)

    if not key:
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []

    try:
        resp = requests.get(
            f"{API_BASE}/sports/{sport_key}/odds",
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
        return data
    except Exception as e:
        print(f"  [soccer/{sport_key}] API error: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


# ─────────────────────────── PnL auto-log ────────────────────────────────────

def _auto_log_picks(edges: list[dict], game_date: date, sport_key: str) -> int:
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
            "sport":       sport_key,
            "market":      market,
            "direction":   e.get("direction", ""),
            "team":        e.get("team", ""),
            "matchup":     e.get("matchup", ""),
            "odds":        e.get("odds", -110),
            "line":        e.get("line"),
            "sportsbook":  e.get("sportsbook", ""),
            "model_prob":  e.get("model_prob"),
            "edge_pct":    e.get("edge_pct"),
            "model_tier":  "tier1",  # Dixon-Coles is Tier 1 (peer-reviewed)
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

def _run_one_league(
    sport_key: str,
    league_name: str,
    model: "SoccerModelV2",
    game_date: date,
    today_str: str,
    refresh: bool,
) -> list[dict]:
    """Run picks pipeline for a single soccer league. Returns edges found."""
    import zoneinfo
    _ET = zoneinfo.ZoneInfo("America/New_York")

    events = fetch_soccer_odds(sport_key, refresh=refresh)
    if not events:
        return []

    today_events = []
    for ev in events:
        ct = ev.get("commence_time", "")
        if not ct:
            continue
        try:
            utc_dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            event_date = utc_dt.astimezone(_ET).strftime("%Y%m%d")
            if event_date == today_str:
                today_events.append(ev)
        except (ValueError, KeyError):
            pass

    if not today_events:
        return []

    print(f"\n  [{league_name}] {len(today_events)} game(s):")
    for ev in today_events:
        print(f"    {ev.get('away_team')} @ {ev.get('home_team')}")

    try:
        edges = model.find_edges(today_events, min_edge_pct=4.0)
    except Exception as e:
        print(f"  [{league_name}] model error: {e}")
        return []

    if not edges:
        print(f"  [{league_name}] No edges meet threshold.")
    else:
        print(f"  [{league_name}] {len(edges)} edge(s):")
        for e in edges[:5]:
            print(
                f"    {e['team']:30s}  {e['market']:10s}  "
                f"edge={e['edge_pct']:+.1f}%  odds={e['odds']:+d}  [{e['sportsbook']}]"
            )

    # Save league-specific output
    out_dir = Path("output/picks") / sport_key / today_str
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "picks.json").write_text(json.dumps(edges, indent=2, default=str))

    # Auto-log to PnL
    added = _auto_log_picks(edges, game_date, sport_key)
    if added:
        print(f"  [{league_name}] Logged {added} pick(s) to PnL.")

    return edges


def run_soccer(args: argparse.Namespace) -> int:
    date_str  = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    refresh   = getattr(args, "refresh", False)
    do_fit    = getattr(args, "fit", False)
    league_filter = getattr(args, "league", None)
    game_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    today_str = game_date.strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print(f"  Soccer Picks — {game_date.strftime('%B %d, %Y')}")
    print(f"{'='*60}")

    # ── Schedule guard: skip if no soccer games across any tracked league ──────
    try:
        from scripts.schedule_check import validate_and_log
        if not validate_and_log("soccer", game_date.isoformat()):
            return 0
    except Exception as _sce:
        print(f"  ⚠  Schedule check skipped ({_sce})")
    # ──────────────────────────────────────────────────────────────────────────

    # 1. Load or fit model (v2: rolling Elo + 2-param Poisson)
    if do_fit:
        model = SoccerModelV2()
        model.fit(verbose=True)
    else:
        model = load_or_fit_model_v2(verbose=True)
    # Seed with live Elo ratings so predictions use current squad strength
    model.seed_from_eloratings()

    # 2. Build league list to iterate
    if league_filter:
        sport_key = _LEAGUE_ALIASES.get(league_filter.lower(), league_filter)
        leagues_to_run = [(sport_key, league_filter.title())]
    else:
        leagues_to_run = SOCCER_LEAGUES

    # 3. Run each league
    all_edges: list[dict] = []
    leagues_active = 0
    for sport_key, league_name in leagues_to_run:
        try:
            edges = _run_one_league(sport_key, league_name, model, game_date, today_str, refresh)
            all_edges.extend(edges)
            if edges:
                leagues_active += 1
        except Exception as e:
            print(f"  [{league_name}] skipped: {e}")

    if not all_edges:
        print(f"\n  No soccer edges found across {len(leagues_to_run)} league(s) for {today_str}.")
        # Show upcoming fixtures
        print("\n  Upcoming fixtures (next 5 across all leagues):")
        upcoming: list[tuple] = []
        for sport_key, league_name in leagues_to_run[:4]:
            events = fetch_soccer_odds(sport_key)
            for ev in events:
                ct = ev.get("commence_time", "")
                try:
                    edate = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    if edate > datetime.now(timezone.utc):
                        upcoming.append((edate, league_name, ev))
                except (ValueError, KeyError):
                    pass
        upcoming.sort(key=lambda x: x[0])
        for dt, lg, ev in upcoming[:5]:
            print(f"    {dt.strftime('%Y-%m-%d %H:%M UTC')}  [{lg}]  {ev.get('away_team')} @ {ev.get('home_team')}")
        return 0

    print(f"\n  Total: {len(all_edges)} edge(s) across {leagues_active} league(s) with games today.")

    # Pinnacle disagreement guard: flag any edge >8% for manual review
    try:
        from src.betting.value_bets import flag_high_edge_picks
        high_edge = flag_high_edge_picks(all_edges, threshold_pct=8.0)
        if high_edge:
            print(f"\n  MANUAL REVIEW: {len(high_edge)} pick(s) with edge >8%:")
            for e in high_edge:
                print(f"    {e['team']}  edge={e['edge_pct']:+.1f}%  — verify line not stale")
    except Exception:
        pass

    # 4. CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} soccer pick(s)")
    except Exception as _clv_err:
        print(f"  [CLV snapshot] {_clv_err}")

    # 5. Captions — combined dir for all leagues
    combined_out_dir = Path("output/picks/soccer") / today_str
    combined_out_dir.mkdir(parents=True, exist_ok=True)
    try:
        from src.output.captions_sports import soccer_captions, write_sport_captions
        # Build list of league names that produced edges
        active_league_names: list[str] = []
        seen_sports: set[str] = set()
        for e in all_edges:
            sk = e.get("sport", "")
            if sk and sk not in seen_sports:
                seen_sports.add(sk)
                # Map sport key → display name
                for sport_key, league_name in SOCCER_LEAGUES:
                    if sport_key == sk:
                        active_league_names.append(league_name)
                        break
        captions = soccer_captions(all_edges, active_league_names, game_date)
        write_sport_captions(captions, combined_out_dir)
        print(f"  Captions → {combined_out_dir / 'captions'}/")
    except Exception as _cap_err:
        print(f"  [captions] {_cap_err}")

    # 6. Pick card (new ChefTonyBets design)
    try:
        from src.output.cards import render_soccer_card
        card_path = render_soccer_card(all_edges, card_date=game_date, out_dir=combined_out_dir)
        if card_path:
            print(f"  Card → {card_path}")
    except Exception as _card_err:
        print(f"  [card] {_card_err}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-league soccer picks pipeline")
    parser.add_argument("--date",    type=str, help="Slate date YYYYMMDD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    parser.add_argument("--fit",     action="store_true", help="Retrain Dixon-Coles model")
    parser.add_argument("--league",  type=str, help="Single league (epl, laliga, seriea, bundesliga, ligue1, championship, worldcup)")
    args = parser.parse_args()
    sys.exit(run_soccer(args))
