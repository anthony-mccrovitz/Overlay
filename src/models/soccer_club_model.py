"""
SoccerClubModel — rolling-Elo + Poisson model for CLUB leagues (MLS, Liga MX).

The international SoccerModelV2 cannot price club fixtures: every club is absent
from its national-team Elo table, defaults to 1500, and the model emits an
identical team-blind price for every game (the MLS shadow record was 2-11 on
exactly that). This model is trained on real club results (ESPN via
soccer_club_data) and keyed on club names.

It subclasses SoccerModelV2 to reuse the validated score-grid / Dixon-Coles /
1X2 / totals / Asian-handicap machinery, and layers on club-specific modeling:

  #5 Season regression + tunable K — ratings regress toward the mean at each
     season/tournament break (gap-based; handles MLS offseason, Liga MX
     Apertura/Clausura, and the World-Cup pause). K is tunable (validated).
  #4 Context features — home-field advantage γ plus altitude difference, away
     travel distance, and rest differential shift match supremacy. Altitude is
     the marquee Liga MX signal.
  #3 xG-proxy tempo — the attack/defense tempo terms are driven by a shot-based
     expected-goals proxy (SOT + off-target shots, embedded in the ESPN
     scoreboard) instead of raw goals, which is far less noisy.
  #2 Self-calibrating temperature — after fitting, an internal temporal holdout
     grid-searches the 1X2 temperature that minimizes log-loss.
  #1 Market anchoring — find_edges() blends the model toward the de-vigged book
     and only emits moneyline edges where the model MEANINGFULLY deviates.

Usage:
    m = SoccerClubModel("soccer_usa_mls").fit()
    m.matchup("Inter Miami CF", "LA Galaxy", neutral=False)
"""
from __future__ import annotations

import math
import pickle
from datetime import date
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from src.models.soccer_model_v2 import SoccerModelV2, _american_to_imp


class SoccerClubModel(SoccerModelV2):

    ELO_HOME_ADV = 65.0     # Elo home expectation baked into rolling updates
    K_FACTOR = 24.0         # default club Elo K; per-league overrides below
    # Per-league K from the walk-forward sweep (validate_soccer_club.py): MLS is
    # a parity league and prefers a lower, more stable K; Liga MX a bit higher.
    K_BY_LEAGUE = {"soccer_usa_mls": 16.0, "soccer_mexico_ligamx": 24.0}
    REGRESS_PHI = 0.80      # keep 80% of (Elo-1500) across a break; regress 20%
    BREAK_DAYS = 45         # gap that counts as a season/tournament break
    TEMPO_SHRINK = 0.5      # club form signal (xG) is denser → shrink tempo less
    CALIBRATION_T = 1.0     # default; fit() overwrites with a data-derived value
    # Market-anchor: final prob = (1-w)*market + w*model, model weight capped low
    # because the model is young/unproven — we only want to bet real deviations.
    ANCHOR_MODEL_WEIGHT = 0.45

    def __init__(self, sport_key: str) -> None:
        super().__init__()
        self.sport_key = sport_key
        self.gamma: float = 0.0     # home-field log-goal advantage
        self.c_alt: float = 0.0     # altitude-diff supremacy coeff (per 1000 m)
        self.c_travel: float = 0.0  # away-travel supremacy coeff (per 1000 km)
        self.c_rest: float = 0.0    # rest-diff supremacy coeff (per day)
        self.k_factor: float = self.K_BY_LEAGUE.get(sport_key, self.K_FACTOR)
        self.xg_sot: float = 0.30   # xG-proxy: goals per shot on target
        self.xg_off: float = 0.03   # xG-proxy: goals per off-target shot
        # fit_date = wall-clock fit time (distinct from fitted_on = last-match
        # date) so an off-season break doesn't force a re-fit every run.
        self.fit_date: date | None = None
        self.model_path = Path(f"data/models/soccer_club_{sport_key}.pkl")

    # ── Club-specific normalization / seeding ─────────────────────────────────

    def _normalize(self, name: str) -> str:
        from src.data.soccer_club_data import normalize_club_team_name
        return normalize_club_team_name(name)

    def seed_from_eloratings(self, allow_network: bool = True) -> None:
        return  # eloratings.net is national teams only — no-op for clubs

    # ── Context features (altitude / travel) from static venue table ──────────

    def _context(self, home: str, away: str, rest_diff: float = 0.0) -> float:
        """Home-favoring supremacy shift (log-goal units) from altitude, away
        travel and rest. Applied ±half to the two lambdas so totals stay put."""
        from src.data.soccer_club_data import VENUES, haversine_km
        vh, va = VENUES.get(home), VENUES.get(away)
        alt_diff = travel = 0.0
        if vh and va:
            alt_diff = (vh["alt"] - va["alt"]) / 1000.0
            travel = haversine_km(vh["lat"], vh["lon"], va["lat"], va["lon"]) / 1000.0
        return self.c_alt * alt_diff + self.c_travel * travel + self.c_rest * rest_diff

    # ── xG proxy ──────────────────────────────────────────────────────────────

    def _xg(self, shots, sot, goals_fallback):
        """Shot-based expected-goals proxy; fall back to actual goals when a
        game has no shot stats (older matches)."""
        if shots is None or sot is None:
            return float(goals_fallback)
        return self.xg_sot * float(sot) + self.xg_off * (float(shots) - float(sot))

    # ── Rolling Elo + xG tempo with season-break regression ───────────────────

    def _compute_rolling_elo(self, matches):
        """Sequential Elo + rolling xG-based attack/defense, taking a snapshot
        BEFORE each match. Regresses ratings toward the mean at season breaks.
        Snapshot tuple: (elo_h, elo_a, atk_h, dfn_a, atk_a, dfn_h, rest_h, rest_a)."""
        self.elo_ratings, self.atk_ratings, self.dfn_ratings = {}, {}, {}
        last_played: dict[str, date] = {}

        # Calibrate the xG proxy so its mean matches actual goals (goals ~ SOT +
        # off-target, least squares), keeping the tempo signal on a goals scale.
        self._calibrate_xg(matches)

        xgs = []
        for m in matches:
            xgs.append(self._xg(m.get("home_shots"), m.get("home_sot"), m["home_score"]))
            xgs.append(self._xg(m.get("away_shots"), m.get("away_sot"), m["away_score"]))
        self.league_avg = (sum(xgs) / len(xgs)) if xgs else 1.30
        avg, decay = self.league_avg, self.AD_DECAY
        phi = self.REGRESS_PHI

        snapshots = []
        for m in sorted(matches, key=lambda x: x["date"]):
            home, away, d0 = m["home_team"], m["away_team"], m["date"]

            # Season-break regression toward the mean (per team, once per break).
            for t in (home, away):
                lp = last_played.get(t)
                if lp is not None and (d0 - lp).days > self.BREAK_DAYS:
                    self.elo_ratings[t] = 1500.0 + phi * (self._elo(t) - 1500.0)
                    self.atk_ratings[t] = avg + phi * (self.atk_ratings.get(t, avg) - avg)
                    self.dfn_ratings[t] = avg + phi * (self.dfn_ratings.get(t, avg) - avg)

            elo_h, elo_a = self._elo(home), self._elo(away)
            atk_h = self.atk_ratings.get(home, avg)
            dfn_h = self.dfn_ratings.get(home, avg)
            atk_a = self.atk_ratings.get(away, avg)
            dfn_a = self.dfn_ratings.get(away, avg)
            rest_h = min((d0 - last_played[home]).days, 14) if home in last_played else 7
            rest_a = min((d0 - last_played[away]).days, 14) if away in last_played else 7
            snapshots.append((elo_h, elo_a, atk_h, dfn_a, atk_a, dfn_h, rest_h, rest_a))

            self._update_elo(home, away, m["home_score"], m["away_score"], self.k_factor)

            xg_h = self._xg(m.get("home_shots"), m.get("home_sot"), m["home_score"])
            xg_a = self._xg(m.get("away_shots"), m.get("away_sot"), m["away_score"])
            self.atk_ratings[home] = (1 - decay) * atk_h + decay * xg_h
            self.dfn_ratings[home] = (1 - decay) * dfn_h + decay * xg_a
            self.atk_ratings[away] = (1 - decay) * atk_a + decay * xg_a
            self.dfn_ratings[away] = (1 - decay) * dfn_a + decay * xg_h
            last_played[home] = last_played[away] = d0

        self.last_played = last_played
        return snapshots

    def _calibrate_xg(self, matches) -> None:
        """Least-squares calibrate goals ~ b_sot*SOT + b_off*off_shots."""
        rows, tgt = [], []
        for m in matches:
            for shots, sot, g in (
                (m.get("home_shots"), m.get("home_sot"), m["home_score"]),
                (m.get("away_shots"), m.get("away_sot"), m["away_score"]),
            ):
                if shots is None or sot is None:
                    continue
                rows.append([float(sot), float(shots) - float(sot)])
                tgt.append(float(g))
        if len(rows) >= 50:
            coef, *_ = np.linalg.lstsq(np.array(rows), np.array(tgt), rcond=None)
            # Guard against pathological fits; keep coeffs sane/non-negative.
            self.xg_sot = float(np.clip(coef[0], 0.05, 0.6))
            self.xg_off = float(np.clip(coef[1], 0.0, 0.2))

    def _update_elo(self, home, away, home_score, away_score, k) -> None:
        elo_h, elo_a = self._elo(home), self._elo(away)
        exp_h = 1.0 / (1.0 + 10.0 ** ((elo_a - (elo_h + self.ELO_HOME_ADV)) / 400.0))
        if home_score > away_score:
            ah, aa = 1.0, 0.0
        elif home_score == away_score:
            ah, aa = 0.5, 0.5
        else:
            ah, aa = 0.0, 1.0
        self.elo_ratings[home] = elo_h + k * (ah - exp_h)
        self.elo_ratings[away] = elo_a + k * (aa - (1.0 - exp_h))

    # ── Vectorized likelihood (μ, α, β, δ, γ, c_alt, c_travel, c_rest) ─────────

    def _make_neg_ll(self, matches, snapshots, rho, avg):
        from src.data.soccer_club_data import VENUES, haversine_km
        snap = np.asarray(snapshots, dtype=float)
        elo_h, elo_a, atk_h, dfn_a, atk_a, dfn_h, rest_h, rest_a = snap.T
        d = (elo_h - elo_a) / 400.0
        la_h = np.log(np.maximum(atk_h, 0.05) / avg)
        lc_a = np.log(np.maximum(dfn_a, 0.05) / avg)
        la_a = np.log(np.maximum(atk_a, 0.05) / avg)
        lc_h = np.log(np.maximum(dfn_h, 0.05) / avg)
        rest_diff = (rest_h - rest_a) / 7.0

        alt_diff = np.zeros(len(matches))
        travel = np.zeros(len(matches))
        for i, m in enumerate(matches):
            vh, va = VENUES.get(m["home_team"]), VENUES.get(m["away_team"])
            if vh and va:
                alt_diff[i] = (vh["alt"] - va["alt"]) / 1000.0
                travel[i] = haversine_km(vh["lat"], vh["lon"], va["lat"], va["lon"]) / 1000.0

        x = np.array([m["home_score"] for m in matches], dtype=float)
        y = np.array([m["away_score"] for m in matches], dtype=float)
        lg_x = np.array([math.lgamma(v + 1) for v in x])
        lg_y = np.array([math.lgamma(v + 1) for v in y])
        m00 = (x == 0) & (y == 0); m01 = (x == 0) & (y == 1)
        m10 = (x == 1) & (y == 0); m11 = (x == 1) & (y == 1)

        def neg_ll(params):
            mu, alpha, beta, delta, gamma, c_alt, c_tr, c_rest = params
            ctx = c_alt * alt_diff + c_tr * travel + c_rest * rest_diff
            lam_h = np.exp(mu + gamma + alpha * d + beta * la_h + delta * lc_a + ctx / 2)
            lam_a = np.exp(mu - alpha * d + beta * la_a + delta * lc_h - ctx / 2)
            ll = (-lam_h + x * np.log(lam_h) - lg_x
                  - lam_a + y * np.log(lam_a) - lg_y)
            tau = np.ones_like(lam_h)
            tau[m00] = 1.0 - lam_h[m00] * lam_a[m00] * rho
            tau[m01] = 1.0 + lam_h[m01] * rho
            tau[m10] = 1.0 + lam_a[m10] * rho
            tau[m11] = 1.0 - rho
            ll += np.log(np.maximum(tau, 1e-9))
            return -float(ll.sum())

        return neg_ll

    def fit(self, verbose: bool = True, seasons=None, _matches=None,
            calibrate: bool = True) -> "SoccerClubModel":
        from src.data.soccer_club_data import load_club_matches
        matches = _matches if _matches is not None else load_club_matches(
            self.sport_key, seasons=seasons)
        if not matches:
            raise RuntimeError(f"No club match data for {self.sport_key}.")
        matches = sorted(matches, key=lambda x: x["date"])
        if verbose:
            print(f"  [club:{self.sport_key}] {len(matches):,} matches. "
                  f"Rolling Elo(K={self.k_factor}) + xG tempo + context...")

        snapshots = self._compute_rolling_elo(matches)
        x0 = np.array([0.3, 1.0, 0.3, 0.3, 0.2, 0.0, 0.0, 0.0])
        bounds = [(0.05, 1.5), (0.0, 3.0), (-1.0, 2.0), (-1.0, 2.0),
                  (-0.5, 1.0), (-0.5, 0.5), (-0.5, 0.5), (-0.5, 0.5)]
        result = minimize(self._make_neg_ll(matches, snapshots, self.rho, self.league_avg),
                          x0, method="L-BFGS-B", bounds=bounds,
                          options={"maxiter": 4000, "ftol": 1e-10})
        (self.mu, self.alpha, self.beta, self.delta, self.gamma,
         self.c_alt, self.c_travel, self.c_rest) = (float(v) for v in result.x)
        self.tempo_shrink = self.TEMPO_SHRINK
        self.fitted_on = matches[-1]["date"]
        self.fit_date = date.today()

        # #2 self-calibrating temperature on an internal temporal holdout.
        self.temperature = 1.0
        if calibrate:
            self.temperature = self._calibrate_temperature(matches, snapshots)

        if verbose:
            print(f"  [club:{self.sport_key}] μ={self.mu:.3f} α={self.alpha:.3f} "
                  f"β={self.beta:.3f} δ={self.delta:.3f} γ={self.gamma:.3f}(×{math.exp(self.gamma):.2f}) "
                  f"alt={self.c_alt:.3f} travel={self.c_travel:.3f} rest={self.c_rest:.3f} "
                  f"T={self.temperature:.2f} xG=[{self.xg_sot:.2f},{self.xg_off:.2f}]")
        if _matches is None:
            self._save()
        return self

    def _calibrate_temperature(self, matches, snapshots) -> float:
        """Grid-search the 1X2 temperature minimizing log-loss on the last 25%
        of the training matches (predicted from their causal snapshots)."""
        n = len(matches)
        start = int(n * 0.75)
        if n - start < 40:
            return 1.0
        save = dict(self.elo_ratings), dict(self.atk_ratings), dict(self.dfn_ratings)
        base_T = self.temperature
        self.temperature = 1.0
        raw = []  # (h,d,a, outcome_index)
        for i in range(start, n):
            m = matches[i]
            eh, ea, ah, da, aa, dh, *_ = snapshots[i]
            h, a = m["home_team"], m["away_team"]
            self.elo_ratings[h], self.elo_ratings[a] = eh, ea
            self.atk_ratings[h], self.dfn_ratings[h] = ah, dh
            self.atk_ratings[a], self.dfn_ratings[a] = aa, da
            r = self.matchup(h, a, neutral=False)
            o = 0 if m["home_score"] > m["away_score"] else (1 if m["home_score"] == m["away_score"] else 2)
            raw.append((r["home_win"], r["draw"], r["away_win"], o))
        self.elo_ratings, self.atk_ratings, self.dfn_ratings = save
        self.temperature = base_T

        def loss(T):
            tot = 0.0
            for h, dd, a, o in raw:
                logits = [math.log(max(p, 1e-9)) / T for p in (h, dd, a)]
                mx = max(logits); ex = [math.exp(z - mx) for z in logits]
                s = sum(ex); probs = [e / s for e in ex]
                tot += -math.log(max(probs[o], 1e-12))
            return tot / len(raw)

        best_T, best = 1.0, loss(1.0)
        for T in [x / 100 for x in range(70, 141, 5)]:
            lv = loss(T)
            if lv < best:
                best, best_T = lv, T
        return best_T

    # ── Prediction: home edge γ + context (altitude/travel/rest) ──────────────

    def _get_lambdas(self, home_team, away_team, neutral=False, home_adv_elo=0.0,
                     rest_diff=0.0):
        home_team = self._normalize(home_team)
        away_team = self._normalize(away_team)
        d = (self._elo(home_team) - self._elo(away_team)) / 400.0
        avg = self.league_avg
        atk_h = self.atk_ratings.get(home_team, avg)
        dfn_h = self.dfn_ratings.get(home_team, avg)
        atk_a = self.atk_ratings.get(away_team, avg)
        dfn_a = self.dfn_ratings.get(away_team, avg)
        s = self.tempo_shrink
        b, dl = self.beta * s, self.delta * s
        if neutral:
            g = ctx = 0.0
        else:
            g = self.gamma
            ctx = self._context(home_team, away_team, rest_diff)
        lam_h = math.exp(self.mu + g + self.alpha * d
                         + b * math.log(max(atk_h, 0.05) / avg)
                         + dl * math.log(max(dfn_a, 0.05) / avg) + ctx / 2)
        lam_a = math.exp(self.mu - self.alpha * d
                         + b * math.log(max(atk_a, 0.05) / avg)
                         + dl * math.log(max(dfn_h, 0.05) / avg) - ctx / 2)
        return lam_h, lam_a

    # ── #1 Market-anchored moneyline edges (clubs bet moneyline only) ─────────

    def find_edges(self, events, min_edge_pct=4.0, host_nations=None):
        """Club moneyline edges, anchored to the de-vigged book consensus. The
        model is blended toward the market (weight capped low) so we only emit
        edges where it meaningfully disagrees with the book — killing the
        phantom edges a young rating model would otherwise manufacture."""
        w = self.ANCHOR_MODEL_WEIGHT
        edges = []
        for event in events:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            if not home or not away or not self.can_price(home, away):
                continue
            neutral = event.get("neutral", False)
            m = self.matchup(home, away, neutral=neutral)
            model_p = {home: m["home_win"], away: m["away_win"], "Draw": m["draw"]}

            for bookmaker in event.get("bookmakers", []):
                book = bookmaker.get("title", "")
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    outcomes = market.get("outcomes", [])
                    total_imp = sum(_american_to_imp(float(o.get("price", -110)))
                                    for o in outcomes)
                    if total_imp <= 0:
                        continue
                    for outcome in outcomes:
                        name = outcome.get("name", "")
                        price = float(outcome.get("price", 0))
                        if not price or name not in model_p:
                            continue
                        novig = _american_to_imp(price) / total_imp  # de-vigged book
                        anchored = w * model_p[name] + (1 - w) * novig
                        edge = (anchored - novig) * 100.0
                        if edge >= min_edge_pct:
                            edges.append({
                                "sport": "soccer", "market": "moneyline",
                                # Outcome, not team name (name → schema
                                # stamped every pick "HOME")
                                "direction": "DRAW" if name == "Draw" else "WIN",
                                "team": name,
                                "matchup": f"{away} @ {home}",
                                "odds": int(price), "best_odds": int(price),
                                "model_prob": round(anchored, 4),
                                "model_prob_raw": round(model_p[name], 4),
                                "implied_prob": round(novig, 4),
                                "edge_pct": round(edge, 2),
                                "sportsbook": book, "exp_total": m["exp_total"],
                            })
        best = {}
        for e in edges:
            # key on team — direction is now WIN/DRAW and would collapse the
            # two win sides of a match into one
            key = (e["matchup"], e["team"])
            if key not in best or e["edge_pct"] > best[key]["edge_pct"]:
                best[key] = e
        return sorted(best.values(), key=lambda x: x["edge_pct"], reverse=True)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump({
                "sport_key": self.sport_key,
                "elo_ratings": self.elo_ratings, "atk_ratings": self.atk_ratings,
                "dfn_ratings": self.dfn_ratings, "league_avg": self.league_avg,
                "mu": self.mu, "alpha": self.alpha, "beta": self.beta,
                "delta": self.delta, "gamma": self.gamma,
                "c_alt": self.c_alt, "c_travel": self.c_travel, "c_rest": self.c_rest,
                "k_factor": self.k_factor, "xg_sot": self.xg_sot, "xg_off": self.xg_off,
                "rho": self.rho, "temperature": self.temperature,
                "tempo_shrink": self.tempo_shrink,
                "fitted_on": self.fitted_on.isoformat(),
                "fit_date": (self.fit_date or date.today()).isoformat(),
            }, f)
        print(f"  [club:{self.sport_key}] saved → {self.model_path}")

    def load(self) -> "SoccerClubModel":
        if not self.model_path.exists():
            raise FileNotFoundError(f"No club model at {self.model_path}. Fit first.")
        with open(self.model_path, "rb") as f:
            d = pickle.load(f)
        self.elo_ratings = d["elo_ratings"]
        self.atk_ratings = d.get("atk_ratings", {})
        self.dfn_ratings = d.get("dfn_ratings", {})
        self.league_avg = d.get("league_avg", 1.4)
        self.mu, self.alpha = d["mu"], d["alpha"]
        self.beta, self.delta = d.get("beta", 0.0), d.get("delta", 0.0)
        self.gamma = d.get("gamma", 0.0)
        self.c_alt = d.get("c_alt", 0.0)
        self.c_travel = d.get("c_travel", 0.0)
        self.c_rest = d.get("c_rest", 0.0)
        self.k_factor = d.get("k_factor", self.K_FACTOR)
        self.xg_sot = d.get("xg_sot", 0.30)
        self.xg_off = d.get("xg_off", 0.03)
        self.rho = d.get("rho", self.RHO)
        self.temperature = d.get("temperature", 1.0)
        self.tempo_shrink = d.get("tempo_shrink", self.TEMPO_SHRINK)
        self.fitted_on = date.fromisoformat(d["fitted_on"])
        fd = d.get("fit_date")
        self.fit_date = date.fromisoformat(fd) if fd else self.fitted_on
        return self


def load_or_fit_club_model(sport_key: str, verbose: bool = True,
                           max_age_days: int = 3) -> SoccerClubModel:
    m = SoccerClubModel(sport_key)
    if m.model_path.exists():
        m.load()
        age = (date.today() - (m.fit_date or m.fitted_on)).days
        if age <= max_age_days:
            if verbose:
                print(f"  [club:{sport_key}] loaded (fit {age}d ago, "
                      f"data through {m.fitted_on}).")
            return m
        if verbose:
            print(f"  [club:{sport_key}] fit {age}d ago — re-fitting...")
    return m.fit(verbose=verbose)
