"""
Barttorvik scraper with CSV caching.

Scrapes team-level advanced stats from barttorvik.com:
- Adjusted offensive/defensive efficiency
- Tempo (possessions per 40 minutes)
- Four Factors: eFG%, turnover rate, offensive rebound rate, FT rate
- Experience metrics

Cache strategy:
- First run scrapes live + saves to data/cache/barttorvik/{year}.csv
- Subsequent runs use cache by default
- Use --refresh flag to re-scrape
"""
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.data.team_names import try_normalize

CACHE_DIR = Path("data/cache/barttorvik")
BASE_URL = "https://barttorvik.com"

# Column mapping from Barttorvik's table to our internal names
STAT_COLUMNS = {
    "Team": "Team",
    "Conf": "Conference",
    "Rec": "Record",
    "AdjOE": "AdjO",       # Adjusted offensive efficiency
    "AdjDE": "AdjDE",      # Adjusted defensive efficiency
    "Barthag": "Barthag",  # Power rating (probability of beating average team)
    "EFG%": "eFGPct",      # Effective field goal %
    "EFGD%": "eFGPctD",    # Effective field goal % defense
    "TOR": "TORatio",      # Turnover rate
    "TORD": "TORatioD",    # Turnover rate defense
    "ORB": "ORBPct",       # Offensive rebound %
    "DRB": "DRBPct",       # Defensive rebound %
    "FTR": "FTRate",       # Free throw rate
    "FTRD": "FTRateD",     # Free throw rate defense
    "2P%": "FG2Pct",       # 2-point %
    "2P%D": "FG2PctD",     # 2-point % defense
    "3P%": "FG3Pct",       # 3-point %
    "3P%D": "FG3PctD",     # 3-point % defense
    "3PR": "FG3Rate",      # 3-point rate (% of shots from 3)
    "3PRD": "FG3RateD",    # 3-point rate defense
    "Adj T.": "AdjTempo",  # Adjusted tempo
    "WAB": "WAB",          # Wins above bubble
}


def _cache_path(year: int) -> Path:
    return CACHE_DIR / f"{year}.csv"


def _scrape_year(year: int) -> pd.DataFrame:
    """
    Scrape Barttorvik team ratings for a given season.

    Barttorvik uses the endpoint year format where 2026 = 2025-26 season.
    """
    url = f"{BASE_URL}/trank.php?year={year}&sort=&conlimit=All"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ConnectionError(f"Failed to scrape Barttorvik for {year}: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Barttorvik renders stats in a table — try to find it
    # The main table has team data
    tables = soup.find_all("table")
    if not tables:
        raise ValueError(f"No tables found on Barttorvik page for {year}")

    # Try pandas read_html as a more robust parser
    try:
        dfs = pd.read_html(resp.text)
        if not dfs:
            raise ValueError("No tables parsed")
        # The main stats table is usually the largest one
        df = max(dfs, key=len)
    except Exception:
        raise ValueError(
            f"Could not parse Barttorvik HTML for {year}. "
            f"Site structure may have changed. Use cached data."
        )

    # Clean up: drop any rows that are header repeats or empty
    df = df.dropna(subset=[df.columns[0]])

    # Try to normalize team names
    if "Team" in df.columns:
        df["CanonicalName"] = df["Team"].apply(
            lambda n: try_normalize(str(n).strip()) if pd.notna(n) else None
        )

    df["Season"] = year

    return df


def scrape_season(year: int, refresh: bool = False) -> pd.DataFrame:
    """
    Get Barttorvik stats for a season. Uses cache unless refresh=True.

    Args:
        year: Season year (e.g., 2026 for 2025-26 season)
        refresh: If True, re-scrape even if cache exists

    Returns:
        DataFrame with team stats for the season
    """
    cache = _cache_path(year)

    if cache.exists() and not refresh:
        df = pd.read_csv(cache)
        return df

    print(f"  Scraping Barttorvik for {year}...")
    df = _scrape_year(year)

    # Cache the result
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    print(f"  Cached to {cache}")

    return df


def scrape_multiple_seasons(
    years: list[int],
    refresh: bool = False,
    delay: float = 1.0,
) -> pd.DataFrame:
    """
    Scrape multiple seasons with polite delay between requests.

    Args:
        years: List of season years to scrape
        refresh: If True, re-scrape all years
        delay: Seconds to wait between requests (be polite)

    Returns:
        Combined DataFrame with all seasons
    """
    all_dfs = []
    for i, year in enumerate(years):
        try:
            df = scrape_season(year, refresh=refresh)
            all_dfs.append(df)
        except (ConnectionError, ValueError) as e:
            # Try cache even if refresh was requested
            cache = _cache_path(year)
            if cache.exists():
                print(f"  Warning: scrape failed for {year}, using cache: {e}")
                all_dfs.append(pd.read_csv(cache))
            else:
                print(f"  Warning: skipping {year}, no data available: {e}")

        # Be polite — don't hammer the server
        if i < len(years) - 1 and refresh:
            time.sleep(delay)

    if not all_dfs:
        raise RuntimeError("No Barttorvik data available for any requested year")

    return pd.concat(all_dfs, ignore_index=True)


def get_current_season(year: int = 2026, refresh: bool = False) -> pd.DataFrame:
    """Convenience: get just the current season stats."""
    return scrape_season(year, refresh=refresh)
