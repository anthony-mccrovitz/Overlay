"""Bayesian logistic regression with seed-based priors."""
import numpy as np
import pandas as pd
from sklearn.linear_model import BayesianRidge
from sklearn.metrics import log_loss, accuracy_score
from sklearn.preprocessing import StandardScaler

from src.features.engineering import prepare_features


class BayesianModel:
    """
    Bayesian approach: uses sklearn's BayesianRidge on log-odds transformed
    features. Captures uncertainty in predictions — useful for identifying
    games where the model is least confident.
    """
    name = "Bayesian"

    def __init__(self):
        self.model = BayesianRidge(
            max_iter=300,
            compute_score=True,
        )
        self.scaler = StandardScaler()
        self._feature_cols: list[str] = []

    def train(self, X: pd.DataFrame, y: pd.Series) -> "BayesianModel":
        X_clean = prepare_features(X)
        self._feature_cols = list(X_clean.columns)
        X_scaled = self.scaler.fit_transform(X_clean)
        self.model.fit(X_scaled, y.values.astype(float))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_clean = prepare_features(X)
        for col in self._feature_cols:
            if col not in X_clean.columns:
                X_clean[col] = 0
        X_clean = X_clean[self._feature_cols]
        X_scaled = self.scaler.transform(X_clean)

        # BayesianRidge gives continuous output — convert to probability
        raw = self.model.predict(X_scaled)
        probs = 1 / (1 + np.exp(-raw))  # Sigmoid
        return np.clip(probs, 0.01, 0.99)

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> dict:
        probs = self.predict_proba(X)
        preds = (probs >= 0.5).astype(int)
        return {
            "log_loss": log_loss(y, probs),
            "accuracy": accuracy_score(y, preds),
            "n_samples": len(y),
        }

    def prediction_uncertainty(self, X: pd.DataFrame) -> np.ndarray:
        """Return prediction standard deviation (uncertainty estimate)."""
        X_clean = prepare_features(X)
        for col in self._feature_cols:
            if col not in X_clean.columns:
                X_clean[col] = 0
        X_clean = X_clean[self._feature_cols]
        X_scaled = self.scaler.transform(X_clean)
        _, std = self.model.predict(X_scaled, return_std=True)
        return std
