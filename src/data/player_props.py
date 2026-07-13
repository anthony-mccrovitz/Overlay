"""
Player props edge detection — strikeouts, hits, home runs.

Pipeline:
  1. Fetch event IDs for today's MLB games from The Odds API
  2. For each event, pull pitcher_strikeouts / batter_hits / batter_home_runs markets
  3. De-vig each line to get fair probability
  4. Compare to our projection (K/9-based for Ks, batting stats for hits)
  5. Return picks where model edge >= threshold

Odds API cost: 1 request per event per market. ~10 games × 3 markets = 30 requests/day.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.data.odds_api import MY_BOOKS_PARAM

load_dotenv()

CACHE_DIR = Path("data/cache/props")
API_BASE = "https://api.the-odds-api.com/v4"

# Props markets to pull
# NOTE: batter_hits, batter_total_bases, AND batter_home_runs all removed from this
# pipeline — they produced identical per-game projections for every batter (no
# per-batter signal). Per-batter projections live in src/models/mlb_batter_props.py
# which uses real season stats (BA, HR/AB) matched against opp pitcher quality.
# This module now handles only pitcher_strikeouts (where projection IS per-pitcher).
PROP_MARKETS = [
    "pitcher_strikeouts",
    # batter_home_runs removed: population-level lambda, not batter-specific — identical
    # probability for every batter facing the same pitcher, produces junk edges
]

# Min edge to surface as a pick (raw probability edge over implied)
MIN_EDGE = 0.04
MIN_OVER_PROB = 0.52      # must project >52% to recommend over
MIN_IMPLIED_PROB = 0.35   # no picks at odds better than +186 — model can't price longshots
MIN_EDGE_OVER = 0.10      # OVERs need higher bar: historically -12.2u vs UNDERs +3.0u
OVER_BIAS_CORRECTION = 0.06  # subtract from p_over: books shade lines, OVERs lose 41% WR


def _api_key() -> str | None:
    return os.environ.get("ODDS_API_KEY")


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _cached_get(key: str, url: str, params: dict, max_age_s: int = 3600) -> dict | list | None:
    cache = _cache_path(key)
    if cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < max_age_s:
            with open(cache) as f:
                return json.load(f)
    api_key = _api_key()
    if not api_key:
        return None
    try:
        resp = requests.get(url, params={**params, "apiKey": api_key}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        print(f"  [props] API error: {e}")
        return None


def _devig(over_odds: float, under_odds: float) -> float:
    """Convert American odds pair to de-vigged probability for the over."""
    def to_prob(a: float) -> float:
        if a > 0:
            return 100 / (a + 100)
        return abs(a) / (abs(a) + 100)

    p_over = to_prob(over_odds)
    p_under = to_prob(under_odds)
    total = p_over + p_under
    if total <= 0:
        return 0.5
    return p_over / total


def fetch_mlb_event_ids(game_date: date | None = None) -> list[dict]:
    """
    Return list of {event_id, home_team, away_team, commence_time}
    for today's (or given date's) MLB games.

    The day window is US/Eastern, converted to UTC for the API. A naive
    UTC window (00:00Z-23:59Z) leaks the previous evening's West Coast
    games (which commence after 00:00Z) into the slate — NRFI/F5/props
    all key off these event ids, so the window must match the ET slate.
    """
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    d = game_date or datetime.now(et).date()
    day_start = datetime(d.year, d.month, d.day, tzinfo=et).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)
    data = _cached_get(
        f"mlb_events_{d.isoformat()}",
        f"{API_BASE}/sports/baseball_mlb/events",
        {
            "commenceTimeFrom": day_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commenceTimeTo": day_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "regions": "us",
        },
        max_age_s=3600,
    )
    if not data or not isinstance(data, list):
        return []
    return [
        {
            "event_id": e["id"],
            "home_team": e.get("home_team", ""),
            "away_team": e.get("away_team", ""),
            "commence_time": e.get("commence_time", ""),
        }
        for e in data
    ]


def fetch_event_props(event_id: str, market: str) -> list[dict]:
    """
    Fetch player prop lines for one event + market.
    Returns list of {player, line, over_odds, under_odds, implied_over_prob, book}
    """
    data = _cached_get(
        f"props_{event_id}_{market}",
        f"{API_BASE}/sports/baseball_mlb/events/{event_id}/odds",
        {
            "regions": "us",
            "markets": market,
            "oddsFormat": "american",
            "bookmakers": MY_BOOKS_PARAM,
        },
        max_age_s=1800,  # 30 min — props move quickly
    )
    if not data or not isinstance(data, dict):
        return []

    props: dict[str, dict] = {}  # player_name -> best line

    for bookmaker in data.get("bookmakers", []):
        book_name = bookmaker.get("title", "")
        for mkt in bookmaker.get("markets", []):
            if mkt.get("key") != market:
                continue
            outcomes = mkt.get("outcomes", [])
            # pair up over/under for each player
            player_outcomes: dict[str, dict] = {}
            for o in outcomes:
                player = o.get("description", o.get("name", ""))
                side = o.get("name", "").lower()  # "Over" or "Under"
                price = float(o.get("price", 0))
                line = float(o.get("point", 0))
                if player not in player_outcomes:
                    player_outcomes[player] = {"line": line, "book": book_name}
                if "over" in side:
                    player_outcomes[player]["over_odds"] = price
                    player_outcomes[player]["line"] = line
                elif "under" in side:
                    player_outcomes[player]["under_odds"] = price

            for player, d in player_outcomes.items():
                if "over_odds" not in d or "under_odds" not in d:
                    continue
                implied = _devig(d["over_odds"], d["under_odds"])
                # Keep the best (most favorable) line per player
                if player not in props or d["over_odds"] > props[player].get("over_odds", -999):
                    props[player] = {
                        "player": player,
                        "line": d["line"],
                        "over_odds": d["over_odds"],
                        "under_odds": d["under_odds"],
                        "implied_over_prob": round(implied, 4),
                        "book": d["book"],
                    }

    return list(props.values())


import math as _math


def _poisson_over(lam: float, line: float) -> float:
    """P(X > line) where X ~ Poisson(lambda). Floor the line for integer cutoff."""
    floor_line = int(line)
    p_under = sum(
        _math.exp(-lam) * (lam ** k) / _math.factorial(k)
        for k in range(floor_line + 1)
    )
    return max(0.0, min(1.0, 1.0 - p_under))


def _project_strikeouts(k9: float, k9_l10: float, lineup_ops: float, innings: float = 5.5) -> float:
    """
    Project expected strikeouts for a starting pitcher.
    Uses weighted blend of season K/9 and last-10-starts K/9,
    adjusted for opposing lineup quality (higher OPS = fewer Ks).
    """
    blended_k9 = k9 * 0.4 + k9_l10 * 0.6
    ops_delta = 0.720 - lineup_ops
    k9_adj = blended_k9 * (1 + ops_delta * 1.5)
    return (k9_adj / 9) * innings


def find_prop_edges(
    matchups_with_stats: list[dict],
    game_date: date | None = None,
    min_edge: float = MIN_EDGE,
) -> list[dict]:
    """
    Main entry point. Given matchup stats, find player prop edges.

    matchups_with_stats: list of dicts with keys:
        event_id, home_team, away_team,
        home_sp_name, home_sp_k9, home_sp_k9_l10, home_sp_lineup_ops,
        away_sp_name, away_sp_k9, away_sp_k9_l10, away_sp_lineup_ops,

    Returns list of prop edge dicts sorted by edge descending.
    """
    if not _api_key():
        return []

    d = game_date or date.today()
    edges = []

    # Fetch event IDs
    events = fetch_mlb_event_ids(d)
    if not events:
        print("  [props] No MLB events found for today.")
        return []

    # Build lookup: (home_team, away_team) -> event_id
    event_lookup: dict[tuple[str, str], str] = {}
    for ev in events:
        event_lookup[(ev["home_team"], ev["away_team"])] = ev["event_id"]

    for m in matchups_with_stats:
        # Try to find the event ID by matching team names (fuzzy)
        event_id = m.get("event_id")
        if not event_id:
            for (ht, at), eid in event_lookup.items():
                if m["home_team"].lower() in ht.lower() or ht.lower() in m["home_team"].lower():
                    if m["away_team"].lower() in at.lower() or at.lower() in m["away_team"].lower():
                        event_id = eid
                        break
        if not event_id:
            continue

        # ── SP K/9 for use in batter projections ──
        avg_sp_k9 = (m.get("home_sp_k9", 8.5) + m.get("away_sp_k9", 8.5)) / 2

        def _confidence_tier(proj_val: float, line_val: float, market_key: str) -> str:
            """Rate confidence based on gap between projection and line vs typical variance."""
            gap = abs(proj_val - line_val)
            # Strikeout variance: ~2 Ks/game std dev. High = gap > 1.5 K, Med = > 0.8 K
            # Points/rebounds: higher variance, need bigger gap
            if market_key == "pitcher_strikeouts":
                if gap >= 1.5:  return "HIGH"
                if gap >= 0.8:  return "MED"
                return "LOW"
            if market_key in ("player_points", "player_pra"):
                if gap >= 5.0:  return "HIGH"
                if gap >= 3.0:  return "MED"
                return "LOW"
            if gap >= 2.0:  return "HIGH"
            if gap >= 1.0:  return "MED"
            return "LOW"

        def _append_edge(market: str, player: str, team: str, opp: str,
                         line: float, p_over: float, implied: float,
                         over_odds: float, under_odds: float, proj,
                         label_suffix: str):
            # Books shade OVER lines — apply systematic downward correction to OVER prob
            # Historical: OVERs 41% WR vs UNDERs 61% WR across all settled picks
            p_over = max(0.01, min(0.99, p_over - OVER_BIAS_CORRECTION))
            edge = p_over - implied
            if abs(edge) < min_edge:
                return
            bet_dir = "OVER" if edge > 0 else "UNDER"
            bet_prob   = p_over if edge > 0 else (1 - p_over)
            bet_implied = implied if edge > 0 else (1 - implied)
            bet_odds   = over_odds if edge > 0 else under_odds
            if bet_dir == "OVER" and bet_prob < MIN_OVER_PROB:
                return
            # Skip longshot odds — model calibration only valid near fair-game odds
            if bet_implied < MIN_IMPLIED_PROB:
                return
            # OVERs need higher edge bar (historically lose vs UNDERs)
            if bet_dir == "OVER" and abs(edge) < MIN_EDGE_OVER:
                return
            confidence = _confidence_tier(float(proj), line, market)
            edges.append({
                "type": "prop",
                "market": market,
                "player": player,
                "team": team,
                "opp": opp,
                "line": line,
                "direction": bet_dir,
                "projected": round(float(proj), 1),
                "model_prob": round(bet_prob, 3),
                "implied_prob": round(bet_implied, 3),
                "edge_pct": round(abs(edge) * 100, 1),
                "confidence": confidence,
                "odds": int(bet_odds),
                "book": prop["book"],
                "label": f"{player} {bet_dir} {line} {label_suffix}",
                "validation": f"Proj {round(float(proj),1)} vs {line} line [{confidence}]",
            })

        # ── Strikeout props ──
        k_props = fetch_event_props(event_id, "pitcher_strikeouts")
        for prop in k_props:
            player = prop["player"]
            line = prop["line"]
            implied = prop["implied_over_prob"]

            sp_stats = None
            if m.get("home_sp_name") and player.lower() in m["home_sp_name"].lower():
                sp_stats = {
                    "k9": m.get("home_sp_k9", 7.5),
                    "k9_l10": m.get("home_sp_k9_l10", 7.5),
                    "lineup_ops": m.get("away_lineup_ops", 0.720),
                    # Real IP/start so aces (6.5 IP) aren't projected at 5.5 and
                    # auto-faded UNDER. Falls back to 5.5 if upstream omits it.
                    "ip": m.get("home_sp_ip", 5.5),
                    "team": m["home_team"],
                    "opp": m["away_team"],
                }
            elif m.get("away_sp_name") and player.lower() in m["away_sp_name"].lower():
                sp_stats = {
                    "k9": m.get("away_sp_k9", 7.5),
                    "k9_l10": m.get("away_sp_k9_l10", 7.5),
                    "lineup_ops": m.get("home_lineup_ops", 0.720),
                    "ip": m.get("away_sp_ip", 5.5),
                    "team": m["away_team"],
                    "opp": m["home_team"],
                }
            if not sp_stats:
                continue

            projected = _project_strikeouts(
                sp_stats["k9"], sp_stats["k9_l10"], sp_stats["lineup_ops"],
                innings=sp_stats["ip"],
            )
            p_over = _poisson_over(projected, line)
            _append_edge("pitcher_strikeouts", player,
                         sp_stats["team"], sp_stats["opp"],
                         line, p_over, implied,
                         prop["over_odds"], prop["under_odds"],
                         projected, "Ks")

        # NOTE: batter_home_runs removed from this pipeline. Per-batter HR projection
        # lives in src/models/mlb_batter_props.py which uses each batter's actual
        # season HR/AB rate matched against opposing pitcher HR/9.

    edges.sort(key=lambda x: x["edge_pct"], reverse=True)
    return edges


def format_props_for_card(edges: list[dict], max_picks: int = 3) -> list[dict]:
    """Return top prop picks formatted for the daily picks terminal output."""
    return edges[:max_picks]
