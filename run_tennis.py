"""
Tennis Daily Picks Pipeline — Overlay

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
from src.config.models import is_live, shadow_stake

import requests

API_BASE = "https://api.the-odds-api.com/v4"
PNL_FILE = Path("data/pnl/picks.json")
CACHE_DIR = Path("data/cache/odds")

# Odds API sport keys → surface mapping.
# Grand Slams + 1000/500-level events where Odds API has coverage.
TENNIS_SPORTS = {
    # Grand Slams
    "tennis_atp_french_open":       "clay",
    "tennis_atp_wimbledon":         "grass",
    "tennis_atp_us_open":           "hard",
    "tennis_atp_australian_open":   "hard",
    "tennis_wta_french_open":       "clay",
    "tennis_wta_wimbledon":         "grass",
    "tennis_wta_us_open":           "hard",
    "tennis_wta_australian_open":   "hard",
    # ATP/WTA tour events (non-Slam) — no qualifying gate applied
    "tennis_atp_hamburg_open":      "clay",
    "tennis_wta_strasbourg":        "clay",
    "tennis_atp_italian_open":      "clay",
    "tennis_wta_italian_open":      "clay",
    "tennis_atp_madrid_open":       "clay",
    "tennis_wta_madrid_open":       "clay",
    "tennis_atp_monte_carlo":       "clay",
    "tennis_atp_barcelona":         "clay",
    "tennis_atp_canadian_open":     "hard",
    "tennis_wta_canadian_open":     "hard",
    "tennis_atp_cincinnati":        "hard",
    "tennis_wta_cincinnati":        "hard",
    "tennis_atp_shanghai":          "hard",
    "tennis_atp_paris_masters":     "hard",
    # Grass-court Wimbledon warm-ups (June). Without these they'd default to
    # clay and the model would use the wrong-surface Elo.
    "tennis_atp_halle_open":        "grass",
    "tennis_atp_queens_club_champ": "grass",
    "tennis_wta_german_open":       "grass",
    "tennis_wta_queens_club_champ": "grass",
    "tennis_atp_stuttgart_open":    "grass",
    "tennis_wta_stuttgart_open":    "grass",
    "tennis_wta_nottingham":        "grass",
    "tennis_atp_eastbourne":        "grass",
    "tennis_wta_eastbourne":        "grass",
}

# Main draw start dates — qualifying rounds suppressed (Elo sparse for qualifiers).
# Non-Slam events are NOT listed here so the gate is skipped for them.
MAIN_DRAW_STARTS: dict[str, date] = {
    "tennis_atp_french_open":     date(2026, 5, 25),
    "tennis_wta_french_open":     date(2026, 5, 25),
    "tennis_atp_wimbledon":       date(2026, 6, 29),
    "tennis_wta_wimbledon":       date(2026, 6, 29),
    "tennis_atp_us_open":         date(2026, 8, 31),
    "tennis_wta_us_open":         date(2026, 8, 31),
    "tennis_atp_australian_open": date(2027, 1, 12),
    "tennis_wta_australian_open": date(2027, 1, 12),
}

# Cap on recommended player's American odds — anything beyond this is a qualifier-level
# longshot where Elo ratings are unreliable due to sparse match data.
MAX_PICK_ODDS = 500

# Active tournament — Roland-Garros starts May 25, 2026
DEFAULT_SPORT = "tennis_atp_french_open"


def fetch_active_tennis_sports() -> list[str]:
    """Query Odds API and return all currently active tennis sport keys."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return list(TENNIS_SPORTS.keys())
    try:
        resp = requests.get(
            f"{API_BASE}/sports",
            params={"apiKey": key},
            timeout=10,
        )
        resp.raise_for_status()
        return [
            s["key"] for s in resp.json()
            if s.get("active") and s["key"].startswith("tennis_")
        ]
    except Exception:
        return list(TENNIS_SPORTS.keys())


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
                "markets":    "h2h,totals",
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
            raw = json.loads(PNL_FILE.read_text())
            pnl_data = {"picks": raw} if isinstance(raw, list) else raw
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
            "model_tier":  "tier1",  # Kovalchik 2016 / Angelini 2022 peer-reviewed Elo
            "stake":       shadow_stake("tennis", market),
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
    PNL_FILE.write_text(json.dumps(picks, indent=2))
    return added


def _run_one_tennis_sport(sport: str, surface: str, best_of: int, refresh: bool,
                           game_date: "date", today_str: str) -> list[dict]:
    """Run the tennis model for a single sport key. Returns list of edges found."""
    tournament = sport.replace("tennis_atp_", "").replace("tennis_wta_", "").replace("_", " ").title()

    # Gate: skip qualifying rounds for Grand Slams only
    main_draw_start = MAIN_DRAW_STARTS.get(sport)
    if main_draw_start and game_date < main_draw_start:
        days_left = (main_draw_start - game_date).days
        print(f"  [{tournament}] Qualifying period — main draw in {days_left}d. Skipping.")
        return []

    events = fetch_tennis_odds(sport, refresh=refresh)
    if not events:
        return []

    import zoneinfo
    _ET = zoneinfo.ZoneInfo("America/New_York")
    today_events = []
    for ev in events:
        ct = ev.get("commence_time", "")
        if not ct:
            continue
        try:
            utc_dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            if utc_dt.astimezone(_ET).strftime("%Y%m%d") == today_str:
                today_events.append(ev)
        except (ValueError, KeyError):
            pass

    if not today_events:
        return []

    print(f"\n  [{tournament}] {len(today_events)} match(es) on slate")
    model = TennisModel(surface=surface)
    edges = model.find_edges(today_events, surface=surface, best_of=best_of)
    edges = [e for e in edges if abs(e.get("odds", 0)) <= MAX_PICK_ODDS]

    # ── Games-total edges (over/under total games) ────────────────────────────
    def _imp(o): o=float(o); return (100/(o+100)) if o>0 else (abs(o)/(abs(o)+100))
    for ev in today_events:
        a = ev.get("home_team", ""); b = ev.get("away_team", "")
        if not a or not b:
            continue
        for bm in ev.get("bookmakers", []):
            book = bm.get("title", "")
            for mk in bm.get("markets", []):
                if mk.get("key") != "totals":
                    continue
                over_o = next((o for o in mk.get("outcomes", []) if o.get("name") == "Over"), None)
                under_o = next((o for o in mk.get("outcomes", []) if o.get("name") == "Under"), None)
                if not over_o or not under_o or over_o.get("point") is None:
                    continue
                line = float(over_o["point"])
                gt = model.games_total_prob(a, b, line, best_of=best_of)
                op = _imp(float(over_o["price"])); up = _imp(float(under_o["price"]))
                tot = op + up
                if tot <= 0:
                    continue
                for direction, mp, price, imp in [
                    ("OVER", gt["over"], float(over_o["price"]), op / tot),
                    ("UNDER", gt["under"], float(under_o["price"]), up / tot),
                ]:
                    edge = (mp - imp) * 100.0
                    if edge >= 4.0 and abs(price) <= MAX_PICK_ODDS:
                        edges.append({
                            "sport": sport, "market": "total", "direction": direction,
                            "team": f"{direction} {line}", "matchup": f"{b} @ {a}",
                            "odds": int(price), "best_odds": int(price), "line": line,
                            "model_prob": round(mp, 4), "implied_prob": round(imp, 4),
                            "edge_pct": round(edge, 2), "sportsbook": book,
                        })

    # Dedup totals to the best-priced edge per (matchup, direction, line);
    # moneyline edges (already deduped by find_edges) pass through untouched.
    non_totals = [e for e in edges if e.get("market") != "total"]
    best_totals: dict[tuple, dict] = {}
    for e in (e for e in edges if e.get("market") == "total"):
        k = (e["matchup"], e["direction"], e["line"])
        if k not in best_totals or e["edge_pct"] > best_totals[k]["edge_pct"]:
            best_totals[k] = e
    edges = non_totals + list(best_totals.values())

    # Tag sport key on each edge so auto-log knows which tournament
    for e in edges:
        e["sport"] = sport

    return edges


def run_tennis(args: argparse.Namespace) -> int:
    sport_arg = getattr(args, "sport", None)
    surface_arg = getattr(args, "surface", None)
    best_of = getattr(args, "best_of", 3)
    refresh = getattr(args, "refresh", False)
    date_str = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    game_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    today_str = game_date.strftime("%Y%m%d")

    # Determine which sport keys to run
    if sport_arg:
        sports_to_run = [sport_arg]
    else:
        # Dynamically detect all active tennis events on Odds API
        active_keys = fetch_active_tennis_sports()
        sports_to_run = [k for k in active_keys if k in TENNIS_SPORTS or k.startswith("tennis_")]
        if not sports_to_run:
            sports_to_run = [DEFAULT_SPORT]

    print(f"\n{'='*60}")
    print(f"  Tennis Picks — {game_date.strftime('%B %d, %Y')}")
    print(f"  Scanning {len(sports_to_run)} active tournament(s): {', '.join(sports_to_run)}")
    print(f"{'='*60}")

    # Legacy single-sport path used below for output/captions — keep surface logic
    sport   = sport_arg or sports_to_run[0]
    surface = surface_arg or TENNIS_SPORTS.get(sport, "clay")
    tournament = sport.replace("tennis_atp_", "").replace("tennis_wta_", "").replace("_", " ").title()

    print(f"\n{'='*60}")
    print(f"  Tennis Picks — {tournament} ({surface.capitalize()})")
    print(f"  {game_date.strftime('%B %d, %Y')}  |  Best of {best_of}")
    print(f"{'='*60}")

    # 0. Refresh live ATP Elo (from JeffSackmann data, cached 12h)
    try:
        from src.data.tennis_data import load_cached_elo, refresh_player_db
        if not load_cached_elo(verbose=True):
            print("  [Elo] Refreshing ATP Elo from 2023-2026 match history...")
            refresh_player_db(verbose=True)
    except Exception as _elo_err:
        print(f"  [Elo refresh] {_elo_err} — using static ratings")

    # 1. Run all active tournaments
    all_edges: list[dict] = []
    for sk in sports_to_run:
        surf = surface_arg or TENNIS_SPORTS.get(sk, "clay")
        edges_for_sport = _run_one_tennis_sport(sk, surf, best_of, refresh, game_date, today_str)
        all_edges.extend(edges_for_sport)

    edges = all_edges

    if not edges:
        print(f"  No edges meet threshold today across {len(sports_to_run)} tournament(s).")
    else:
        print(f"\n  Found {len(edges)} edge(s) across all tournaments:")
        for e in edges[:10]:
            tourn_label = e.get("sport", sport).replace("tennis_atp_", "ATP ").replace("tennis_wta_", "WTA ").replace("_", " ").title()
            print(
                f"    [{tourn_label}] {e['team']:30s}  edge={e['edge_pct']:+.1f}%  "
                f"odds={e['odds']:+d}  model={e['model_prob']:.1%}  [{e['sportsbook']}]"
            )

    # Pinnacle disagreement guard
    try:
        from src.betting.value_bets import flag_high_edge_picks
        high_edge = flag_high_edge_picks(edges, threshold_pct=8.0)
        if high_edge:
            print(f"\n  ⚠  MANUAL REVIEW: {len(high_edge)} pick(s) with edge >8%:")
            for e in high_edge:
                print(f"    {e['team']}  edge={e['edge_pct']:+.1f}%  — verify Elo is current")
    except Exception:
        pass

    # 3. Save output — one file per tournament
    total_saved = 0
    by_sport: dict[str, list] = {}
    for e in edges:
        sk = e.get("sport", sport)
        by_sport.setdefault(sk, []).append(e)

    for sk, sk_edges in by_sport.items():
        sk_dir = Path("output/picks") / sk / today_str
        sk_dir.mkdir(parents=True, exist_ok=True)
        (sk_dir / "picks.json").write_text(json.dumps(sk_edges, indent=2, default=str))
        print(f"\n  Picks saved → {sk_dir}/picks.json ({len(sk_edges)} pick(s))")
        total_saved += len(sk_edges)

    out_dir = Path("output/picks") / sport / today_str
    out_dir.mkdir(parents=True, exist_ok=True)

    # 4. Auto-log — use per-edge sport key
    added = 0
    for sk, sk_edges in by_sport.items():
        added += _auto_log_picks(sk_edges, game_date, sk)
    if added:
        print(f"  Logged {added} pick(s) to PnL.")

    # 5. CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} tennis pick(s)")
    except Exception as _clv_err:
        print(f"  [CLV snapshot] {_clv_err}")

    # 6. Pick card (new Overlay design)
    try:
        from src.output.cards import render_tennis_card
        card_path = render_tennis_card(
            edges, tournament=tournament, surface=surface,
            card_date=game_date, out_dir=out_dir,
        )
        if card_path:
            print(f"  Card → {card_path}")
    except Exception as _card_err:
        print(f"  [card] {_card_err}")

    # 7. Captions
    try:
        from src.output.captions_sports import tennis_captions, write_sport_captions
        captions = tennis_captions(edges, tournament, surface, game_date)
        write_sport_captions(captions, out_dir)
        print(f"  Captions → {out_dir / 'captions'}/")
    except Exception as _cap_err:
        print(f"  [captions] {_cap_err}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tennis picks pipeline")
    parser.add_argument("--sport",   type=str, default=None,
                        help="Odds API sport key. Default: auto-detect all active "
                             "tournaments via fetch_active_tennis_sports().")
    parser.add_argument("--surface", type=str, choices=["clay", "hard", "grass"],
                        help="Court surface (auto-detected from sport key if omitted)")
    parser.add_argument("--best-of", type=int, default=3, choices=[3, 5],
                        help="Match format: 3 or 5 sets (default 3)")
    parser.add_argument("--date",    type=str, help="Slate date YYYYMMDD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    args = parser.parse_args()
    sys.exit(run_tennis(args))
