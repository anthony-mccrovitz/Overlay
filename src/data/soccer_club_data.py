"""
Club soccer match-result loader (MLS + Liga MX).

Source: ESPN's public scoreboard API (no key). Full seasons fetch in one call
via a date-range query, cached locally per league-year.

    https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates=YYYY0101-YYYY1231

The international model (SoccerModelV2 / soccer_data.py) is national-teams-only
and CANNOT price club fixtures — every club falls back to a 1500 default and the
model emits an identical team-blind price for every game (the MLS shadow record
was 2-11 on exactly that). This module feeds a dedicated club model instead.

Name reconciliation is the whole ballgame: ESPN says "LAFC" / "Tigres UANL",
the Odds API says "Los Angeles FC" / "Tigres". Both are normalized to a single
canonical form (the Odds API name, since that's the prediction surface) via
CLUB_ALIASES + normalize_club_team_name. LEAGUE_ROSTERS is the source of truth
for who is actually in each league; training keeps only matches where BOTH teams
are in the roster, which cleanly drops All-Star games, pre-season friendlies
(e.g. "Arsenal"), and cross-league cup ties.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import requests

CACHE_DIR = Path("data/cache/soccer")
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Overlay sport_key → ESPN league code.
ESPN_LEAGUE_CODE: dict[str, str] = {
    "soccer_usa_mls":        "usa.1",
    "soccer_mexico_ligamx":  "mex.1",
}

# Canonical team name → set of source variants (ESPN and/or Odds API) that map
# to it. Canonical form = the Odds API name we predict on. Any variant not
# listed passes through unchanged (and, if absent from the roster, is dropped
# from training / flagged as unpriceable).
_MLS_VARIANTS: dict[str, list[str]] = {
    "Atlanta United FC":     [],
    "Austin FC":             [],
    "Charlotte FC":          [],
    "Chicago Fire":          ["Chicago Fire FC"],
    "Colorado Rapids":       [],
    "Columbus Crew SC":      ["Columbus Crew"],
    "D.C. United":           [],
    "FC Cincinnati":         [],
    "FC Dallas":             [],
    "Houston Dynamo":        ["Houston Dynamo FC"],
    "Inter Miami CF":        [],
    "LA Galaxy":             [],
    "Los Angeles FC":        ["LAFC"],
    "CF Montreal":           ["CF Montréal"],
    "Minnesota United FC":   [],
    "Nashville SC":          [],
    "New England Revolution":[],
    "New York City FC":      [],
    "New York Red Bulls":    ["Red Bull New York"],
    "Orlando City SC":       [],
    "Philadelphia Union":    [],
    "Portland Timbers":      [],
    "Real Salt Lake":        [],
    "San Diego FC":          [],
    "San Jose Earthquakes":  [],
    "Seattle Sounders FC":   [],
    "Sporting Kansas City":  [],
    "St. Louis City SC":     ["St. Louis CITY SC"],
    "Toronto FC":            [],
    "Vancouver Whitecaps FC":["Vancouver Whitecaps"],
}

_LIGAMX_VARIANTS: dict[str, list[str]] = {
    "América":            [],
    "Atlas":              [],
    "Atlético San Luis":  ["Atlético de San Luis"],
    "Cruz Azul":          [],
    "FC Juárez":          ["FC Juarez"],
    "Guadalajara":        [],
    "León":               [],
    "Mazatlán FC":        [],
    "Monterrey":          [],
    "Necaxa":             [],
    "Pachuca":            [],
    "Puebla":             [],
    "Pumas":              ["Pumas UNAM"],
    "Querétaro":          [],
    "Santos Laguna":      ["Santos"],
    "Tigres":             ["Tigres UANL"],
    "Tijuana":            [],
    "Toluca":             [],
    # Atlante is currently a second-division side but shows up in some cup/odds
    # data; map its variants so it never silently defaults, though it won't be
    # in the top-flight roster used for the intra-league training filter.
    "Atlante FC":         ["Atlante"],
}

LEAGUE_ROSTERS: dict[str, set[str]] = {
    "soccer_usa_mls":       set(_MLS_VARIANTS),
    "soccer_mexico_ligamx": set(_LIGAMX_VARIANTS) - {"Atlante FC"},
}

# Build variant → canonical lookup once.
CLUB_ALIASES: dict[str, str] = {}
for _canon, _variants in {**_MLS_VARIANTS, **_LIGAMX_VARIANTS}.items():
    for _v in _variants:
        CLUB_ALIASES[_v] = _canon


def normalize_club_team_name(name: str) -> str:
    """Map an ESPN or Odds API club name onto its canonical (Odds API) form."""
    return CLUB_ALIASES.get(name, name)


def _fetch_season(espn_code: str, year: int, refresh: bool = False) -> list[dict]:
    """Fetch one league-year of ESPN scoreboard events (whole season, one call).
    Cached to data/cache/soccer/club_{code}_{year}.json for 1 day (current
    season) / effectively forever (past seasons rarely change)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"club_{espn_code}_{year}.json"
    if not refresh and cache.exists():
        age = time.time() - cache.stat().st_mtime
        # Past seasons are immutable; only refresh the current year daily.
        if year < datetime.now().year or age < 86400:
            try:
                return json.loads(cache.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    try:
        resp = requests.get(
            f"{ESPN_BASE}/{espn_code}/scoreboard",
            params={"dates": f"{year}0101-{year}1231", "limit": 900},
            timeout=30,
        )
        resp.raise_for_status()
        events = resp.json().get("events", [])
        cache.write_text(json.dumps(events))
        return events
    except Exception as e:
        print(f"  [club_data] ESPN fetch failed {espn_code} {year}: {e}")
        if cache.exists():
            try:
                return json.loads(cache.read_text())
            except (json.JSONDecodeError, OSError):
                return []
        return []


def _stat(competitor: dict, name: str) -> float | None:
    """Pull a named stat (e.g. totalShots) from an ESPN competitor's embedded
    scoreboard statistics. None if absent (older games may lack shot stats)."""
    for st in competitor.get("statistics", []):
        if st.get("name") == name:
            try:
                return float(st.get("displayValue"))
            except (TypeError, ValueError):
                return None
    return None


def _parse_event(ev: dict, league_name: str) -> dict | None:
    """Parse one ESPN event into a standard match dict, or None if unusable."""
    comps = ev.get("competitions", [])
    if not comps:
        return None
    comp = comps[0]
    status = comp.get("status", {}).get("type", {})
    if not status.get("completed"):
        return None  # only settled results train the model
    teams = comp.get("competitors", [])
    if len(teams) != 2:
        return None

    home_c = next((c for c in teams if c.get("homeAway") == "home"), None)
    away_c = next((c for c in teams if c.get("homeAway") == "away"), None)
    if home_c is None or away_c is None:
        return None

    home = normalize_club_team_name(home_c.get("team", {}).get("displayName", ""))
    away = normalize_club_team_name(away_c.get("team", {}).get("displayName", ""))
    try:
        hs = int(home_c.get("score"))
        as_ = int(away_c.get("score"))
    except (TypeError, ValueError):
        return None

    date_str = ev.get("date", "")[:10]
    try:
        match_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    # Full kickoff datetime (UTC) — needed to target the true pre-game closing
    # odds board in the CLV backtest (guessing the time captures in-play odds).
    kickoff = None
    try:
        kickoff = datetime.fromisoformat(ev.get("date", "").replace("Z", "+00:00"))
    except ValueError:
        pass

    return {
        "date":       match_date,
        "kickoff":    kickoff,
        "home_team":  home,
        "away_team":  away,
        "home_score": hs,
        "away_score": as_,
        # Shot volume (embedded in the scoreboard, no extra calls) → xG proxy.
        "home_shots": _stat(home_c, "totalShots"),
        "away_shots": _stat(away_c, "totalShots"),
        "home_sot":   _stat(home_c, "shotsOnTarget"),
        "away_sot":   _stat(away_c, "shotsOnTarget"),
        "tournament": league_name,
        "year":       match_date.year,
        "neutral":    False,   # club league games have a real home side
    }


# ── Venues: altitude (m) + coordinates for rest/altitude/travel features ──────
# Altitude is the marquee signal (Liga MX high-altitude venues); coordinates
# drive away-travel distance. Values are stadium-city approximations.
VENUES: dict[str, dict[str, float]] = {
    # MLS
    "Atlanta United FC":      {"alt": 320,  "lat": 33.75,  "lon": -84.40},
    "Austin FC":              {"alt": 149,  "lat": 30.27,  "lon": -97.74},
    "Charlotte FC":           {"alt": 229,  "lat": 35.23,  "lon": -80.84},
    "Chicago Fire":           {"alt": 182,  "lat": 41.86,  "lon": -87.62},
    "Colorado Rapids":        {"alt": 1580, "lat": 39.81,  "lon": -104.89},
    "Columbus Crew SC":       {"alt": 275,  "lat": 39.96,  "lon": -83.00},
    "D.C. United":            {"alt": 6,    "lat": 38.87,  "lon": -77.01},
    "FC Cincinnati":          {"alt": 150,  "lat": 39.11,  "lon": -84.52},
    "FC Dallas":              {"alt": 200,  "lat": 33.15,  "lon": -96.83},
    "Houston Dynamo":         {"alt": 15,   "lat": 29.75,  "lon": -95.35},
    "Inter Miami CF":         {"alt": 3,    "lat": 26.19,  "lon": -80.16},
    "LA Galaxy":              {"alt": 12,   "lat": 33.86,  "lon": -118.26},
    "Los Angeles FC":         {"alt": 58,   "lat": 34.01,  "lon": -118.28},
    "CF Montreal":            {"alt": 36,   "lat": 45.56,  "lon": -73.55},
    "Minnesota United FC":    {"alt": 265,  "lat": 44.95,  "lon": -93.10},
    "Nashville SC":           {"alt": 168,  "lat": 36.13,  "lon": -86.77},
    "New England Revolution": {"alt": 89,   "lat": 42.09,  "lon": -71.26},
    "New York City FC":       {"alt": 8,    "lat": 40.83,  "lon": -73.93},
    "New York Red Bulls":     {"alt": 3,    "lat": 40.74,  "lon": -74.15},
    "Orlando City SC":        {"alt": 30,   "lat": 28.54,  "lon": -81.39},
    "Philadelphia Union":     {"alt": 3,    "lat": 39.83,  "lon": -75.38},
    "Portland Timbers":       {"alt": 15,   "lat": 45.52,  "lon": -122.69},
    "Real Salt Lake":         {"alt": 1300, "lat": 40.58,  "lon": -111.89},
    "San Diego FC":           {"alt": 20,   "lat": 32.71,  "lon": -117.16},
    "San Jose Earthquakes":   {"alt": 26,   "lat": 37.35,  "lon": -121.92},
    "Seattle Sounders FC":    {"alt": 56,   "lat": 47.60,  "lon": -122.33},
    "Sporting Kansas City":   {"alt": 265,  "lat": 39.12,  "lon": -94.82},
    "St. Louis City SC":      {"alt": 142,  "lat": 38.63,  "lon": -90.21},
    "Toronto FC":             {"alt": 76,   "lat": 43.63,  "lon": -79.42},
    "Vancouver Whitecaps FC": {"alt": 4,    "lat": 49.28,  "lon": -123.11},
    # Liga MX — altitude is the key signal
    "América":            {"alt": 2240, "lat": 19.30, "lon": -99.15},
    "Atlas":              {"alt": 1566, "lat": 20.68, "lon": -103.46},
    "Atlético San Luis":  {"alt": 1860, "lat": 22.15, "lon": -100.98},
    "Cruz Azul":          {"alt": 2240, "lat": 19.30, "lon": -99.15},
    "FC Juárez":          {"alt": 1140, "lat": 31.69, "lon": -106.42},
    "Guadalajara":        {"alt": 1551, "lat": 20.68, "lon": -103.46},
    "León":               {"alt": 1815, "lat": 21.12, "lon": -101.68},
    "Mazatlán FC":        {"alt": 3,    "lat": 23.24, "lon": -106.42},
    "Monterrey":          {"alt": 540,  "lat": 25.67, "lon": -100.24},
    "Necaxa":             {"alt": 1880, "lat": 21.88, "lon": -102.28},
    "Pachuca":            {"alt": 2400, "lat": 20.12, "lon": -98.73},
    "Puebla":             {"alt": 2135, "lat": 19.03, "lon": -98.20},
    "Pumas":              {"alt": 2240, "lat": 19.33, "lon": -99.18},
    "Querétaro":          {"alt": 1820, "lat": 20.59, "lon": -100.39},
    "Santos Laguna":      {"alt": 1120, "lat": 25.55, "lon": -103.41},
    "Tigres":             {"alt": 500,  "lat": 25.72, "lon": -100.31},
    "Tijuana":            {"alt": 20,   "lat": 32.51, "lon": -117.01},
    "Toluca":             {"alt": 2660, "lat": 19.29, "lon": -99.66},
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    from math import radians, sin, cos, asin, sqrt
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def load_club_matches(
    sport_key: str,
    seasons: list[int] | None = None,
    refresh: bool = False,
    intra_league_only: bool = True,
) -> list[dict]:
    """
    Load completed club-league results for a league (MLS or Liga MX).

    intra_league_only keeps only matches where BOTH teams are in the league
    roster — this drops All-Star games, pre-season friendlies vs foreign clubs,
    and cross-league cup ties that would otherwise pollute the single-league
    Elo pool.
    """
    espn_code = ESPN_LEAGUE_CODE.get(sport_key)
    if not espn_code:
        raise ValueError(f"No ESPN league code for {sport_key}")
    if seasons is None:
        this_year = datetime.now().year
        seasons = list(range(this_year - 4, this_year + 1))

    league_name = {"soccer_usa_mls": "MLS", "soccer_mexico_ligamx": "Liga MX"}.get(
        sport_key, sport_key)
    roster = LEAGUE_ROSTERS.get(sport_key, set())

    matches: list[dict] = []
    for yr in seasons:
        for ev in _fetch_season(espn_code, yr, refresh=refresh):
            m = _parse_event(ev, league_name)
            if m is None:
                continue
            if intra_league_only and (
                m["home_team"] not in roster or m["away_team"] not in roster):
                continue
            matches.append(m)
        time.sleep(0.2)

    # De-dup (a fixture can appear in adjacent range windows) and sort causally.
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for m in sorted(matches, key=lambda x: x["date"]):
        key = (m["date"], m["home_team"], m["away_team"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    print(f"  [club_data] {league_name}: {len(deduped)} completed intra-league "
          f"matches across seasons {seasons[0]}–{seasons[-1]}")
    return deduped
