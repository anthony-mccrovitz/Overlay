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


def weather_run_adjustment(
    wind_mph: float,
    wind_dir_deg: float,
    is_outdoor: bool,
) -> float:
    """
    Estimate run adjustment from wind.

    Convention: wind_dir_deg is the direction the wind is coming FROM
    (meteorological standard). A wind blowing *out* to center field
    corresponds roughly to wind coming from behind home plate, i.e.
    from the south (180 deg) toward the outfield — which in standard
    orientation means the wind direction reported is ~135-225 deg.

    Simplified logic used here:
      - "blowing out"  = wind_dir_deg in [45, 135]  (wind from SW/W/NW, pushing toward CF)
      - "blowing in"   = wind_dir_deg in [225, 315]
      - thresholds: 15 mph => +/-0.4 runs, 10 mph => +/-0.2 runs

    Returns 0.0 for non-outdoor parks.
    """
    if not is_outdoor:
        return 0.0

    blowing_out = 45 <= wind_dir_deg <= 135
    blowing_in = 225 <= wind_dir_deg <= 315

    if blowing_out:
        if wind_mph >= 15:
            return 0.4
        if wind_mph >= 10:
            return 0.2
    elif blowing_in:
        if wind_mph >= 15:
            return -0.4
        if wind_mph >= 10:
            return -0.2

    return 0.0
