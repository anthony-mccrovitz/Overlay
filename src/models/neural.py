"""Neural network model for tournament prediction."""
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import log_loss, accuracy_score
from sklearn.preprocessing import StandardScaler

from src.features.engineering import prepare_features


class NeuralModel:
    name = "Neural"

    def __init__(self):
        self.model = MLPClassifier(
            hidden_layer_sizes=(64, 32),
            max_iter=500,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.15,
        )
        self.scaler = StandardScaler()
        self._feature_cols: list[str] = []

    def train(self, X: pd.DataFrame, y: pd.Series) -> "NeuralModel":
        X_clean = prepare_features(X)
        self._feature_cols = list(X_clean.columns)
        X_scaled = self.scaler.fit_transform(X_clean)
        self.model.fit(X_scaled, y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_clean = prepare_features(X)
        for col in self._feature_cols:
            if col not in X_clean.columns:
                X_clean[col] = 0
        X_clean = X_clean[self._feature_cols]
        X_scaled = self.scaler.transform(X_clean)
        probs = self.model.predict_proba(X_scaled)[:, 1]
        return np.clip(probs, 0.01, 0.99)

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> dict:
        probs = self.predict_proba(X)
        preds = (probs >= 0.5).astype(int)
        return {
            "log_loss": log_loss(y, probs),
            "accuracy": accuracy_score(y, preds),
            "n_samples": len(y),
        }
