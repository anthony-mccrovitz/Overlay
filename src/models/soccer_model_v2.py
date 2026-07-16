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

import json
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
# Last-good eloratings.net snapshot — reused on fetch failure so same-day pick
# runs are reproducible instead of diverging onto computed Elo (see
# SoccerModelV2.seed_from_eloratings).
ELO_SNAPSHOT_PATH = Path("data/models/eloratings_snapshot.json")

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
    AD_DECAY = 0.12   # EWMA weight for rolling attack/defense (recent form)
    HOST_BONUS = 60.0  # Elo-equivalent home edge for 2026 co-hosts at home venues
    # Calibration temperature (<1 sharpens, >1 softens) on the 1X2 probs. The
    # walk-forward favorite-calibration on 852 tournament matches showed the
    # model UNDER-confident on the favorite (actual hit-rate > predicted in
    # every bin) — so it needs SHARPENING, not softening. T=0.85 is the optimum
    # from scripts/calibrate_soccer_1x2.py (min pooled 1X2 log loss): it cut
    # Brier 0.3039 → 0.3011 vs the old 1.25. The remaining gap to a sharp book
    # (~0.28) is RESOLUTION, not calibration — it needs new signal (xG, lineups,
    # rest), which temperature scaling cannot manufacture.
    CALIBRATION_T = 0.85
    # Tempo shrinkage (0..1) on the rolling attack/defense terms (β, δ). The
    # MLE fits β, δ to in-sample recent-form signal, but they over-swing the
    # expected total out-of-sample (exp_total ranged 1.76–3.39 across one WC
    # slate, manufacturing phantom ±30% totals edges). Shrinking them toward 0
    # pulls exp_total back to the μ+α baseline the market agrees with. Value is
    # the walk-forward optimum from scripts/calibrate_soccer_totals.py (min
    # pooled O/U-2.5 Brier across all tournament instances since 2006): s=0.2
    # cut O/U Brier 0.2613→0.2514 and the exp_total swing (σ) by 66%, more than
    # halving over-2.5 ECE (0.091→0.035). Raw β,δ (s=1.0) scored WORSE than the
    # 0.25 naive base rate — i.e. the un-shrunk totals model subtracted value.
    TEMPO_SHRINK = 0.20

    def __init__(self) -> None:
        self.elo_ratings: dict[str, float] = {}
        # Rolling attack (goals scored) / defense (goals conceded) tendencies.
        # Captured causally like Elo; feed the goals/tempo side of the model.
        self.atk_ratings: dict[str, float] = {}
        self.dfn_ratings: dict[str, float] = {}
        self.league_avg: float = 1.30   # avg goals per team per game (refit)
        self.mu: float = 0.0
        self.alpha: float = 1.0
        self.beta: float = 0.0    # own-attack coefficient (goals/tempo)
        self.delta: float = 0.0   # opponent-leak coefficient (goals/tempo)
        self.rho: float = self.RHO
        self.temperature: float = 1.0   # calibration: >1 softens overconfidence
        self.tempo_shrink: float = self.TEMPO_SHRINK  # shrink β,δ toward 0
        self.fitted_on: date | None = None

    # ── Name normalization (overridable) ──────────────────────────────────────

    def _normalize(self, name: str) -> str:
        """Map an external team name onto the canonical form the model is keyed
        on. Base = international national-team aliases. Club subclasses override
        this with their own league roster aliases."""
        from src.data.soccer_data import normalize_team_name
        return normalize_team_name(name)

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

    def _compute_rolling_elo(self, matches: list[dict]) -> list[tuple]:
        """
        Sequentially update Elo AND rolling attack/defense from all matches.
        Returns a list of per-match snapshots taken BEFORE each match, so the
        fit only ever sees information available at game time:
            (elo_h, elo_a, atk_h, dfn_a, atk_a, dfn_h)
        atk = rolling goals scored, dfn = rolling goals conceded (EWMA).
        """
        self.elo_ratings = {}
        self.atk_ratings = {}
        self.dfn_ratings = {}

        # League average goals/team/game — used to centre the attack/defense
        # features so β, δ ≈ 0 means "no tempo signal".
        scored = [m["home_score"] + m["away_score"] for m in matches]
        self.league_avg = (sum(scored) / (2 * len(scored))) if scored else 1.30
        avg = self.league_avg
        decay = self.AD_DECAY

        snapshots: list[tuple] = []

        for m in sorted(matches, key=lambda x: x["date"]):
            home, away = m["home_team"], m["away_team"]
            x, y = m["home_score"], m["away_score"]

            elo_h, elo_a = self._elo(home), self._elo(away)
            atk_h = self.atk_ratings.get(home, avg)
            dfn_h = self.dfn_ratings.get(home, avg)
            atk_a = self.atk_ratings.get(away, avg)
            dfn_a = self.dfn_ratings.get(away, avg)
            snapshots.append((elo_h, elo_a, atk_h, dfn_a, atk_a, dfn_h))

            # Elo update
            self._update_elo(home, away, x, y, _k_factor(m.get("tournament", "")))

            # Rolling attack/defense (EWMA toward the goals just observed)
            self.atk_ratings[home] = (1 - decay) * atk_h + decay * x
            self.dfn_ratings[home] = (1 - decay) * dfn_h + decay * y
            self.atk_ratings[away] = (1 - decay) * atk_a + decay * y
            self.dfn_ratings[away] = (1 - decay) * dfn_a + decay * x

        return snapshots

    # ── Negative log-likelihood ───────────────────────────────────────────────

    @staticmethod
    def _neg_ll(
        params: np.ndarray,
        matches: list[dict],
        snapshots: list[tuple],
        rho: float,
        avg: float,
    ) -> float:
        mu, alpha, beta, delta = params
        ll = 0.0

        for i, m in enumerate(matches):
            elo_h, elo_a, atk_h, dfn_a, atk_a, dfn_h = snapshots[i]
            d_h = (elo_h - elo_a) / 400.0

            la_h = math.log(max(atk_h, 0.05) / avg)
            lc_a = math.log(max(dfn_a, 0.05) / avg)
            la_a = math.log(max(atk_a, 0.05) / avg)
            lc_h = math.log(max(dfn_h, 0.05) / avg)

            lam_h = math.exp(mu + alpha * d_h + beta * la_h + delta * lc_a)
            lam_a = math.exp(mu - alpha * d_h + beta * la_a + delta * lc_h)

            x = m["home_score"]
            y = m["away_score"]

            p = (poisson.pmf(x, lam_h) *
                 poisson.pmf(y, lam_a) *
                 _dc_correction(x, y, lam_h, lam_a, rho))
            ll += math.log(max(p, 1e-12))

        return -ll

    def _apply_temperature(self, ph: float, pd: float, pa: float) -> tuple[float, float, float]:
        """Soften (h,d,a) by self.temperature via logit scaling (>1 softens)."""
        T = self.temperature
        logits = [math.log(max(p, 1e-9)) / T for p in (ph, pd, pa)]
        mx = max(logits)
        exps = [math.exp(z - mx) for z in logits]
        s = sum(exps)
        return exps[0] / s, exps[1] / s, exps[2] / s

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

        # Step 1: compute Elo + attack/defense snapshots at game time
        snapshots = self._compute_rolling_elo(matches)

        if verbose:
            print(f"  [soccer_v2] Elo + attack/defense computed for "
                  f"{len(self.elo_ratings)} teams. Fitting μ, α, β, δ...")

        # Step 2: fit μ, α (Elo→supremacy), β (own attack), δ (opp leak) via MLE
        x0 = np.array([0.3, 1.0, 0.3, 0.3])
        bounds = [(0.1, 1.5), (0.0, 3.0), (-1.0, 2.0), (-1.0, 2.0)]

        result = minimize(
            self._neg_ll,
            x0,
            args=(matches, snapshots, self.rho, self.league_avg),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 2000, "ftol": 1e-10},
        )

        self.mu    = float(result.x[0])
        self.alpha = float(result.x[1])
        self.beta  = float(result.x[2])
        self.delta = float(result.x[3])
        self.fitted_on = matches[-1]["date"]

        # Step 3: apply the cross-validated calibration temperature. See
        # CALIBRATION_T — fitting per-model on an in-sample slice is unreliable.
        self.temperature = self.CALIBRATION_T

        if verbose:
            print(f"  [soccer_v2] Fit complete. μ={self.mu:.4f}, α={self.alpha:.4f}, "
                  f"β={self.beta:.4f}, δ={self.delta:.4f}, T={self.temperature:.2f}, "
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
                "atk_ratings": self.atk_ratings,
                "dfn_ratings": self.dfn_ratings,
                "league_avg":  self.league_avg,
                "mu":          self.mu,
                "alpha":       self.alpha,
                "beta":        self.beta,
                "delta":       self.delta,
                "rho":         self.rho,
                "temperature": self.temperature,
                "tempo_shrink": self.tempo_shrink,
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
        self.atk_ratings = data.get("atk_ratings", {})
        self.dfn_ratings = data.get("dfn_ratings", {})
        self.league_avg  = data.get("league_avg", 1.30)
        self.mu          = data["mu"]
        self.alpha       = data["alpha"]
        self.beta        = data.get("beta", 0.0)
        self.delta       = data.get("delta", 0.0)
        self.rho         = data.get("rho", self.RHO)
        self.temperature = data.get("temperature", 1.0)
        # Older pickles predate tempo_shrink — fall back to the class default so
        # the calibrated shrinkage still applies after a plain load().
        self.tempo_shrink = data.get("tempo_shrink", self.TEMPO_SHRINK)
        self.fitted_on   = date.fromisoformat(data["fitted_on"])
        return self

    def get_elo(self, team_name: str) -> float:
        """Return current Elo for a team (default 1500 if unknown)."""
        return self.elo_ratings.get(self._normalize(team_name), self.DEFAULT_ELO)

    def can_price(self, home_team: str, away_team: str) -> bool:
        """True only if BOTH teams have a real rating in this model.

        This is an international national-team model (Elo trained on martj42
        internationals + eloratings.net). Club sides — MLS, Liga MX, EPL, etc. —
        are absent from elo_ratings and silently fall back to DEFAULT_ELO (1500),
        which makes the model emit an identical, team-blind price for every such
        fixture and manufactures phantom edges against the book. Callers MUST gate
        on this before pricing, so unpriceable fixtures are skipped rather than
        turned into meaningless picks.
        """
        return (self._normalize(home_team) in self.elo_ratings
                and self._normalize(away_team) in self.elo_ratings)

    def seed_from_eloratings(self, allow_network: bool = True) -> None:
        """
        Overlay live Elo ratings from eloratings.net onto self.elo_ratings.

        DETERMINISM: this used to hit the network live on every pick run and, on
        intermittent fetch failure, silently keep the divergent computed Elo baked
        into the pickle. Two runs of the same slate then produced different
        probabilities (the England-41.6% vs Argentina-45.7% phantom). Now the last
        successful snapshot is cached to disk; a failed fetch reuses that snapshot
        instead of falling back to a different rating basis. Same-day runs are
        therefore reproducible, and ratings still evolve day-to-day as intended.

        allow_network=False forces cache-only (used by the reproducibility test and
        any run that must not touch the network).
        """
        ratings = None
        if allow_network:
            ratings = self._fetch_eloratings()
            if ratings:
                self._write_elo_snapshot(ratings)
        if not ratings:
            ratings = self._read_elo_snapshot()
            if ratings:
                print(f"  [soccer_v2] eloratings.net unavailable — using cached "
                      f"snapshot ({len(ratings)} teams).")
        if not ratings:
            print("  [soccer_v2] No live or cached eloratings — using computed Elo.")
            return

        updated = 0
        for team, live_elo in ratings.items():
            self.elo_ratings[team] = live_elo
            updated += 1
        print(f"  [soccer_v2] Seeded {updated} teams from eloratings.")

    @staticmethod
    def _fetch_eloratings() -> dict[str, float] | None:
        """Fetch + parse eloratings.net into {team: elo}. None on any failure."""
        url = "https://www.eloratings.net/World.tsv"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
        except Exception as e:
            print(f"  [soccer_v2] eloratings.net fetch failed: {e}.")
            return None
        out: dict[str, float] = {}
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
            out[team] = live_elo
        return out or None

    @staticmethod
    def _write_elo_snapshot(ratings: dict[str, float]) -> None:
        """Persist the last-good eloratings snapshot for deterministic reuse."""
        try:
            ELO_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            ELO_SNAPSHOT_PATH.write_text(json.dumps(
                {"fetched_at": date.today().isoformat(), "ratings": ratings},
                indent=2, sort_keys=True))
        except Exception as e:
            print(f"  [soccer_v2] could not cache eloratings snapshot: {e}")

    @staticmethod
    def _read_elo_snapshot() -> dict[str, float] | None:
        """Read the cached eloratings snapshot, or None if absent/unreadable."""
        try:
            data = json.loads(ELO_SNAPSHOT_PATH.read_text())
            ratings = data.get("ratings")
            return {k: float(v) for k, v in ratings.items()} if ratings else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def _get_lambdas(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = True,
        home_adv_elo: float = 0.0,
    ) -> tuple[float, float]:
        """
        Expected goals for each team. Combines:
          - Elo difference (μ, α) → who's stronger / supremacy
          - rolling attack/defense (β, δ) → absolute scoring tempo
          - home_adv_elo → venue edge in Elo points (0 if neutral)
        """
        home_team = self._normalize(home_team)
        away_team = self._normalize(away_team)

        elo_h = self._elo(home_team)
        elo_a = self._elo(away_team)

        # Home-field edge as an Elo bump. Generic venues get a small default;
        # 2026 co-hosts at home get HOST_BONUS via home_adv_elo.
        adv = home_adv_elo if home_adv_elo else (0.0 if neutral else 50.0)
        d_h = (elo_h - elo_a + adv) / 400.0

        avg = self.league_avg
        atk_h = self.atk_ratings.get(home_team, avg)
        dfn_h = self.dfn_ratings.get(home_team, avg)
        atk_a = self.atk_ratings.get(away_team, avg)
        dfn_a = self.dfn_ratings.get(away_team, avg)

        # Shrink the rolling attack/defense tempo terms toward 0 (see
        # TEMPO_SHRINK): the raw MLE β, δ over-swing exp_total out-of-sample.
        s = self.tempo_shrink
        b, dl = self.beta * s, self.delta * s

        lam_h = math.exp(self.mu + self.alpha * d_h
                         + b * math.log(max(atk_h, 0.05) / avg)
                         + dl * math.log(max(dfn_a, 0.05) / avg))
        lam_a = math.exp(self.mu - self.alpha * d_h
                         + b * math.log(max(atk_a, 0.05) / avg)
                         + dl * math.log(max(dfn_h, 0.05) / avg))
        return lam_h, lam_a

    def score_grid(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = True,
        max_goals: int = MAX_GOALS,
        home_adv_elo: float = 0.0,
    ) -> np.ndarray:
        """
        Compute P(home=i, away=j) score probability matrix with DC correction.
        Shape: (max_goals+1, max_goals+1).
        """
        lam_h, lam_a = self._get_lambdas(home_team, away_team, neutral, home_adv_elo)
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
        home_adv_elo: float = 0.0,
    ) -> dict:
        """
        Compute full market probabilities for a matchup.

        Returns:
            home_win, draw, away_win, btts, over_0_5 … over_4_5,
            home_over_0_5, away_over_0_5, exp_home, exp_away, exp_total,
            home_team, away_team
        """
        grid = self.score_grid(home_team, away_team, neutral=neutral,
                               home_adv_elo=home_adv_elo)
        n = grid.shape[0]

        home_win = float(np.tril(grid, -1).sum())
        draw     = float(np.trace(grid))
        away_win = float(np.triu(grid, 1).sum())

        # Calibration: temperature-scale the 1X2 probs to curb favorite
        # overconfidence (T>1 softens). Totals are left on the raw grid.
        if self.temperature and abs(self.temperature - 1.0) > 1e-6:
            home_win, draw, away_win = self._apply_temperature(home_win, draw, away_win)

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

    def handicap_cover_prob(
        self,
        home_team: str,
        away_team: str,
        handicap: float,
        side: str = "home",
        neutral: bool = True,
        home_adv_elo: float = 0.0,
    ) -> float:
        """P(picked side covers the Asian handicap) from the score grid.

        handicap is the line on the PICKED side, e.g. home -1.5 → handicap=-1.5,
        side='home'. Cover = (home_goals - away_goals + handicap) > 0 for home,
        or (away_goals - home_goals + handicap) > 0 for away. Quarter-lines
        (e.g. -0.25) split the stake across the two adjacent half-lines, so a
        push is worth half (standard Asian-handicap settlement).
        """
        grid = self.score_grid(home_team, away_team, neutral=neutral,
                               home_adv_elo=home_adv_elo).copy()
        n = grid.shape[0]

        # Reweight the score grid so its 1X2 margins match the CALIBRATED
        # (temperature-scaled) win/draw/loss probs. This makes the handicap model
        # inherit the same favorite-overconfidence correction as the ML model —
        # and guarantees the -0.5 cover exactly equals the calibrated win prob.
        cal = self.matchup(home_team, away_team, neutral=neutral,
                           home_adv_elo=home_adv_elo)
        raw_h = float(np.tril(grid, -1).sum())
        raw_d = float(np.trace(grid))
        raw_a = float(np.triu(grid, 1).sum())
        for i in range(n):
            for j in range(n):
                if i > j and raw_h > 1e-12:   # home win region
                    grid[i][j] *= cal["home_win"] / raw_h
                elif i == j and raw_d > 1e-12:
                    grid[i][j] *= cal["draw"] / raw_d
                elif i < j and raw_a > 1e-12:
                    grid[i][j] *= cal["away_win"] / raw_a
        tot = grid.sum()
        if tot > 0:
            grid /= tot

        win = push = 0.0
        for i in range(n):
            for j in range(n):
                margin = (i - j) if side == "home" else (j - i)
                adj = margin + handicap
                if adj > 1e-9:
                    win += grid[i][j]
                elif abs(adj) <= 1e-9:
                    push += grid[i][j]
        denom = 1.0 - push  # exclude pushes (stake returned), renormalize
        return float(win / denom) if denom > 1e-9 else float(win)

    def find_edges(
        self,
        events: list[dict],
        min_edge_pct: float = 4.0,
        host_nations: set[str] | None = None,
    ) -> list[dict]:
        """
        Find edges against book odds for a list of soccer events.

        events: Odds API format (h2h, totals markets)
        host_nations: teams that get a home edge regardless of home/away label
            (the 2026 World Cup co-hosts — USA/Mexico/Canada — are effectively
            home at every match). Pass None for ordinary neutral fixtures.
        Returns list of edge dicts compatible with pnl schema.
        """
        hosts = {self._normalize(h) for h in (host_nations or set())}
        edges = []
        for event in events:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            neutral = event.get("neutral", True)
            if not home or not away:
                continue

            # Co-host home edge (only one side can be a host in a given match).
            host_adv = 0.0
            if hosts:
                nh, na = self._normalize(home), self._normalize(away)
                if nh in hosts and na not in hosts:
                    host_adv = self.HOST_BONUS
                elif na in hosts and nh not in hosts:
                    host_adv = -self.HOST_BONUS

            m = self.matchup(home, away, neutral=neutral, home_adv_elo=host_adv)

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
                        # Books often return several ALTERNATE total lines in one
                        # market (points 1.25, 1.5, 2.5, 3.5…). Pair Over/Under by
                        # MATCHING point — pairing an Over@1.5 with an Under@2.5
                        # de-vigs to garbage and manufactured the fake +30% edges.
                        by_point: dict[float, dict[str, dict]] = {}
                        for o in outcomes:
                            pt = o.get("point")
                            if pt is None:
                                continue
                            by_point.setdefault(float(pt), {})[o.get("name", "")] = o

                        # Build the set of valid same-point pairs the model can
                        # price (standard half-lines on the score grid: over_0_5 …
                        # over_4_5). Exotic Asian quarter-lines (1.25, 2.75) settle
                        # on split stakes the model can't price — skip them.
                        priceable: list[tuple] = []
                        for line, pair in by_point.items():
                            over_o, under_o = pair.get("Over"), pair.get("Under")
                            if not over_o or not under_o:
                                continue  # need both sides AT THE SAME line
                            key_str = f"over_{str(line).replace('.', '_')}"
                            model_over = m.get(key_str)
                            if model_over is None:
                                continue
                            over_price  = float(over_o.get("price", -110))
                            under_price = float(under_o.get("price", -110))
                            total_imp   = (_american_to_imp(over_price) +
                                           _american_to_imp(under_price))
                            if total_imp <= 0:
                                continue
                            imp_over = _american_to_imp(over_price) / total_imp
                            priceable.append((line, model_over, imp_over,
                                              over_price, under_price))

                        if not priceable:
                            continue

                        # Bet ONLY the MAIN line — the one the book prices closest
                        # to 50/50 (its genuine expected total). Alternate lines
                        # are where a 2-parameter Poisson model's tail error
                        # manufactures phantom edges (the old +30% "OVER 1.5").
                        line, model_over, imp_over, over_price, under_price = min(
                            priceable, key=lambda t: abs(t[2] - 0.5))
                        model_under = 1.0 - model_over
                        imp_under   = 1.0 - imp_over

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

                    elif mkey == "spreads":
                        # Asian handicap. Each outcome is a team with a `point`.
                        home_o = next((o for o in outcomes if o.get("name") == home), None)
                        away_o = next((o for o in outcomes if o.get("name") == away), None)
                        if not home_o or not away_o:
                            continue
                        ho_price = float(home_o.get("price", -110))
                        ao_price = float(away_o.get("price", -110))
                        total_imp = _american_to_imp(ho_price) + _american_to_imp(ao_price)
                        if total_imp <= 0:
                            continue
                        for side_name, side_key, oc, price in [
                            (home, "home", home_o, ho_price),
                            (away, "away", away_o, ao_price),
                        ]:
                            pt = oc.get("point")
                            if pt is None:
                                continue
                            hcap = float(pt)
                            model_p = self.handicap_cover_prob(
                                home, away, hcap, side=side_key,
                                neutral=neutral, home_adv_elo=host_adv)
                            imp = _american_to_imp(price) / total_imp
                            edge = (model_p - imp) * 100.0
                            if edge >= min_edge_pct:
                                edges.append({
                                    "sport":        "soccer",
                                    "market":       "spread",
                                    "direction":    "COVER",
                                    "team":         f"{side_name} {hcap:+g}",
                                    "matchup":      f"{away} @ {home}",
                                    "odds":         int(price),
                                    "best_odds":    int(price),
                                    "line":         hcap,
                                    "model_prob":   round(model_p, 4),
                                    "implied_prob": round(imp, 4),
                                    "edge_pct":     round(edge, 2),
                                    "sportsbook":   book,
                                    "exp_total":    m["exp_total"],
                                })

        # Dedup: keep best-odds edge per (matchup, market, direction, team)
        best: dict[tuple, dict] = {}
        for e in edges:
            key = (e["matchup"], e["market"], e["direction"], e.get("team"))
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
