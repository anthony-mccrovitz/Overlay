"""
Ensemble model combiner.

Combines predictions from multiple models using weighted averaging.
Weights are determined by each model's performance on validation data.
Gracefully degrades — if one model fails, the rest carry on.

Architecture:
  Elo ──────────┐
  XGBoost ──────┤
  Logistic ─────┼──▶ Weighted Average ──▶ Final P(win)
  Neural ───────┤
  Bayesian ─────┘
"""
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, accuracy_score

from src.models.base import BaseModel


class EnsembleModel:
    """Weighted ensemble of multiple prediction models."""

    name = "Ensemble"

    def __init__(self, models: list[BaseModel] | None = None):
        self.models: list[BaseModel] = models or []
        self.weights: dict[str, float] = {}
        self._trained_models: list[BaseModel] = []

    def add_model(self, model: BaseModel) -> None:
        """Add a model to the ensemble."""
        self.models.append(model)

    def train(self, X: pd.DataFrame, y: pd.Series) -> "EnsembleModel":
        """
        Train all models. Failed models are dropped with a warning.
        Weights are set to equal initially — call optimize_weights()
        with validation data to set performance-based weights.
        """
        self._trained_models = []

        for model in self.models:
            try:
                model.train(X, y)
                self._trained_models.append(model)
                print(f"  Trained: {model.name}")
            except Exception as e:
                print(f"  Warning: {model.name} failed to train: {e}")

        if not self._trained_models:
            raise RuntimeError("All models failed to train. Cannot build ensemble.")

        # Default: equal weights
        n = len(self._trained_models)
        self.weights = {m.name: 1.0 / n for m in self._trained_models}

        return self

    def optimize_weights(self, X_val: pd.DataFrame, y_val: pd.Series) -> dict[str, float]:
        """
        Set weights based on validation performance.
        Better log_loss → higher weight (inverse log_loss, normalized).
        """
        scores = {}
        for model in self._trained_models:
            try:
                metrics = model.evaluate(X_val, y_val)
                scores[model.name] = metrics["log_loss"]
            except Exception as e:
                print(f"  Warning: {model.name} failed evaluation: {e}")
                scores[model.name] = 1.0  # Bad score

        if not scores:
            return self.weights

        # Inverse log_loss weighting (lower loss → higher weight)
        inv_scores = {name: 1.0 / score for name, score in scores.items()}
        total = sum(inv_scores.values())
        self.weights = {name: inv / total for name, inv in inv_scores.items()}

        print("  Ensemble weights:")
        for name, weight in sorted(self.weights.items(), key=lambda x: -x[1]):
            print(f"    {name}: {weight:.3f} (log_loss: {scores[name]:.4f})")

        return self.weights

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Weighted average of all model predictions.
        Clipped to [0.01, 0.99].
        """
        if not self._trained_models:
            raise RuntimeError("Ensemble has no trained models. Call train() first.")

        all_probs = []
        all_weights = []

        for model in self._trained_models:
            try:
                probs = model.predict_proba(X)
                weight = self.weights.get(model.name, 1.0 / len(self._trained_models))
                all_probs.append(probs)
                all_weights.append(weight)
            except Exception as e:
                print(f"  Warning: {model.name} failed prediction: {e}")

        if not all_probs:
            raise RuntimeError("All models failed prediction.")

        # Renormalize weights for surviving models
        total_weight = sum(all_weights)
        weighted_sum = sum(
            p * (w / total_weight) for p, w in zip(all_probs, all_weights)
        )

        return np.clip(weighted_sum, 0.01, 0.99)

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """Evaluate ensemble performance."""
        probs = self.predict_proba(X)
        preds = (probs >= 0.5).astype(int)

        result = {
            "log_loss": log_loss(y, probs),
            "accuracy": accuracy_score(y, preds),
            "n_models": len(self._trained_models),
            "n_samples": len(y),
        }

        # Also report per-model performance
        for model in self._trained_models:
            try:
                metrics = model.evaluate(X, y)
                result[f"{model.name}_log_loss"] = metrics["log_loss"]
                result[f"{model.name}_accuracy"] = metrics["accuracy"]
            except Exception:
                pass

        return result

    def per_model_predictions(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return individual model predictions (for debugging/analysis)."""
        preds = {}
        for model in self._trained_models:
            try:
                preds[model.name] = model.predict_proba(X)
            except Exception:
                pass
        return preds
