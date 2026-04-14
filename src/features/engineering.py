"""
Feature engineering pipeline.

Transforms raw team stats into model-ready features.
Handles missing values, scaling, and feature selection.
"""
import numpy as np
import pandas as pd

from src.data.store import FEATURE_COLS, BARTTORVIK_FEATURE_COLS


def prepare_features(X: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare features for model training/prediction.

    - Selects relevant feature columns
    - Fills NaN with 0 for basic features
    - Drops Barttorvik features if mostly NaN
    - Clips extreme values
    """
    # Start with basic features that should always be present
    available = [c for c in FEATURE_COLS if c in X.columns]
    df = X[available].copy()

    # Add Barttorvik features if available (>50% non-null)
    for col in BARTTORVIK_FEATURE_COLS:
        if col in X.columns and X[col].notna().mean() > 0.5:
            df[col] = X[col]

    # Fill remaining NaN with 0 (neutral value for difference features)
    df = df.fillna(0)

    # Clip extreme values (>4 std devs) to reduce outlier impact
    for col in df.columns:
        if df[col].std() > 0:
            mean, std = df[col].mean(), df[col].std()
            df[col] = df[col].clip(mean - 4 * std, mean + 4 * std)

    return df


def get_feature_names(X: pd.DataFrame) -> list[str]:
    """Return the feature columns that will be used for modeling."""
    available = [c for c in FEATURE_COLS if c in X.columns]
    for col in BARTTORVIK_FEATURE_COLS:
        if col in X.columns and X[col].notna().mean() > 0.5:
            available.append(col)
    return available
