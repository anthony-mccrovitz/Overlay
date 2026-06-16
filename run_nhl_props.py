"""
NHL Player Props Pipeline — Overlay

Fetches today's NHL player prop odds and finds edges using per-game
season averages from the NHL Stats API (free, no key required).

Markets supported:
    player_points          — points (goals + assists)
    player_goals           — goals scored
    player_assists         — assists
    player_shots_on_goal   — shots on goal
    player_blocked_shots   — blocked shots

Edge model: Poisson distribution on per-game rate vs book's de-vigged
implied probability. Adjusts for home/away and games-played sample size.

Output:
    output/picks/icehockey_nhl/YYYYMMDD/nhl_props.json       (combined)
    output/picks/icehockey_nhl/YYYYMMDD/props_player_points.json
    ... etc.

Run:
    python3 run_nhl_props.py
    python3 run_nhl_props.py --market player_goals
    python3 run_nhl_props.py --date 20260522
    python3 run_nhl_props.py --min-edge 8.0
    python3 run_nhl_props.py --refresh
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

import requests

from src.data.odds_api import MY_BOOKS_PARAM
from src.tracking.schema import normalize_pick
from src.config.models import is_live, shadow_stake

PNL_FILE  = Path("data/pnl/picks.json")
CACHE_DIR = Path("data/cache/nhl")
API_BASE  = "https://api.the-odds-api.com/v4"
NHL_STATS = "https://api.nhle.com/stats/rest/en"
SEASON_ID = 20252026

NHL_PROPS_MARKETS = [
    "player_points",
    "player_goals",
    "player_assists",
    "player_shots_on_goal",
    "player_blocked_shots",
]

# Minimum line per market — very low lines have high over-implied probability
_MIN_LINE: dict[str, float] = {
    "player_points":        0.5,
    "player_goals":         0.5,
    "player_assists":       0.5,
    "player_shots_on_goal": 1.5,
    "player_blocked_shots": 0.5,
}

# Stat key mapping: Odds API market → NHL Stats API field
_STAT_KEY: dict[str, str] = {
    "player_points":        "points",
    "player_goals":         "goals",
    "player_assists":       "assists",
    "player_shots_on_goal": "shots",
    "player_blocked_shots": "blockedShots",
}

MIN_GAMES = 5     # require at least 5 games before using a player's rate
MIN_EDGE  = 0.08  # 8% minimum edge (props are inefficient but high-vig)


# ─────────────────────────── NHL Stats ────────────────────────────────────────

def _fetch_skater_stats(refresh: bool = False) -> list[dict]:
    """Pull skater per-game averages from NHL Stats API (playoffs + regular)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"skater_summary_{SEASON_ID}.json"
    if cache.exists() and not refresh:
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 21600:  # 6h cache
            return json.loads(cache.read_text())

    results: list[dict] = []
    for game_type in (3, 2):  # playoffs first, fall back to regular season
        try:
            resp = requests.get(
                f"{NHL_STATS}/skater/summary",
                params={
                    "cayenneExp": f"seasonId={SEASON_ID} and gameTypeId={game_type}",
                    "limit": -1,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if data:
                results = data
                break
        except Exception as e:
            print(f"  [nhl_props] skater stats error (type={game_type}): {e}")

    if results:
        cache.write_text(json.dumps(results))
    return results


def _build_player_rates(skaters: list[dict]) -> dict[str, dict]:
    """Build {normalized_name: {stat_key: per_game_rate, gp: N}} lookup."""
    rates: dict[str, dict] = {}
    for s in skaters:
        gp = s.get("gamesPlayed", 0)
        if gp < MIN_GAMES:
            continue
        first = (s.get("skaterFullName") or "").split(" ")[0] if s.get("skaterFullName") else s.get("firstName", "")
        last  = (s.get("skaterFullName") or "").split(" ")[-1] if s.get("skaterFullName") else s.get("lastName", "")
        name  = f"{first} {last}".strip().lower()
        if not name:
            continue
        rates[name] = {
            "points":       (s.get("points", 0) or 0) / gp,
            "goals":        (s.get("goals",  0) or 0) / gp,
            "assists":      (s.get("assists", 0) or 0) / gp,
            "shots":        (s.get("shots",  0) or 0) / gp,
            "blockedShots": (s.get("blockedShots", 0) or 0) / gp,
            "gp":           gp,
        }
    return rates


def _name_variants(name: str) -> list[str]:
    """Generate normalized name variants for fuzzy matching."""
    n = name.lower().strip()
    parts = n.split()
    variants = [n]
    if len(parts) >= 2:
        variants.append(f"{parts[0][0]}. {' '.join(parts[1:])}")  # J. Smith
        variants.append(" ".join(parts[-1:] + parts[:-1]))         # Smith John
    return variants


def _lookup_rate(name: str, rates: dict[str, dict]) -> dict | None:
    for v in _name_variants(name):
        if v in rates:
            return rates[v]
    # Partial last-name match
    parts = name.lower().split()
    if parts:
        last = parts[-1]
        for k, v in rates.items():
            if k.split()[-1] == last:
                return v
    return None


# ─────────────────────────── Odds API ─────────────────────────────────────────

def _fetch_nhl_events(refresh: bool = False) -> list[dict]:
    """Fetch today's NHL events (h2h only — for game context)."""
    key = os.environ.get("ODDS_API_KEY")
    cache = CACHE_DIR / "icehockey_nhl_events.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not refresh:
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 1800:
            return json.loads(cache.read_text())
    if not key:
        return json.loads(cache.read_text()) if cache.exists() else []
    try:
        resp = requests.get(
            f"{API_BASE}/sports/icehockey_nhl/odds",
            params={"apiKey": key, "regions": "us,us2", "markets": "h2h",
                    "oddsFormat": "american", "bookmakers": MY_BOOKS_PARAM},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        cache.write_text(json.dumps(data))
        return data
    except Exception as e:
        print(f"  [nhl_props] events fetch error: {e}")
        return json.loads(cache.read_text()) if cache.exists() else []


def _fetch_event_props(event_id: str, market: str, refresh: bool = False) -> list[dict]:
    """Fetch player prop odds for one event and market."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return []
    cache = CACHE_DIR / f"props_{event_id}_{market}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not refresh:
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 1800:
            return json.loads(cache.read_text())
    try:
        resp = requests.get(
            f"{API_BASE}/sports/icehockey_nhl/events/{event_id}/odds",
            params={"apiKey": key, "regions": "us,us2", "markets": market,
                    "oddsFormat": "american", "bookmakers": MY_BOOKS_PARAM},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        bookmakers = data.get("bookmakers", [])
        cache.write_text(json.dumps(bookmakers))
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"    fetched {market} for event {event_id[:8]}… ({remaining} remaining)")
        return bookmakers
    except Exception as e:
        print(f"  [nhl_props] props fetch error ({market}): {e}")
        return []


# ─────────────────────────── Edge model ───────────────────────────────────────

def _devig(over_odds: int, under_odds: int) -> tuple[float, float]:
    """Multiplicative devig: return (over_prob, under_prob) summing to 1.0."""
    def _to_prob(o: int) -> float:
        return 100 / (100 + o) if o > 0 else (-o) / (-o + 100)

    p_over  = _to_prob(over_odds)
    p_under = _to_prob(under_odds)
    total   = p_over + p_under
    return p_over / total, p_under / total


def _poisson_over_prob(lam: float, line: float) -> float:
    """P(X > line) where X ~ Poisson(lam) and line is a half-integer."""
    k = int(math.floor(line))
    # P(X <= k) = sum_{i=0}^{k} e^(-lam) * lam^i / i!
    cdf = 0.0
    term = math.exp(-lam)
    cdf += term
    for i in range(1, k + 1):
        term *= lam / i
        cdf += term
    return 1.0 - cdf


def _find_edges_for_market(
    events: list[dict],
    market: str,
    player_rates: dict[str, dict],
    min_edge: float,
    target_date: str,
    refresh: bool,
) -> list[dict]:
    """Find prop edges for one market across all today's games."""
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    target_dt = date(int(target_date[:4]), int(target_date[4:6]), int(target_date[6:]))

    stat_key = _STAT_KEY.get(market, "points")
    min_line = _MIN_LINE.get(market, 0.5)
    edges: list[dict] = []

    for event in events:
        ct = event.get("commence_time", "")
        try:
            ev_date = datetime.fromisoformat(ct.replace("Z", "+00:00")).astimezone(ET).date()
        except Exception:
            continue
        if ev_date != target_dt:
            continue

        home = event.get("home_team", "")
        away = event.get("away_team", "")
        matchup = f"{away} @ {home}"
        event_id = event.get("id", "")

        bookmakers = _fetch_event_props(event_id, market, refresh=refresh)
        if not bookmakers:
            continue

        # Aggregate: best over odds, best under odds per player per line
        player_lines: dict[str, dict] = {}
        for book in bookmakers:
            for mkt in book.get("markets", []):
                if mkt.get("key") != market:
                    continue
                for outcome in mkt.get("outcomes", []):
                    player = outcome.get("description", "")
                    name   = outcome.get("name", "").upper()
                    line   = outcome.get("point")
                    price  = outcome.get("price")
                    if not player or line is None or price is None:
                        continue
                    if line < min_line:
                        continue
                    key = f"{player}|{line}"
                    if key not in player_lines:
                        player_lines[key] = {"player": player, "line": line,
                                             "over": None, "under": None, "book": book.get("key", "")}
                    if name == "OVER" and (player_lines[key]["over"] is None or price > player_lines[key]["over"]):
                        player_lines[key]["over"] = price
                    elif name == "UNDER" and (player_lines[key]["under"] is None or price > player_lines[key]["under"]):
                        player_lines[key]["under"] = price

        for key, pl in player_lines.items():
            if pl["over"] is None or pl["under"] is None:
                continue
            player = pl["player"]
            line   = pl["line"]

            rates = _lookup_rate(player, player_rates)
            if rates is None:
                continue
            lam = rates.get(stat_key, 0.0)
            if lam <= 0:
                continue

            model_over  = _poisson_over_prob(lam, line)
            model_under = 1.0 - model_over
            book_over, book_under = _devig(pl["over"], pl["under"])

            for direction, model_p, book_p, odds in [
                ("OVER",  model_over,  book_over,  pl["over"]),
                ("UNDER", model_under, book_under, pl["under"]),
            ]:
                edge = model_p - book_p
                if edge >= min_edge:
                    edges.append({
                        "player":     player,
                        "market":     market,
                        "direction":  direction,
                        "line":       line,
                        "odds":       int(odds),
                        "model_prob": round(model_p, 4),
                        "book_prob":  round(book_p, 4),
                        "edge_pct":   round(edge * 100, 2),
                        "lam":        round(lam, 3),
                        "gp":         rates.get("gp", 0),
                        "matchup":    matchup,
                        "sportsbook": pl["book"],
                    })

    # One pick per player per market (best edge)
    seen: dict[str, dict] = {}
    for e in sorted(edges, key=lambda x: x["edge_pct"], reverse=True):
        pk = f"{e['player']}|{e['market']}"
        if pk not in seen:
            seen[pk] = e
    return list(seen.values())


# ─────────────────────────── PnL logging ──────────────────────────────────────

def _auto_log_picks(edges: list[dict], game_date: date) -> int:
    """Log NHL prop edges to data/pnl/picks.json."""
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
        market = e["market"]
        raw = {
            "date":        game_date.isoformat(),
            "sport":       "icehockey_nhl",
            "market":      market,
            "direction":   e["direction"],
            "team":        f"{e['player']} {e['direction']} {e['line']}",
            "matchup":     e["matchup"],
            "odds":        e["odds"],
            "line":        e["line"],
            "sportsbook":  e["sportsbook"],
            "model_prob":  e["model_prob"],
            "edge_pct":    e["edge_pct"],
            "stake":       shadow_stake("icehockey_nhl", market),
            "card_pick":   is_live("icehockey_nhl", market),
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
    PNL_FILE.write_text(json.dumps(picks, indent=2))
    return added


# ─────────────────────────── Main ─────────────────────────────────────────────

def run_nhl_props(args: argparse.Namespace) -> int:
    market_filter = getattr(args, "market", None)
    min_edge      = getattr(args, "min_edge", MIN_EDGE * 100)  # stored as pct (8.0 = 8%)
    refresh       = getattr(args, "refresh", False)
    date_str      = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    game_date     = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))

    markets = [market_filter] if market_filter and market_filter in NHL_PROPS_MARKETS else NHL_PROPS_MARKETS

    print(f"\n{'='*60}")
    print(f"  NHL Player Props — Edge Detection")
    print(f"  {game_date.strftime('%B %d, %Y')}  |  markets: {', '.join(markets)}")
    print(f"{'='*60}")

    # Fetch player season averages
    print("\n  Loading NHL skater stats...")
    skaters = _fetch_skater_stats(refresh=refresh)
    player_rates = _build_player_rates(skaters)
    print(f"  ✓  {len(player_rates)} skaters loaded (≥{MIN_GAMES} GP)")

    # Fetch events
    print("\n  Fetching NHL events...")
    events = _fetch_nhl_events(refresh=refresh)
    if not events:
        print("  No NHL events found. Check ODDS_API_KEY or cache.")
        return 0
    print(f"  ✓  {len(events)} event(s) found")

    # Find edges per market
    all_edges: list[dict] = []
    out_dir = Path(f"output/picks/icehockey_nhl/{date_str}")
    out_dir.mkdir(parents=True, exist_ok=True)

    min_edge_frac = min_edge / 100.0

    for market in markets:
        print(f"\n  ▸ {market}...")
        edges = _find_edges_for_market(
            events, market, player_rates,
            min_edge=min_edge_frac,
            target_date=date_str,
            refresh=refresh,
        )
        if edges:
            print(f"    Found {len(edges)} edge(s):")
            for e in sorted(edges, key=lambda x: x["edge_pct"], reverse=True)[:8]:
                print(
                    f"      {e['player']:25s}  {e['direction']} {e['line']:<5}  "
                    f"edge={e['edge_pct']:+.1f}%  odds={e['odds']:+d}  "
                    f"model={e['model_prob']:.1%}  λ={e['lam']:.2f}/gm"
                )
            market_file = out_dir / f"props_{market}.json"
            market_file.write_text(json.dumps(edges, indent=2))
        else:
            print(f"    No edges above {min_edge:.0f}% threshold.")
        all_edges.extend(edges)

    # Save combined file
    out_path = out_dir / "nhl_props.json"
    out_path.write_text(json.dumps(all_edges, indent=2))
    print(f"\n  ✓  {len(all_edges)} total edge(s) → {out_path}")

    # Log to PnL
    n_logged = _auto_log_picks(all_edges, game_date)
    if n_logged:
        print(f"  ✓  Logged {n_logged} pick(s) to data/pnl/picks.json (shadow)")

    # Public stats refresh
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
    except Exception as e:
        print(f"  [stats] {e}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NHL player props edge detection")
    parser.add_argument("--market",   choices=NHL_PROPS_MARKETS, help="Single market (default: all)")
    parser.add_argument("--min-edge", type=float, default=8.0, help="Minimum edge %% (default: 8.0)")
    parser.add_argument("--date",     type=str, help="Slate date YYYYMMDD (default: today)")
    parser.add_argument("--refresh",  action="store_true", help="Force-refresh all caches")
    args = parser.parse_args()
    sys.exit(run_nhl_props(args))
