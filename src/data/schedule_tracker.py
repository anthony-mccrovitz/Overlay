"""
Rest days, back-to-back detection, and travel fatigue for NBA and NHL.
Used by models to adjust projected spreads and totals.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

# Stadium/arena coordinates for travel distance calculation
_ARENA_COORDS: dict[str, tuple[float, float]] = {
    # NBA
    "Atlanta Hawks": (33.757, -84.396),
    "Boston Celtics": (42.366, -71.062),
    "Brooklyn Nets": (40.683, -73.975),
    "Charlotte Hornets": (35.225, -80.839),
    "Chicago Bulls": (41.881, -87.674),
    "Cleveland Cavaliers": (41.497, -81.688),
    "Dallas Mavericks": (32.790, -96.810),
    "Denver Nuggets": (39.749, -104.999),
    "Detroit Pistons": (42.341, -83.055),
    "Golden State Warriors": (37.768, -122.388),
    "Houston Rockets": (29.751, -95.362),
    "Indiana Pacers": (39.764, -86.156),
    "Los Angeles Clippers": (34.043, -118.267),
    "Los Angeles Lakers": (34.043, -118.267),
    "Memphis Grizzlies": (35.138, -90.051),
    "Miami Heat": (25.781, -80.188),
    "Milwaukee Bucks": (43.045, -87.917),
    "Minnesota Timberwolves": (44.979, -93.276),
    "New Orleans Pelicans": (29.949, -90.082),
    "New York Knicks": (40.751, -73.994),
    "Oklahoma City Thunder": (35.463, -97.515),
    "Orlando Magic": (28.539, -81.384),
    "Philadelphia 76ers": (39.901, -75.172),
    "Phoenix Suns": (33.446, -112.071),
    "Portland Trail Blazers": (45.532, -122.667),
    "Sacramento Kings": (38.580, -121.499),
    "San Antonio Spurs": (29.427, -98.438),
    "Toronto Raptors": (43.643, -79.379),
    "Utah Jazz": (40.768, -111.901),
    "Washington Wizards": (38.898, -77.021),
    # NHL (approx arena locations)
    "Anaheim Ducks": (33.807, -117.877),
    "Boston Bruins": (42.366, -71.062),
    "Buffalo Sabres": (42.875, -78.877),
    "Calgary Flames": (51.038, -114.052),
    "Carolina Hurricanes": (35.803, -78.722),
    "Chicago Blackhawks": (41.881, -87.674),
    "Colorado Avalanche": (39.749, -104.999),
    "Columbus Blue Jackets": (39.969, -83.006),
    "Dallas Stars": (32.790, -96.810),
    "Detroit Red Wings": (42.341, -83.055),
    "Edmonton Oilers": (53.547, -113.498),
    "Florida Panthers": (26.158, -80.323),
    "Los Angeles Kings": (34.043, -118.267),
    "Minnesota Wild": (44.945, -93.101),
    "Montreal Canadiens": (45.496, -73.569),
    "Nashville Predators": (36.159, -86.779),
    "New Jersey Devils": (40.734, -74.171),
    "New York Islanders": (40.723, -73.590),
    "New York Rangers": (40.751, -73.994),
    "Ottawa Senators": (45.297, -75.927),
    "Philadelphia Flyers": (39.901, -75.172),
    "Pittsburgh Penguins": (40.439, -79.989),
    "San Jose Sharks": (37.333, -121.901),
    "Seattle Kraken": (47.622, -122.354),
    "St. Louis Blues": (38.627, -90.203),
    "Tampa Bay Lightning": (27.943, -82.452),
    "Toronto Maple Leafs": (43.643, -79.379),
    "Utah Hockey Club": (40.768, -111.901),
    "Vancouver Canucks": (49.278, -123.109),
    "Vegas Golden Knights": (36.103, -115.178),
    "Washington Capitals": (38.898, -77.021),
    "Winnipeg Jets": (49.893, -97.143),
}

# Rest-day value by days of rest (diminishing returns past 2 days)
_REST_VALUE_NBA = {0: -2.5, 1: -1.0, 2: 0.0, 3: 0.5, 4: 0.5}   # pts relative to 2-day rest
_REST_VALUE_NHL = {0: -0.4, 1: -0.15, 2: 0.0, 3: 0.1, 4: 0.1}  # goals relative to 2-day rest



def _get_sport_schedule(team: str, sport: str) -> list[str]:
    """Load cached schedule for a team. Returns list of game date strings YYYYMMDD."""
    cache_dir = Path(f"data/cache/schedule/{sport}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = team.lower().replace(" ", "_")
    cache_file = cache_dir / f"{slug}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass
    return []


def get_rest_days(team: str, game_date: date, sport: str) -> int:
    """
    Return days of rest before game_date for the given team.
    0 = back-to-back, 1 = one day off, 2+ = normal rest.
    Falls back to 2 (neutral) if schedule data unavailable.
    """
    schedule = _get_sport_schedule(team, sport)
    if not schedule:
        return 2  # neutral fallback

    game_ds = game_date.strftime("%Y%m%d")
    past_games = sorted(g for g in schedule if g < game_ds)
    if not past_games:
        return 2

    last_game = past_games[-1]
    last_date = date(int(last_game[:4]), int(last_game[4:6]), int(last_game[6:]))
    return min((game_date - last_date).days - 1, 4)  # cap at 4




