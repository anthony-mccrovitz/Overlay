"""
Base model protocol for the ensemble.

All prediction models implement this interface so ensemble.py can treat
them uniformly. Uses Python Protocol for structural subtyping — models
don't need to inherit from anything, just implement the methods.
"""
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd


@runtime_checkable
class BaseModel(Protocol):
    """
    Contract for all prediction models in the ensemble.

    train() fits the model on historical matchup data.
    predict_proba() returns P(team_a wins) for each matchup row.
    evaluate() returns a dict of metrics (log_loss, accuracy, etc.).
    name is a human-readable identifier for logging.
    """

    name: str

    def train(self, X: pd.DataFrame, y: pd.Series) -> "BaseModel":
        """Fit the model. Returns self for chaining."""
        ...

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Return P(team_a wins) for each row.
        Output shape: (n_matchups,), values in [0.01, 0.99].
        """
        ...

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """Return dict with at least 'log_loss' and 'accuracy' keys."""
        ...
