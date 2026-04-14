"""
Unified data store — single access point for all data sources.

All team name normalization happens here. Downstream code never touches
raw data directly — everything goes through store.py.

Data flow:
  Barttorvik (advanced) ─┐
                          ├──▶ store.py (normalize + join) ──▶ features
  Kaggle (basic + seeds) ─┘
"""
import pandas as pd
import numpy as np

from src.data import kaggle_loader, barttorvik, kenpom
from src.data.team_names import normalize, try_normalize


def load_team_stats(
    season: int = 2026,
    use_barttorvik: bool = True,
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Load comprehensive team stats for a season.
    Combines Kaggle basic stats with Barttorvik advanced stats.

    Args:
        season: Season year (e.g., 2026 for 2025-26)
        use_barttorvik: Whether to include Barttorvik advanced stats
        refresh: Whether to re-scrape Barttorvik

    Returns:
        DataFrame indexed by TeamID with all available stats
    """
    # Load Kaggle basic stats
    kaggle_stats = kaggle_loader.build_team_season_stats(min_year=season - 1)
    kaggle_stats = kaggle_stats[kaggle_stats["Season"] == season].copy()

    # Load team name mapping
    teams = kaggle_loader.load_teams()
    team_map = dict(zip(teams["TeamID"], teams["CanonicalName"]))

    kaggle_stats["CanonicalName"] = kaggle_stats["TeamID"].map(team_map)

    if use_barttorvik:
        advanced_merged = False

        # Try KenPom first (pre-packaged, no scraping)
        if kenpom.check_data_exists():
            try:
                kp = kenpom.load_season(season)
                if "CanonicalName" in kp.columns and len(kp) > 0:
                    kp_cols = [c for c in kp.columns if c not in kaggle_stats.columns or c == "CanonicalName"]
                    kaggle_stats = kaggle_stats.merge(
                        kp[kp_cols],
                        on="CanonicalName",
                        how="left",
                        suffixes=("", "_kp"),
                    )
                    n_matched = kaggle_stats["AdjO"].notna().sum() if "AdjO" in kaggle_stats.columns else 0
                    n_total = len(kaggle_stats)
                    print(f"  KenPom match: {n_matched}/{n_total} teams")
                    advanced_merged = True
            except Exception as e:
                print(f"  Warning: KenPom data unavailable ({e})")

        # Fall back to Barttorvik scraper
        if not advanced_merged:
            try:
                bart = barttorvik.get_current_season(year=season, refresh=refresh)
                if "CanonicalName" in bart.columns:
                    kaggle_stats = kaggle_stats.merge(
                        bart.drop(columns=["Season"], errors="ignore"),
                        on="CanonicalName",
                        how="left",
                        suffixes=("", "_bart"),
                    )
                    n_matched = kaggle_stats["AdjO"].notna().sum() if "AdjO" in kaggle_stats.columns else 0
                    n_total = len(kaggle_stats)
                    print(f"  Barttorvik match: {n_matched}/{n_total} teams")
            except Exception as e:
                print(f"  Warning: Advanced stats unavailable ({e}). Using Kaggle stats only.")

    return kaggle_stats


def load_tourney_matchups(season: int) -> pd.DataFrame:
    """
    Load tournament bracket structure for a given year.
    Returns matchups with team stats for each side.
    """
    seeds = kaggle_loader.load_seeds(min_year=season)
    seeds = seeds[seeds["Season"] == season]

    teams = kaggle_loader.load_teams()
    team_map = dict(zip(teams["TeamID"], teams["CanonicalName"]))

    seeds["CanonicalName"] = seeds["TeamID"].map(team_map)

    return seeds


def build_training_data(
    min_year: int = 2010,
    max_year: int = 2025,
    use_barttorvik: bool = False,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Build training dataset from historical tournament matchups.

    For each tournament game, creates a feature row with:
    - Team A stats (higher seed)
    - Team B stats (lower seed)
    - Seed difference
    - Label: 1 if Team A won, 0 if Team B won

    Args:
        min_year: First season to include
        max_year: Last season to include
        use_barttorvik: Use Barttorvik stats (requires cached data)

    Returns:
        (X, y) tuple — features DataFrame and binary labels
    """
    all_rows = []

    for season in range(min_year, max_year + 1):
        if season == 2020:
            # No tournament in 2020
            continue

        try:
            # Get team stats for this season
            stats = _get_season_stats(season, use_barttorvik)
            if stats.empty:
                continue

            # Get tournament results
            results = kaggle_loader.load_tourney_results(min_year=season)
            results = results[results["Season"] == season]

            # Get seeds
            seeds = kaggle_loader.load_seeds(min_year=season)
            seeds = seeds[seeds["Season"] == season]
            seed_map = dict(zip(seeds["TeamID"], seeds["SeedNum"]))

            for _, game in results.iterrows():
                w_id = game["WTeamID"]
                l_id = game["LTeamID"]

                w_seed = seed_map.get(w_id, 8)
                l_seed = seed_map.get(l_id, 8)

                w_stats = stats[stats["TeamID"] == w_id]
                l_stats = stats[stats["TeamID"] == l_id]

                if w_stats.empty or l_stats.empty:
                    continue

                w_stats = w_stats.iloc[0]
                l_stats = l_stats.iloc[0]

                # Always put the higher seed (lower number) as Team A
                if w_seed <= l_seed:
                    row = _make_matchup_row(w_stats, l_stats, w_seed, l_seed, season)
                    row["Result"] = 1  # Higher seed won
                else:
                    row = _make_matchup_row(l_stats, w_stats, l_seed, w_seed, season)
                    row["Result"] = 0  # Higher seed lost (upset)

                all_rows.append(row)

        except Exception as e:
            print(f"  Warning: skipping season {season}: {e}")

    if not all_rows:
        raise RuntimeError("No training data could be built. Check Kaggle data.")

    df = pd.DataFrame(all_rows)
    y = df.pop("Result")
    return df, y


def _get_season_stats(season: int, use_barttorvik: bool) -> pd.DataFrame:
    """Get team stats for a season, with Barttorvik if available."""
    try:
        kaggle_stats = kaggle_loader.build_team_season_stats(min_year=season - 1)
        stats = kaggle_stats[kaggle_stats["Season"] == season].copy()
    except Exception:
        return pd.DataFrame()

    if use_barttorvik:
        advanced_merged = False

        # Try KenPom first
        if kenpom.check_data_exists():
            try:
                kp = kenpom.load_season(season)
                if "CanonicalName" in kp.columns and len(kp) > 0:
                    teams = kaggle_loader.load_teams()
                    team_map = dict(zip(teams["CanonicalName"], teams["TeamID"]))
                    kp["TeamID"] = kp["CanonicalName"].map(team_map)
                    kp = kp.dropna(subset=["TeamID"])
                    kp["TeamID"] = kp["TeamID"].astype(int)
                    kp_cols = ["TeamID"] + [c for c in kp.columns if c not in stats.columns and c != "TeamID"]
                    stats = stats.merge(kp[kp_cols], on="TeamID", how="left")
                    advanced_merged = True
            except Exception:
                pass

        # Fall back to Barttorvik
        if not advanced_merged:
            try:
                bart = barttorvik.scrape_season(season, refresh=False)
                if "CanonicalName" in bart.columns:
                    teams = kaggle_loader.load_teams()
                    team_map = dict(zip(teams["CanonicalName"], teams["TeamID"]))
                    bart["TeamID"] = bart["CanonicalName"].map(team_map)
                    bart = bart.dropna(subset=["TeamID"])
                    bart["TeamID"] = bart["TeamID"].astype(int)
                    stats = stats.merge(
                        bart[["TeamID"] + [c for c in bart.columns if c not in stats.columns and c != "TeamID"]],
                        on="TeamID",
                        how="left",
                    )
            except Exception:
                pass

    return stats


# Feature columns used for model training
FEATURE_COLS = [
    "SeedDiff",
    "WinPctDiff",
    "PPGDiff",
    "OppPPGDiff",
    "FGPctDiff",
    "FG3PctDiff",
    "FTPctDiff",
    "ORBRateDiff",
    "TORatioDiff",
    "PossessionsDiff",
    "PointMarginDiff",
    "SeedA",
    "SeedB",
]

# Extended features when Barttorvik data is available
BARTTORVIK_FEATURE_COLS = [
    "AdjODiff",
    "AdjDEDiff",
    "AdjTempoDiff",
    "BarthagDiff",
    "eFGPctDiff",
    "eFGPctDDiff",
    # Tournament experience & matchup features (available but optional)
    # "ExperienceDiff",
    # "TourneyAppsDiff",
    # "TempoMismatch",
]


def _build_tourney_apps_cache() -> dict[int, dict[int, int]]:
    """
    Build a cache of tournament appearances per team in the last 5 years.
    Returns {season: {team_id: num_appearances_in_last_5_years}}.
    """
    all_seeds = kaggle_loader.load_seeds(min_year=2003)
    cache = {}
    for season in all_seeds["Season"].unique():
        lookback = all_seeds[
            (all_seeds["Season"] >= season - 5) & (all_seeds["Season"] < season)
        ]
        counts = lookback["TeamID"].value_counts().to_dict()
        cache[int(season)] = counts
    return cache


_TOURNEY_APPS_CACHE: dict[int, dict[int, int]] | None = None


def _get_tourney_apps(team_id: int, season: int) -> int:
    """Get number of tournament appearances in the last 5 years for a team."""
    global _TOURNEY_APPS_CACHE
    if _TOURNEY_APPS_CACHE is None:
        _TOURNEY_APPS_CACHE = _build_tourney_apps_cache()
    return _TOURNEY_APPS_CACHE.get(season, {}).get(team_id, 0)


def _make_matchup_row(
    team_a: pd.Series,
    team_b: pd.Series,
    seed_a: int,
    seed_b: int,
    season: int,
) -> dict:
    """Create a feature row for a matchup between Team A (higher seed) and Team B."""
    row = {
        "Season": season,
        "TeamA_ID": team_a.get("TeamID"),
        "TeamB_ID": team_b.get("TeamID"),
        "SeedA": seed_a,
        "SeedB": seed_b,
        "SeedDiff": seed_b - seed_a,  # Positive = A is higher seed
    }

    # Difference features (A - B) for basic stats
    diff_cols = [
        ("WinPct", "WinPctDiff"),
        ("PPG", "PPGDiff"),
        ("OppPPG", "OppPPGDiff"),
        ("FGPct", "FGPctDiff"),
        ("FG3Pct", "FG3PctDiff"),
        ("FTPct", "FTPctDiff"),
        ("ORBRate", "ORBRateDiff"),
        ("TORatio", "TORatioDiff"),
        ("Possessions", "PossessionsDiff"),
        ("PointMargin", "PointMarginDiff"),
    ]

    for src_col, feat_name in diff_cols:
        a_val = team_a.get(src_col, 0) or 0
        b_val = team_b.get(src_col, 0) or 0
        row[feat_name] = float(a_val) - float(b_val)

    # Barttorvik/KenPom advanced stats (if available)
    bart_diff_cols = [
        ("AdjO", "AdjODiff"),
        ("AdjDE", "AdjDEDiff"),
        ("AdjTempo", "AdjTempoDiff"),
        ("Barthag", "BarthagDiff"),
        ("eFGPct", "eFGPctDiff"),
        ("eFGPctD", "eFGPctDDiff"),
    ]

    for src_col, feat_name in bart_diff_cols:
        a_val = team_a.get(src_col)
        b_val = team_b.get(src_col)
        if pd.notna(a_val) and pd.notna(b_val):
            row[feat_name] = float(a_val) - float(b_val)
        else:
            row[feat_name] = np.nan

    # --- Tournament experience features (scaled down to inform, not override) ---

    # 1. Roster experience differential (KenPom Experience column)
    #    Scaled by 0.5 to prevent overriding core efficiency metrics
    a_exp = team_a.get("Experience")
    b_exp = team_b.get("Experience")
    if pd.notna(a_exp) and pd.notna(b_exp):
        row["ExperienceDiff"] = (float(a_exp) - float(b_exp)) * 0.5
    else:
        row["ExperienceDiff"] = np.nan

    # 2. Tournament appearances in last 5 years (institutional March knowledge)
    #    Cap at 3 to prevent blue bloods from getting too much credit
    a_id = team_a.get("TeamID")
    b_id = team_b.get("TeamID")
    if pd.notna(a_id) and pd.notna(b_id):
        a_apps = min(_get_tourney_apps(int(a_id), season), 3)
        b_apps = min(_get_tourney_apps(int(b_id), season), 3)
        row["TourneyAppsDiff"] = a_apps - b_apps
    else:
        row["TourneyAppsDiff"] = np.nan

    # 3. Tempo mismatch — how much one team's preferred pace differs from the other's
    #    Helps identify games where a slow grinder disrupts a fast team
    a_tempo = team_a.get("AdjTempo")
    b_tempo = team_b.get("AdjTempo")
    if pd.notna(a_tempo) and pd.notna(b_tempo):
        row["TempoMismatch"] = abs(float(a_tempo) - float(b_tempo))
    else:
        row["TempoMismatch"] = np.nan

    return row
