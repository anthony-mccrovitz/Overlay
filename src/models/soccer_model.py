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
OVER_BIAS_CORRECTION = 0.04   # books shade totals; OVERs underperform empirically
MIN_IMPLIED_PROB = 0.25        # skip picks at odds better than +300 — model unreliable

# Time-decay half-life: ~107 days. This is the Dixon-Coles recommended value.
# Matches ~3.5 months ago have ~50% weight.
XI = 0.0065


# ─────────────────────────── Dixon-Coles correction ──────────────────────────

def _dc_correction(x: int, y: int, lam_h: float, lam_a: float, rho: float) -> float:
    """DC low-score correction factor τ(x,y) — used by score_grid for market derivation."""
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


def _preprocess_matches(
    matches: list[dict],
    team_to_idx: dict[str, int],
    today: date,
    elo_ratings: dict[str, float] | None = None,
) -> dict:
    """
    Convert match list to numpy arrays once so the vectorized log-likelihood
    doesn't re-parse dicts on every optimizer call. Filters out unknown teams.

    If elo_ratings is provided, each match's time-decay weight is multiplied by
    a quality factor = (avg_elo / 1500)^2 — France vs Germany (~2000 avg) counts
    ~1.78x more than Japan vs Bahrain (~1580 avg). This corrects DC's blind spot
    where it can't distinguish opponent quality from raw scores alone.
    """
    valid_home, valid_away, valid_hs, valid_as = [], [], [], []
    valid_weights, valid_neutral = [], []
    ELO_BASE = 1500.0

    for m in matches:
        hi = team_to_idx.get(m["home_team"])
        ai = team_to_idx.get(m["away_team"])
        if hi is None or ai is None:
            continue
        days_ago = (today - m["date"]).days
        time_weight = math.exp(-XI * days_ago)
        if elo_ratings:
            elo_h = elo_ratings.get(m["home_team"], ELO_BASE)
            elo_a = elo_ratings.get(m["away_team"], ELO_BASE)
            avg_elo = (elo_h + elo_a) / 2.0
            quality = min(2.5, max(0.1, (avg_elo / ELO_BASE) ** 2))
        else:
            quality = 1.0
        valid_home.append(hi)
        valid_away.append(ai)
        valid_hs.append(m["home_score"])
        valid_as.append(m["away_score"])
        valid_weights.append(time_weight * quality)
        valid_neutral.append(bool(m.get("neutral", False)))

    return {
        "hi":      np.array(valid_home,    dtype=np.int32),
        "ai":      np.array(valid_away,    dtype=np.int32),
        "hs":      np.array(valid_hs,      dtype=np.int32),
        "as_":     np.array(valid_as,      dtype=np.int32),
        "weights": np.array(valid_weights, dtype=np.float64),
        "neutral": np.array(valid_neutral, dtype=bool),
    }


def _neg_log_likelihood(
    params: np.ndarray,
    data: dict,
    n_teams: int,
) -> float:
    """
    Vectorised negative log-likelihood (numpy). ~50-100x faster than the
    Python-loop version. `data` is the dict from _preprocess_matches().
    """
    attack   = params[:n_teams]
    defense  = params[n_teams:2 * n_teams]
    home_adv = params[-2]
    rho      = params[-1]

    hi, ai = data["hi"], data["ai"]
    hs, as_ = data["hs"], data["as_"]
    w = data["weights"]

    home_boost = np.where(data["neutral"], 0.0, home_adv)
    lam_h = np.exp(attack[hi] - defense[ai] + home_boost)
    lam_a = np.exp(attack[ai] - defense[hi])

    # Dixon-Coles low-score correction (vectorised over all 4 cases)
    tau = np.ones(len(hs))
    m00 = (hs == 0) & (as_ == 0)
    m01 = (hs == 0) & (as_ == 1)
    m10 = (hs == 1) & (as_ == 0)
    m11 = (hs == 1) & (as_ == 1)
    tau[m00] = np.maximum(1 - lam_h[m00] * lam_a[m00] * rho, 1e-10)
    tau[m01] = np.maximum(1 + lam_h[m01] * rho, 1e-10)
    tau[m10] = np.maximum(1 + lam_a[m10] * rho, 1e-10)
    tau[m11] = np.maximum(1 - rho, 1e-10)

    log_ll = (
        poisson.logpmf(hs, lam_h)
        + poisson.logpmf(as_, lam_a)
        + np.log(tau)
    )
    return -float(w @ log_ll)


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
        min_year: int = 2020,
        min_elo: float = 0.0,
        refresh_data: bool = False,
        verbose: bool = True,
        _matches: list[dict] | None = None,
    ) -> "SoccerModel":
        """
        Fit Dixon-Coles parameters on historical international match data.
        Saves model to MODEL_PATH. Pass _matches to override data loading (for backtests).

        min_year=2020 by default: DC time-decay (XI=0.0065) gives matches
        older than ~2 years weight <0.001, so going back further wastes
        optimizer time without meaningfully changing parameters. Elo ratings
        (used as shrinkage prior) are computed from full history back to 2000.
        """
        from src.data.soccer_data import load_training_data

        if _matches is not None:
            matches = _matches
        else:
            if verbose:
                print("  [soccer] Loading match data...")
            matches = load_training_data(min_year=min_year)
        if not matches:
            raise RuntimeError("No match data loaded — check network or cache.")
        if verbose:
            print(f"  [soccer] {len(matches):,} competitive matches from {min_year} onward.")

        # Load Elo ratings once — used for min_elo filtering, quality weighting,
        # and shrinkage prior. Loaded here so all three steps share the same data.
        elo_ratings: dict[str, float] = {}
        try:
            from src.data.soccer_data import get_elo_ratings
            elo_ratings = get_elo_ratings()
            if verbose:
                print(f"  [soccer] Elo ratings loaded ({len(elo_ratings)} teams).")
        except Exception as exc:
            if verbose:
                print(f"  [soccer] Elo load failed: {exc}")

        # Filter training data to matches where both teams have meaningful Elo ratings.
        # min_elo=1650 excludes weak qualifier-zone fodder (Bahrain, Guam, etc.) that
        # inflates strong teams' DC attack parameters without providing useful signal.
        if min_elo > 0 and elo_ratings:
            pre_filter = len(matches)
            matches = [
                m for m in matches
                if elo_ratings.get(m["home_team"], 0) >= min_elo
                and elo_ratings.get(m["away_team"], 0) >= min_elo
            ]
            if verbose:
                print(f"  [soccer] Elo filter (≥{min_elo:.0f}): {pre_filter:,} → {len(matches):,} matches")
            if not matches:
                raise RuntimeError(f"No matches remain after Elo filter (min_elo={min_elo}). Lower the threshold.")

        # Build team universe — only include teams with enough matches to
        # get reliable parameter estimates. Teams with <MIN_TEAM_MATCHES
        # get mean parameters (equivalent to an average-strength team).
        MIN_TEAM_MATCHES = 5
        team_counts: dict[str, int] = {}
        for m in matches:
            team_counts[m["home_team"]] = team_counts.get(m["home_team"], 0) + 1
            team_counts[m["away_team"]] = team_counts.get(m["away_team"], 0) + 1
        teams_set = {t for t, cnt in team_counts.items() if cnt >= MIN_TEAM_MATCHES}
        self.teams = sorted(teams_set)
        self._team_to_idx = {t: i for i, t in enumerate(self.teams)}
        n = len(self.teams)
        today = date.today()

        if verbose:
            skipped = len(team_counts) - len(teams_set)
            print(f"  [soccer] {n} teams in model ({skipped} skipped, <{MIN_TEAM_MATCHES} matches). Fitting...")

        # Pre-convert match list to numpy arrays so the optimizer doesn't
        # re-parse Python dicts on every function call (50-100x speedup).
        data = _preprocess_matches(matches, self._team_to_idx, today, elo_ratings=elo_ratings or None)
        if verbose:
            print(f"  [soccer] {len(data['hi'])} match rows after filtering to known teams.")

        # Initial parameters: attack=0, defense=0, home_adv=0.25, rho=-0.1
        x0 = np.concatenate([
            np.zeros(n),     # attack (log scale, constraint: sum=0 via normalization)
            np.zeros(n),     # defense
            [0.25, -0.10],   # home_adv, rho
        ])

        atk_def_bounds = [(-3.0, 3.0)] * (2 * n)
        extra_bounds   = [(-1.0, 1.0), (-0.25, 0.1)]
        bounds = atk_def_bounds + extra_bounds

        result = minimize(
            _neg_log_likelihood,
            x0,
            args=(data, n),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 1000, "ftol": 1e-8},
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

        # ── Elo shrinkage prior ───────────────────────────────────────────────
        # For teams with few competitive matches, DC parameters have high
        # uncertainty. Shrink toward Elo-implied strength so e.g. Morocco and
        # Senegal aren't treated as average teams just because they have 20
        # matches in training vs France's 60.
        try:
            from src.data.soccer_data import normalize_team_name
            if not elo_ratings:
                raise ValueError("No Elo ratings available")
            # SHRINK_K=150: DC only contributes ~30% for a team with 60 games.
            # This is aggressive but necessary because DC trained on qualifiers
            # can't see opponent quality — Japan beating Bahrain 6-0 looks the
            # same as France beating Germany 2-0. Elo (trained on all matches
            # since 2000) knows the difference.
            # ELO_SCALE=400: amplifies Elo spread so elite teams (Elo ~2100)
            # get a strong positive prior vs average teams (Elo ~1600).
            SHRINK_K = 150
            ELO_BASE = 1500.0
            ELO_SCALE = 400.0  # 200-pt Elo gap → +0.5 attack diff

            for team in self.teams:
                elo = elo_ratings.get(team) or elo_ratings.get(normalize_team_name(team))
                if elo is None:
                    continue
                # In lam = exp(attack - defense): higher defense → fewer goals against → stronger defense
                # So strong teams (high Elo) should get POSITIVE defense values.
                elo_attack  = (elo - ELO_BASE) / ELO_SCALE
                elo_defense = (elo - ELO_BASE) / ELO_SCALE
                n_games = team_counts.get(team, 0)
                alpha = n_games / (n_games + SHRINK_K)   # → 1 as n_games → ∞
                self.attack[team]  = alpha * self.attack[team]  + (1 - alpha) * elo_attack
                self.defense[team] = alpha * self.defense[team] + (1 - alpha) * elo_defense

            if verbose:
                print(f"  [soccer] Elo shrinkage applied (K={SHRINK_K}, {len(elo_ratings)} teams in Elo table).")
        except Exception as exc:
            if verbose:
                print(f"  [soccer] Elo shrinkage skipped: {exc}")

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

            grid = self.score_grid(home, away, neutral=neutral)
            m = self.markets(grid, home_team=home, away_team=away)

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

                        model_over = max(0.01, model_over - OVER_BIAS_CORRECTION)
                        model_under = 1.0 - model_over

                        for direction, model_p, imp_p, price in [
                            ("OVER",  model_over,  imp_over,  over_price),
                            ("UNDER", model_under, imp_under, under_price),
                        ]:
                            if imp_p < MIN_IMPLIED_PROB:
                                continue
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

                    elif mkey == "btts":
                        yes_o = next((o for o in outcomes if o.get("name") in ("Yes", "yes")), None)
                        no_o  = next((o for o in outcomes if o.get("name") in ("No", "no")), None)
                        if not yes_o or not no_o:
                            continue
                        yes_price = float(yes_o.get("price", -110))
                        no_price  = float(no_o.get("price", -110))
                        total_imp = _american_to_imp(yes_price) + _american_to_imp(no_price)
                        imp_yes   = _american_to_imp(yes_price) / total_imp
                        imp_no    = _american_to_imp(no_price)  / total_imp
                        model_yes = m["btts"]
                        model_no  = 1.0 - model_yes
                        for direction, model_p, imp_p, price in [
                            ("YES", model_yes, imp_yes, yes_price),
                            ("NO",  model_no,  imp_no,  no_price),
                        ]:
                            if imp_p < MIN_IMPLIED_PROB:
                                continue
                            edge = (model_p - imp_p) * 100
                            if edge >= min_edge_pct:
                                edges.append({
                                    "sport":        "soccer",
                                    "market":       "btts",
                                    "direction":    direction,
                                    "team":         f"BTTS {direction}",
                                    "matchup":      f"{away} @ {home}",
                                    "odds":         int(price),
                                    "best_odds":    int(price),
                                    "line":         None,
                                    "model_prob":   round(model_p, 4),
                                    "implied_prob": round(imp_p, 4),
                                    "edge_pct":     round(edge, 2),
                                    "sportsbook":   book,
                                    "exp_total":    m["exp_total"],
                                })

                    elif mkey == "asian_handicap":
                        for outcome in outcomes:
                            name  = outcome.get("name", "")
                            price = float(outcome.get("price", -110))
                            point = outcome.get("point")
                            if point is None:
                                continue
                            handicap = float(point)
                            side = "home" if _team_match_simple(name, home) else "away"
                            model_p = _asian_handicap_prob(grid, handicap, side)
                            imp_raw = _american_to_imp(price)
                            counterpart = next((o for o in outcomes if o.get("name") != name), None)
                            if counterpart:
                                total_imp = imp_raw + _american_to_imp(float(counterpart.get("price", -110)))
                                imp_p = imp_raw / total_imp
                            else:
                                imp_p = imp_raw
                            if imp_p < MIN_IMPLIED_PROB:
                                continue
                            edge = (model_p - imp_p) * 100
                            if edge >= min_edge_pct:
                                edges.append({
                                    "sport":        "soccer",
                                    "market":       "asian_handicap",
                                    "direction":    f"{name} {handicap:+.2f}",
                                    "team":         name,
                                    "matchup":      f"{away} @ {home}",
                                    "odds":         int(price),
                                    "best_odds":    int(price),
                                    "line":         handicap,
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


class EloSoccerModel(SoccerModel):
    """
    Pure Elo-based soccer model. Bypasses DC parameter estimation entirely.
    Expected goals derived directly from Elo rating differentials — Elo inherently
    accounts for opponent quality (France beating Germany >>> Japan beating Bahrain).

    Calibration: GOALS_BASE=1.2 (avg goals/team), ELO_SCALE=0.00128 so a
    200-point Elo gap yields a 1.29x per-team goal ratio (realistic for WC matchups).
    Inherits score_grid(), markets(), matchup(), and find_edges() from SoccerModel
    via polymorphism on _get_lambdas().
    """
    GOALS_BASE     = 1.2
    ELO_SCALE      = 0.00128   # 200pt gap → exp(0.256) ≈ 1.29x goal ratio per team
    HOME_ELO_BONUS = 50        # ~equivalent to home-field in Elo terms

    def __init__(self) -> None:
        super().__init__()
        self._elo_ratings: dict[str, float] = {}

    def fit(  # type: ignore[override]
        self,
        min_year: int = 2020,
        verbose: bool = True,
        **kwargs,
    ) -> "EloSoccerModel":
        from src.data.soccer_data import get_elo_ratings
        if verbose:
            print("  [elo_model] Loading Elo ratings...")
        self._elo_ratings = get_elo_ratings()
        self.teams        = sorted(self._elo_ratings.keys())
        self._team_to_idx = {t: i for i, t in enumerate(self.teams)}
        self.home_adv     = float(self.HOME_ELO_BONUS)
        self.rho          = -0.10
        self.fitted_on    = date.today()
        if verbose:
            print(f"  [elo_model] Elo ratings loaded for {len(self.teams)} teams.")
        return self

    def _get_lambdas(self, home_team: str, away_team: str, neutral: bool = False) -> tuple[float, float]:
        from src.data.soccer_data import normalize_team_name
        home_team = normalize_team_name(home_team)
        away_team = normalize_team_name(away_team)
        elo_h = self._elo_ratings.get(home_team, 1500.0)
        elo_a = self._elo_ratings.get(away_team, 1500.0)
        bonus = self.HOME_ELO_BONUS if not neutral else 0.0
        delta = (elo_h + bonus) - elo_a
        lam_h = self.GOALS_BASE * math.exp( delta * self.ELO_SCALE)
        lam_a = self.GOALS_BASE * math.exp(-delta * self.ELO_SCALE)
        return lam_h, lam_a


class EnsembleSoccerModel(SoccerModel):
    """
    Ensemble: blends Dixon-Coles score grid with Elo score grid.

    DC captures recent form and exact score distributions; Elo captures long-run
    strength with implicit opponent-quality adjustment. dc_weight=0.35 means
    Elo drives 65% of the prediction — corrects DC's qualifier blind spot while
    retaining DC's superior score distribution shape.

    Inherits markets(), matchup(), and find_edges() from SoccerModel.
    score_grid() is overridden to blend the two underlying model grids.
    """

    def __init__(self, dc_weight: float = 0.35) -> None:
        super().__init__()
        self._dc_model  = SoccerModel()
        self._elo_model = EloSoccerModel()
        self.dc_weight  = dc_weight

    def fit(  # type: ignore[override]
        self,
        min_year: int = 2020,
        min_elo: float = 1650,
        verbose: bool = True,
        **kwargs,
    ) -> "EnsembleSoccerModel":
        self._dc_model.fit(min_year=min_year, min_elo=min_elo, verbose=verbose)
        self._elo_model.fit(verbose=verbose)
        # Expose DC model state so inherited helpers (matchup, find_edges) work
        self.teams        = self._dc_model.teams
        self.attack       = self._dc_model.attack    # for external team-presence checks
        self.defense      = self._dc_model.defense
        self.home_adv     = self._dc_model.home_adv
        self.rho          = self._dc_model.rho
        self.fitted_on    = self._dc_model.fitted_on
        self._team_to_idx = self._dc_model._team_to_idx
        return self

    def score_grid(  # type: ignore[override]
        self,
        home_team: str,
        away_team: str,
        neutral: bool = False,
        max_goals: int = MAX_GOALS,
    ) -> np.ndarray:
        dc_g  = self._dc_model.score_grid(home_team, away_team, neutral=neutral, max_goals=max_goals)
        elo_g = self._elo_model.score_grid(home_team, away_team, neutral=neutral, max_goals=max_goals)
        blended = self.dc_weight * dc_g + (1.0 - self.dc_weight) * elo_g
        total = blended.sum()
        if total > 0:
            blended /= total
        return blended


def _american_to_imp(o: float) -> float:
    if o >= 0:
        return 100 / (o + 100)
    return abs(o) / (abs(o) + 100)


def _team_match_simple(a: str, b: str) -> bool:
    """Loose team name match for market side detection."""
    na = (a or "").lower().strip()
    nb = (b or "").lower().strip()
    return na == nb or na in nb or nb in na


def _asian_handicap_prob(grid: np.ndarray, handicap: float, side: str) -> float:
    """
    Compute P(bet wins) for an Asian handicap line from the score grid.

    handicap: line applied to the team (e.g., -1.5 means team gives 1.5 goals)
    side: "home" or "away"

    Handles whole-ball (push), half-ball (binary), quarter-ball (split into two adjacent lines).
    Returns P(win) excluding pushes. For quarter-ball: average of the two adjacent probs.
    """
    n = grid.shape[0]
    # Normalise sign: work from home perspective
    h = handicap if side == "home" else -handicap

    def _prob_for_line(line: float) -> float:
        p_win = p_push = 0.0
        for i in range(n):
            for j in range(n):
                margin = (i - j) + line   # positive = home covers
                if margin > 0:
                    p_win += grid[i, j]
                elif margin == 0:
                    p_push += grid[i, j]
        denom = 1.0 - p_push
        return p_win / denom if denom > 0.01 else 0.5

    # Quarter-ball: split into two adjacent half/whole lines
    frac = abs(h) % 0.5
    if abs(frac - 0.25) < 0.01:
        sign = 1 if h >= 0 else -1
        p1 = _prob_for_line(h - 0.25 * sign)
        p2 = _prob_for_line(h + 0.25 * sign)
        return (p1 + p2) / 2.0

    return _prob_for_line(h)


# ─────────────────────────── Convenience ─────────────────────────────────────

def load_or_fit_model(
    min_year: int = 2020,
    min_elo: float = 1650,
    use_ensemble: bool = True,
    verbose: bool = True,
) -> SoccerModel:
    """
    Load DC model from disk if recent; build EnsembleSoccerModel on top.
    use_ensemble=True (default): returns EnsembleSoccerModel (DC + Elo blend).
    use_ensemble=False: returns raw SoccerModel (DC only) for backtests.
    """
    dc = SoccerModel()
    if MODEL_PATH.exists():
        dc.load()
        age_days = (date.today() - dc.fitted_on).days
        if age_days <= 7:
            if verbose:
                print(f"  [soccer] Loaded DC model (fitted {age_days}d ago).")
            if use_ensemble:
                ens = EnsembleSoccerModel()
                ens._dc_model = dc
                ens._elo_model = EloSoccerModel().fit(verbose=verbose)
                ens.teams        = dc.teams
                ens.attack       = dc.attack
                ens.defense      = dc.defense
                ens.home_adv     = dc.home_adv
                ens.rho          = dc.rho
                ens.fitted_on    = dc.fitted_on
                ens._team_to_idx = dc._team_to_idx
                return ens
            return dc
        if verbose:
            print(f"  [soccer] Model is {age_days}d old — re-fitting...")
    else:
        if verbose:
            print("  [soccer] No model found — fitting from scratch...")
    if use_ensemble:
        return EnsembleSoccerModel().fit(min_year=min_year, min_elo=min_elo, verbose=verbose)
    return dc.fit(min_year=min_year, min_elo=min_elo, verbose=verbose)
