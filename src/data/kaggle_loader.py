"""
Load Kaggle March Machine Learning Mania datasets.

Expected directory structure (data/kaggle/):
  MTeams.csv                     - Team ID → name mapping
  MNCAATourneySeeds.csv          - Seeds by year
  MNCAATourneyCompactResults.csv - Tournament game results
  MRegularSeasonDetailedResults.csv - Regular season box scores
  MRegularSeasonCompactResults.csv  - Regular season W/L

Download: Search Kaggle for "March Machine Learning Mania" and download
the most recent competition dataset, then unzip into data/kaggle/.
(Competition slug changes yearly — check https://www.kaggle.com/competitions?search=march+machine+learning+mania)
"""
import os
from pathlib import Path

import pandas as pd

from src.data.team_names import try_normalize

KAGGLE_DIR = Path("data/kaggle")

# Required files — we fail loud if any are missing
REQUIRED_FILES = [
    "MTeams.csv",
    "MNCAATourneySeeds.csv",
    "MNCAATourneyCompactResults.csv",
    "MRegularSeasonDetailedResults.csv",
]


def check_data_exists() -> bool:
    """Check if Kaggle data has been downloaded."""
    return all((KAGGLE_DIR / f).exists() for f in REQUIRED_FILES)


def _get_download_instructions() -> str:
    return (
        "Kaggle data not found. Download it:\n"
        "  1. pip install kaggle\n"
        "  2. Set up ~/.kaggle/kaggle.json (API credentials)\n"
        "  3. Search Kaggle for 'March Machine Learning Mania' (current year)\n"
        "     kaggle competitions download -c <competition-slug>\n"
        "  4. Unzip into data/kaggle/\n"
        "\n"
        "Or browse:\n"
        "  https://www.kaggle.com/competitions?search=march+machine+learning+mania"
    )


def load_teams() -> pd.DataFrame:
    """
    Load team ID → name mapping.
    Returns DataFrame with columns: [TeamID, TeamName, CanonicalName]
    """
    if not check_data_exists():
        raise FileNotFoundError(_get_download_instructions())

    df = pd.read_csv(KAGGLE_DIR / "MTeams.csv")
    # Try to map each team name to canonical; keep original if not found
    df["CanonicalName"] = df["TeamName"].apply(
        lambda n: try_normalize(n) or n
    )
    return df


def load_seeds(min_year: int = 2010) -> pd.DataFrame:
    """
    Load tournament seeds by year.
    Returns DataFrame with columns: [Season, TeamID, Seed, SeedNum]
    SeedNum is the numeric seed (1-16), extracted from the string seed.
    """
    if not check_data_exists():
        raise FileNotFoundError(_get_download_instructions())

    df = pd.read_csv(KAGGLE_DIR / "MNCAATourneySeeds.csv")
    df = df[df["Season"] >= min_year].copy()

    # Parse seed string (e.g., "W01" → 1, "X16a" → 16)
    df["SeedNum"] = df["Seed"].str.extract(r"(\d+)").astype(int)
    df["Region"] = df["Seed"].str[0]

    return df


def load_tourney_results(min_year: int = 2010) -> pd.DataFrame:
    """
    Load tournament game results.
    Returns DataFrame with: [Season, WTeamID, LTeamID, WScore, LScore]
    """
    if not check_data_exists():
        raise FileNotFoundError(_get_download_instructions())

    df = pd.read_csv(KAGGLE_DIR / "MNCAATourneyCompactResults.csv")
    df = df[df["Season"] >= min_year].copy()
    return df


def load_regular_season_detailed(min_year: int = 2010) -> pd.DataFrame:
    """
    Load detailed regular season box scores.
    Columns include FGM, FGA, FGM3, FGA3, FTM, FTA, OR, DR, Ast, TO, Stl, Blk, PF
    for both winning (W*) and losing (L*) teams.
    """
    if not check_data_exists():
        raise FileNotFoundError(_get_download_instructions())

    df = pd.read_csv(KAGGLE_DIR / "MRegularSeasonDetailedResults.csv")
    df = df[df["Season"] >= min_year].copy()
    return df


def load_regular_season_compact(min_year: int = 2010) -> pd.DataFrame:
    """Load compact regular season results (W/L only, no box scores)."""
    path = KAGGLE_DIR / "MRegularSeasonCompactResults.csv"
    if not path.exists():
        raise FileNotFoundError(_get_download_instructions())

    df = pd.read_csv(path)
    df = df[df["Season"] >= min_year].copy()
    return df


def build_team_season_stats(min_year: int = 2010) -> pd.DataFrame:
    """
    Aggregate regular season detailed results into per-team-per-season stats.

    Returns DataFrame with columns:
    [Season, TeamID, Games, Wins, Losses, WinPct,
     PPG, OppPPG, FGPct, FG3Pct, FTPct, ORBRate, DRBRate, TORatio,
     AstRate, StlRate, BlkRate]

    These are basic box-score-derived stats. Barttorvik provides the
    adjusted/advanced stats (efficiency, tempo, Four Factors).
    """
    detailed = load_regular_season_detailed(min_year)

    rows = []
    for season in detailed["Season"].unique():
        season_games = detailed[detailed["Season"] == season]

        # Get all teams that played this season
        all_teams = set(season_games["WTeamID"]) | set(season_games["LTeamID"])

        for team_id in all_teams:
            # Games where this team won
            wins = season_games[season_games["WTeamID"] == team_id]
            # Games where this team lost
            losses = season_games[season_games["LTeamID"] == team_id]

            n_wins = len(wins)
            n_losses = len(losses)
            n_games = n_wins + n_losses

            if n_games == 0:
                continue

            # Offensive stats (when winning: W* columns, when losing: L* columns)
            pts = wins["WScore"].sum() + losses["LScore"].sum()
            opp_pts = wins["LScore"].sum() + losses["WScore"].sum()
            fgm = wins["WFGM"].sum() + losses["LFGM"].sum()
            fga = wins["WFGA"].sum() + losses["LFGA"].sum()
            fgm3 = wins["WFGM3"].sum() + losses["LFGM3"].sum()
            fga3 = wins["WFGA3"].sum() + losses["LFGA3"].sum()
            ftm = wins["WFTM"].sum() + losses["LFTM"].sum()
            fta = wins["WFTA"].sum() + losses["LFTA"].sum()
            orb = wins["WOR"].sum() + losses["LOR"].sum()
            drb = wins["WDR"].sum() + losses["LDR"].sum()
            ast = wins["WAst"].sum() + losses["LAst"].sum()
            to = wins["WTO"].sum() + losses["LTO"].sum()
            stl = wins["WStl"].sum() + losses["LStl"].sum()
            blk = wins["WBlk"].sum() + losses["LBlk"].sum()

            # Possessions estimate (for rate stats)
            poss = fga - orb + to + 0.475 * fta

            rows.append({
                "Season": season,
                "TeamID": team_id,
                "Games": n_games,
                "Wins": n_wins,
                "Losses": n_losses,
                "WinPct": n_wins / n_games,
                "PPG": pts / n_games,
                "OppPPG": opp_pts / n_games,
                "FGPct": fgm / fga if fga > 0 else 0,
                "FG3Pct": fgm3 / fga3 if fga3 > 0 else 0,
                "FTPct": ftm / fta if fta > 0 else 0,
                "ORBRate": orb / (orb + drb) if (orb + drb) > 0 else 0,
                "DRBRate": drb / (orb + drb) if (orb + drb) > 0 else 0,
                "TORatio": to / poss if poss > 0 else 0,
                "AstRate": ast / fgm if fgm > 0 else 0,
                "StlRate": stl / n_games,
                "BlkRate": blk / n_games,
                "Possessions": poss / n_games,
                "PointMargin": (pts - opp_pts) / n_games,
            })

    return pd.DataFrame(rows)
