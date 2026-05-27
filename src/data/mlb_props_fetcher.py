"""
MLB Player Props Fetcher — ChefTonyBets

Fetches live player prop odds from The Odds API and enriches them with
pitcher/batter stats from the MLB Stats API for use with mlb_props_nb.NegBinPropModel.

Supported markets:
  pitcher_strikeouts, batter_hits, batter_total_bases, batter_home_runs

Data flow:
  Odds API events → per-event props → enrich with MLB Stats API → NB model input rows
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

CACHE_DIR = Path("data/cache/props")
_ODDS_BASE = "https://api.the-odds-api.com/v4"
_STATS_BASE = "https://statsapi.mlb.com/api/v1"

# Markets available through Odds API event-level endpoints
PROP_MARKETS = [
    "pitcher_strikeouts",
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",
]

# MLB Stats API group IDs
_HITTING_GROUP  = "hitting"
_PITCHING_GROUP = "pitching"


# ── MLB Stats API helpers ─────────────────────────────────────────────────────

def _mlb_player_search(name: str) -> int | None:
    """Search MLB Stats API for a player ID by name. Returns player_id or None."""
    try:
        resp = requests.get(
            f"{_STATS_BASE}/people/search",
            params={"names": name, "sportId": 1},
            timeout=10,
        )
        data = resp.json()
        people = data.get("people", [])
        if people:
            return int(people[0]["id"])
    except Exception:
        pass
    return None


def _mlb_season_stats(player_id: int, stat_group: str, season: int = 2026) -> dict:
    """Fetch season stats for a player from MLB Stats API."""
    try:
        resp = requests.get(
            f"{_STATS_BASE}/people/{player_id}/stats",
            params={
                "stats":   "season",
                "group":   stat_group,
                "season":  season,
                "sportId": 1,
            },
            timeout=10,
        )
        data = resp.json()
        groups = data.get("stats", [])
        for group in groups:
            splits = group.get("splits", [])
            if splits:
                return splits[0].get("stat", {})
    except Exception:
        pass
    return {}


def _player_id_cache() -> dict[str, int]:
    """Load or initialize the player_id cache."""
    p = CACHE_DIR / "player_ids.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_player_id_cache(cache: dict[str, int]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / "player_ids.json"
    p.write_text(json.dumps(cache, indent=2))


def get_player_id(name: str, id_cache: dict[str, int] | None = None) -> int | None:
    if id_cache is None:
        id_cache = _player_id_cache()
    if name in id_cache:
        return id_cache[name]
    pid = _mlb_player_search(name)
    if pid:
        id_cache[name] = pid
        _save_player_id_cache(id_cache)
    return pid


def get_team_k_rate(team_name: str, season: int | None = None) -> float:
    """
    Return the opponent K-rate (strikeouts per PA) for a team this season.
    Uses MLB Stats API team standings/stats. Falls back to league avg 0.22.
    """
    if season is None:
        from datetime import date
        season = date.today().year

    cache_key = f"team_k_rate_{season}"
    cache_file = CACHE_DIR / f"{cache_key}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    team_rates: dict[str, float] = {}
    if cache_file.exists():
        try:
            age = __import__("time").time() - cache_file.stat().st_mtime
            if age < 86400:  # 24h cache
                team_rates = json.loads(cache_file.read_text())
        except Exception:
            pass

    if not team_rates:
        try:
            resp = requests.get(
                f"{_STATS_BASE}/stats",
                params={"stats": "season", "group": "hitting",
                        "season": season, "sportId": 1,
                        "playerPool": "All", "limit": 30,
                        "gameType": "R"},
                timeout=15,
            )
            # Team hitting stats endpoint
            resp2 = requests.get(
                f"{_STATS_BASE}/teams",
                params={"season": season, "sportId": 1},
                timeout=10,
            )
            teams_data = resp2.json().get("teams", [])
            for team in teams_data:
                tid  = team.get("id")
                tname = team.get("name", "")
                if not tid:
                    continue
                try:
                    tr = requests.get(
                        f"{_STATS_BASE}/teams/{tid}/stats",
                        params={"stats": "season", "group": "hitting",
                                "season": season, "sportId": 1},
                        timeout=8,
                    )
                    tstat = tr.json()
                    for grp in tstat.get("stats", []):
                        for split in grp.get("splits", []):
                            s = split.get("stat", {})
                            pa  = int(s.get("plateAppearances", 0) or 0)
                            sos = int(s.get("strikeOuts", 0) or 0)
                            if pa > 0:
                                team_rates[tname] = sos / pa
                except Exception:
                    pass
            if team_rates:
                cache_file.write_text(json.dumps(team_rates, indent=2))
        except Exception:
            pass

    if not team_rates:
        return 0.22

    # Fuzzy match team name
    tl = team_name.lower()
    for name, rate in team_rates.items():
        parts = name.lower().split()
        if any(p in tl for p in parts if len(p) > 3):
            return rate

    return 0.22


def get_pitcher_stats_row(name: str, opp_k_rate: float = 0.22) -> dict[str, float]:
    """
    Build a feature dict for the NB pitcher_strikeouts model.
    Falls back to reasonable league-average values if stats unavailable.
    """
    defaults: dict[str, float] = {
        "k_per_9":           8.5,
        "whip":              1.25,
        "innings_per_start": 5.5,
        "opp_k_rate":        opp_k_rate,
        "recent_ks_3g":      5.0,
    }

    id_cache = _player_id_cache()
    pid = get_player_id(name, id_cache)
    if not pid:
        return defaults

    stats = _mlb_season_stats(pid, "pitching")
    if not stats:
        return defaults

    k9   = float(stats.get("strikeoutsPer9Inn", defaults["k_per_9"]) or defaults["k_per_9"])
    whip = float(stats.get("whip", defaults["whip"]) or defaults["whip"])
    gs   = int(stats.get("gamesStarted", 0) or 0)
    gp   = int(stats.get("gamesPlayed", 1) or 1)

    # IP per start: only reliable if pitcher is predominantly a starter.
    # If gamesStarted < 60% of appearances, they're a swing man — use league avg IP/start.
    # Use outs/3 to convert to decimal innings (avoids "27.1" string issues).
    outs = int(stats.get("outs", 0) or 0)
    total_ip = outs / 3.0 if outs > 0 else 0.0

    if gs >= 1 and gs >= gp * 0.5:
        # Mostly a starter — apportion IP to starts vs relief
        # Starter average ~5.5 IP, relief ~1.0 IP per appearance
        relief_appearances = gp - gs
        approx_relief_ip   = relief_appearances * 1.0
        starter_ip         = max(total_ip - approx_relief_ip, 0.0)
        ip_per_start       = starter_ip / gs if gs > 0 else defaults["innings_per_start"]
        ip_per_start       = min(max(ip_per_start, 2.0), 8.0)  # sanity clamp 2–8 IP
    else:
        ip_per_start = defaults["innings_per_start"]

    # Expected Ks per start from K/9 rate × expected IP
    recent_ks_3g = k9 * ip_per_start / 9.0

    return {
        "k_per_9":           k9,
        "whip":              whip,
        "innings_per_start": ip_per_start,
        "opp_k_rate":        opp_k_rate,
        "recent_ks_3g":      recent_ks_3g,
    }


def get_batter_stats_row(name: str) -> dict[str, float]:
    """Build a feature dict for batter prop models (hits, TB, runs, RBIs)."""
    defaults: dict[str, float] = {
        "ba_season":         0.250,
        "babip":             0.300,
        "contact_pct":       0.750,
        "slg_season":        0.400,
        "iso_power":         0.150,
        "hr_rate":           0.035,
        "obp_season":        0.320,
        "batting_order_pos": 5,
        "rbi_per_game":      0.45,
        "risp_ba":           0.250,
    }

    id_cache = _player_id_cache()
    pid = get_player_id(name, id_cache)
    if not pid:
        return defaults

    stats = _mlb_season_stats(pid, "hitting")
    if not stats:
        return defaults

    avg  = float(stats.get("avg",  defaults["ba_season"]) or defaults["ba_season"])
    slg  = float(stats.get("slg",  defaults["slg_season"]) or defaults["slg_season"])
    obp  = float(stats.get("obp",  defaults["obp_season"]) or defaults["obp_season"])
    babip = float(stats.get("babip", defaults["babip"]) or defaults["babip"])
    hrs  = int(stats.get("homeRuns", 0) or 0)
    g    = int(stats.get("gamesPlayed", 1) or 1)
    rbis = int(stats.get("rbi", 0) or 0)
    hits = int(stats.get("hits", 0) or 0)
    tbases = int(stats.get("totalBases", 0) or 0)

    hits_pg  = hits  / max(g, 1)
    tb_pg    = tbases / max(g, 1)
    return {
        "ba_season":         avg,
        "babip":             babip,
        "contact_pct":       avg / max(babip, 0.001) * 0.75,
        "slg_season":        slg,
        "iso_power":         slg - avg,
        "hr_rate":           hrs / max(g, 1),
        "obp_season":        obp,
        "batting_order_pos": 5,      # unknown without lineup data
        "rbi_per_game":      rbis / max(g, 1),
        "risp_ba":           avg,    # proxy — no RISP BA in Stats API standard
        "hits_per_game":     hits_pg,
        "tb_per_game":       tb_pg,
        # Aliases for PROP_CONFIGS feature names
        "recent_hits_3g":    hits_pg,
        "recent_tb_3g":      tb_pg,
        "recent_runs_3g":    rbis / max(g, 1),   # proxy: runs ≈ RBI rate
        "recent_rbis_3g":    rbis / max(g, 1),
        "opp_whip":          1.30,   # league avg — no matchup data at enrichment time
        "opp_k_rate":        0.22,
        "park_factor_hits":  1.0,
        "opp_hr_rate":       0.025,
        "park_hr_factor":    1.0,
    }


# ── Odds API fetcher ──────────────────────────────────────────────────────────

def fetch_all_mlb_props(
    markets: list[str] | None = None,
    refresh: bool = False,
    verbose: bool = True,
) -> list[dict]:
    """
    Fetch all MLB player props for today across all games.
    Returns flat list of prop dicts ready for NB model.

    Each dict has: player, market, direction, line, over_odds, under_odds,
                   matchup, sportsbook, + feature columns (added by enrich step)
    """
    if markets is None:
        markets = ["pitcher_strikeouts", "batter_hits", "batter_total_bases", "batter_home_runs"]

    key = os.environ.get("ODDS_API_KEY")
    if not key:
        if verbose:
            print("  [props] No ODDS_API_KEY")
        return []

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"mlb_props_{'_'.join(markets)}.json"

    if not refresh and cache_file.exists():
        age = datetime.now(timezone.utc).timestamp() - cache_file.stat().st_mtime
        if age < 1800 and verbose:
            print(f"  [props] Using cached props ({age/60:.0f}m old)")
            return json.loads(cache_file.read_text())

    # Step 1: Get today's game event IDs
    try:
        resp = requests.get(
            f"{_ODDS_BASE}/sports/baseball_mlb/events",
            params={"apiKey": key},
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        if verbose:
            print(f"  [props] Events fetch failed: {e}")
        return []

    if verbose:
        print(f"  [props] {len(events)} game(s) today")

    props: list[dict] = []
    markets_str = ",".join(markets)

    for ev in events:
        ev_id  = ev["id"]
        home   = ev.get("home_team", "")
        away   = ev.get("away_team", "")
        matchup = f"{away} @ {home}"

        try:
            resp2 = requests.get(
                f"{_ODDS_BASE}/sports/baseball_mlb/events/{ev_id}/odds",
                params={
                    "apiKey":     key,
                    "regions":    "us,us2",
                    "markets":    markets_str,
                    "oddsFormat": "american",
                },
                timeout=15,
            )
            resp2.raise_for_status()
            game_data = resp2.json()
        except Exception as e:
            if verbose:
                print(f"  [props] {matchup} fetch failed: {e}")
            continue

        # Parse props per bookmaker
        by_player_market: dict[tuple, dict] = {}
        for book in game_data.get("bookmakers", []):
            book_name = book.get("title", "")
            for market in book.get("markets", []):
                mkey     = market.get("key", "")
                outcomes = market.get("outcomes", [])

                # Group outcomes by (player, line)
                for o in outcomes:
                    direction = o.get("name", "").upper()  # OVER / UNDER
                    player    = o.get("description", "")
                    line      = float(o.get("point", 0))
                    price     = int(o.get("price", -110))
                    if not player or not line:
                        continue

                    key_tuple = (player, mkey, line, book_name)
                    if key_tuple not in by_player_market:
                        by_player_market[key_tuple] = {
                            "player":    player,
                            "market":    mkey,
                            "line":      line,
                            "matchup":   matchup,
                            "sportsbook": book_name,
                        }
                    if direction == "OVER":
                        by_player_market[key_tuple]["over_odds"] = price
                    elif direction == "UNDER":
                        by_player_market[key_tuple]["under_odds"] = price

        for prop in by_player_market.values():
            if "over_odds" in prop and "under_odds" in prop:
                props.append(prop)

    if verbose:
        print(f"  [props] Fetched {len(props)} player props across {len(events)} games")

    cache_file.write_text(json.dumps(props, indent=2))
    return props


def enrich_props_with_stats(props: list[dict], verbose: bool = True) -> list[dict]:
    """
    Add pitcher/batter stat features to each prop dict.
    Caches player stats lookups to avoid repeated API calls.
    For pitcher props, looks up the opposing team's K-rate from MLB Stats API.
    """
    stat_cache: dict[str, dict] = {}
    team_k_cache: dict[str, float] = {}
    enriched     = []
    n_looked_up  = 0

    for prop in props:
        player  = prop.get("player", "")
        market  = prop.get("market", "")
        matchup = prop.get("matchup", "")  # "Away @ Home"

        cache_key = f"{player}::{market}"
        if cache_key not in stat_cache:
            if "pitcher" in market:
                # Infer opposing team from matchup: pitcher is home → opp is away team
                opp_team = matchup.split(" @ ")[0] if " @ " in matchup else ""
                if opp_team and opp_team not in team_k_cache:
                    team_k_cache[opp_team] = get_team_k_rate(opp_team)
                opp_k_rate = team_k_cache.get(opp_team, 0.22)
                stat_cache[cache_key] = get_pitcher_stats_row(player, opp_k_rate=opp_k_rate)
            else:
                stat_cache[cache_key] = get_batter_stats_row(player)
            n_looked_up += 1
            if n_looked_up % 10 == 0 and verbose:
                print(f"  [props] Looked up {n_looked_up} player stat rows...")

        row = {**prop, **stat_cache[cache_key]}
        enriched.append(row)

    if verbose:
        print(f"  [props] Enriched {len(enriched)} props ({n_looked_up} new stat lookups)")

    return enriched
