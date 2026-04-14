"""
XGBoost model for tournament game prediction.

XGBoost is the workhorse — it consistently performs well in Kaggle's
March Madness competitions due to its ability to handle:
- Mixed feature types (numeric stats + categorical seeds)
- Missing values (NaN in Barttorvik features for some teams)
- Non-linear interactions (seed + tempo → upset probability)
"""
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, accuracy_score
from xgboost import XGBClassifier

from src.features.engineering import prepare_features


class XGBoostModel:
    """XGBoost binary classifier for win probability prediction."""

    name = "XGBoost"

    def __init__(self, **kwargs):
        defaults = {
            "n_estimators": 200,
            "max_depth": 4,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 3,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": 42,
            "eval_metric": "logloss",
            "use_label_encoder": False,
        }
        defaults.update(kwargs)
        self.model = XGBClassifier(**defaults)
        self._feature_cols: list[str] = []

    def train(self, X: pd.DataFrame, y: pd.Series) -> "XGBoostModel":
        """Fit on historical matchup data."""
        X_clean = prepare_features(X)
        self._feature_cols = list(X_clean.columns)
        self.model.fit(X_clean, y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Return P(Team A wins) for each matchup.
        Clipped to [0.01, 0.99] — no game is truly 0% or 100%.
        """
        X_clean = prepare_features(X)

        # Ensure same columns as training
        for col in self._feature_cols:
            if col not in X_clean.columns:
                X_clean[col] = 0
        X_clean = X_clean[self._feature_cols]

        probs = self.model.predict_proba(X_clean)[:, 1]
        return np.clip(probs, 0.01, 0.99)

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """Compute performance metrics."""
        probs = self.predict_proba(X)
        preds = (probs >= 0.5).astype(int)

        return {
            "log_loss": log_loss(y, probs),
            "accuracy": accuracy_score(y, preds),
            "n_samples": len(y),
            "mean_prob": float(probs.mean()),
        }

    def feature_importance(self) -> dict[str, float]:
        """Return feature importance scores."""
        if not self._feature_cols:
            return {}
        importances = self.model.feature_importances_
        return dict(zip(self._feature_cols, importances))
