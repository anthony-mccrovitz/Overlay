"""
Dixon-Coles soccer model for international football betting.

Reference: Dixon & Coles (1997), "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market."

Architecture:
  1. Fit team attack (α) and defense (β) parameters via weighted MLE
     using scipy.optimize.minimize on negative log-likelihood.
  2. Apply Dixon-Coles low-score correction (ρ parameter).
  3. Apply time-decay weighting (ξ=0.0065 per day).
  4. Build score probability grid P(home=i, away=j).
  5. Derive all markets from the grid:
     - 1X2 (home/draw/away)
     - Asian handicap
     - Totals (over/under any line)
     - Both teams to score
     - Correct score
     - Team totals

Usage:
    from src.models.soccer_model import SoccerModel
    model = SoccerModel()
    model.fit()                          # trains on historical data
    grid = model.score_grid("France", "Germany", neutral=False)
    probs = model.markets(grid)          # all market probabilities
"""
from __future__ import annotations

import json
import math
import pickle
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MODEL_PATH = Path("data/models/soccer_dixoncoles.pkl")
MAX_GOALS = 10   # P(X > 10) is negligible

# Time-decay half-life: ~107 days. This is the Dixon-Coles recommended value.
# Matches ~3.5 months ago have ~50% weight.
XI = 0.0065


# ─────────────────────────── Dixon-Coles correction ──────────────────────────

def _dc_correction(x: int, y: int, lam_h: float, lam_a: float, rho: float) -> float:
    """
    Dixon-Coles low-score correction factor τ(x, y).
    Adjusts the bivariate independence assumption for 0-0, 1-0, 0-1, 1-1.
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
    return max(tau, 0.0)  # clamp: rho can push correction negative for high-lambda teams


def _neg_log_likelihood(
    params: np.ndarray,
    matches: list[dict],
    team_to_idx: dict[str, int],
    today: date,
) -> float:
    """
    Negative log-likelihood of observed scores given attack/defense/home/rho params.
    Time-weighted so recent matches count more.
    """
    n = len(team_to_idx)
    attack  = params[:n]
    defense = params[n:2*n]
    home_adv = params[-2]
    rho      = params[-1]

    ll = 0.0
    for m in matches:
        days_ago = (today - m["date"]).days
        weight = math.exp(-XI * days_ago)

        hi = team_to_idx.get(m["home_team"])
        ai = team_to_idx.get(m["away_team"])
        if hi is None or ai is None:
            continue

        # Apply home advantage only for non-neutral venues
        home_boost = home_adv if not m.get("neutral", False) else 0.0

        lam_h = math.exp(attack[hi] - defense[ai] + home_boost)
        lam_a = math.exp(attack[ai] - defense[hi])

        x = m["home_score"]
        y = m["away_score"]

        p = (poisson.pmf(x, lam_h) *
             poisson.pmf(y, lam_a) *
             _dc_correction(x, y, lam_h, lam_a, rho))
        ll += weight * math.log(max(p, 1e-12))

    return -ll


# ─────────────────────────── Model class ─────────────────────────────────────

class SoccerModel:
    """
    Dixon-Coles model for international football.

    Attributes after fit():
        teams:       sorted list of team names in the model
        attack:      dict[team → float] — attack strength
        defense:     dict[team → float] — defense weakness (lower = better)
        home_adv:    float — home ground advantage (log scale, ~0.25)
        rho:         float — low-score correction (~-0.10)
        fitted_on:   date of most recent training data
    """

    def __init__(self) -> None:
        self.teams: list[str] = []
        self.attack: dict[str, float] = {}
        self.defense: dict[str, float] = {}
        self.home_adv: float = 0.25
        self.rho: float = -0.10
        self.fitted_on: date | None = None
        self._team_to_idx: dict[str, int] = {}

    def fit(
        self,
        min_year: int = 2010,
        refresh_data: bool = False,
        verbose: bool = True,
    ) -> "SoccerModel":
        """
        Fit Dixon-Coles parameters on historical international match data.
        Saves model to MODEL_PATH.
        """
        from src.data.soccer_data import load_training_data

        if verbose:
            print("  [soccer] Loading match data...")
        all_matches = load_training_data()
        matches = [m for m in all_matches if m["year"] >= min_year]
        if not matches:
            raise RuntimeError("No match data loaded — check network or cache.")
        if verbose:
            print(f"  [soccer] {len(matches):,} competitive matches from {min_year} onward.")

        # Build team universe from matches
        teams_set: set[str] = set()
        for m in matches:
            teams_set.add(m["home_team"])
            teams_set.add(m["away_team"])
        self.teams = sorted(teams_set)
        self._team_to_idx = {t: i for i, t in enumerate(self.teams)}
        n = len(self.teams)
        today = date.today()

        if verbose:
            print(f"  [soccer] {n} teams in model. Fitting...")

        # Initial parameters: attack=0, defense=0, home_adv=0.25, rho=-0.1
        x0 = np.concatenate([
            np.zeros(n),     # attack (log scale, constraint: sum=0 via normalization)
            np.zeros(n),     # defense
            [0.25, -0.10],   # home_adv, rho
        ])

        # Bounds: attack/defense [-3,3], home_adv [-1,1], rho (-0.25, 0.1)
        # rho in Dixon-Coles is typically -0.13. With max attack ~+1.2 (lam≈3.3),
        # we need rho > -0.30 to keep all DC corrections non-negative.
        atk_def_bounds = [(-3.0, 3.0)] * (2 * n)
        extra_bounds   = [(-1.0, 1.0), (-0.25, 0.1)]
        bounds = atk_def_bounds + extra_bounds

        result = minimize(
            _neg_log_likelihood,
            x0,
            args=(matches, self._team_to_idx, today),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 2000, "ftol": 1e-10},
        )

        params = result.x
        attack_raw  = params[:n]
        defense_raw = params[n:2*n]
        home_adv    = params[-2]
        rho         = params[-1]

        # Normalize: subtract mean so attack parameters are centered
        attack_mean  = attack_raw.mean()
        defense_mean = defense_raw.mean()
        attack_raw  -= attack_mean
        defense_raw -= defense_mean

        self.attack    = {t: float(attack_raw[i])  for t, i in self._team_to_idx.items()}
        self.defense   = {t: float(defense_raw[i]) for t, i in self._team_to_idx.items()}
        self.home_adv  = float(home_adv)
        self.rho       = float(rho)
        self.fitted_on = today

        if verbose:
            print(f"  [soccer] Fit complete. home_adv={self.home_adv:.3f}, rho={self.rho:.3f}")
            # Top 10 attack ratings
            top_attack = sorted(self.attack.items(), key=lambda x: x[1], reverse=True)[:10]
            print("  [soccer] Top 10 attack ratings:")
            for team, val in top_attack:
                print(f"           {team:25s}  atk={val:+.3f}  def={self.defense[team]:+.3f}")

        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({
                "teams":       self.teams,
                "attack":      self.attack,
                "defense":     self.defense,
                "home_adv":    self.home_adv,
                "rho":         self.rho,
                "fitted_on":   self.fitted_on.isoformat(),
            }, f)
        print(f"  [soccer] Model saved → {MODEL_PATH}")
        return self

    def load(self) -> "SoccerModel":
        """Load a previously fitted model from disk."""
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"No model at {MODEL_PATH}. Run model.fit() first.")
        with open(MODEL_PATH, "rb") as f:
            data = pickle.load(f)
        self.teams      = data["teams"]
        self.attack     = data["attack"]
        self.defense    = data["defense"]
        self.home_adv   = data["home_adv"]
        self.rho        = data["rho"]
        self.fitted_on  = date.fromisoformat(data["fitted_on"])
        self._team_to_idx = {t: i for i, t in enumerate(self.teams)}
        return self

    def _get_lambdas(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = False,
    ) -> tuple[float, float]:
        """Return (lambda_home, lambda_away) — expected goals for each team."""
        from src.data.soccer_data import normalize_team_name
        home_team = normalize_team_name(home_team)
        away_team = normalize_team_name(away_team)
        # Unknown teams: use mean parameters (equivalent to an average team)
        atk_h = self.attack.get(home_team, 0.0)
        def_h = self.defense.get(home_team, 0.0)
        atk_a = self.attack.get(away_team, 0.0)
        def_a = self.defense.get(away_team, 0.0)

        home_boost = self.home_adv if not neutral else 0.0
        lam_h = math.exp(atk_h - def_a + home_boost)
        lam_a = math.exp(atk_a - def_h)
        return lam_h, lam_a

    def score_grid(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = False,
        max_goals: int = MAX_GOALS,
    ) -> np.ndarray:
        """
        Compute P(home=i, away=j) score probability matrix.

        Shape: (max_goals+1, max_goals+1)
        grid[i][j] = P(home scores i, away scores j)
        """
        lam_h, lam_a = self._get_lambdas(home_team, away_team, neutral)
        grid = np.zeros((max_goals + 1, max_goals + 1))
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                p_ij = poisson.pmf(i, lam_h) * poisson.pmf(j, lam_a)
                tau = _dc_correction(i, j, lam_h, lam_a, self.rho)
                grid[i][j] = p_ij * tau
        # Normalize (correction breaks summing to 1 slightly)
        total = grid.sum()
        if total > 0:
            grid /= total
        return grid

    def markets(
        self,
        grid: np.ndarray,
        home_team: str = "",
        away_team: str = "",
    ) -> dict:
        """
        Derive all standard markets from a score probability grid.

        Returns:
            home_win:   P(home wins)
            draw:       P(draw)
            away_win:   P(away wins)
            btts:       P(both teams score ≥1)
            over_0_5:   P(total goals ≥1)
            over_1_5:   P(total goals ≥2)
            over_2_5:   P(total goals ≥3)
            over_3_5:   P(total goals ≥4)
            home_over_0_5: P(home scores ≥1)
            away_over_0_5: P(away scores ≥1)
            exp_home:   expected home goals
            exp_away:   expected away goals
            exp_total:  expected total goals
        """
        n = grid.shape[0]
        home_win = float(np.tril(grid, -1).sum())
        draw     = float(np.trace(grid))
        away_win = float(np.triu(grid, 1).sum())

        # BTTS: both score at least 1
        btts = float(1 - grid[0, :].sum() - grid[:, 0].sum() + grid[0, 0])

        # Totals: P(home+away >= N+0.5)
        total_grid = np.zeros(n * 2)
        for i in range(n):
            for j in range(n):
                if i + j < len(total_grid):
                    total_grid[i + j] += grid[i, j]

        def p_over(line: float) -> float:
            threshold = int(math.ceil(line + 0.5))
            return float(total_grid[threshold:].sum())

        # Team totals
        home_marginal = grid.sum(axis=1)  # P(home=i)
        away_marginal = grid.sum(axis=0)  # P(away=j)

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

    def matchup(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = False,
    ) -> dict:
        """One-shot: compute grid + all markets for a matchup."""
        grid = self.score_grid(home_team, away_team, neutral=neutral)
        return self.markets(grid, home_team=home_team, away_team=away_team)

    def find_edges(
        self,
        events: list[dict],
        min_edge_pct: float = 4.0,
    ) -> list[dict]:
        """
        Find edges against book odds for a list of soccer events.

        events: same Odds API format as NBA/MLB (h2h, spreads, totals markets)
        Returns list of edge dicts compatible with pnl schema.
        """
        edges = []
        for event in events:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            # WC/international tournaments are at neutral venues; Odds API doesn't flag this
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
                            home: m["home_win"],
                            away: m["away_win"],
                            "Draw": m["draw"],
                        }
                        for outcome in outcomes:
                            name = outcome.get("name", "")
                            price = float(outcome.get("price", 0))
                            if not price or name not in probs:
                                continue
                            # De-vig: use multiplicative (3-way market)
                            total_imp = sum(
                                _american_to_imp(float(o.get("price", -110)))
                                for o in outcomes
                            )
                            imp = _american_to_imp(price) / total_imp
                            model_p = probs[name]
                            edge = (model_p - imp) * 100
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
                        over_o = next((o for o in outcomes if o.get("name") == "Over"), None)
                        under_o = next((o for o in outcomes if o.get("name") == "Under"), None)
                        if not over_o or not under_o:
                            continue
                        line = float(over_o.get("point", 2.5))
                        over_price = float(over_o.get("price", -110))
                        under_price = float(under_o.get("price", -110))
                        total_imp = _american_to_imp(over_price) + _american_to_imp(under_price)
                        imp_over = _american_to_imp(over_price) / total_imp
                        imp_under = _american_to_imp(under_price) / total_imp

                        model_over  = m.get(f"over_{str(line).replace('.', '_')}", None)
                        if model_over is None:
                            # Compute directly from exp_total
                            from scipy.stats import poisson as _pois
                            mu = m["exp_total"]
                            threshold = int(math.ceil(line + 0.5))
                            model_over = float(1 - _pois.cdf(threshold - 1, mu))
                        model_under = 1.0 - model_over

                        for direction, model_p, imp_p, price in [
                            ("OVER",  model_over,  imp_over,  over_price),
                            ("UNDER", model_under, imp_under, under_price),
                        ]:
                            edge = (model_p - imp_p) * 100
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
        deduped = sorted(best.values(), key=lambda x: x["edge_pct"], reverse=True)
        return deduped


def _american_to_imp(o: float) -> float:
    if o >= 0:
        return 100 / (o + 100)
    return abs(o) / (abs(o) + 100)


# ─────────────────────────── Convenience ─────────────────────────────────────

def load_or_fit_model(min_year: int = 2010, verbose: bool = True) -> SoccerModel:
    """Load model from disk if recent; otherwise re-fit."""
    model = SoccerModel()
    if MODEL_PATH.exists():
        model.load()
        age_days = (date.today() - model.fitted_on).days
        if age_days <= 7:
            if verbose:
                print(f"  [soccer] Loaded model (fitted {age_days}d ago).")
            return model
        if verbose:
            print(f"  [soccer] Model is {age_days}d old — re-fitting...")
    else:
        if verbose:
            print("  [soccer] No model found — fitting from scratch...")
    return model.fit(min_year=min_year, verbose=verbose)
