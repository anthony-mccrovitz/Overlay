"""
Elo rating model for tournament prediction.

Builds Elo ratings from regular season game results, then uses the
rating difference to predict tournament matchups. Simple but effective
— Elo captures team strength through a recursive "you are who you beat"
framework.

Standard Elo parameters for college basketball:
- K-factor: 20 (higher = more responsive to recent results)
- Home advantage: 100 rating points
- Initial rating: 1500
"""
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, accuracy_score

from src.data import kaggle_loader
from src.features.engineering import prepare_features


class EloModel:
    """Elo rating system adapted for NCAA tournament prediction."""

    name = "Elo"

    def __init__(self, k_factor: float = 20.0, home_advantage: float = 100.0):
        self.k_factor = k_factor
        self.home_advantage = home_advantage
        self.ratings: dict[int, float] = {}  # TeamID → Elo rating
        self._season_ratings: dict[tuple[int, int], float] = {}  # (season, team) → rating
        self._elo_scale = 400.0  # Standard Elo scale factor

    def train(self, X: pd.DataFrame, y: pd.Series) -> "EloModel":
        """
        Build Elo ratings from regular season data, then fit a logistic
        model to map Elo difference → win probability for tournament games.
        """
        # Get unique seasons in training data
        seasons = sorted(X["Season"].unique()) if "Season" in X.columns else []

        for season in seasons:
            self._build_season_ratings(int(season))

        return self

    def _build_season_ratings(self, season: int) -> None:
        """Build Elo ratings for a single season from game results."""
        try:
            games = kaggle_loader.load_regular_season_compact(min_year=season)
            games = games[games["Season"] == season]
        except Exception:
            return

        # Start with previous season's ratings or default
        season_ratings: dict[int, float] = {}

        # Regress toward mean between seasons (prevents runaway ratings)
        for team_id, rating in self.ratings.items():
            season_ratings[team_id] = 1500 + 0.75 * (rating - 1500)

        for _, game in games.iterrows():
            w_id = game["WTeamID"]
            l_id = game["LTeamID"]

            # Initialize new teams at 1500
            if w_id not in season_ratings:
                season_ratings[w_id] = 1500
            if l_id not in season_ratings:
                season_ratings[l_id] = 1500

            w_rating = season_ratings[w_id]
            l_rating = season_ratings[l_id]

            # Determine home advantage (WLoc: H=home, A=away, N=neutral)
            w_loc = game.get("WLoc", "N")
            if w_loc == "H":
                w_expected = 1 / (1 + 10 ** ((l_rating - w_rating + self.home_advantage) / self._elo_scale))
            elif w_loc == "A":
                w_expected = 1 / (1 + 10 ** ((l_rating + self.home_advantage - w_rating) / self._elo_scale))
            else:
                w_expected = 1 / (1 + 10 ** ((l_rating - w_rating) / self._elo_scale))

            # Margin of victory adjustment
            mov = game["WScore"] - game["LScore"]
            mov_mult = np.log(abs(mov) + 1) * (2.2 / (0.001 * (w_rating - l_rating) + 2.2))

            # Update ratings
            season_ratings[w_id] += self.k_factor * mov_mult * (1 - w_expected)
            season_ratings[l_id] -= self.k_factor * mov_mult * (1 - w_expected)

        # Store end-of-season ratings
        for team_id, rating in season_ratings.items():
            self._season_ratings[(season, team_id)] = rating
            self.ratings[team_id] = rating

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict P(Team A wins) using Elo rating difference.
        Falls back to seed-based prediction if no Elo rating exists.
        """
        probs = []

        for _, row in X.iterrows():
            team_a = row.get("TeamA_ID")
            team_b = row.get("TeamB_ID")
            season = row.get("Season", 2026)
            seed_diff = row.get("SeedDiff", 0)

            # Get Elo ratings
            rating_a = self._season_ratings.get(
                (int(season), int(team_a)),
                self.ratings.get(int(team_a), 1500) if pd.notna(team_a) else 1500,
            ) if pd.notna(team_a) else 1500

            rating_b = self._season_ratings.get(
                (int(season), int(team_b)),
                self.ratings.get(int(team_b), 1500) if pd.notna(team_b) else 1500,
            ) if pd.notna(team_b) else 1500

            # Tournament games are neutral site
            elo_prob = 1 / (1 + 10 ** ((rating_b - rating_a) / self._elo_scale))

            # Blend with seed-based prior (Elo 70%, seed 30%)
            seed_prob = 1 / (1 + np.exp(-0.15 * seed_diff))
            prob = 0.7 * elo_prob + 0.3 * seed_prob

            probs.append(np.clip(prob, 0.01, 0.99))

        return np.array(probs)

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """Evaluate Elo predictions."""
        probs = self.predict_proba(X)
        preds = (probs >= 0.5).astype(int)
        return {
            "log_loss": log_loss(y, probs),
            "accuracy": accuracy_score(y, preds),
            "n_samples": len(y),
        }
