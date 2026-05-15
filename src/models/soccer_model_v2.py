"""
SoccerModelV2 — Rolling Elo + 2-parameter Poisson soccer model.

Improvements over Dixon-Coles v1:
  - Rolling Elo ratings computed sequentially from all training matches
    (each match uses Elo-at-game-time, not end-of-training Elo)
  - Only 2 free parameters (μ, α) instead of 2*N team params + home_adv + rho
  - Much lower risk of overfitting on small tournament datasets
  - Same Dixon-Coles low-score correction and score-grid API as v1

Model:
    λ_i = exp(μ + α × d)   where d = (elo_i - elo_j) / 400
    Goals for team i ~ Poisson(λ_i), independently

Elo update rule:
    K = 40 (WC) | 30 (Euros/Copa) | 20 (qualifier)
    expected = 1 / (1 + 10^((opp_elo - team_elo) / 400))
    new_elo  = old_elo + K × (actual - expected)
    actual   = 1 (win) | 0.5 (draw) | 0 (loss)

Usage:
    model = SoccerModelV2()
    model.fit(verbose=True)
    model.seed_from_eloratings()          # overlay live Elo from eloratings.net
    probs = model.matchup("Spain", "Germany", neutral=True)
    # → {'home_win': 0.45, 'draw': 0.25, 'away_win': 0.30, 'exp_total': 2.4}
"""
from __future__ import annotations

import math
import pickle
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import requests
from scipy.optimize import minimize
from scipy.stats import poisson

MODEL_PATH_V2 = Path("data/models/soccer_dixoncoles_v2.pkl")

# Score-grid size: 9×9 (goals 0–8). P(X > 8) is negligible for int'l soccer.
MAX_GOALS = 8

# ── Elo K-factors by tournament type ─────────────────────────────────────────

def _k_factor(tournament: str) -> int:
    t = tournament.lower()
    if "world cup" in t:
        return 40
    if "euro" in t or "copa" in t:
        return 30
    return 20


# ── Dixon-Coles low-score correction (copied + clamped from v1) ──────────────

def _dc_correction(x: int, y: int, lam_h: float, lam_a: float, rho: float) -> float:
    """
    τ(x, y) Dixon-Coles adjustment for low-scoring outcomes.
    Clamp ensures correction stays non-negative.
    """
    if x == 0 and y == 0:
        tau = 1 - lam_h * lam_a * rho
    elif x == 0 and y == 1:
        tau = 1 + lam_h * rho
    elif x == 1 and y == 0:
        tau = 1 + lam_a * rho
    elif x == 1 and y == 1:
        tau = 1 - rho
    else:
        return 1.0
    return max(tau, 0.0)


# ── Elo seed map (eloratings.net country codes → full team names) ─────────────

ELO_CODE_MAP: dict[str, str] = {
    "ES": "Spain",
    "AR": "Argentina",
    "FR": "France",
    "EN": "England",
    "BR": "Brazil",
    "PT": "Portugal",
    "CO": "Colombia",
    "NL": "Netherlands",
    "EC": "Ecuador",
    "HR": "Croatia",
    "DE": "Germany",
    "NO": "Norway",
    "JP": "Japan",
    "TR": "Turkey",
    "UY": "Uruguay",
    "CH": "Switzerland",
    "SN": "Senegal",
    "DK": "Denmark",
    "BE": "Belgium",
    "MX": "Mexico",
    "MA": "Morocco",
    "AU": "Australia",
    "US": "United States",
    "NG": "Nigeria",
    "IT": "Italy",
    "PO": "Poland",
    "CZ": "Czech Republic",
    "AT": "Austria",
    "SE": "Sweden",
    "KR": "South Korea",
    "GH": "Ghana",
    "CM": "Cameroon",
    "EG": "Egypt",
    "TN": "Tunisia",
    "CI": "Ivory Coast",
    "ZA": "South Africa",
    "ML": "Mali",
    "RW": "Rwanda",
    "PE": "Peru",
    "CL": "Chile",
    "VE": "Venezuela",
    "PY": "Paraguay",
    "BO": "Bolivia",
    "JM": "Jamaica",
    "CA": "Canada",
    "PA": "Panama",
    "CR": "Costa Rica",
    "HN": "Honduras",
    "JA": "Jamaica",
    "SA": "Saudi Arabia",
    "IR": "Iran",
    "QA": "Qatar",
    "KW": "Kuwait",
    "AE": "United Arab Emirates",
    "IQ": "Iraq",
    "JO": "Jordan",
    "RU": "Russia",
    "UA": "Ukraine",
    "RS": "Serbia",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "HU": "Hungary",
    "RO": "Romania",
    "BG": "Bulgaria",
    "AL": "Albania",
    "GR": "Greece",
    "CY": "Cyprus",
    "SL": "Sierra Leone",
    "GN": "Guinea",
}


# ── Helper ────────────────────────────────────────────────────────────────────

def _american_to_imp(o: float) -> float:
    if o >= 0:
        return 100.0 / (o + 100.0)
    return abs(o) / (abs(o) + 100.0)


# ── Model class ───────────────────────────────────────────────────────────────

class SoccerModelV2:
    """
    Rolling Elo + 2-parameter Poisson model for international football.

    Attributes after fit():
        elo_ratings:  dict[team → float] — final Elo after all training matches
        mu:           float — baseline log-goals intercept
        alpha:        float — Elo sensitivity (log-scale)
        rho:          float — Dixon-Coles low-score correction (fixed at -0.10)
        fitted_on:    date of most recent training match
    """

    DEFAULT_ELO = 1500.0
    RHO = -0.10  # Fixed DC correction (same as v1 default)

    def __init__(self) -> None:
        self.elo_ratings: dict[str, float] = {}
        self.mu: float = 0.0
        self.alpha: float = 1.0
        self.rho: float = self.RHO
        self.fitted_on: date | None = None

    # ── Elo helpers ───────────────────────────────────────────────────────────

    def _elo(self, team: str) -> float:
        return self.elo_ratings.get(team, self.DEFAULT_ELO)

    def _update_elo(
        self,
        home: str,
        away: str,
        home_score: int,
        away_score: int,
        k: int,
    ) -> None:
        """Apply one Elo update in-place."""
        elo_h = self._elo(home)
        elo_a = self._elo(away)

        exp_h = 1.0 / (1.0 + 10.0 ** ((elo_a - elo_h) / 400.0))
        exp_a = 1.0 - exp_h

        if home_score > away_score:
            actual_h, actual_a = 1.0, 0.0
        elif home_score == away_score:
            actual_h, actual_a = 0.5, 0.5
        else:
            actual_h, actual_a = 0.0, 1.0

        self.elo_ratings[home] = elo_h + k * (actual_h - exp_h)
        self.elo_ratings[away] = elo_a + k * (actual_a - exp_a)

    def _compute_rolling_elo(self, matches: list[dict]) -> dict[str, list[tuple]]:
        """
        Sequentially update Elo from all matches (sorted by date).
        Returns a dict mapping match index → (elo_home_before, elo_away_before).
        We store the Elo BEFORE each match so the fit uses Elo-at-game-time.
        """
        self.elo_ratings = {}
        elo_snapshots: list[tuple[float, float]] = []

        for m in sorted(matches, key=lambda x: x["date"]):
            home = m["home_team"]
            away = m["away_team"]

            elo_h_before = self._elo(home)
            elo_a_before = self._elo(away)
            elo_snapshots.append((elo_h_before, elo_a_before))

            k = _k_factor(m.get("tournament", ""))
            self._update_elo(home, away, m["home_score"], m["away_score"], k)

        return elo_snapshots

    # ── Negative log-likelihood ───────────────────────────────────────────────

    @staticmethod
    def _neg_ll(
        params: np.ndarray,
        matches: list[dict],
        elo_snapshots: list[tuple[float, float]],
        rho: float,
    ) -> float:
        mu, alpha = params
        ll = 0.0

        for i, m in enumerate(matches):
            elo_h, elo_a = elo_snapshots[i]
            d_h = (elo_h - elo_a) / 400.0
            d_a = -d_h

            lam_h = math.exp(mu + alpha * d_h)
            lam_a = math.exp(mu + alpha * d_a)

            x = m["home_score"]
            y = m["away_score"]

            p = (poisson.pmf(x, lam_h) *
                 poisson.pmf(y, lam_a) *
                 _dc_correction(x, y, lam_h, lam_a, rho))
            ll += math.log(max(p, 1e-12))

        return -ll

    # ── Public API ────────────────────────────────────────────────────────────

    def fit(
        self,
        min_year: int = 2010,
        verbose: bool = True,
        _matches: list[dict] | None = None,
    ) -> "SoccerModelV2":
        """
        Train on historical international match data.
        Pass _matches to override data loading (for backtests/cross-validation).
        """
        from src.data.soccer_data import load_training_data

        if _matches is not None:
            matches = _matches
        else:
            if verbose:
                print("  [soccer_v2] Loading match data...")
            all_matches = load_training_data()
            matches = [m for m in all_matches if m["year"] >= min_year]

        if not matches:
            raise RuntimeError("No match data loaded — check network or cache.")

        # Sort chronologically so Elo updates are causal
        matches = sorted(matches, key=lambda x: x["date"])

        if verbose:
            print(f"  [soccer_v2] {len(matches):,} matches from {min_year}+. "
                  f"Computing rolling Elo...")

        # Step 1: compute Elo-at-game-time snapshots
        elo_snapshots = self._compute_rolling_elo(matches)

        if verbose:
            print(f"  [soccer_v2] Elo computed for {len(self.elo_ratings)} teams. Fitting μ, α...")

        # Step 2: fit μ and α via MLE
        x0 = np.array([0.3, 1.0])  # sensible starting point
        bounds = [(0.1, 1.5), (0.0, 3.0)]

        result = minimize(
            self._neg_ll,
            x0,
            args=(matches, elo_snapshots, self.rho),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 2000, "ftol": 1e-10},
        )

        self.mu = float(result.x[0])
        self.alpha = float(result.x[1])
        self.fitted_on = matches[-1]["date"]

        if verbose:
            print(f"  [soccer_v2] Fit complete. μ={self.mu:.4f}, α={self.alpha:.4f}, "
                  f"converged={result.success}")
            # Top 10 Elo ratings
            top10 = sorted(self.elo_ratings.items(), key=lambda x: x[1], reverse=True)[:10]
            print("  [soccer_v2] Top 10 Elo ratings:")
            for team, elo in top10:
                print(f"             {team:25s}  Elo={elo:.0f}")

        self._save()
        return self

    def _save(self) -> None:
        MODEL_PATH_V2.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_PATH_V2, "wb") as f:
            pickle.dump({
                "elo_ratings": self.elo_ratings,
                "mu":          self.mu,
                "alpha":       self.alpha,
                "rho":         self.rho,
                "fitted_on":   self.fitted_on.isoformat(),
            }, f)
        print(f"  [soccer_v2] Model saved → {MODEL_PATH_V2}")

    def load(self) -> "SoccerModelV2":
        """Load previously fitted model from disk."""
        if not MODEL_PATH_V2.exists():
            raise FileNotFoundError(
                f"No model at {MODEL_PATH_V2}. Run model.fit() first."
            )
        with open(MODEL_PATH_V2, "rb") as f:
            data = pickle.load(f)
        self.elo_ratings = data["elo_ratings"]
        self.mu          = data["mu"]
        self.alpha       = data["alpha"]
        self.rho         = data.get("rho", self.RHO)
        self.fitted_on   = date.fromisoformat(data["fitted_on"])
        return self

    def get_elo(self, team_name: str) -> float:
        """Return current Elo for a team (default 1500 if unknown)."""
        from src.data.soccer_data import normalize_team_name
        return self.elo_ratings.get(normalize_team_name(team_name), self.DEFAULT_ELO)

    def seed_from_eloratings(self) -> None:
        """
        Fetch live Elo ratings from eloratings.net and overlay onto self.elo_ratings.
        Only updates teams present in ELO_CODE_MAP.
        Falls back silently if fetch fails.
        """
        url = "https://www.eloratings.net/World.tsv"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
        except Exception as e:
            print(f"  [soccer_v2] eloratings.net fetch failed: {e}. Using computed Elo.")
            return

        updated = 0
        for line in lines:
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            code = parts[2].strip()
            try:
                live_elo = float(parts[3].strip())
            except ValueError:
                continue
            team = ELO_CODE_MAP.get(code)
            if team is None:
                continue
            # Always use live eloratings.net Elo when available
            self.elo_ratings[team] = live_elo
            updated += 1

        print(f"  [soccer_v2] Seeded {updated} teams from eloratings.net.")

    def _get_lambdas(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = True,
    ) -> tuple[float, float]:
        """Compute expected goals for each team using fitted μ/α and Elo."""
        from src.data.soccer_data import normalize_team_name
        home_team = normalize_team_name(home_team)
        away_team = normalize_team_name(away_team)

        elo_h = self._elo(home_team)
        elo_a = self._elo(away_team)

        d_h = (elo_h - elo_a) / 400.0
        d_a = -d_h

        # Small home advantage: +50 Elo points ≈ +0.125 d for home team
        # Neutral venue → no adjustment
        if not neutral:
            d_h += 50.0 / 400.0
            d_a -= 50.0 / 400.0

        lam_h = math.exp(self.mu + self.alpha * d_h)
        lam_a = math.exp(self.mu + self.alpha * d_a)
        return lam_h, lam_a

    def score_grid(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = True,
        max_goals: int = MAX_GOALS,
    ) -> np.ndarray:
        """
        Compute P(home=i, away=j) score probability matrix with DC correction.
        Shape: (max_goals+1, max_goals+1).
        """
        lam_h, lam_a = self._get_lambdas(home_team, away_team, neutral)
        grid = np.zeros((max_goals + 1, max_goals + 1))
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                p_ij = poisson.pmf(i, lam_h) * poisson.pmf(j, lam_a)
                tau = _dc_correction(i, j, lam_h, lam_a, self.rho)
                grid[i][j] = p_ij * tau
        total = grid.sum()
        if total > 0:
            grid /= total
        return grid

    def matchup(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = True,
    ) -> dict:
        """
        Compute full market probabilities for a matchup.

        Returns:
            home_win, draw, away_win, btts, over_0_5 … over_4_5,
            home_over_0_5, away_over_0_5, exp_home, exp_away, exp_total,
            home_team, away_team
        """
        grid = self.score_grid(home_team, away_team, neutral=neutral)
        n = grid.shape[0]

        home_win = float(np.tril(grid, -1).sum())
        draw     = float(np.trace(grid))
        away_win = float(np.triu(grid, 1).sum())

        # BTTS
        btts = float(1.0 - grid[0, :].sum() - grid[:, 0].sum() + grid[0, 0])

        # Total goals distribution
        total_dist = np.zeros(n * 2)
        for i in range(n):
            for j in range(n):
                if i + j < len(total_dist):
                    total_dist[i + j] += grid[i, j]

        def p_over(line: float) -> float:
            threshold = int(math.ceil(line + 0.5))
            return float(total_dist[threshold:].sum())

        home_marginal = grid.sum(axis=1)
        away_marginal = grid.sum(axis=0)

        exp_home  = float(sum(i * home_marginal[i] for i in range(n)))
        exp_away  = float(sum(j * away_marginal[j] for j in range(n)))
        exp_total = exp_home + exp_away

        return {
            "home_win":      round(home_win, 4),
            "draw":          round(draw, 4),
            "away_win":      round(away_win, 4),
            "btts":          round(btts, 4),
            "over_0_5":      round(p_over(0.5), 4),
            "over_1_5":      round(p_over(1.5), 4),
            "over_2_5":      round(p_over(2.5), 4),
            "over_3_5":      round(p_over(3.5), 4),
            "over_4_5":      round(p_over(4.5), 4),
            "home_over_0_5": round(float(home_marginal[1:].sum()), 4),
            "away_over_0_5": round(float(away_marginal[1:].sum()), 4),
            "exp_home":      round(exp_home, 3),
            "exp_away":      round(exp_away, 3),
            "exp_total":     round(exp_total, 3),
            "home_team":     home_team,
            "away_team":     away_team,
        }

    def find_edges(
        self,
        events: list[dict],
        min_edge_pct: float = 4.0,
    ) -> list[dict]:
        """
        Find edges against book odds for a list of soccer events.

        events: Odds API format (h2h, totals markets)
        Returns list of edge dicts compatible with pnl schema.
        """
        edges = []
        for event in events:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            neutral = event.get("neutral", True)
            if not home or not away:
                continue

            m = self.matchup(home, away, neutral=neutral)

            for bookmaker in event.get("bookmakers", []):
                book = bookmaker.get("title", "")
                for market in bookmaker.get("markets", []):
                    mkey = market.get("key", "")
                    outcomes = market.get("outcomes", [])

                    if mkey == "h2h":
                        probs = {
                            home:   m["home_win"],
                            away:   m["away_win"],
                            "Draw": m["draw"],
                        }
                        total_imp = sum(
                            _american_to_imp(float(o.get("price", -110)))
                            for o in outcomes
                        )
                        if total_imp <= 0:
                            continue
                        for outcome in outcomes:
                            name  = outcome.get("name", "")
                            price = float(outcome.get("price", 0))
                            if not price or name not in probs:
                                continue
                            imp      = _american_to_imp(price) / total_imp
                            model_p  = probs[name]
                            edge     = (model_p - imp) * 100.0
                            if edge >= min_edge_pct:
                                edges.append({
                                    "sport":        "soccer",
                                    "market":       "moneyline",
                                    "direction":    name,
                                    "team":         name,
                                    "matchup":      f"{away} @ {home}",
                                    "odds":         int(price),
                                    "best_odds":    int(price),
                                    "model_prob":   round(model_p, 4),
                                    "implied_prob": round(imp, 4),
                                    "edge_pct":     round(edge, 2),
                                    "sportsbook":   book,
                                    "exp_total":    m["exp_total"],
                                })

                    elif mkey == "totals":
                        over_o  = next((o for o in outcomes if o.get("name") == "Over"), None)
                        under_o = next((o for o in outcomes if o.get("name") == "Under"), None)
                        if not over_o or not under_o:
                            continue
                        line        = float(over_o.get("point", 2.5))
                        over_price  = float(over_o.get("price", -110))
                        under_price = float(under_o.get("price", -110))
                        total_imp   = (_american_to_imp(over_price) +
                                       _american_to_imp(under_price))
                        if total_imp <= 0:
                            continue
                        imp_over  = _american_to_imp(over_price)  / total_imp
                        imp_under = _american_to_imp(under_price) / total_imp

                        key_str = f"over_{str(line).replace('.', '_')}"
                        model_over = m.get(key_str)
                        if model_over is None:
                            from scipy.stats import poisson as _pois
                            threshold  = int(math.ceil(line + 0.5))
                            model_over = float(1.0 - _pois.cdf(threshold - 1, m["exp_total"]))
                        model_under = 1.0 - model_over

                        for direction, model_p, imp_p, price in [
                            ("OVER",  model_over,  imp_over,  over_price),
                            ("UNDER", model_under, imp_under, under_price),
                        ]:
                            edge = (model_p - imp_p) * 100.0
                            if edge >= min_edge_pct:
                                edges.append({
                                    "sport":        "soccer",
                                    "market":       "total",
                                    "direction":    direction,
                                    "team":         f"{direction} {line}",
                                    "matchup":      f"{away} @ {home}",
                                    "odds":         int(price),
                                    "best_odds":    int(price),
                                    "line":         line,
                                    "model_prob":   round(model_p, 4),
                                    "implied_prob": round(imp_p, 4),
                                    "edge_pct":     round(edge, 2),
                                    "sportsbook":   book,
                                    "exp_total":    m["exp_total"],
                                })

        # Dedup: keep best-odds edge per (matchup, market, direction)
        best: dict[tuple, dict] = {}
        for e in edges:
            key = (e["matchup"], e["market"], e["direction"])
            if key not in best or e["edge_pct"] > best[key]["edge_pct"]:
                best[key] = e
        return sorted(best.values(), key=lambda x: x["edge_pct"], reverse=True)


# ── Convenience ───────────────────────────────────────────────────────────────

def load_or_fit_model_v2(min_year: int = 2010, verbose: bool = True) -> SoccerModelV2:
    """Load model from disk if recent; otherwise re-fit."""
    model = SoccerModelV2()
    if MODEL_PATH_V2.exists():
        model.load()
        age_days = (date.today() - model.fitted_on).days
        if age_days <= 7:
            if verbose:
                print(f"  [soccer_v2] Loaded model (fitted {age_days}d ago).")
            return model
        if verbose:
            print(f"  [soccer_v2] Model is {age_days}d old — re-fitting...")
    else:
        if verbose:
            print("  [soccer_v2] No model found — fitting from scratch...")
    return model.fit(min_year=min_year, verbose=verbose)
