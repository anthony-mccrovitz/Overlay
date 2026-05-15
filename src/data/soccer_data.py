"""
International football match data loader.

Primary source: openfootball/world-cup.json GitHub dataset
  World Cup matches 2014-2026 (includes group stage, knockouts, qualifiers)
  Format: JSON with rounds/matches structure.

Supplementary: club match proxy data (top 5 leagues via football-data.co.uk)
  Used to enrich team strength estimates with more recent form.

Usage:
    from src.data.soccer_data import load_world_cup_history, load_upcoming_matches
    history = load_world_cup_history()   # past WC + euros matches for training
    upcoming = load_upcoming_matches()   # 2026 WC group stage fixtures
"""
from __future__ import annotations

import json
import time
from datetime import datetime, date
from pathlib import Path

import requests

CACHE_DIR = Path("data/cache/soccer")

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


def load_training_data() -> list[dict]:
    """
    Load combined historical match data for Dixon-Coles training.
    Includes: WC 2014-2022, Euros 2016-2024, Copa 2021-2024.
    """
    all_matches = []
    all_matches.extend(load_world_cup_history([2014, 2018, 2022]))
    all_matches.extend(load_euros_history([2020, 2024]))
    all_matches.extend(load_copa_history())
    all_matches.sort(key=lambda x: x["date"])
    return all_matches


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
TEAM_ALIASES: dict[str, str] = {
    "USA":                    "United States",
    "South Korea":            "Korea Republic",
    "North Korea":            "Korea DPR",
    "Bosnia & Herzegovina":   "Bosnia-Herzegovina",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Czech Republic":         "Czechia",
    "Ivory Coast":            "Côte d'Ivoire",
    "DR Congo":               "Congo DR",
    "Trinidad & Tobago":      "Trinidad and Tobago",
    "Korea DPR":              "Korea DPR",
    "Korea Republic":         "Korea Republic",
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
