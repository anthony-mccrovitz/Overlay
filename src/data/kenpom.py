"""
KenPom advanced stats loader.

Loads pre-packaged KenPom data from the Kaggle dataset
(jonathanpilafas/2024-march-madness-statistical-analysis).

This replaces the Barttorvik scraper for advanced stats — same metrics,
no scraping required, and covers 2002-2026.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.team_names import try_normalize

KENPOM_DIR = Path("data/kenpom")
DEV_FILE = KENPOM_DIR / "DEV _ March Madness.csv"


def check_data_exists() -> bool:
    return DEV_FILE.exists()


def load_all() -> pd.DataFrame:
    """
    Load the full KenPom dataset (all seasons).

    Maps columns to the internal names used by store.py and features.
    """
    if not check_data_exists():
        raise FileNotFoundError(
            f"KenPom data not found at {DEV_FILE}. "
            "Download from: kaggle datasets download jonathanpilafas/2024-march-madness-statistical-analysis"
        )

    df = pd.read_csv(DEV_FILE)

    # Map to internal column names matching Barttorvik interface
    col_map = {
        "Season": "Season",
        "Mapped ESPN Team Name": "Team",
        "Full Team Name": "FullName",
        "Short Conference Name": "Conference",
        "AdjOE": "AdjO",
        "AdjDE": "AdjDE",
        "AdjTempo": "AdjTempo",
        "AdjEM": "AdjEM",
        "eFGPct": "eFGPct",
        "FG2Pct": "FG2Pct",
        "FG3Pct": "FG3Pct",
        "FTPct": "FTPct",
        "TOPct": "TORatio",
        "ORPct": "ORBPct",
        "FTRate": "FTRate",
        "OppFG2Pct": "FG2PctD",
        "OppFG3Pct": "FG3PctD",
        "OppFTPct": "FTPctD",
        "BlockPct": "BlockPct",
        "StlRate": "StlRate",
        "FG3Rate": "FG3Rate",
        "OppFG3Rate": "FG3RateD",
        "ARate": "AstRate",
        "Experience": "Experience",
        "EffectiveHeight": "EffectiveHeight",
        "AvgHeight": "AvgHeight",
        "Net Rating": "NetRating",
        "Seed": "Seed",
        "Region": "Region",
        # Pre-tournament stats (before tourney games bias the numbers)
        "Pre-Tournament.AdjOE": "PreTourney_AdjO",
        "Pre-Tournament.AdjDE": "PreTourney_AdjDE",
        "Pre-Tournament.AdjTempo": "PreTourney_AdjTempo",
        "Pre-Tournament.AdjEM": "PreTourney_AdjEM",
    }

    # Defensive Four Factors (from the DEV file)
    defense_cols = {}
    for orig_col in df.columns:
        if orig_col.startswith("Def") and orig_col not in col_map:
            # e.g. DefFT, Def2PtFG, Def3PtFG
            pass  # Already mapped above via Opp* columns

    # Select and rename available columns
    available = {k: v for k, v in col_map.items() if k in df.columns}
    result = df[list(available.keys())].rename(columns=available).copy()

    # Compute Barthag (power rating) from AdjO and AdjDE if not present
    # Barthag ≈ AdjO^11.5 / (AdjO^11.5 + AdjDE^11.5)
    if "AdjO" in result.columns and "AdjDE" in result.columns:
        adj_o = result["AdjO"].values
        adj_d = result["AdjDE"].values
        with np.errstate(over="ignore", invalid="ignore"):
            result["Barthag"] = np.where(
                (adj_o > 0) & (adj_d > 0),
                adj_o**11.5 / (adj_o**11.5 + adj_d**11.5),
                np.nan,
            )

    # Compute eFGPctD from defensive shooting stats if available
    if "FG2PctD" in result.columns and "FG3PctD" in result.columns and "FG3RateD" in result.columns:
        fg3_rate_d = result["FG3RateD"] / 100 if result["FG3RateD"].mean() > 1 else result["FG3RateD"]
        fg2_rate_d = 1 - fg3_rate_d
        result["eFGPctD"] = (
            fg2_rate_d * result["FG2PctD"] / 100 +
            fg3_rate_d * result["FG3PctD"] / 100 * 1.5
        ) if result["FG2PctD"].mean() > 1 else (
            fg2_rate_d * result["FG2PctD"] +
            fg3_rate_d * result["FG3PctD"] * 1.5
        )

    # Normalize team names for matching with Kaggle data
    if "Team" in result.columns:
        result["CanonicalName"] = result["Team"].apply(
            lambda n: try_normalize(str(n).strip()) if pd.notna(n) else None
        )
    elif "FullName" in result.columns:
        result["CanonicalName"] = result["FullName"].apply(
            lambda n: try_normalize(str(n).strip()) if pd.notna(n) else None
        )

    return result


def load_season(year: int) -> pd.DataFrame:
    """Load KenPom stats for a single season."""
    df = load_all()
    return df[df["Season"] == year].copy()


def get_current_season(year: int = 2026, refresh: bool = False) -> pd.DataFrame:
    """
    Get current season stats. Drop-in replacement for barttorvik.get_current_season().
    refresh parameter is accepted but ignored (data is static CSV).
    """
    return load_season(year)
