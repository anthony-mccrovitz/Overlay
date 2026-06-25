"""
NBA Player Props Pipeline — Overlay

Fetches today's NBA events and finds prop edges for every market,
saving each market to its own file plus a combined props.json.

Output:
    output/picks/basketball_nba/YYYYMMDD/props.json                         (combined)
    output/picks/basketball_nba/YYYYMMDD/props_player_points.json
    output/picks/basketball_nba/YYYYMMDD/props_player_rebounds.json
    output/picks/basketball_nba/YYYYMMDD/props_player_assists.json
    ... etc.

Run:
    python3 run_nba_props.py
    python3 run_nba_props.py --market player_points
    python3 run_nba_props.py --date 20260515
    python3 run_nba_props.py --min-edge 10.0
    python3 run_nba_props.py --refresh
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
from src.data.nba_props import find_nba_prop_edges, NBA_PROPS_MARKETS
from src.data.odds_api import MY_BOOKS_PARAM
from src.tracking.schema import normalize_pick
from src.config.models import is_live, shadow_stake

PNL_FILE  = Path("data/pnl/picks.json")
CACHE_DIR = Path("data/cache/odds")
API_BASE  = "https://api.the-odds-api.com/v4"

# Confidence gate matching run_nba.py
MIN_PROP_CONFIDENCE = 0.53
MAX_PROP_CONFIDENCE = 0.78


def _fetch_nba_events(refresh: bool = False) -> list[dict]:
    """Fetch today's NBA events from The Odds API (or cached)."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("  [NBA props] No ODDS_API_KEY — using cached data.")
        cache = CACHE_DIR / "basketball_nba_latest.json"
        if cache.exists():
            return json.loads(cache.read_text())
        return []

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "basketball_nba_latest.json"

    if cache.exists() and not refresh:
        age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
        if age < 1800:
            return json.loads(cache.read_text())

    try:
        resp = requests.get(
            f"{API_BASE}/sports/basketball_nba/odds",
            params={
                "apiKey":      key,
                "regions":     "us,us2",
                "markets":     "h2h",
                "oddsFormat":  "american",
                "bookmakers":  MY_BOOKS_PARAM,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        cache.write_text(json.dumps(data))
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  [NBA props] Live events fetched — {remaining} requests remaining")
        return data
    except Exception as e:
        print(f"  [NBA props] Events fetch error: {e}")
        if cache.exists():
            return json.loads(cache.read_text())
        return []


def _filter_today_events(events: list[dict], target_date: str) -> list[dict]:
    """Filter events to those whose ET date matches target_date (YYYYMMDD)."""
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    target_dt = date(int(target_date[:4]), int(target_date[4:6]), int(target_date[6:]))

    def _et_date(iso: str) -> date:
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET).date()
        except Exception:
            return date.min

    filtered = [e for e in events if _et_date(e.get("commence_time", "")) == target_dt]
    if not filtered:
        # Fallback: all future events
        now_utc = datetime.now(timezone.utc)
        filtered = [
            e for e in events
            if datetime.fromisoformat(
                e.get("commence_time", "2000-01-01T00:00:00Z").replace("Z", "+00:00")
            ) > now_utc
        ]
    return filtered


def _auto_log_picks(edges: list[dict], game_date: date) -> int:
    """Log prop edges to data/pnl/picks.json with their specific market name."""
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

    now   = datetime.now(timezone.utc).isoformat()
    added = 0

    for e in edges:
        direction = e.get("direction", "OVER")
        market    = e.get("market", "player_points")
        line      = e.get("line")
        player    = e.get("player", "")
        raw = {
            "date":        game_date.isoformat(),
            "sport":       "basketball_nba",
            "market":      market,
            "direction":   direction,
            "team":        f"{player} {direction} {line}",
            "matchup":     e.get("matchup", ""),
            "odds":        e.get("odds", -110),
            "line":        line,
            "sportsbook":  e.get("book", ""),
            "model_prob":  e.get("model_prob"),
            "edge_pct":    e.get("edge_pct"),
            "stake":       shadow_stake("basketball_nba", market),
            "card_pick":   is_live("basketball_nba", market),
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


def _apply_confidence_gate(edges: list[dict]) -> list[dict]:
    """Keep one edge per player (best), within the calibrated confidence window."""
    seen: dict[str, dict] = {}
    for prop in sorted(edges, key=lambda x: float(x.get("edge_pct", 0)), reverse=True):
        player = prop.get("player", "")
        conf   = float(prop.get("model_prob", 0))
        if (
            player
            and player not in seen
            and MIN_PROP_CONFIDENCE <= conf <= MAX_PROP_CONFIDENCE
        ):
            seen[player] = prop
    return list(seen.values())


def run_nba_props(args: argparse.Namespace) -> int:
    market_filter = getattr(args, "market", None)
    min_edge      = getattr(args, "min_edge", 0.12)  # fraction (nba_props uses 0.12)
    refresh       = getattr(args, "refresh", False)
    date_str      = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    game_date     = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))

    # Determine which markets to run
    if market_filter:
        # Accept either short form or full form
        _market_aliases = {
            "player-points":               "player_points",
            "player-rebounds":             "player_rebounds",
            "player-assists":              "player_assists",
            "player-threes":               "player_threes",
            "player-pra":                  "player_points_rebounds_assists",
            "player_pra":                  "player_points_rebounds_assists",
            "player-blocks":               "player_blocks",
            "player-steals":               "player_steals",
        }
        canonical = _market_aliases.get(market_filter, market_filter)
        if canonical not in NBA_PROPS_MARKETS:
            print(f"  Unknown market: {market_filter}")
            print(f"  Valid markets: {', '.join(NBA_PROPS_MARKETS)}")
            return 1
        markets_to_run = [canonical]
    else:
        markets_to_run = list(NBA_PROPS_MARKETS)

    print(f"\n{'='*60}")
    print(f"  NBA Player Props — Edge Detection")
    print(f"  {game_date.strftime('%B %d, %Y')}  |  markets: {', '.join(markets_to_run)}")
    print(f"{'='*60}")

    # Fetch events
    print("\n  Fetching NBA events...")
    all_events = _fetch_nba_events(refresh=refresh)
    events = _filter_today_events(all_events, date_str)
    if not events:
        print(f"  No NBA games found for {date_str}.")
        return 0
    print(f"  Found {len(events)} game(s):")
    for ev in events:
        print(f"    {ev['away_team']} @ {ev['home_team']}")

    # Run find_nba_prop_edges once (it queries all markets internally)
    print(f"\n  Running NBA prop model (markets: {', '.join(markets_to_run)})...")
    all_raw_edges = find_nba_prop_edges(events[:4])  # cap at 4 games like run_nba.py
    print(f"  Raw edges found: {len(all_raw_edges)}")

    # Filter to requested markets
    if market_filter:
        canonical = _market_aliases.get(market_filter, market_filter) if market_filter else None
        all_raw_edges = [e for e in all_raw_edges if e.get("market") == canonical]

    # Apply confidence gate (per-player dedup)
    confident_edges = _apply_confidence_gate(all_raw_edges)
    print(
        f"  After confidence gate ({MIN_PROP_CONFIDENCE}–{MAX_PROP_CONFIDENCE}): "
        f"{len(confident_edges)} edges"
    )

    # Sort by edge desc
    confident_edges.sort(key=lambda x: float(x.get("edge_pct", 0)), reverse=True)

    # Print top edges
    if confident_edges:
        print(f"\n  Top edges:")
        for e in confident_edges[:15]:
            print(
                f"    {e['player']:25s}  {e['direction']} {e['line']}  "
                f"[{e['market']}]  edge={e['edge_pct']:+.1f}%  "
                f"odds={e['odds']:+d}  model={e['model_prob']:.1%}  [{e['book']}]"
            )
    else:
        print("  No edges found.")

    # ── Save outputs ───────────────────────────────────────────────────────────
    out_dir = Path("output/picks/basketball_nba") / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    # Combined props.json (backward compat)
    combined_path = out_dir / "props.json"
    combined_path.write_text(json.dumps(confident_edges, indent=2))
    print(f"\n  Combined props → {combined_path}")

    # Per-market files
    markets_in_output = {e.get("market") for e in confident_edges if e.get("market")}
    for market in markets_in_output:
        market_edges = [e for e in confident_edges if e.get("market") == market]
        # Filename: props_player_points.json
        fname = f"props_{market}.json"
        market_path = out_dir / fname
        market_path.write_text(json.dumps(market_edges, indent=2))
        print(f"  {market:45s} → {market_path.name}  ({len(market_edges)} edge(s))")

    # Also write empty files for markets that had no edges (makes it clear the run happened)
    for market in NBA_PROPS_MARKETS:
        if market not in markets_in_output:
            fname = f"props_{market}.json"
            market_path = out_dir / fname
            if not market_path.exists():
                market_path.write_text("[]")

    # ── Log to PnL ─────────────────────────────────────────────────────────────
    added = _auto_log_picks(confident_edges, game_date)
    if added:
        print(f"\n  Logged {added} NBA prop edge(s) to PnL (market-specific).")
    else:
        print(f"\n  No new picks to log (already logged or no card-pick markets).")

    # ── CLV snapshot ────────────────────────────────────────────────────────────
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} NBA prop pick(s)")
    except Exception as err:
        print(f"  [CLV snapshot] {err}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    _market_choices = NBA_PROPS_MARKETS + [
        "player-points", "player-rebounds", "player-assists",
        "player-threes", "player-pra", "player_pra", "player-blocks", "player-steals",
    ]

    parser = argparse.ArgumentParser(description="NBA player props picks pipeline")
    parser.add_argument(
        "--market", type=str, default=None,
        metavar="MARKET",
        help=(
            "Single market to run (default: all). "
            f"Options: {', '.join(NBA_PROPS_MARKETS)}"
        ),
    )
    parser.add_argument("--min-edge", type=float, default=0.12,
                        help="Min edge as fraction (default 0.12 = 12%%)")
    parser.add_argument("--date",    type=str, help="Date YYYYMMDD (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    args = parser.parse_args()
    sys.exit(run_nba_props(args))
