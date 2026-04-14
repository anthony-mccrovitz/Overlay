"""
Matchup-specific features.

Goes beyond generic team stats to model how Team A's strengths
interact with Team B's weaknesses. A team that lives on 3-pointers
will struggle against elite 3-point defense — this module captures that.

Four Factors framework (Dean Oliver):
1. Effective FG% (shooting efficiency)
2. Turnover rate (ball security)
3. Offensive rebound rate (second chances)
4. Free throw rate (getting to the line)
"""
import numpy as np
import pandas as pd


def add_matchup_features(X: pd.DataFrame, stats_a: pd.DataFrame, stats_b: pd.DataFrame) -> pd.DataFrame:
    """
    Add matchup-specific interaction features to a feature DataFrame.

    These capture HOW team styles interact, not just raw stat differences.
    Example: Team A's 3-point rate × Team B's 3-point defense rating.
    """
    df = X.copy()

    # Style interaction features
    # Team A's offensive style vs Team B's defensive style
    style_interactions = _compute_style_interactions(stats_a, stats_b)
    for col, values in style_interactions.items():
        if len(values) == len(df):
            df[col] = values

    return df


def _compute_style_interactions(stats_a: pd.DataFrame, stats_b: pd.DataFrame) -> dict:
    """
    Compute interaction features between offensive/defensive styles.

    Returns dict of column_name → values array.
    """
    features = {}

    # 3-point heavy offense vs 3-point defense
    if "FG3Rate" in stats_a.columns and "FG3PctD" in stats_b.columns:
        # If Team A takes lots of 3s and Team B defends 3s well → bad for A
        features["A_3ptVolume_vs_B_3ptDef"] = (
            stats_a["FG3Rate"].values * stats_b["FG3PctD"].values
        )
        features["B_3ptVolume_vs_A_3ptDef"] = (
            stats_b["FG3Rate"].values * stats_a["FG3PctD"].values
        )

    # Tempo mismatch (difference in preferred pace)
    if "AdjTempo" in stats_a.columns and "AdjTempo" in stats_b.columns:
        features["TempoMismatch"] = np.abs(
            stats_a["AdjTempo"].values - stats_b["AdjTempo"].values
        )

    # Rebounding battle
    if "ORBPct" in stats_a.columns and "DRBPct" in stats_b.columns:
        # Team A's offensive boards vs Team B's defensive boards
        features["A_ORB_vs_B_DRB"] = (
            stats_a["ORBPct"].values - stats_b["DRBPct"].values
        )

    # Turnover differential
    if "TORatio" in stats_a.columns and "TORatioD" in stats_b.columns:
        # Team A's turnover rate vs Team B's ability to force turnovers
        features["A_TO_vs_B_TOForce"] = (
            stats_a["TORatio"].values - stats_b["TORatioD"].values
        )

    return features


def compute_four_factors_matchup(team_a: dict, team_b: dict) -> dict:
    """
    Compute Four Factors matchup analysis for a single game.

    Returns a dict with matchup advantages for each factor.
    Positive = advantage Team A, Negative = advantage Team B.
    """
    factors = {}

    # Factor 1: Shooting (eFG%)
    a_efg = team_a.get("eFGPct", team_a.get("FGPct", 0.45))
    b_efg_d = team_b.get("eFGPctD", team_b.get("FGPct", 0.45))
    b_efg = team_b.get("eFGPct", team_b.get("FGPct", 0.45))
    a_efg_d = team_a.get("eFGPctD", team_a.get("FGPct", 0.45))

    factors["shooting_edge_a"] = float(a_efg) - float(b_efg_d)
    factors["shooting_edge_b"] = float(b_efg) - float(a_efg_d)
    factors["shooting_net"] = factors["shooting_edge_a"] - factors["shooting_edge_b"]

    # Factor 2: Turnovers
    a_to = team_a.get("TORatio", 0.18)
    b_to_d = team_b.get("TORatioD", 0.18)
    b_to = team_b.get("TORatio", 0.18)
    a_to_d = team_a.get("TORatioD", 0.18)

    factors["turnover_edge_a"] = float(b_to_d) - float(a_to)  # Higher = A forces more
    factors["turnover_edge_b"] = float(a_to_d) - float(b_to)
    factors["turnover_net"] = factors["turnover_edge_a"] - factors["turnover_edge_b"]

    # Factor 3: Rebounding
    a_orb = team_a.get("ORBPct", team_a.get("ORBRate", 0.30))
    b_drb = team_b.get("DRBPct", team_b.get("DRBRate", 0.70))

    factors["rebounding_edge_a"] = float(a_orb) - (1 - float(b_drb))
    factors["rebounding_net"] = factors["rebounding_edge_a"]

    # Factor 4: Free throws
    a_ftr = team_a.get("FTRate", 0.30)
    b_ftr_d = team_b.get("FTRateD", 0.30)

    factors["ft_edge_a"] = float(a_ftr) - float(b_ftr_d)
    factors["ft_net"] = factors["ft_edge_a"]

    # Overall matchup score (weighted by factor importance)
    # Dean Oliver weights: eFG% (40%), TO (25%), ORB (20%), FT (15%)
    factors["overall_matchup_score"] = (
        0.40 * factors["shooting_net"]
        + 0.25 * factors["turnover_net"]
        + 0.20 * factors["rebounding_net"]
        + 0.15 * factors["ft_net"]
    )

    return factors
