"""
MLB batter prop projections — hits, home runs, RBIs, total bases.

Uses batter season stats from MLB Stats API matched against
opposing pitcher profile to project expected stat output, then
compares to Odds API book lines to find edges.

Signal: batter_hits and batter_home_runs are less efficient markets
than pitcher_strikeouts because books rely on season averages while
matchup-specific adjustments (LHP vs RHB, high K-rate pitchers, etc.)
are not fully priced in.
"""
from __future__ import annotations

import json
import math
import time
from datetime import date
from pathlib import Path

import requests

from src.data.odds_api import MY_BOOKS_PARAM

CACHE_DIR   = Path("data/cache/batter_props")
MLB_API     = "https://statsapi.mlb.com/api/v1"
ODDS_API    = "https://api.the-odds-api.com/v4"

BATTER_MARKETS = ["batter_hits", "batter_home_runs", "batter_rbis", "batter_total_bases"]
MIN_EDGE        = 0.05
MIN_CONFIDENCE  = 0.58
# No picks at implied < 20% (odds longer than +400) — model unreliable at longshots.
MIN_IMPLIED_PROB = 0.20

# Minimum line per market — OVER 0.5 hits/TB/RBIs produce phantom 40-55% edges
# because P(≥1 hit in a game) is ~70% for any starter at league-average WHIP,
# creating systematic overconfidence at trivially low lines.
_MIN_LINE_BY_MARKET: dict[str, float] = {
    "batter_hits":        1.5,
    "batter_total_bases": 1.5,
    "batter_rbis":        0.5,   # 0.5 is valid for RBIs (rare enough to have signal)
    "batter_home_runs":   0.5,   # 0.5 is the only HR line that exists
}


def _api_key() -> str | None:
    try:
        from pathlib import Path as P
        for line in P(".env").read_text().splitlines():
            if line.startswith("ODDS_API_KEY="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    import os
    return os.getenv("ODDS_API_KEY")


def _cached_get(key: str, url: str, params: dict, max_age_s: int = 3600):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_s:
        return json.loads(path.read_text())
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        path.write_text(json.dumps(data))
        return data
    except Exception:
        return None


def _safe_float(v, default: float = 0.0) -> float:
    """Coerce to float, falling back to default on None/'-/non-numeric strings."""
    if v is None or v == "" or v == "-":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


_PLAYER_ID_CACHE: dict[str, int] = {}


def _norm_name(name: str) -> str:
    """Strip punctuation/case/accents for fuzzy player name matching."""
    import unicodedata
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return name.lower().replace(".", "").replace(",", "").replace("'", "").strip()


def _build_player_id_map(season: int = 2026) -> dict[str, int]:
    """Walk all 30 MLB rosters once and build a {normalized_name: player_id} cache.

    Cached for 24h via the standard _cached_get layer. Returns the in-memory
    `_PLAYER_ID_CACHE` (also persists it as a JSON cache file).
    """
    global _PLAYER_ID_CACHE
    if _PLAYER_ID_CACHE:
        return _PLAYER_ID_CACHE

    cache_path = CACHE_DIR / f"player_id_map_{season}.json"
    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < 86400:
        try:
            _PLAYER_ID_CACHE = json.loads(cache_path.read_text())
            return _PLAYER_ID_CACHE
        except Exception:
            pass

    # Pull every team's roster for the season
    try:
        teams_data = _cached_get(
            f"teams_{season}",
            f"{MLB_API}/teams",
            {"sportId": 1, "season": season},
            max_age_s=86400 * 7,
        )
    except Exception:
        return {}

    if not teams_data:
        return {}

    name_map: dict[str, int] = {}
    for team in teams_data.get("teams", []):
        tid = team.get("id")
        if not tid:
            continue
        try:
            roster = _cached_get(
                f"roster_full_{tid}_{season}",
                f"{MLB_API}/teams/{tid}/roster",
                {"rosterType": "fullSeason", "season": season},
                max_age_s=86400,
            )
        except Exception:
            continue
        for entry in (roster or {}).get("roster", []):
            pid = entry.get("person", {}).get("id")
            full = entry.get("person", {}).get("fullName", "")
            if pid and full:
                name_map[_norm_name(full)] = pid

    _PLAYER_ID_CACHE = name_map
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(name_map))
    except Exception:
        pass
    return name_map


def _lookup_player_id(name: str, season: int = 2026) -> int | None:
    """Return MLB player_id for a name, building the cache on first call."""
    if not _PLAYER_ID_CACHE:
        _build_player_id_map(season)
    return _PLAYER_ID_CACHE.get(_norm_name(name))


def _devig(over_odds: float, under_odds: float) -> float:
    def p(o): return 100/(o+100) if o > 0 else abs(o)/(abs(o)+100)
    po, pu = p(over_odds), p(under_odds)
    return po / (po + pu) if (po + pu) > 0 else 0.5


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _poisson_over_prob(lam: float, line: float) -> float:
    """P(X > line) for Poisson-distributed X with mean lam."""
    import math
    k = int(math.floor(line))
    prob_le_k = sum(
        math.exp(-lam) * (lam ** i) / math.factorial(i)
        for i in range(k + 1)
    )
    return max(0.0, min(1.0, 1.0 - prob_le_k))


def fetch_batter_season_stats(player_id: int, season: int = 2026) -> dict:
    data = _cached_get(
        f"batter_{player_id}_{season}",
        f"{MLB_API}/people/{player_id}/stats",
        {"stats": "season", "season": season, "group": "hitting"},
        max_age_s=3600 * 6,
    )
    if not data:
        return {}
    splits = data.get("stats", [{}])[0].get("splits", [])
    return splits[0].get("stat", {}) if splits else {}


def fetch_pitcher_stats(player_id: int, season: int = 2026) -> dict:
    data = _cached_get(
        f"pitcher_{player_id}_{season}",
        f"{MLB_API}/people/{player_id}/stats",
        {"stats": "season", "season": season, "group": "pitching"},
        max_age_s=3600 * 6,
    )
    if not data:
        return {}
    splits = data.get("stats", [{}])[0].get("splits", [])
    return splits[0].get("stat", {}) if splits else {}


def _project_hits(batter_avg: float, opp_whip: float, at_bats: float = 3.8) -> float:
    """Project expected hits. Adjust for pitcher quality via WHIP deviation from league avg."""
    LG_AVG_WHIP = 1.30
    pitcher_adj = (opp_whip - LG_AVG_WHIP) / LG_AVG_WHIP  # positive = pitcher worse than avg
    adj_avg = batter_avg * (1 + pitcher_adj * 0.15)
    return max(0.0, adj_avg * at_bats)


def _project_hr(batter_hr_per_ab: float, opp_hr9: float, at_bats: float = 3.8) -> float:
    """Project expected HRs. Adjust for pitcher HR rate."""
    LG_AVG_HR9 = 1.20
    pitcher_adj = (opp_hr9 - LG_AVG_HR9) / max(LG_AVG_HR9, 0.01)
    adj_rate = batter_hr_per_ab * (1 + pitcher_adj * 0.20)
    return max(0.0, adj_rate * at_bats)


def fetch_batter_prop_lines(event_id: str) -> dict[str, list[dict]]:
    """
    Fetch batter prop lines for one MLB event across all markets.
    Returns {market_key: [{player, line, over_odds, under_odds, book}]}
    """
    api_key = _api_key()
    if not api_key:
        return {}

    markets_str = ",".join(BATTER_MARKETS)
    data = _cached_get(
        f"batter_odds_{event_id}",
        f"{ODDS_API}/sports/baseball_mlb/events/{event_id}/odds",
        {
            "apiKey":    api_key,
            "regions":   "us,us2",
            "markets":   markets_str,
            "oddsFormat": "american",
            "bookmakers": MY_BOOKS_PARAM,
        },
        max_age_s=1800,
    )
    if not data or "bookmakers" not in data:
        return {}

    result: dict[str, dict[str, dict]] = {}
    for bk in data.get("bookmakers", []):
        book = bk.get("title", "")
        for mkt in bk.get("markets", []):
            mkey = mkt.get("key", "")
            if mkey not in BATTER_MARKETS:
                continue
            # Group outcomes by player
            players: dict[str, dict] = {}
            for o in mkt.get("outcomes", []):
                player = o.get("description") or o.get("name", "")
                side   = o.get("name", "").lower()
                price  = float(o.get("price", 0))
                line   = o.get("point")
                if player not in players:
                    players[player] = {"player": player, "line": line, "book": book}
                if side == "over":
                    players[player]["over_odds"] = price
                elif side == "under":
                    players[player]["under_odds"] = price

            for player, pdata in players.items():
                if "over_odds" not in pdata or "under_odds" not in pdata:
                    continue
                key = f"{player}_{mkey}"
                existing = result.get(mkey, {}).get(key)
                if existing is None:
                    result.setdefault(mkey, {})[key] = pdata
                else:
                    # Keep best over odds
                    if pdata["over_odds"] > existing["over_odds"]:
                        result[mkey][key] = pdata

    return {mkey: list(v.values()) for mkey, v in result.items()}


def find_batter_prop_edges(
    matchups: list[dict],
    game_date: date | None = None,
) -> list[dict]:
    """
    Find batter prop edges across today's slate.

    Each matchup dict: {home_team, away_team, event_id (optional),
                        home_sp_era, away_sp_era, home_sp_whip, away_sp_whip,
                        home_sp_hr9, away_sp_hr9}

    Returns sorted list of edge dicts.
    """
    from src.data.player_props import fetch_mlb_event_ids

    # Build event_id lookup
    event_lookup: dict[tuple[str, str], str] = {}
    if any(not m.get("event_id") for m in matchups):
        try:
            for ev in fetch_mlb_event_ids(game_date or date.today()):
                event_lookup[(ev["home_team"], ev["away_team"])] = ev["event_id"]
        except Exception:
            pass

    edges = []
    for m in matchups:
        event_id = m.get("event_id")
        if not event_id:
            for (ht, at), eid in event_lookup.items():
                if (m["home_team"].lower() in ht.lower() or ht.lower() in m["home_team"].lower()):
                    event_id = eid
                    break
        if not event_id:
            continue

        lines_by_market = fetch_batter_prop_lines(event_id)
        if not lines_by_market:
            continue

        home_sp_whip = float(m.get("home_sp_whip") or 1.30)
        away_sp_whip = float(m.get("away_sp_whip") or 1.30)
        home_sp_hr9  = float(m.get("home_sp_hr9")  or 1.20)
        away_sp_hr9  = float(m.get("away_sp_hr9")  or 1.20)

        for market, player_lines in lines_by_market.items():
            for pl in player_lines:
                line       = pl.get("line")
                over_odds  = pl.get("over_odds")
                under_odds = pl.get("under_odds")
                if line is None or over_odds is None or under_odds is None:
                    continue

                line_f = float(line)
                if line_f < _MIN_LINE_BY_MARKET.get(market, 1.5):
                    continue

                implied_over = _devig(over_odds, under_odds)

                # Use average of both starters as the pitcher matchup proxy
                avg_whip = (home_sp_whip + away_sp_whip) / 2
                avg_hr9  = (home_sp_hr9  + away_sp_hr9)  / 2

                # Per-batter stats: look up MLB player_id from name, fetch
                # season hitting stats. Falls back to league averages if not found.
                player_name = pl.get("player", "")
                pid = _lookup_player_id(player_name)
                batter_stats = {}
                if pid:
                    try:
                        batter_stats = fetch_batter_season_stats(pid)
                    except Exception:
                        batter_stats = {}

                ab = _safe_float(batter_stats.get("atBats"), 0)
                hits = _safe_float(batter_stats.get("hits"), 0)
                hr = _safe_float(batter_stats.get("homeRuns"), 0)
                tb = _safe_float(batter_stats.get("totalBases"), 0)
                rbi = _safe_float(batter_stats.get("rbi"), 0)
                games = _safe_float(batter_stats.get("gamesPlayed"), 0)

                # Per-batter rates — only use if the player has ≥30 AB (real sample)
                has_batter_data = ab >= 30
                batter_avg = (hits / ab) if has_batter_data and ab else 0.250
                batter_hr_per_ab = (hr / ab) if has_batter_data and ab else 0.035
                batter_tb_per_ab = (tb / ab) if has_batter_data and ab else (0.250 * 1.5)
                batter_rbi_per_g = (rbi / games) if has_batter_data and games else 0.65

                if market == "batter_hits":
                    proj = _project_hits(batter_avg, avg_whip)
                    model_over = _poisson_over_prob(proj, line_f)

                elif market == "batter_home_runs":
                    proj = _project_hr(batter_hr_per_ab, avg_hr9)
                    model_over = _poisson_over_prob(proj, line_f)

                elif market == "batter_rbis":
                    # Adjust per-game RBI by pitcher WHIP (more baserunners → more RBI ops)
                    pitcher_adj = (avg_whip - 1.30) / 1.30
                    proj = max(0.0, batter_rbi_per_g * (1 + pitcher_adj * 0.15))
                    model_over = _poisson_over_prob(proj, line_f)

                elif market == "batter_total_bases":
                    # TB per game = TB/AB * AB/game (assume 3.8 AB/game for starters)
                    AB_PER_GAME = 3.8
                    pitcher_adj = (avg_whip - 1.30) / 1.30
                    proj = max(0.0, batter_tb_per_ab * AB_PER_GAME * (1 + pitcher_adj * 0.15))
                    model_over = _poisson_over_prob(proj, line_f)

                else:
                    continue

                # NOTE: We intentionally do NOT apply the shared mlb-prop
                # Platt calibrator here. It was trained on pitcher_strikeouts
                # where true probs hover around 0.50; applied to HR (true probs
                # ~5-15%) it pulls every projection toward 0.45, manufacturing
                # phantom edges on weak hitters at +900 prices. The raw Poisson
                # projection with per-batter rates is the honest signal.

                edge = (model_over - implied_over) * 100
                direction = "OVER" if edge > 0 else "UNDER"
                bet_prob  = model_over if direction == "OVER" else (1 - model_over)
                bet_implied = implied_over if direction == "OVER" else (1 - implied_over)

                # Skip longshot lines — implied < 20% means +400 or longer odds,
                # where the model's Poisson projection has no reliable signal.
                if bet_implied < MIN_IMPLIED_PROB:
                    continue

                # HR uses a lower confidence floor — HR is a rare event, the model
                # rarely projects >30% even for sluggers but the +EV is still real.
                # All other markets (hits/TB/RBI) keep the standard 0.58 floor.
                conf_floor = 0.25 if market == "batter_home_runs" else MIN_CONFIDENCE

                if abs(edge) >= MIN_EDGE * 100 and bet_prob >= conf_floor:
                    pick_odds  = over_odds if direction == "OVER" else under_odds
                    edges.append({
                        "type":         "batter_prop",
                        "market":       market,
                        "player":       pl["player"],
                        "line":         line_f,
                        "direction":    direction,
                        "model_prob":   round(model_over if direction == "OVER" else 1 - model_over, 3),
                        "implied_prob": round(implied_over if direction == "OVER" else 1 - implied_over, 3),
                        "edge_pct":     round(abs(edge), 1),
                        "odds":         int(pick_odds),
                        "book":         pl["book"],
                        "projected":    round(proj, 2),
                        "label":        f"{pl['player']} {direction} {line_f} {_market_short(market)}",
                        "matchup":      f"{m['away_team']} @ {m['home_team']}",
                        "home_team":    m["home_team"],
                        "away_team":    m["away_team"],
                    })

    edges.sort(key=lambda x: x["edge_pct"], reverse=True)
    return edges


def _market_short(market: str) -> str:
    return {
        "batter_hits":        "Hits",
        "batter_home_runs":   "HRs",
        "batter_rbis":        "RBIs",
        "batter_total_bases": "TB",
    }.get(market, market)
