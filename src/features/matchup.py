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


