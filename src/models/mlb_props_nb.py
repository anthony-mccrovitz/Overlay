"""
MLB Props — Negative Binomial regression for count-data markets.

Covers: pitcher_strikeouts, batter_hits, batter_total_bases, batter_runs, batter_rbis

Negative binomial is better than XGBoost point estimates because:
  - Count data is overdispersed (variance > mean for Ks, hits)
  - NB gives the full distribution → P(X > line) directly
  - Calibrated for O/U prop betting without extra calibration step

Model per prop type:
  mu    = exp(X @ β)      — expected count
  alpha = dispersion      — fitted from data
  P(X = k) = NegBin(mu, alpha)
  P(X > line) = 1 - CDF(floor(line), mu, alpha)
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import nbinom

MODEL_DIR = Path("data/models/mlb_props")

# ── NB helpers ────────────────────────────────────────────────────────────────

def _nb_params(mu: float, alpha: float) -> tuple[float, float]:
    """Convert NB(mu, alpha) → scipy NegBin (n, p) parameterization."""
    n = 1.0 / alpha
    p = n / (n + mu)
    return n, p


def nb_over_prob(mu: float, alpha: float, line: float) -> float:
    """P(X > line) for NegBin(mu, alpha)."""
    n, p = _nb_params(max(mu, 0.01), max(alpha, 0.01))
    return float(1.0 - nbinom.cdf(int(line), n, p))


def nb_exact_prob(mu: float, alpha: float, k: int) -> float:
    """P(X = k) for NegBin(mu, alpha)."""
    n, p = _nb_params(max(mu, 0.01), max(alpha, 0.01))
    return float(nbinom.pmf(k, n, p))


# ── Prop type registry ────────────────────────────────────────────────────────

PROP_CONFIGS: dict[str, dict] = {
    "pitcher_strikeouts": {
        "target":   "actual_ks",
        "features": [
            "k_per_9", "whip", "innings_per_start",
            "opp_k_rate", "recent_ks_3g",
        ],
        "log_link": True,
    },
    "batter_hits": {
        "target":   "actual_hits",
        "features": [
            "ba_season", "babip", "contact_pct", "opp_whip",
            "opp_k_rate", "park_factor_hits", "batting_order_pos",
            "recent_hits_3g",
        ],
        "log_link": True,
    },
    "batter_total_bases": {
        "target":   "actual_tb",
        "features": [
            "slg_season", "iso_power", "hr_rate", "opp_hr_rate",
            "park_hr_factor", "batting_order_pos", "recent_tb_3g",
        ],
        "log_link": True,
    },
    "batter_runs": {
        "target":   "actual_runs",
        "features": [
            "obp_season", "speed_score", "batting_order_pos",
            "team_wrc_plus", "opp_era", "recent_runs_3g",
        ],
        "log_link": True,
    },
    "batter_rbis": {
        "target":   "actual_rbis",
        "features": [
            "rbi_per_game", "risp_ba", "batting_order_pos",
            "team_obp", "opp_era", "recent_rbis_3g",
        ],
        "log_link": True,
    },
}


# ── Model class ───────────────────────────────────────────────────────────────

class NegBinPropModel:
    """
    Negative Binomial regression for a single MLB prop type.
    Uses statsmodels GLM with NB family for proper uncertainty.
    """

    def __init__(self, prop_type: str) -> None:
        if prop_type not in PROP_CONFIGS:
            raise ValueError(f"Unknown prop type: {prop_type}. Choose from {list(PROP_CONFIGS)}")
        self.prop_type = prop_type
        self.cfg       = PROP_CONFIGS[prop_type]
        self.features  = self.cfg["features"]
        self.target    = self.cfg["target"]

        self.model_path = MODEL_DIR / f"{prop_type}_nb.pkl"
        self._fitted_params: dict[str, float] = {}  # {feature: coef, "intercept": val, "alpha": val}

        self._coefs: np.ndarray | None = None
        self._intercept: float = 0.0
        self._alpha: float = 0.5   # NB dispersion
        self._feature_means: dict[str, float] = {}

    def fit(self, df: pd.DataFrame, verbose: bool = True) -> "NegBinPropModel":
        """
        Fit NB GLM on training DataFrame. Requires columns: self.features + self.target.
        Missing feature values are imputed with feature means.
        """
        import statsmodels.api as sm

        available_features = [f for f in self.features if f in df.columns]
        if not available_features:
            raise ValueError(f"No matching feature columns found. Expected: {self.features}")

        df_clean = df[available_features + [self.target]].copy()
        self._feature_means = {f: float(df_clean[f].mean()) for f in available_features}
        df_clean = df_clean.fillna(self._feature_means)

        X = sm.add_constant(df_clean[available_features].values, has_constant="add")
        y = df_clean[self.target].values.astype(float)

        # Filter out zero or negative targets
        mask = y > 0
        X, y = X[mask], y[mask]

        if verbose:
            print(f"  [nb_{self.prop_type}] Fitting on {len(y)} obs, {len(available_features)} features")

        try:
            glm = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=0.5)).fit(maxiter=200)
            self._coefs     = glm.params[1:]     # skip intercept
            self._intercept = float(glm.params[0])
            # Extract alpha from the fitted model
            self._alpha = float(getattr(glm, "scale", 0.5))
            self._fitted_params = {
                f: round(float(self._coefs[i]), 5)
                for i, f in enumerate(available_features)
            }
            self._fitted_params["intercept"] = round(self._intercept, 5)
            self._fitted_params["alpha"]     = round(self._alpha, 5)
            self._available_features         = available_features

            if verbose:
                mae = float(np.mean(np.abs(glm.predict() - y)))
                print(f"  [nb_{self.prop_type}] MAE={mae:.3f}  alpha={self._alpha:.4f}  "
                      f"converged={glm.converged}")

        except Exception as e:
            if verbose:
                print(f"  [nb_{self.prop_type}] GLM failed ({e}), falling back to Poisson GLM")
            glm = sm.GLM(y, X, family=sm.families.Poisson()).fit(maxiter=200)
            self._coefs     = glm.params[1:]
            self._intercept = float(glm.params[0])
            self._alpha     = 0.5
            self._available_features = available_features

        self._save()
        return self

    def predict_mu(self, row: dict[str, float]) -> float:
        """Predict expected count for a single observation."""
        if self._coefs is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
        features = getattr(self, "_available_features", self.features)
        coefs = np.atleast_1d(self._coefs)
        if len(coefs) == 0 or len(features) == 0:
            # Intercept-only model — return exp(intercept)
            return float(np.exp(self._intercept))
        x = np.array([
            row.get(f, self._feature_means.get(f, 0.0))
            for f in features
        ])
        # Trim coefs/x to matching length (handles Poisson fallback edge cases)
        n = min(len(coefs), len(x))
        log_mu = self._intercept + float(np.dot(coefs[:n], x[:n]))
        return float(np.exp(log_mu))

    def over_prob(self, row: dict[str, float], line: float) -> float:
        """P(actual > line) for the given player/game context."""
        mu = self.predict_mu(row)
        return nb_over_prob(mu, self._alpha, line)

    def full_distribution(self, row: dict[str, float], max_k: int = 20) -> dict[int, float]:
        """Return P(X = k) for k in 0..max_k."""
        mu = self.predict_mu(row)
        return {k: nb_exact_prob(mu, self._alpha, k) for k in range(max_k + 1)}

    def find_edges(
        self,
        props: list[dict],
        min_edge_pct: float = 3.0,
    ) -> list[dict]:
        """
        Find edges in a list of prop bets.

        Each prop dict needs: feature columns + "line" + "over_odds" + "under_odds"
        and optionally "player", "matchup", "sportsbook".
        """
        edges = []
        for prop in props:
            line = float(prop.get("line", 0))
            if line <= 0:
                continue

            over_odds  = int(prop.get("over_odds", -110))
            under_odds = int(prop.get("under_odds", -110))

            # Devig
            imp_over  = abs(over_odds) / (abs(over_odds) + 100) if over_odds < 0 else 100 / (over_odds + 100)
            imp_under = abs(under_odds) / (abs(under_odds) + 100) if under_odds < 0 else 100 / (under_odds + 100)
            total_imp = imp_over + imp_under
            imp_over_fair  = imp_over  / total_imp
            imp_under_fair = imp_under / total_imp

            mu = self.predict_mu(prop)
            model_over  = nb_over_prob(mu, self._alpha, line)
            model_under = 1.0 - model_over

            for direction, model_p, imp_p, odds in [
                ("OVER",  model_over,  imp_over_fair,  over_odds),
                ("UNDER", model_under, imp_under_fair, under_odds),
            ]:
                edge = (model_p - imp_p) * 100.0
                if edge >= min_edge_pct:
                    edges.append({
                        "market":       self.prop_type,
                        "direction":    direction,
                        "player":       prop.get("player", ""),
                        "team":         f"{prop.get('player', '')} {direction} {line}",
                        "matchup":      prop.get("matchup", ""),
                        "line":         line,
                        "odds":         odds,
                        "model_prob":   round(model_p, 4),
                        "implied_prob": round(imp_p, 4),
                        "edge_pct":     round(edge, 2),
                        "model_mu":     round(mu, 2),
                        "sportsbook":   prop.get("sportsbook", ""),
                    })

        return sorted(edges, key=lambda x: x["edge_pct"], reverse=True)

    def _save(self) -> None:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump({
                "prop_type":          self.prop_type,
                "coefs":              self._coefs,
                "intercept":          self._intercept,
                "alpha":              self._alpha,
                "feature_means":      self._feature_means,
                "available_features": getattr(self, "_available_features", self.features),
                "fitted_params":      self._fitted_params,
            }, f)

    def load(self) -> "NegBinPropModel":
        with open(self.model_path, "rb") as f:
            d = pickle.load(f)
        self._coefs              = d["coefs"]
        self._intercept          = d["intercept"]
        self._alpha              = d["alpha"]
        self._feature_means      = d["feature_means"]
        self._available_features = d.get("available_features", self.features)
        self._fitted_params      = d.get("fitted_params", {})
        return self

    def is_fitted(self) -> bool:
        return self._coefs is not None and self.model_path.exists()


# ── Training data builders ────────────────────────────────────────────────────

def build_pitcher_ks_nb_data(seasons: list[int] | None = None) -> pd.DataFrame:
    """
    Build NB training data for pitcher_strikeouts.
    Reuses existing mlb_pitcher_ks.build_ks_training_data but maps columns to NB features.

    Actual columns from build_ks_training_data:
      pitcher_k9, pitcher_whip, pitcher_avg_ip, opp_team_k_rate,
      pitcher_recent_k_avg, pitcher_starts, actual_ks, season, ...
    """
    from src.models.mlb_pitcher_ks import build_ks_training_data

    if seasons is None:
        seasons = list(range(2021, 2026))

    df = build_ks_training_data(seasons, verbose=False)
    if df.empty:
        return df

    # Map actual column names → NB feature names
    col_map = {
        "pitcher_k9":           "k_per_9",
        "pitcher_whip":         "whip",
        "pitcher_avg_ip":       "innings_per_start",
        "opp_team_k_rate":      "opp_k_rate",
        "pitcher_recent_k_avg": "recent_ks_3g",
    }
    for old, new in col_map.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    # Synthetic: k% approximation from K/9 and IP/start
    if "k_per_9" in df.columns and "innings_per_start" in df.columns:
        df["k_pct_season"] = df["k_per_9"] / 27.0  # rough K per batter faced
    else:
        df["k_pct_season"] = 0.22

    # Park factor placeholder — no park data in current pipeline
    df["park_k_factor"] = 1.0

    # Ensure actual_ks target exists
    if "actual_ks" not in df.columns:
        df["actual_ks"] = df.get("ks", 0)

    return df


def train_all_prop_models(seasons: list[int] | None = None, verbose: bool = True) -> dict:
    """
    Train NB models for all available prop types.
    Returns summary dict with MAE per model.
    """
    if seasons is None:
        seasons = list(range(2021, 2026))

    results = {}

    # Pitcher strikeouts — we have good training data
    try:
        df = build_pitcher_ks_nb_data(seasons)
        if not df.empty:
            model = NegBinPropModel("pitcher_strikeouts")
            model.fit(df, verbose=verbose)
            results["pitcher_strikeouts"] = "trained"
        else:
            results["pitcher_strikeouts"] = "no_data"
    except Exception as e:
        results["pitcher_strikeouts"] = f"error: {e}"
        if verbose:
            print(f"  [nb_props] pitcher_strikeouts failed: {e}")

    # Batter props — will train when data is available
    for prop in ["batter_hits", "batter_total_bases", "batter_runs", "batter_rbis"]:
        results[prop] = "pending_data"

    return results


# ── Quick backtest ────────────────────────────────────────────────────────────

def backtest_pitcher_ks(holdout_season: int = 2025) -> dict:
    """
    Hold out one season, train on rest, evaluate P(Ks > line) calibration.
    """
    from src.models.mlb_pitcher_ks import build_ks_training_data

    all_seasons = list(range(2021, holdout_season + 1))
    train_seasons = [s for s in all_seasons if s != holdout_season]

    df_all = build_pitcher_ks_nb_data(all_seasons)
    if df_all.empty:
        return {"error": "no data"}

    df_train = df_all[df_all["season"].isin(train_seasons)]
    df_test  = df_all[df_all["season"] == holdout_season]

    model = NegBinPropModel("pitcher_strikeouts")
    model.fit(df_train, verbose=False)

    results = []
    for _, row in df_test.iterrows():
        mu = model.predict_mu(row.to_dict())
        actual = int(row.get("actual_ks", 0))
        # Check calibration at common lines (4.5, 5.5, 6.5)
        for line in [4.5, 5.5, 6.5]:
            p_over = nb_over_prob(mu, model._alpha, line)
            hit    = 1 if actual > line else 0
            results.append({"line": line, "p_over": p_over, "hit": hit, "mu": mu, "actual": actual})

    df_r = pd.DataFrame(results)
    summary: dict[str, Any] = {}
    for line in [4.5, 5.5, 6.5]:
        sub = df_r[df_r["line"] == line]
        if len(sub) == 0:
            continue
        brier = float(((sub["p_over"] - sub["hit"]) ** 2).mean())
        actual_over_rate = float(sub["hit"].mean())
        avg_p = float(sub["p_over"].mean())
        summary[f"line_{line}"] = {
            "N":          len(sub),
            "brier":      round(brier, 4),
            "avg_pred":   round(avg_p, 3),
            "actual_rate": round(actual_over_rate, 3),
            "calibration_err": round(avg_p - actual_over_rate, 3),
        }

    return summary
