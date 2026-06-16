"""
International football match data loader.

Primary source: martj42/international_results CSV dataset
  All international results from 1872–present (qualifiers, tournaments, friendlies).
  Filtered to competitive matches only for Dixon-Coles training.

Supplementary: openfootball/world-cup.json GitHub dataset
  Used as fallback if martj42 fetch fails.

Usage:
    from src.data.soccer_data import load_training_data, get_elo_ratings
    history = load_training_data()      # competitive internationals 2012+
    elo = get_elo_ratings()             # World Football Elo ratings dict
"""
from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime, date
from pathlib import Path

import requests

CACHE_DIR = Path("data/cache/soccer")

# martj42/international_results — all international results from 1872–present
INTL_RESULTS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"

# Only include these tournament types for Dixon-Coles training (no friendlies)
COMPETITIVE_TOURNAMENTS: frozenset[str] = frozenset([
    "FIFA World Cup",
    "FIFA World Cup qualification",
    "UEFA Euro",
    "UEFA Euro qualification",
    "Copa América",
    "Copa America",
    "Gold Cup",
    "CONCACAF Gold Cup",
    "CONCACAF Nations League",
    "UEFA Nations League",
    "Africa Cup of Nations",
    "African Nations Cup",
    "AFC Asian Cup",
    "AFC Asian Cup qualification",
    "Confederations Cup",
    "FIFA Confederations Cup",
    "CONMEBOL–UEFA Cup of Champions",
])

# openfootball World Cup JSON — confirmed working
WC_URLS = {
    2014: "https://raw.githubusercontent.com/openfootball/world-cup.json/master/2014/worldcup.json",
    2018: "https://raw.githubusercontent.com/openfootball/world-cup.json/master/2018/worldcup.json",
    2022: "https://raw.githubusercontent.com/openfootball/world-cup.json/master/2022/worldcup.json",
    2026: "https://raw.githubusercontent.com/openfootball/world-cup.json/master/2026/worldcup.json",
}

EUROS_URLS = {
    2020: "https://raw.githubusercontent.com/openfootball/euro.json/master/2020/euro.json",
    2024: "https://raw.githubusercontent.com/openfootball/euro.json/master/2024/euro.json",
}

COPA_URLS: dict[int, str] = {}  # openfootball Copa data is in .txt format, not JSON


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _fetch_json(url: str, cache_key: str, max_age_days: int = 1) -> dict | list | None:
    cache = _cache_path(cache_key)
    if cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < max_age_days * 86400:
            with open(cache) as f:
                return json.load(f)
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        print(f"  [soccer_data] Failed to fetch {url}: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return None


def load_international_results(
    min_year: int = 2012,
    competitive_only: bool = True,
) -> list[dict]:
    """
    Load all international results from the martj42 dataset (CSV on GitHub).
    ~50k matches from 1872–present. Filtered to competitive matches by default.
    Cached locally for 1 day.
    """
    cache_path = CACHE_DIR / "intl_results.csv"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    raw_csv: str | None = None
    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < 86400:
            raw_csv = cache_path.read_text(encoding="utf-8")

    if raw_csv is None:
        try:
            resp = requests.get(INTL_RESULTS_URL, timeout=30)
            resp.raise_for_status()
            raw_csv = resp.text
            cache_path.write_text(raw_csv, encoding="utf-8")
            print(f"  [soccer_data] Fetched martj42 dataset ({len(raw_csv)//1024}KB)")
        except Exception as exc:
            print(f"  [soccer_data] martj42 fetch failed: {exc}")
            if cache_path.exists():
                raw_csv = cache_path.read_text(encoding="utf-8")
                print("  [soccer_data] Using stale cache.")
            else:
                return []

    if not raw_csv:
        return []

    reader = csv.DictReader(io.StringIO(raw_csv))
    results: list[dict] = []
    for row in reader:
        try:
            match_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        if match_date.year < min_year:
            continue
        tournament = row.get("tournament", "")
        if competitive_only and tournament not in COMPETITIVE_TOURNAMENTS:
            continue
        try:
            home_score = int(row["home_score"])
            away_score = int(row["away_score"])
        except (ValueError, KeyError):
            continue
        neutral_raw = row.get("neutral", "False")
        neutral = neutral_raw.strip().lower() in ("true", "1", "yes")
        results.append({
            "date":       match_date,
            "home_team":  row.get("home_team", "").strip(),
            "away_team":  row.get("away_team", "").strip(),
            "home_score": home_score,
            "away_score": away_score,
            "tournament": tournament,
            "year":       match_date.year,
            "neutral":    neutral,
        })

    results.sort(key=lambda x: x["date"])
    return results


# In-process Elo cache so repeated calls don't recompute
_ELO_CACHE: dict[str, float] | None = None


def compute_elo_ratings(
    matches: list[dict],
    k: float = 32.0,
    base: float = 1500.0,
) -> dict[str, float]:
    """
    Compute World Football Elo ratings from a sorted list of match dicts.
    Returns {team_name: elo_rating}.

    Uses World Football Elo conventions:
    - Home advantage: +100 Elo points to home team's effective rating
    - Goal-difference multiplier: 1.0 (gd≤1), 1.5 (gd=2), (11+gd)/8 (gd≥3)
    - Standard K=32 (higher than chess, lower than some sport systems)
    """
    ratings: dict[str, float] = {}

    for m in matches:
        home = m["home_team"]
        away = m["away_team"]
        if not home or not away:
            continue

        ra = ratings.get(home, base)
        rb = ratings.get(away, base)

        # Home advantage boost (temporary — not stored)
        ra_eff = ra + (0 if m.get("neutral", False) else 100)

        ea = 1.0 / (1.0 + 10.0 ** ((rb - ra_eff) / 400.0))

        hs, as_ = m["home_score"], m["away_score"]
        if hs > as_:
            sa = 1.0
        elif hs == as_:
            sa = 0.5
        else:
            sa = 0.0

        gd = abs(hs - as_)
        if gd <= 1:
            gdf = 1.0
        elif gd == 2:
            gdf = 1.5
        else:
            gdf = (11 + gd) / 8.0

        ratings[home] = ra + k * gdf * (sa - ea)
        ratings[away] = rb + k * gdf * ((1 - sa) - (1 - ea))

    return ratings


def get_elo_ratings(min_year: int = 2000) -> dict[str, float]:
    """
    Return current World Football Elo ratings computed from all international
    results (including friendlies) from min_year. Result is cached in-process.
    """
    global _ELO_CACHE
    if _ELO_CACHE is not None:
        return _ELO_CACHE
    matches = load_international_results(min_year=min_year, competitive_only=False)
    if not matches:
        # Fallback: compute from openfootball tournament data only
        matches = []
        matches.extend(load_world_cup_history([2014, 2018, 2022]))
        matches.extend(load_euros_history([2020, 2024]))
        matches.sort(key=lambda x: x["date"])
    _ELO_CACHE = compute_elo_ratings(matches)
    return _ELO_CACHE


def _parse_openfootball(data: dict | list, tournament: str, year: int) -> list[dict]:
    """Parse openfootball JSON format into standardized match list."""
    if data is None:
        return []

    matches_raw = []
    if isinstance(data, dict):
        matches_raw = data.get("matches", data.get("rounds", []))
        # Handle rounds-based structure
        if matches_raw and isinstance(matches_raw[0], dict) and "matches" in matches_raw[0]:
            flattened = []
            for rnd in matches_raw:
                flattened.extend(rnd.get("matches", []))
            matches_raw = flattened
    elif isinstance(data, list):
        matches_raw = data

    results = []
    for m in matches_raw:
        if not isinstance(m, dict):
            continue
        date_str = m.get("date", "")
        team1 = m.get("team1", "")
        team2 = m.get("team2", "")
        score = m.get("score", {})
        if isinstance(score, dict):
            ft = score.get("ft", [])
        else:
            ft = []

        if not (date_str and team1 and team2 and len(ft) == 2):
            continue

        try:
            match_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            home_score = int(ft[0])
            away_score = int(ft[1])
        except (ValueError, TypeError, IndexError):
            continue

        results.append({
            "date":       match_date,
            "home_team":  team1,
            "away_team":  team2,
            "home_score": home_score,
            "away_score": away_score,
            "tournament": tournament,
            "year":       year,
            "neutral":    True,   # World Cup / tournament matches are at neutral venues
        })

    return results


def load_world_cup_history(years: list[int] | None = None) -> list[dict]:
    """
    Load World Cup match results for specified years.
    Default: 2014, 2018, 2022.
    """
    if years is None:
        years = [2014, 2018, 2022]

    all_matches = []
    for year in years:
        url = WC_URLS.get(year)
        if not url:
            continue
        data = _fetch_json(url, f"wc_{year}", max_age_days=7)
        matches = _parse_openfootball(data, f"FIFA World Cup {year}", year)
        all_matches.extend(matches)
        print(f"  [soccer_data] WC {year}: {len(matches)} matches")

    all_matches.sort(key=lambda x: x["date"])
    return all_matches


def load_euros_history(years: list[int] | None = None) -> list[dict]:
    """Load UEFA Euro tournament match results."""
    if years is None:
        years = [2020, 2024]

    all_matches = []
    for year in years:
        url = EUROS_URLS.get(year)
        if not url:
            continue
        data = _fetch_json(url, f"euros_{year}", max_age_days=7)
        matches = _parse_openfootball(data, f"UEFA Euro {year}", year)
        all_matches.extend(matches)
        if matches:
            print(f"  [soccer_data] Euros {year}: {len(matches)} matches")

    all_matches.sort(key=lambda x: x["date"])
    return all_matches


def load_copa_history(years: list[int] | None = None) -> list[dict]:
    """Load Copa América match results."""
    if years is None:
        years = [2021, 2024]

    all_matches = []
    for year in years:
        url = COPA_URLS.get(year)
        if not url:
            continue
        data = _fetch_json(url, f"copa_{year}", max_age_days=7)
        matches = _parse_openfootball(data, f"Copa América {year}", year)
        all_matches.extend(matches)
        if matches:
            print(f"  [soccer_data] Copa {year}: {len(matches)} matches")

    all_matches.sort(key=lambda x: x["date"])
    return all_matches


def load_training_data(min_year: int = 2012) -> list[dict]:
    """
    Load comprehensive international match data for Dixon-Coles training.
    Primary: martj42 dataset (all competitive internationals from min_year onward).
    Includes: WC qualifiers, Euros qualifiers, CONMEBOL qualifiers, Nations League,
              Copa América (all years incl. 2016/2019), Gold Cup, etc.
    Fallback: openfootball WC/Euros/Copa JSONs if martj42 fetch fails.
    """
    matches = load_international_results(min_year=min_year, competitive_only=True)
    if len(matches) < 100:
        print("  [soccer_data] martj42 unavailable — falling back to openfootball sources.")
        matches = []
        matches.extend(load_world_cup_history([2014, 2018, 2022]))
        matches.extend(load_euros_history([2020, 2024]))
        matches.extend(load_copa_history())
    matches.sort(key=lambda x: x["date"])
    print(f"  [soccer_data] Training data: {len(matches):,} competitive matches (min_year={min_year})")
    return matches


def load_upcoming_wc2026() -> list[dict]:
    """
    Load 2026 World Cup schedule/fixtures.
    Returns fixtures (may have no scores yet for future games).
    """
    url = WC_URLS.get(2026)
    data = _fetch_json(url, "wc_2026", max_age_days=1)
    if not data:
        return []
    return _parse_openfootball(data, "FIFA World Cup 2026", 2026)


def get_team_universe(matches: list[dict]) -> list[str]:
    """Return sorted list of all teams in the match list."""
    teams: set[str] = set()
    for m in matches:
        teams.add(m["home_team"])
        teams.add(m["away_team"])
    return sorted(teams)


# Odds API name → openfootball canonical name
# Maps every name variant (Odds API, openfootball bracket, FIFA "official")
# onto the martj42 canonical form the model is actually TRAINED on. The model's
# Elo / attack / defense are keyed on martj42 names, so all lookups must resolve
# there or the team silently falls back to a 1500 default (an invisible bug that
# previously hit South Korea, Czech Republic, Ivory Coast, DR Congo, Bosnia).
TEAM_ALIASES: dict[str, str] = {
    "USA":                    "United States",
    # South Korea — martj42 uses "South Korea"
    "Korea Republic":         "South Korea",
    "Korea DPR":              "North Korea",
    # Bosnia — martj42 uses "Bosnia and Herzegovina"
    "Bosnia & Herzegovina":   "Bosnia and Herzegovina",
    "Bosnia-Herzegovina":     "Bosnia and Herzegovina",
    # Czechia — martj42 uses "Czech Republic"
    "Czechia":                "Czech Republic",
    # Ivory Coast — martj42 uses "Ivory Coast"
    "Côte d'Ivoire":          "Ivory Coast",
    "Cote d'Ivoire":          "Ivory Coast",
    # DR Congo — martj42 uses "DR Congo"
    "Congo DR":               "DR Congo",
    "Trinidad & Tobago":      "Trinidad and Tobago",
    "Macao":                  "Macau",
}


def normalize_team_name(name: str) -> str:
    """Normalize Odds API team names to openfootball canonical form."""
    return TEAM_ALIASES.get(name, name)


def get_confederation(team: str) -> str:
    """Return confederation for a team (for hierarchical priors)."""
    UEFA = {
        "Germany", "France", "Spain", "England", "Italy", "Portugal", "Netherlands",
        "Belgium", "Croatia", "Denmark", "Sweden", "Norway", "Switzerland", "Austria",
        "Poland", "Czech Republic", "Hungary", "Romania", "Greece", "Turkey",
        "Serbia", "Ukraine", "Slovakia", "Wales", "Scotland", "Ireland", "Albania",
        "Slovenia", "Montenegro", "North Macedonia", "Kosovo", "Georgia", "Moldova",
        "Bosnia and Herzegovina", "Iceland", "Finland", "Latvia", "Lithuania", "Estonia",
        "Luxembourg", "Malta", "Cyprus", "Andorra", "Liechtenstein", "San Marino",
        "Faroe Islands", "Gibraltar", "Azerbaijan", "Armenia", "Kazakhstan",
    }
    CONMEBOL = {
        "Brazil", "Argentina", "Uruguay", "Colombia", "Chile", "Paraguay",
        "Ecuador", "Bolivia", "Peru", "Venezuela",
    }
    CONCACAF = {
        "United States", "Mexico", "Canada", "Costa Rica", "Panama", "Honduras",
        "Jamaica", "El Salvador", "Haiti", "Guatemala", "Trinidad and Tobago",
        "Nicaragua", "Belize", "Cuba",
    }
    CAF = {
        "Morocco", "Senegal", "Nigeria", "Ghana", "Ivory Coast", "Cameroon",
        "Egypt", "Tunisia", "Algeria", "Mali", "DR Congo", "South Africa",
        "Zimbabwe", "Zambia", "Tanzania", "Kenya", "Uganda", "Ethiopia",
        "Mozambique", "Cape Verde", "Benin", "Guinea", "Burkina Faso",
    }
    AFC = {
        "Japan", "South Korea", "Australia", "Iran", "Saudi Arabia", "Qatar",
        "UAE", "China", "Iraq", "Jordan", "Syria", "Uzbekistan", "Bahrain",
        "Oman", "Kuwait", "Lebanon", "Indonesia", "Vietnam", "Thailand",
    }
    if team in UEFA:     return "UEFA"
    if team in CONMEBOL: return "CONMEBOL"
    if team in CONCACAF: return "CONCACAF"
    if team in CAF:      return "CAF"
    if team in AFC:      return "AFC"
    return "OFC"
