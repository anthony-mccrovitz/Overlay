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
            "obp_season", "batting_order_pos", "recent_runs_3g",
        ],
        "log_link": True,
    },
    "batter_rbis": {
        "target":   "actual_rbis",
        "features": [
            "rbi_per_game", "risp_ba", "batting_order_pos", "recent_rbis_3g",
        ],
        "log_link": True,
    },
    "batter_home_runs": {
        "target":   "actual_hr",
        "features": [
            "hr_per_game", "iso_power", "batting_order_pos", "recent_hr_3g",
        ],
        "log_link": True,
    },
    "batter_walks": {
        "target":   "actual_walks",
        "features": [
            "bb_per_game", "obp_season", "batting_order_pos", "recent_walks_3g",
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

        # Keep zero-count games — they are real outcomes that define the true mean.
        # The old `y > 0` filter dropped them, so low-rate props (HR, walks) trained
        # on the conditional-on-positive distribution and predicted mu 3-7x too high
        # → a permanent OVER bias. NB regression handles zeros natively; only drop
        # impossible negatives.
        mask = y >= 0
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


def _fetch_batter_game_logs(player_id: int, season: int) -> list[dict]:
    """Fetch per-game hitting stats from MLB Stats API for one player/season."""
    import requests
    try:
        resp = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            params={"stats": "gameLog", "group": "hitting", "season": season, "sportId": 1},
            timeout=15,
        )
        data = resp.json()
        for group in data.get("stats", []):
            return group.get("splits", [])
    except Exception:
        pass
    return []


def _get_qualified_batters(season: int, min_pa: int = 200) -> list[dict]:
    """Return list of {id, fullName} for batters with ≥ min_pa PA in season."""
    import requests
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/stats",
            params={
                "stats":   "season",
                "group":   "hitting",
                "season":  season,
                "sportId": 1,
                "limit":   500,
            },
            timeout=20,
        )
        data = resp.json()
        rows = []
        for group in data.get("stats", []):
            for split in group.get("splits", []):
                stat   = split.get("stat", {})
                player = split.get("player", {})
                pa     = int(stat.get("plateAppearances", 0) or 0)
                if pa >= min_pa and player.get("id"):
                    rows.append({"id": player["id"], "fullName": player.get("fullName", "")})
        return rows
    except Exception:
        return []


def build_batter_hits_data(
    seasons: list[int] | None = None,
    verbose: bool = True,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Build per-game batter_hits training rows from MLB Stats API game logs.

    Each row: one player-game with actual_hits + season batting features.
    Features map to PROP_CONFIGS["batter_hits"] columns.
    """
    import requests, time

    if seasons is None:
        seasons = list(range(2022, 2026))

    cache_dir = cache_dir or Path("data/cache/batter_logs")
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []

    for season in seasons:
        cache_file = cache_dir / f"batter_hits_{season}.json"
        if cache_file.exists():
            try:
                rows = json.loads(cache_file.read_text())
                all_rows.extend(rows)
                if verbose:
                    print(f"  [batter_hits] {season}: loaded {len(rows)} rows from cache")
                continue
            except Exception:
                pass

        if verbose:
            print(f"  [batter_hits] {season}: fetching qualified batters...")
        batters = _get_qualified_batters(season, min_pa=150)
        if verbose:
            print(f"  [batter_hits] {season}: {len(batters)} qualified batters")

        season_rows: list[dict] = []
        for i, batter in enumerate(batters):
            pid  = batter["id"]
            name = batter["fullName"]

            # Season-level stats for feature columns
            try:
                resp = requests.get(
                    f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                    params={"stats": "season", "group": "hitting",
                            "season": season, "sportId": 1},
                    timeout=10,
                )
                sdata  = resp.json()
                season_stat: dict = {}
                for grp in sdata.get("stats", []):
                    splits = grp.get("splits", [])
                    if splits:
                        season_stat = splits[0].get("stat", {})
                        break
            except Exception:
                season_stat = {}

            avg   = float(season_stat.get("avg",  0.250) or 0.250)
            babip = float(season_stat.get("babip", 0.300) or 0.300)
            obp   = float(season_stat.get("obp",  0.320) or 0.320)
            slg   = float(season_stat.get("slg",  0.400) or 0.400)
            g     = int(season_stat.get("gamesPlayed", 1) or 1)
            hits  = int(season_stat.get("hits", 0) or 0)

            # Per-game logs for the target variable
            game_splits = _fetch_batter_game_logs(pid, season)
            time.sleep(0.05)  # gentle rate limit

            for split in game_splits:
                gs = split.get("stat", {})
                actual_hits = int(gs.get("hits", 0) or 0)
                ab          = int(gs.get("atBats", 0) or 0)
                if ab < 1:
                    continue

                season_rows.append({
                    "season":            season,
                    "player_id":         pid,
                    "player":            name,
                    "actual_hits":       actual_hits,
                    # Features matching PROP_CONFIGS["batter_hits"]
                    "ba_season":         avg,
                    "babip":             babip,
                    "contact_pct":       avg / max(babip, 0.001) * 0.75,
                    "opp_whip":          1.30,   # league avg placeholder
                    "opp_k_rate":        0.22,   # league avg placeholder
                    "park_factor_hits":  1.0,    # neutral placeholder
                    "batting_order_pos": 5,      # unknown without lineup
                    "recent_hits_3g":    hits / max(g, 1),
                })

        cache_file.write_text(json.dumps(season_rows, indent=2))
        all_rows.extend(season_rows)
        if verbose:
            print(f"  [batter_hits] {season}: {len(season_rows)} game rows cached")

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


def build_batter_tb_data(
    seasons: list[int] | None = None,
    verbose: bool = True,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Build per-game batter_total_bases training rows from MLB Stats API game logs.
    Features map to PROP_CONFIGS["batter_total_bases"] columns.
    """
    import requests, time

    if seasons is None:
        seasons = list(range(2022, 2026))

    cache_dir = cache_dir or Path("data/cache/batter_logs")
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []

    for season in seasons:
        cache_file = cache_dir / f"batter_tb_{season}.json"
        if cache_file.exists():
            try:
                rows = json.loads(cache_file.read_text())
                all_rows.extend(rows)
                if verbose:
                    print(f"  [batter_tb] {season}: loaded {len(rows)} rows from cache")
                continue
            except Exception:
                pass

        if verbose:
            print(f"  [batter_tb] {season}: fetching qualified batters...")
        batters = _get_qualified_batters(season, min_pa=150)

        season_rows: list[dict] = []
        for batter in batters:
            pid  = batter["id"]
            name = batter["fullName"]

            try:
                resp = requests.get(
                    f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                    params={"stats": "season", "group": "hitting",
                            "season": season, "sportId": 1},
                    timeout=10,
                )
                sdata       = resp.json()
                season_stat = {}
                for grp in sdata.get("stats", []):
                    splits = grp.get("splits", [])
                    if splits:
                        season_stat = splits[0].get("stat", {})
                        break
            except Exception:
                season_stat = {}

            avg   = float(season_stat.get("avg",  0.250) or 0.250)
            slg   = float(season_stat.get("slg",  0.400) or 0.400)
            g     = int(season_stat.get("gamesPlayed", 1) or 1)
            hrs   = int(season_stat.get("homeRuns", 0) or 0)
            tbases = int(season_stat.get("totalBases", 0) or 0)

            game_splits = _fetch_batter_game_logs(pid, season)
            time.sleep(0.05)

            for split in game_splits:
                gs    = split.get("stat", {})
                ab    = int(gs.get("atBats", 0) or 0)
                h     = int(gs.get("hits", 0) or 0)
                doubles = int(gs.get("doubles", 0) or 0)
                triples = int(gs.get("triples", 0) or 0)
                home_runs = int(gs.get("homeRuns", 0) or 0)
                actual_tb = h + doubles + (2 * triples) + (3 * home_runs)
                if ab < 1:
                    continue

                season_rows.append({
                    "season":            season,
                    "player_id":         pid,
                    "player":            name,
                    "actual_tb":         actual_tb,
                    "slg_season":        slg,
                    "iso_power":         slg - avg,
                    "hr_rate":           hrs / max(g, 1),
                    "opp_hr_rate":       0.025,  # league avg placeholder
                    "park_hr_factor":    1.0,
                    "batting_order_pos": 5,
                    "recent_tb_3g":      tbases / max(g, 1),
                })

        cache_file.write_text(json.dumps(season_rows, indent=2))
        all_rows.extend(season_rows)
        if verbose:
            print(f"  [batter_tb] {season}: {len(season_rows)} game rows cached")

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


def build_batter_runs_data(
    seasons: list[int] | None = None,
    verbose: bool = True,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Build per-game batter_runs training rows from MLB Stats API game logs.
    Uses player-only features: obp_season, batting_order_pos, recent_runs_3g.
    """
    import requests, time

    if seasons is None:
        seasons = list(range(2022, 2026))

    cache_dir = cache_dir or Path("data/cache/batter_logs")
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []

    for season in seasons:
        cache_file = cache_dir / f"batter_runs_{season}.json"
        if cache_file.exists():
            try:
                rows = json.loads(cache_file.read_text())
                all_rows.extend(rows)
                if verbose:
                    print(f"  [batter_runs] {season}: loaded {len(rows)} rows from cache")
                continue
            except Exception:
                pass

        if verbose:
            print(f"  [batter_runs] {season}: fetching qualified batters...")
        batters = _get_qualified_batters(season, min_pa=150)

        season_rows: list[dict] = []
        for batter in batters:
            pid  = batter["id"]
            name = batter["fullName"]

            try:
                resp = requests.get(
                    f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                    params={"stats": "season", "group": "hitting",
                            "season": season, "sportId": 1},
                    timeout=10,
                )
                sdata       = resp.json()
                season_stat = {}
                for grp in sdata.get("stats", []):
                    splits = grp.get("splits", [])
                    if splits:
                        season_stat = splits[0].get("stat", {})
                        break
            except Exception:
                season_stat = {}

            obp  = float(season_stat.get("obp",  0.320) or 0.320)
            g    = int(season_stat.get("gamesPlayed", 1) or 1)
            runs = int(season_stat.get("runs", 0) or 0)

            game_splits = _fetch_batter_game_logs(pid, season)
            time.sleep(0.05)

            for split in game_splits:
                gs  = split.get("stat", {})
                ab  = int(gs.get("atBats", 0) or 0)
                actual_runs = int(gs.get("runs", 0) or 0)
                if ab < 1:
                    continue

                season_rows.append({
                    "season":            season,
                    "player_id":         pid,
                    "player":            name,
                    "actual_runs":       actual_runs,
                    "obp_season":        obp,
                    "batting_order_pos": 5,
                    "recent_runs_3g":    runs / max(g, 1),
                })

        cache_file.write_text(json.dumps(season_rows, indent=2))
        all_rows.extend(season_rows)
        if verbose:
            print(f"  [batter_runs] {season}: {len(season_rows)} game rows cached")

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


def build_batter_rbis_data(
    seasons: list[int] | None = None,
    verbose: bool = True,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Build per-game batter_rbis training rows from MLB Stats API game logs.
    Uses player-only features: rbi_per_game, risp_ba, batting_order_pos, recent_rbis_3g.
    """
    import requests, time

    if seasons is None:
        seasons = list(range(2022, 2026))

    cache_dir = cache_dir or Path("data/cache/batter_logs")
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []

    for season in seasons:
        cache_file = cache_dir / f"batter_rbis_{season}.json"
        if cache_file.exists():
            try:
                rows = json.loads(cache_file.read_text())
                all_rows.extend(rows)
                if verbose:
                    print(f"  [batter_rbis] {season}: loaded {len(rows)} rows from cache")
                continue
            except Exception:
                pass

        if verbose:
            print(f"  [batter_rbis] {season}: fetching qualified batters...")
        batters = _get_qualified_batters(season, min_pa=150)

        season_rows: list[dict] = []
        for batter in batters:
            pid  = batter["id"]
            name = batter["fullName"]

            try:
                resp = requests.get(
                    f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                    params={"stats": "season", "group": "hitting",
                            "season": season, "sportId": 1},
                    timeout=10,
                )
                sdata       = resp.json()
                season_stat = {}
                for grp in sdata.get("stats", []):
                    splits = grp.get("splits", [])
                    if splits:
                        season_stat = splits[0].get("stat", {})
                        break
            except Exception:
                season_stat = {}

            avg  = float(season_stat.get("avg",  0.250) or 0.250)
            g    = int(season_stat.get("gamesPlayed", 1) or 1)
            rbis = int(season_stat.get("rbi", 0) or 0)

            game_splits = _fetch_batter_game_logs(pid, season)
            time.sleep(0.05)

            for split in game_splits:
                gs  = split.get("stat", {})
                ab  = int(gs.get("atBats", 0) or 0)
                actual_rbis = int(gs.get("rbi", 0) or 0)
                if ab < 1:
                    continue

                season_rows.append({
                    "season":            season,
                    "player_id":         pid,
                    "player":            name,
                    "actual_rbis":       actual_rbis,
                    "rbi_per_game":      rbis / max(g, 1),
                    "risp_ba":           avg,   # proxy — RISP BA not in standard API
                    "batting_order_pos": 5,
                    "recent_rbis_3g":    rbis / max(g, 1),
                })

        cache_file.write_text(json.dumps(season_rows, indent=2))
        all_rows.extend(season_rows)
        if verbose:
            print(f"  [batter_rbis] {season}: {len(season_rows)} game rows cached")

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


def build_batter_home_runs_data(
    seasons: list[int] | None = None,
    verbose: bool = True,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Build per-game batter_home_runs training rows from MLB Stats API game logs.
    Player-only features: hr_per_game, iso_power (slg-avg), batting_order_pos,
    recent_hr_3g. HR is a low-rate count, well-suited to the NB the model fits.
    """
    import requests, time

    if seasons is None:
        seasons = list(range(2022, 2026))

    cache_dir = cache_dir or Path("data/cache/batter_logs")
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []

    for season in seasons:
        cache_file = cache_dir / f"batter_home_runs_{season}.json"
        if cache_file.exists():
            try:
                rows = json.loads(cache_file.read_text())
                all_rows.extend(rows)
                if verbose:
                    print(f"  [batter_home_runs] {season}: loaded {len(rows)} rows from cache")
                continue
            except Exception:
                pass

        if verbose:
            print(f"  [batter_home_runs] {season}: fetching qualified batters...")
        batters = _get_qualified_batters(season, min_pa=150)

        season_rows: list[dict] = []
        for batter in batters:
            pid  = batter["id"]
            name = batter["fullName"]

            try:
                resp = requests.get(
                    f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                    params={"stats": "season", "group": "hitting",
                            "season": season, "sportId": 1},
                    timeout=10,
                )
                sdata       = resp.json()
                season_stat = {}
                for grp in sdata.get("stats", []):
                    splits = grp.get("splits", [])
                    if splits:
                        season_stat = splits[0].get("stat", {})
                        break
            except Exception:
                season_stat = {}

            slg = float(season_stat.get("slg", 0.400) or 0.400)
            avg = float(season_stat.get("avg", 0.250) or 0.250)
            g   = int(season_stat.get("gamesPlayed", 1) or 1)
            hr  = int(season_stat.get("homeRuns", 0) or 0)

            game_splits = _fetch_batter_game_logs(pid, season)
            time.sleep(0.05)

            for split in game_splits:
                gs  = split.get("stat", {})
                ab  = int(gs.get("atBats", 0) or 0)
                actual_hr = int(gs.get("homeRuns", 0) or 0)
                if ab < 1:
                    continue

                season_rows.append({
                    "season":            season,
                    "player_id":         pid,
                    "player":            name,
                    "actual_hr":         actual_hr,
                    "hr_per_game":       hr / max(g, 1),
                    "iso_power":         max(slg - avg, 0.0),
                    "batting_order_pos": 5,
                    "recent_hr_3g":      hr / max(g, 1),
                })

        cache_file.write_text(json.dumps(season_rows, indent=2))
        all_rows.extend(season_rows)
        if verbose:
            print(f"  [batter_home_runs] {season}: {len(season_rows)} game rows cached")

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


def build_batter_walks_data(
    seasons: list[int] | None = None,
    verbose: bool = True,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Build per-game batter_walks training rows from MLB Stats API game logs.
    Player-only features: bb_per_game, obp_season, batting_order_pos, recent_walks_3g.
    """
    import requests, time

    if seasons is None:
        seasons = list(range(2022, 2026))

    cache_dir = cache_dir or Path("data/cache/batter_logs")
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []

    for season in seasons:
        cache_file = cache_dir / f"batter_walks_{season}.json"
        if cache_file.exists():
            try:
                rows = json.loads(cache_file.read_text())
                all_rows.extend(rows)
                if verbose:
                    print(f"  [batter_walks] {season}: loaded {len(rows)} rows from cache")
                continue
            except Exception:
                pass

        if verbose:
            print(f"  [batter_walks] {season}: fetching qualified batters...")
        batters = _get_qualified_batters(season, min_pa=150)

        season_rows: list[dict] = []
        for batter in batters:
            pid  = batter["id"]
            name = batter["fullName"]

            try:
                resp = requests.get(
                    f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                    params={"stats": "season", "group": "hitting",
                            "season": season, "sportId": 1},
                    timeout=10,
                )
                sdata       = resp.json()
                season_stat = {}
                for grp in sdata.get("stats", []):
                    splits = grp.get("splits", [])
                    if splits:
                        season_stat = splits[0].get("stat", {})
                        break
            except Exception:
                season_stat = {}

            obp = float(season_stat.get("obp", 0.320) or 0.320)
            g   = int(season_stat.get("gamesPlayed", 1) or 1)
            bb  = int(season_stat.get("baseOnBalls", 0) or 0)

            game_splits = _fetch_batter_game_logs(pid, season)
            time.sleep(0.05)

            for split in game_splits:
                gs  = split.get("stat", {})
                pa  = int(gs.get("plateAppearances", 0) or 0)
                actual_walks = int(gs.get("baseOnBalls", 0) or 0)
                if pa < 1:
                    continue

                season_rows.append({
                    "season":            season,
                    "player_id":         pid,
                    "player":            name,
                    "actual_walks":      actual_walks,
                    "bb_per_game":       bb / max(g, 1),
                    "obp_season":        obp,
                    "batting_order_pos": 5,
                    "recent_walks_3g":   bb / max(g, 1),
                })

        cache_file.write_text(json.dumps(season_rows, indent=2))
        all_rows.extend(season_rows)
        if verbose:
            print(f"  [batter_walks] {season}: {len(season_rows)} game rows cached")

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


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

    # Batter hits
    try:
        df_hits = build_batter_hits_data(seasons, verbose=verbose)
        if not df_hits.empty and "actual_hits" in df_hits.columns:
            model = NegBinPropModel("batter_hits")
            model.fit(df_hits, verbose=verbose)
            results["batter_hits"] = "trained"
        else:
            results["batter_hits"] = "no_data"
    except Exception as e:
        results["batter_hits"] = f"error: {e}"
        if verbose:
            print(f"  [nb_props] batter_hits failed: {e}")

    # Batter total bases
    try:
        df_tb = build_batter_tb_data(seasons, verbose=verbose)
        if not df_tb.empty and "actual_tb" in df_tb.columns:
            model = NegBinPropModel("batter_total_bases")
            model.fit(df_tb, verbose=verbose)
            results["batter_total_bases"] = "trained"
        else:
            results["batter_total_bases"] = "no_data"
    except Exception as e:
        results["batter_total_bases"] = f"error: {e}"
        if verbose:
            print(f"  [nb_props] batter_total_bases failed: {e}")

    # Batter runs
    try:
        df_runs = build_batter_runs_data(seasons, verbose=verbose)
        if not df_runs.empty and "actual_runs" in df_runs.columns:
            model = NegBinPropModel("batter_runs")
            model.fit(df_runs, verbose=verbose)
            results["batter_runs"] = "trained"
        else:
            results["batter_runs"] = "no_data"
    except Exception as e:
        results["batter_runs"] = f"error: {e}"
        if verbose:
            print(f"  [nb_props] batter_runs failed: {e}")

    # Batter RBIs
    try:
        df_rbis = build_batter_rbis_data(seasons, verbose=verbose)
        if not df_rbis.empty and "actual_rbis" in df_rbis.columns:
            model = NegBinPropModel("batter_rbis")
            model.fit(df_rbis, verbose=verbose)
            results["batter_rbis"] = "trained"
        else:
            results["batter_rbis"] = "no_data"
    except Exception as e:
        results["batter_rbis"] = f"error: {e}"
        if verbose:
            print(f"  [nb_props] batter_rbis failed: {e}")

    # Batter home runs
    try:
        df_hr = build_batter_home_runs_data(seasons, verbose=verbose)
        if not df_hr.empty and "actual_hr" in df_hr.columns:
            model = NegBinPropModel("batter_home_runs")
            model.fit(df_hr, verbose=verbose)
            results["batter_home_runs"] = "trained"
        else:
            results["batter_home_runs"] = "no_data"
    except Exception as e:
        results["batter_home_runs"] = f"error: {e}"
        if verbose:
            print(f"  [nb_props] batter_home_runs failed: {e}")

    # Batter walks
    try:
        df_bb = build_batter_walks_data(seasons, verbose=verbose)
        if not df_bb.empty and "actual_walks" in df_bb.columns:
            model = NegBinPropModel("batter_walks")
            model.fit(df_bb, verbose=verbose)
            results["batter_walks"] = "trained"
        else:
            results["batter_walks"] = "no_data"
    except Exception as e:
        results["batter_walks"] = f"error: {e}"
        if verbose:
            print(f"  [nb_props] batter_walks failed: {e}")

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
