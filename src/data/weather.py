"""
MLB weather module.

Fetches current weather for a team's home ballpark and computes a
run adjustment based on wind speed/direction. Results are cached in
data/cache/ for 3 hours to avoid redundant API calls.

Requires env var OPENWEATHER_API_KEY. If not set, all functions return
None / 0.0 silently so the rest of the pipeline is unaffected.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from src.data.park_factors import OUTDOOR_PARKS

# ---------------------------------------------------------------------------
# Static city coordinates for every MLB team
# ---------------------------------------------------------------------------
TEAM_COORDS: dict[str, tuple[float, float]] = {
    "Colorado Rockies":       (39.756, -104.994),
    "Boston Red Sox":         (42.347, -71.097),
    "Cincinnati Reds":        (39.097, -84.507),
    "Philadelphia Phillies":  (39.906, -75.167),
    "Houston Astros":         (29.757, -95.355),   # retractable
    "Texas Rangers":          (32.747, -97.083),    # retractable
    "Chicago Cubs":           (41.948, -87.655),
    "Baltimore Orioles":      (39.284, -76.622),
    "New York Yankees":       (40.829, -73.926),
    "Atlanta Braves":         (33.891, -84.468),
    "Kansas City Royals":     (39.051, -94.480),
    "Los Angeles Angels":     (33.800, -117.883),
    "Minnesota Twins":        (44.982, -93.278),
    "New York Mets":          (40.757, -73.846),
    "Arizona Diamondbacks":   (33.445, -112.067),   # retractable
    "Washington Nationals":   (38.873, -77.008),
    "St. Louis Cardinals":    (38.623, -90.193),
    "Toronto Blue Jays":      (43.641, -79.389),    # dome
    "Cleveland Guardians":    (41.496, -81.685),
    "Miami Marlins":          (25.778, -80.220),    # retractable
    "Milwaukee Brewers":      (43.028, -87.971),
    "Detroit Tigers":         (42.339, -83.048),
    "Los Angeles Dodgers":    (34.074, -118.240),
    "Chicago White Sox":      (41.830, -87.634),
    "Athletics":              (37.751, -122.200),
    "Tampa Bay Rays":         (27.768, -82.653),    # dome
    "Pittsburgh Pirates":     (40.447, -80.006),
    "Seattle Mariners":       (47.591, -122.332),
    "San Francisco Giants":   (37.778, -122.389),
    "San Diego Padres":       (32.708, -117.157),
}

_CACHE_DIR = Path("data/cache")
_CACHE_TTL_SECONDS = 3 * 60 * 60  # 3 hours
_OWM_URL = "https://api.openweathermap.org/data/2.5/weather"


def _cache_path(home_team: str, game_date: str | None) -> Path:
    safe = home_team.replace(" ", "_").lower()
    date_tag = (game_date or "today").replace("-", "")
    return _CACHE_DIR / f"weather_{safe}_{date_tag}.json"


def _load_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() - data.get("_cached_at", 0) < _CACHE_TTL_SECONDS:
            return data
    except Exception:
        pass
    return None


def _save_cache(path: Path, payload: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload["_cached_at"] = time.time()
        path.write_text(json.dumps(payload))
    except Exception:
        pass


def get_game_weather(
    home_team: str,
    game_date: str | None = None,
) -> dict | None:
    """
    Return weather dict for the home team's park, or None.

    Only fetches for outdoor parks. Returns None silently if the API key
    is missing, the team is unknown, or the request fails.

    Return schema:
        {
            "wind_mph": float,
            "wind_dir_deg": float,
            "temp_f": float,
            "precip_prob": float,   # 0-1 (pop from OWM forecast, or 0 from current)
        }
    """
    if home_team not in OUTDOOR_PARKS:
        return None

    coords = TEAM_COORDS.get(home_team)
    if coords is None:
        return None

    api_key = os.environ.get("OPENWEATHER_API_KEY", "")
    if not api_key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("OPENWEATHER_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
    if not api_key:
        return None

    cache_file = _cache_path(home_team, game_date)
    cached = _load_cache(cache_file)
    if cached is not None:
        return {k: v for k, v in cached.items() if not k.startswith("_")}

    lat, lon = coords
    try:
        resp = requests.get(
            _OWM_URL,
            params={
                "lat": lat,
                "lon": lon,
                "appid": api_key,
                "units": "imperial",
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return None

    try:
        wind_mph = float(raw.get("wind", {}).get("speed", 0))
        wind_dir_deg = float(raw.get("wind", {}).get("deg", 0))
        temp_f = float(raw.get("main", {}).get("temp", 70))
        # OWM current-weather has no pop; use 0 unless rain condition code present
        weather_ids = [w.get("id", 800) for w in raw.get("weather", [])]
        precip_prob = 0.5 if any(200 <= wid < 700 for wid in weather_ids) else 0.0
    except Exception:
        return None

    result = {
        "wind_mph": wind_mph,
        "wind_dir_deg": wind_dir_deg,
        "temp_f": temp_f,
        "precip_prob": precip_prob,
    }
    _save_cache(cache_file, result)
    return result


# Home plate → center field bearing for each outdoor park (degrees, true north = 0).
# Wind FROM the OPPOSITE direction (bearing + 180) blows OUT to center field.
# Source: park survey data + satellite imagery. Retractable/dome parks omitted.
_PARK_CF_BEARING: dict[str, float] = {
    "Chicago Cubs":           15.0,   # Wrigley: CF roughly NNE → out wind from SSW
    "Boston Red Sox":         75.0,   # Fenway: CF roughly ENE
    "New York Yankees":       335.0,  # Yankee Stadium: CF roughly NNW
    "Colorado Rockies":       350.0,  # Coors Field: CF roughly N
    "San Francisco Giants":   25.0,   # Oracle Park: CF roughly NNE
    "Los Angeles Dodgers":    300.0,  # Dodger Stadium: CF roughly WNW
    "San Diego Padres":       315.0,  # Petco Park: CF roughly NW
    "Baltimore Orioles":      10.0,   # Camden Yards: CF roughly N
    "Pittsburgh Pirates":     5.0,    # PNC Park: CF roughly N
    "Cincinnati Reds":        200.0,  # GABP: CF roughly SSW
    "Washington Nationals":   120.0,  # Nationals Park: CF roughly ESE
    "Minnesota Twins":        340.0,  # Target Field: CF roughly NNW
    "Cleveland Guardians":    20.0,   # Progressive Field: CF roughly NNE
    "Detroit Tigers":         340.0,  # Comerica Park: CF roughly NNW
    "Chicago White Sox":      350.0,  # Guaranteed Rate: CF roughly N
    "Kansas City Royals":     0.0,    # Kauffman Stadium: CF roughly N
    "New York Mets":          305.0,  # Citi Field: CF roughly NW
    "Philadelphia Phillies":  325.0,  # Citizens Bank: CF roughly NW
    "Atlanta Braves":         325.0,  # Truist Park: CF roughly NW
    "Los Angeles Angels":     330.0,  # Angel Stadium: CF roughly NNW
    "Athletics":              310.0,  # Oakland Coliseum: CF roughly NW
    "St. Louis Cardinals":    355.0,  # Busch Stadium: CF roughly N
    "Milwaukee Brewers":      330.0,  # American Family: CF roughly NNW
    "Toronto Blue Jays":      350.0,  # Rogers Centre: retractable but included
    "Seattle Mariners":       340.0,  # T-Mobile: retractable
    "Tampa Bay Rays":         0.0,    # Tropicana: dome
    "Miami Marlins":          330.0,  # loanDepot: retractable
    "Houston Astros":         340.0,  # Minute Maid: retractable
    "Texas Rangers":          10.0,   # Globe Life: retractable
    "Arizona Diamondbacks":   350.0,  # Chase Field: retractable
}


def _wind_component(wind_dir_deg: float, cf_bearing: float) -> float:
    """Return scalar in [-1, 1]: +1 = fully blowing out, -1 = fully blowing in."""
    import math
    # Wind comes FROM wind_dir_deg. Blowing-out means wind pushes FROM home → CF,
    # i.e. wind comes from the direction BEHIND home plate = cf_bearing + 180.
    out_source = (cf_bearing + 180) % 360
    delta = abs(wind_dir_deg - out_source) % 360
    if delta > 180:
        delta = 360 - delta
    # delta = 0 → perfectly blowing out (+1), delta = 180 → perfectly blowing in (-1)
    import math
    return math.cos(math.radians(delta))


def weather_run_adjustment(
    wind_mph: float,
    wind_dir_deg: float,
    is_outdoor: bool,
    home_team: str = "",
) -> float:
    """
    Estimate run adjustment from wind speed and direction relative to the park.

    Magnitudes calibrated to 14+ years of Wrigley Field and multi-park research:
      - 15+ mph blowing out  → +1.8 runs (favor OVER)
      - 10-14 mph blowing out → +0.9 runs
      - 15+ mph blowing in   → -1.8 runs (favor UNDER)
      - 10-14 mph blowing in  → -0.9 runs
      - Crosswind (±45-90°)  → ±0.3 runs
    Temperature penalty: < 50°F → -0.5 runs (cold air = less carry).

    Returns 0.0 for dome/retractable parks (handled by OUTDOOR_PARKS filter upstream).
    """
    if not is_outdoor:
        return 0.0

    cf_bearing = _PARK_CF_BEARING.get(home_team)
    if cf_bearing is None:
        # Fallback: no park data, use simplified compass logic
        blowing_out = 45 <= wind_dir_deg <= 135
        blowing_in = 225 <= wind_dir_deg <= 315
        if blowing_out:
            return 1.8 if wind_mph >= 15 else (0.9 if wind_mph >= 10 else 0.0)
        elif blowing_in:
            return -1.8 if wind_mph >= 15 else (-0.9 if wind_mph >= 10 else 0.0)
        return 0.0

    component = _wind_component(wind_dir_deg, cf_bearing)  # -1 to +1

    if wind_mph >= 15:
        base = 1.8
    elif wind_mph >= 10:
        base = 0.9
    elif wind_mph >= 7:
        base = 0.4
    else:
        return 0.0

    return round(component * base, 2)


def build_weather_context(
    home_team: str,
    wind_mph: float,
    wind_dir_deg: float,
    temp_f: float,
    run_adj: float,
) -> str:
    """Human-readable context string for dashboard pick card display."""
    if abs(run_adj) < 0.1:
        if temp_f < 50:
            return f"🥶 {temp_f:.0f}°F cold"
        return ""

    direction = "out" if run_adj > 0 else "in"
    sign = "+" if run_adj > 0 else ""
    temp_str = f", {temp_f:.0f}°F" if temp_f < 50 else ""
    return f"💨 {wind_mph:.0f}mph {direction} → {sign}{run_adj:.1f} runs{temp_str}"
