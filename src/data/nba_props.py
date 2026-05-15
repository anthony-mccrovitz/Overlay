"""
NBA Player Props edge detection.

Markets supported (Odds API):
  player_points              — points scored
  player_rebounds            — total rebounds
  player_assists             — assists
  player_threes              — 3-pointers made
  player_points_rebounds_assists — PRA combo
  player_blocks              — blocks
  player_steals              — steals

Pipeline per market:
  1. Fetch player season averages from NBA Stats API
  2. Adjust for opponent defensive quality (pts allowed vs position)
  3. Adjust for home/away and rest days
  4. Model probability of going over/under the line
  5. Compare to de-vigged implied prob → surface edges ≥ threshold

Usage:
    from src.data.nba_props import find_nba_prop_edges
    edges = find_nba_prop_edges(events_with_team_context)
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.data.odds_api import MY_BOOKS_PARAM
from src.data.nba_stats import (
    LG_AVG_DRTG,
    LG_AVG_PACE,
    fetch_player_stats,
    get_player_stats,
    get_team_ratings,
    get_team_opp_pts_allowed,
    fetch_opp_position_defense,
)

load_dotenv()

CACHE_DIR = Path("data/cache/props")
NBA_PROPS_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_points_rebounds_assists",
    "player_blocks",
    "player_steals",
]
API_BASE = "https://api.the-odds-api.com/v4"
MIN_EDGE = 0.12      # 12% — raised from 5%; NBA prop ECE=0.43 means stated edges are ~3x overstated
MIN_OVER_PROB = 0.50  # removed asymmetric gate — let edge sign decide direction


def _api_key() -> str | None:
    return os.environ.get("ODDS_API_KEY")


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _cached_get(key: str, url: str, params: dict, max_age_s: int = 1800) -> dict | None:
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
        print(f"  [nba_props] {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return None


def _devig(over_odds: float, under_odds: float) -> float:
    def to_prob(a: float) -> float:
        return 100 / (a + 100) if a >= 0 else abs(a) / (abs(a) + 100)
    p_o = to_prob(over_odds)
    p_u = to_prob(under_odds)
    t = p_o + p_u
    return p_o / t if t > 0 else 0.5


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _normal_over_prob(projected: float, line: float, std: float) -> float:
    """P(stat > line) where stat ~ Normal(projected, std)."""
    return 1.0 - _normal_cdf((line - projected) / std)


def _poisson_over(lam: float, line: float) -> float:
    """P(X > floor(line)) where X ~ Poisson(lambda). Good for low-count stats."""
    k = int(line)
    p_under = sum(
        math.exp(-lam) * (lam ** i) / math.factorial(i)
        for i in range(k + 1)
    )
    return max(0.0, min(1.0, 1.0 - p_under))


# ─────────────────── Projection helpers per stat type ────────────────────────

def _project_points(player: dict, opp_drtg: float) -> tuple[float, float]:
    """
    Return (projected_pts, std_dev).
    opp_drtg: opponent's defensive rating (per-100-possessions).
    Higher DRtg = worse defense = more points allowed.
    """
    pts = float(player.get("PTS", 15.0))
    # Adjust: if opponent DRtg > league avg, player scores more; if lower, less
    def_factor = opp_drtg / LG_AVG_DRTG
    projected = pts * def_factor
    # Points std dev ≈ 35% of average (coefficient of variation from NBA data)
    std = projected * 0.35
    return projected, max(std, 3.0)


def _project_rebounds(player: dict, opp_drtg: float = LG_AVG_DRTG) -> tuple[float, float]:
    reb = float(player.get("REB", 5.0))
    # Worse defense (higher DRtg) → more missed shots → more rebounding opportunities
    def_factor = opp_drtg / LG_AVG_DRTG
    projected = reb * (1.0 + (def_factor - 1.0) * 0.4)
    return projected, max(projected * 0.45, 1.5)


def _project_assists(player: dict, opp_pace: float = LG_AVG_PACE, opp_drtg: float = LG_AVG_DRTG) -> tuple[float, float]:
    ast = float(player.get("AST", 4.0))
    # Higher pace → more possessions → more assist opportunities
    pace_factor = opp_pace / LG_AVG_PACE
    # Worse defense → more made buckets → slight more assists
    def_factor = opp_drtg / LG_AVG_DRTG
    projected = ast * pace_factor * (1.0 + (def_factor - 1.0) * 0.2)
    return projected, max(projected * 0.50, 1.0)


def _project_threes(player: dict) -> tuple[float, float]:
    fg3m = float(player.get("FG3M", 1.5))
    return fg3m, max(fg3m * 0.60, 0.8)


def _project_pra(player: dict, opp_pts_allowed: float) -> tuple[float, float]:
    pts, _  = _project_points(player, opp_pts_allowed)
    reb, _  = _project_rebounds(player)
    ast, _  = _project_assists(player)
    total   = pts + reb + ast
    std     = total * 0.28
    return total, max(std, 4.0)


def _project_blocks(player: dict) -> tuple[float, float]:
    blk = float(player.get("BLK", 0.8))
    return blk, max(blk * 0.70, 0.4)


def _project_steals(player: dict) -> tuple[float, float]:
    stl = float(player.get("STL", 0.9))
    return stl, max(stl * 0.65, 0.4)


# ─────────────────── Props fetcher ──────────────────────────────────────────

def fetch_nba_event_props(event_id: str, market: str) -> list[dict]:
    """
    Fetch NBA player prop lines for one event + market.
    Returns list of {player, line, over_odds, under_odds, implied_over_prob, book}.
    """
    data = _cached_get(
        f"nba_props_{event_id}_{market}",
        f"{API_BASE}/sports/basketball_nba/events/{event_id}/odds",
        {
            "regions": "us",
            "markets": market,
            "oddsFormat": "american",
            "bookmakers": MY_BOOKS_PARAM,
        },
        max_age_s=900,  # 15-min refresh for live props
    )
    if not data or not isinstance(data, dict):
        return []

    props: dict[str, dict] = {}

    for bookmaker in data.get("bookmakers", []):
        book_name = bookmaker.get("title", "")
        for mkt in bookmaker.get("markets", []):
            if mkt.get("key") != market:
                continue
            player_data: dict[str, dict] = {}
            for o in mkt.get("outcomes", []):
                player = o.get("description", o.get("name", ""))
                side   = o.get("name", "").lower()
                price  = float(o.get("price", 0))
                line   = float(o.get("point", 0))

                if player not in player_data:
                    player_data[player] = {"line": line, "book": book_name}
                if "over" in side:
                    player_data[player]["over_odds"] = price
                    player_data[player]["line"] = line
                elif "under" in side:
                    player_data[player]["under_odds"] = price

            for player, d in player_data.items():
                if "over_odds" not in d or "under_odds" not in d:
                    continue
                implied = _devig(d["over_odds"], d["under_odds"])
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


# ─────────────────── Main edge finder ───────────────────────────────────────

def find_nba_prop_edges(
    events: list[dict],
    min_edge: float = MIN_EDGE,
) -> list[dict]:
    """
    Find NBA player prop edges for tonight's games.

    events: list of dicts with {id, home_team, away_team, commence_time}
    """
    if not _api_key():
        return []

    all_players = fetch_player_stats()
    opp_defense  = fetch_opp_position_defense()
    edges: list[dict] = []

    for event in events:
        event_id  = event["id"]
        home_team = event["home_team"]
        away_team = event["away_team"]
        matchup   = f"{away_team} @ {home_team}"

        # DRtg: lower = better defense. Home player faces away defense; away player faces home defense.
        home_drtg = get_team_opp_pts_allowed(home_team, opp_defense)
        away_drtg = get_team_opp_pts_allowed(away_team, opp_defense)
        home_pace = float(get_team_ratings(home_team).get("PACE", LG_AVG_PACE))
        away_pace = float(get_team_ratings(away_team).get("PACE", LG_AVG_PACE))
        game_pace = (home_pace + away_pace) / 2.0

        def _opp_drtg(player_stats: dict) -> float:
            """Return the defensive rating the player faces based on their team."""
            player_team = player_stats.get("TEAM_NAME", "")
            if player_team:
                home_words = set(home_team.lower().split())
                away_words = set(away_team.lower().split())
                player_words = set(player_team.lower().split())
                # If player's team matches home team → they face away team's defense
                if home_words & player_words:
                    return away_drtg
                if away_words & player_words:
                    return home_drtg
            # Fallback: average of both defenses
            return (home_drtg + away_drtg) / 2.0

        def _append(
            market: str, player_name: str, line: float,
            proj: float, std: float, use_poisson: bool,
            implied: float, over_odds: float, under_odds: float,
            book: str, stat_label: str,
        ) -> None:
            from src.analytics.calibration import apply_calibration
            if use_poisson:
                p_over_raw = _poisson_over(proj, line)
            else:
                p_over_raw = _normal_over_prob(proj, line, std)

            # Apply Platt calibration — corrects for overconfidence in prop projections
            p_over = apply_calibration(p_over_raw, "nba", "prop")

            for direction, model_prob, imp, odds in [
                ("OVER",  p_over,       implied,     over_odds),
                ("UNDER", 1 - p_over,   1 - implied, under_odds),
            ]:
                edge = model_prob - imp
                # Only positive edge — direction is already set by the loop,
                # so abs() would silently fire on wrong-direction props.
                if edge < min_edge:
                    continue
                edges.append({
                    "type": "nba_prop",
                    "market": market,
                    "player": player_name,
                    "matchup": matchup,
                    "home_team": home_team,
                    "away_team": away_team,
                    "line": line,
                    "direction": direction,
                    "projected": round(float(proj), 1),
                    "model_prob": round(model_prob, 3),
                    "implied_prob": round(imp, 3),
                    "edge_pct": round(edge * 100, 1),
                    "odds": int(odds),
                    "book": book,
                    "label": f"{player_name} {direction} {line} {stat_label}",
                })

        # ── Points ──────────────────────────────────────────────────────────
        pts_props = fetch_nba_event_props(event_id, "player_points")
        for prop in pts_props:
            stats = get_player_stats(prop["player"], all_players)
            if not stats:
                continue
            proj, std = _project_points(stats, _opp_drtg(stats))
            _append("player_points", prop["player"], prop["line"],
                    proj, std, False,
                    prop["implied_over_prob"], prop["over_odds"], prop["under_odds"],
                    prop["book"], "PTS")

        # ── Rebounds ────────────────────────────────────────────────────────
        reb_props = fetch_nba_event_props(event_id, "player_rebounds")
        for prop in reb_props:
            stats = get_player_stats(prop["player"], all_players)
            if not stats:
                continue
            proj, std = _project_rebounds(stats, _opp_drtg(stats))
            _append("player_rebounds", prop["player"], prop["line"],
                    proj, std, True,
                    prop["implied_over_prob"], prop["over_odds"], prop["under_odds"],
                    prop["book"], "REB")

        # ── Assists ─────────────────────────────────────────────────────────
        ast_props = fetch_nba_event_props(event_id, "player_assists")
        for prop in ast_props:
            stats = get_player_stats(prop["player"], all_players)
            if not stats:
                continue
            proj, std = _project_assists(stats, game_pace, _opp_drtg(stats))
            _append("player_assists", prop["player"], prop["line"],
                    proj, std, True,
                    prop["implied_over_prob"], prop["over_odds"], prop["under_odds"],
                    prop["book"], "AST")

        # ── 3-Pointers ──────────────────────────────────────────────────────
        three_props = fetch_nba_event_props(event_id, "player_threes")
        for prop in three_props:
            stats = get_player_stats(prop["player"], all_players)
            if not stats:
                continue
            proj, std = _project_threes(stats)
            _append("player_threes", prop["player"], prop["line"],
                    proj, std, True,
                    prop["implied_over_prob"], prop["over_odds"], prop["under_odds"],
                    prop["book"], "3PM")

        # ── PRA combo ───────────────────────────────────────────────────────
        pra_props = fetch_nba_event_props(event_id, "player_points_rebounds_assists")
        for prop in pra_props:
            stats = get_player_stats(prop["player"], all_players)
            if not stats:
                continue
            proj, std = _project_pra(stats, _opp_drtg(stats))
            _append("player_pra", prop["player"], prop["line"],
                    proj, std, False,
                    prop["implied_over_prob"], prop["over_odds"], prop["under_odds"],
                    prop["book"], "PRA")

        # ── Blocks ──────────────────────────────────────────────────────────
        blk_props = fetch_nba_event_props(event_id, "player_blocks")
        for prop in blk_props:
            stats = get_player_stats(prop["player"], all_players)
            if not stats:
                continue
            proj, std = _project_blocks(stats)
            _append("player_blocks", prop["player"], prop["line"],
                    proj, std, True,
                    prop["implied_over_prob"], prop["over_odds"], prop["under_odds"],
                    prop["book"], "BLK")

        # ── Steals ──────────────────────────────────────────────────────────
        stl_props = fetch_nba_event_props(event_id, "player_steals")
        for prop in stl_props:
            stats = get_player_stats(prop["player"], all_players)
            if not stats:
                continue
            proj, std = _project_steals(stats)
            _append("player_steals", prop["player"], prop["line"],
                    proj, std, True,
                    prop["implied_over_prob"], prop["over_odds"], prop["under_odds"],
                    prop["book"], "STL")

    edges.sort(key=lambda x: x["edge_pct"], reverse=True)
    return edges
