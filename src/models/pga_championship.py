"""
PGA Championship 2026 — Monte Carlo simulation model.

Quail Hollow Club, Charlotte NC  |  Par 71  |  ~7,600 yards
May 14–17, 2026

Model approach:
  1. Each player gets a skill rating = weighted SG composite
  2. Course-fit adjustments for Quail Hollow (premium on SG Approach + length)
  3. Per-round score sampled from Normal(expected_score, σ)
  4. 4 rounds summed → lowest total wins
  5. 100k simulations → win probability per player
  6. Compare to market implied probability → edge

Quail Hollow course profile:
  - Long (7,600 yds), par 71
  - "The Green Mile" finish (holes 16-18) punishes mistakes
  - Bentgrass greens — rewards precise approaches
  - Tree-lined fairways — accuracy off tee matters
  - SG: Approach weighted 40%, OTT 25%, Putting 25%, ATG 10%
"""
from __future__ import annotations

import json
import math
import random
from datetime import date
from pathlib import Path

import numpy as np

# ── Player database ───────────────────────────────────────────────────────────
# sg_total:   season-avg strokes gained vs. field per round
# sg_app:     SG approach (most course-relevant at QH)
# sg_ott:     SG off the tee
# sg_putt:    SG putting
# sg_atg:     SG around the green
# form:       recent 8-week form multiplier (0.8=cold, 1.0=avg, 1.2=hot)
# major_exp:  PGA Championship specific bonus (wins=0.15/top5=0.08/top10=0.04)
# qh_history: course bonus for Quail Hollow (Wells Fargo wins / top finishes)
#
# Stats are 2025-2026 PGA Tour season approximations based on
# world rankings + known performance profiles. Replace with DataGolf
# API data when available: https://datagolf.com/api-access (free tier)

PLAYER_DB: dict[str, dict] = {
    # ── Elite tier ─────────────────────────────────────────────────────────
    "Scottie Scheffler": {
        "sg_total": 3.45, "sg_app": 1.20, "sg_ott": 0.85,
        "sg_putt": 0.60, "sg_atg": 0.80,
        "form": 1.15, "major_exp": 0.10, "qh_history": 0.05,
    },
    "Rory McIlroy": {
        "sg_total": 2.50, "sg_app": 0.90, "sg_ott": 1.10,
        "sg_putt": 0.25, "sg_atg": 0.25,
        "form": 1.10, "major_exp": 0.08,
        "qh_history": 0.25,  # 4 Wells Fargo wins at Quail Hollow
    },
    "Cameron Young": {
        "sg_total": 2.20, "sg_app": 0.75, "sg_ott": 1.05,
        "sg_putt": 0.20, "sg_atg": 0.20,
        "form": 1.15, "major_exp": 0.04, "qh_history": 0.05,
    },
    "Jon Rahm": {
        "sg_total": 2.15, "sg_app": 1.00, "sg_ott": 0.60,
        "sg_putt": 0.25, "sg_atg": 0.30,
        "form": 1.10, "major_exp": 0.12, "qh_history": 0.05,
    },
    "Xander Schauffele": {
        "sg_total": 2.00, "sg_app": 0.85, "sg_ott": 0.65,
        "sg_putt": 0.25, "sg_atg": 0.25,
        "form": 1.05, "major_exp": 0.15, "qh_history": 0.0,
        # Won 2024 PGA Championship
    },
    "Ludvig Aberg": {
        "sg_total": 2.00, "sg_app": 0.95, "sg_ott": 0.70,
        "sg_putt": 0.15, "sg_atg": 0.20,
        "form": 1.08, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Bryson DeChambeau": {
        "sg_total": 1.80, "sg_app": 0.55, "sg_ott": 1.40,
        "sg_putt": -0.10, "sg_atg": -0.05,
        "form": 1.05, "major_exp": 0.12, "qh_history": 0.0,
    },
    "Matthew Fitzpatrick": {
        "sg_total": 1.80, "sg_app": 1.10, "sg_ott": 0.30,
        "sg_putt": 0.20, "sg_atg": 0.20,
        "form": 1.05, "major_exp": 0.10, "qh_history": 0.10,
    },
    "Tommy Fleetwood": {
        "sg_total": 1.70, "sg_app": 1.05, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.15,
        "form": 1.08, "major_exp": 0.06, "qh_history": 0.05,
    },
    "Brooks Koepka": {
        "sg_total": 1.50, "sg_app": 0.70, "sg_ott": 0.55,
        "sg_putt": 0.10, "sg_atg": 0.15,
        "form": 0.95, "major_exp": 0.20, "qh_history": 0.05,
        # 3 PGA Championship wins — massive major_exp bonus
    },
    "Collin Morikawa": {
        "sg_total": 1.55, "sg_app": 1.15, "sg_ott": 0.05,
        "sg_putt": 0.15, "sg_atg": 0.20,
        "form": 1.02, "major_exp": 0.12, "qh_history": 0.0,
    },
    "Patrick Cantlay": {
        "sg_total": 1.50, "sg_app": 0.80, "sg_ott": 0.30,
        "sg_putt": 0.25, "sg_atg": 0.15,
        "form": 1.00, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Justin Rose": {
        "sg_total": 1.30, "sg_app": 0.75, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.15,
        "form": 1.10, "major_exp": 0.08, "qh_history": 0.0,
    },
    "Christopher Gotterup": {
        "sg_total": 1.45, "sg_app": 0.65, "sg_ott": 0.70,
        "sg_putt": -0.05, "sg_atg": 0.15,
        "form": 1.15, "major_exp": 0.00, "qh_history": 0.05,
    },
    "Russell Henley": {
        "sg_total": 1.40, "sg_app": 0.70, "sg_ott": 0.40,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.05,
    },
    "Rickie Fowler": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.08, "major_exp": 0.04, "qh_history": 0.10,
    },
    "Justin Thomas": {
        "sg_total": 1.40, "sg_app": 0.70, "sg_ott": 0.45,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 0.95, "major_exp": 0.12, "qh_history": 0.08,
    },
    "Tyrrell Hatton": {
        "sg_total": 1.40, "sg_app": 0.75, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.15,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Sam Burns": {
        "sg_total": 1.40, "sg_app": 0.60, "sg_ott": 0.50,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.10,
    },
    "J. J. Spaun": {
        "sg_total": 1.35, "sg_app": 0.60, "sg_ott": 0.45,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.12, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Min Woo Lee": {
        "sg_total": 1.30, "sg_app": 0.55, "sg_ott": 0.50,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 1.10, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Jake Knapp": {
        "sg_total": 1.30, "sg_app": 0.55, "sg_ott": 0.65,
        "sg_putt": -0.05, "sg_atg": 0.15,
        "form": 1.08, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Nicolai Hojgaard": {
        "sg_total": 1.30, "sg_app": 0.65, "sg_ott": 0.40,
        "sg_putt": 0.10, "sg_atg": 0.15,
        "form": 1.05, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Adam Scott": {
        "sg_total": 1.20, "sg_app": 0.60, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 1.00, "major_exp": 0.06, "qh_history": 0.0,
    },
    "Viktor Hovland": {
        "sg_total": 1.50, "sg_app": 0.65, "sg_ott": 0.55,
        "sg_putt": 0.15, "sg_atg": 0.15,
        "form": 0.90, "major_exp": 0.04, "qh_history": 0.0,
        # Cold form in 2026
    },
    "Si Woo Kim": {
        "sg_total": 1.15, "sg_app": 0.50, "sg_ott": 0.40,
        "sg_putt": 0.20, "sg_atg": 0.05,
        "form": 1.10, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Robert Macintyre": {
        "sg_total": 1.25, "sg_app": 0.55, "sg_ott": 0.50,
        "sg_putt": 0.10, "sg_atg": 0.10,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Hideki Matsuyama": {
        "sg_total": 1.20, "sg_app": 0.70, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 0.95, "major_exp": 0.06, "qh_history": 0.0,
    },
    "Jordan Spieth": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.20,
        "sg_putt": 0.35, "sg_atg": 0.10,
        "form": 0.98, "major_exp": 0.10, "qh_history": 0.08,
    },
    "Kurt Kitayama": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.10,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Harris English": {
        "sg_total": 1.15, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 1.08, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Sepp Straka": {
        "sg_total": 1.15, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Shane Lowry": {
        "sg_total": 1.10, "sg_app": 0.55, "sg_ott": 0.25,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.02, "major_exp": 0.08, "qh_history": 0.0,
    },
    "Maverick Mcnealy": {
        "sg_total": 1.15, "sg_app": 0.60, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.05, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Keegan Bradley": {
        "sg_total": 1.10, "sg_app": 0.50, "sg_ott": 0.40,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 0.98, "major_exp": 0.06, "qh_history": 0.0,
    },
    "Kristoffer Reitan": {
        "sg_total": 1.10, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.10, "sg_atg": 0.10,
        "form": 1.08, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Akshay Bhatia": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.50,
        "sg_putt": 0.05, "sg_atg": 0.10,
        "form": 1.10, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Joaquin Niemann": {
        "sg_total": 1.15, "sg_app": 0.55, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Patrick Reed": {
        "sg_total": 1.00, "sg_app": 0.55, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 0.95, "major_exp": 0.08, "qh_history": 0.0,
    },
    "Tony Finau": {
        "sg_total": 1.15, "sg_app": 0.55, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.06, "qh_history": 0.05,
    },
    "Wyndham Clark": {
        "sg_total": 1.20, "sg_app": 0.60, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.05,
        "form": 0.92, "major_exp": 0.08, "qh_history": 0.0,
    },
    "Corey Conners": {
        "sg_total": 1.10, "sg_app": 0.70, "sg_ott": 0.25,
        "sg_putt": 0.05, "sg_atg": 0.10,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Denny McCarthy": {
        "sg_total": 1.00, "sg_app": 0.40, "sg_ott": 0.30,
        "sg_putt": 0.25, "sg_atg": 0.05,
        "form": 1.05, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Nick Taylor": {
        "sg_total": 1.05, "sg_app": 0.50, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.02, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Sungjae Im": {
        "sg_total": 1.10, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Jason Day": {
        "sg_total": 1.00, "sg_app": 0.55, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.10, "qh_history": 0.0,
    },
    "Gary Woodland": {
        "sg_total": 0.90, "sg_app": 0.40, "sg_ott": 0.40,
        "sg_putt": 0.05, "sg_atg": 0.05,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Sahith Theegala": {
        "sg_total": 1.25, "sg_app": 0.60, "sg_ott": 0.50,
        "sg_putt": 0.05, "sg_atg": 0.10,
        "form": 0.95, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Tom Kim": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.10,
        "form": 0.90, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Max Homa": {
        "sg_total": 1.15, "sg_app": 0.60, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 0.88, "major_exp": 0.04, "qh_history": 0.05,
    },
    "Christiaan Bezuidenhout": {
        "sg_total": 1.05, "sg_app": 0.60, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Stephan Jaeger": {
        "sg_total": 1.05, "sg_app": 0.50, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.05, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Taylor Moore": {
        "sg_total": 0.95, "sg_app": 0.45, "sg_ott": 0.30,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Eric Cole": {
        "sg_total": 1.00, "sg_app": 0.50, "sg_ott": 0.35,
        "sg_putt": 0.10, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.00, "qh_history": 0.0,
    },
}

# ── Course fit weights for Quail Hollow ───────────────────────────────────────
# Long, demanding par 71 — rewards ball-strikers, penalizes crooked drivers
QH_WEIGHTS = {
    "sg_app":  0.40,   # #1 factor — approach to bentgrass greens
    "sg_ott":  0.25,   # length + accuracy off the tee on long holes
    "sg_putt": 0.25,   # fast bentgrass greens reward good putters
    "sg_atg":  0.10,   # scrambling matters but less than approach
}

# Per-round scoring standard deviation (PGA Tour typical)
ROUND_SIGMA = 3.4


def _course_adjusted_skill(player: str, db: dict[str, dict]) -> float:
    """
    Compute course-adjusted skill rating for Quail Hollow.
    Returns expected strokes-gained per round vs. field (higher = better).

    Formula:
      base        = sg_total (primary predictor)
      course_adj  = component-level fit to Quail Hollow profile
                    (+bonus if sg_app / sg_ott match course demands)
      form_adj    = form multiplier applied to base
      bonuses     = major exp + course history (additive, capped)
    """
    p = db.get(player, {})
    if not p:
        return 0.0

    base = p.get("sg_total", 0.0)

    # Course fit delta: how much does this player's component profile
    # over/under-index for Quail Hollow vs. a generic tour-average course?
    # Positive = profile matches QH demands, negative = mismatches
    course_adj = (
        p.get("sg_app",  0) * 0.15 +   # iron play heavily rewarded
        p.get("sg_ott",  0) * 0.05 +   # length bonus (long course)
        p.get("sg_putt", 0) * 0.05 -   # putting on bentgrass
        p.get("sg_atg",  0) * 0.02     # small penalty for relying on scrambling
    )

    # Form: scale base by form multiplier
    form_adj = base * (p.get("form", 1.0) - 1.0)

    # Major experience + course-specific history (additive, capped at 0.4)
    bonus = min(p.get("major_exp", 0.0) + p.get("qh_history", 0.0), 0.40)

    return base + course_adj + form_adj + bonus


def _field_default_skill(odds: int) -> float:
    """
    Estimate skill rating for players not in DB using implied odds.
    Maps implied probability back to approximate SG total.
    """
    if odds > 0:
        impl_prob = 100 / (100 + odds)
    else:
        impl_prob = abs(odds) / (abs(odds) + 100)

    # Rough calibration: Scheffler (impl ~15%) → ~2.0 adjusted skill
    # 100/1 shot (impl ~1%) → ~0.3 adjusted skill
    # Linear interpolation in log-probability space
    if impl_prob <= 0:
        return 0.1
    # log-linear map: log(0.15) ≈ -1.9, log(0.001) ≈ -6.9
    log_p  = math.log(max(impl_prob, 0.001))
    # Scale to [0.1, 2.0]
    scaled = (log_p - math.log(0.001)) / (math.log(0.15) - math.log(0.001))
    return max(0.05, min(2.0, scaled * 2.0))


def run_simulation(
    players: list[str],
    skill_ratings: dict[str, float],
    n_sim: int = 150_000,
    seed: int = 42,
) -> dict[str, dict]:
    """
    Monte Carlo simulation: 4 rounds, 156 players.
    Returns per-player win/top5/top10/top20 probabilities.
    """
    rng = np.random.default_rng(seed)
    n   = len(players)

    # Expected score per round (strokes above avg → below par)
    # Par 71, field average ~71.5 for a major
    field_avg  = 71.5
    exp_scores = np.array([field_avg - skill_ratings.get(p, 0.3) for p in players])

    # Simulate n_sim tournaments
    # Shape: (n_sim, n_players, 4_rounds)
    rounds = rng.normal(
        loc   = exp_scores[np.newaxis, :, np.newaxis],   # (1, n, 1)
        scale = ROUND_SIGMA,
        size  = (n_sim, n, 4),
    )
    totals = rounds.sum(axis=2)   # (n_sim, n_players)

    # Fully vectorised finish counting — (n_sim, n_players) argsort
    ranks = np.argsort(totals, axis=1)   # ranks[s, k] = player index finishing kth in sim s

    # For each player, count how many sims they finished in each position bucket
    # ranks[:, 0]  → winner index per sim
    wins  = np.bincount(ranks[:, 0],        minlength=n).astype(np.float64)
    top5  = np.zeros(n, dtype=np.float64)
    top10 = np.zeros(n, dtype=np.float64)
    top20 = np.zeros(n, dtype=np.float64)

    for k in range(min(20, n)):
        col = ranks[:, k]
        if k < 5:  top5  += np.bincount(col, minlength=n)
        if k < 10: top10 += np.bincount(col, minlength=n)
        top20 += np.bincount(col, minlength=n)

    results = {}
    for i, player in enumerate(players):
        results[player] = {
            "win_prob":   wins[i]  / n_sim,
            "top5_prob":  top5[i]  / n_sim,
            "top10_prob": top10[i] / n_sim,
            "top20_prob": top20[i] / n_sim,
            "skill":      skill_ratings.get(player, 0.0),
        }
    return results


def _american_to_decimal(odds: int) -> float:
    if odds > 0:
        return odds / 100 + 1
    return 100 / abs(odds) + 1


def _implied_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (100 + odds)
    return abs(odds) / (abs(odds) + 100)


def fetch_odds() -> dict[str, dict]:
    """Fetch current PGA Championship outright odds from The Odds API."""
    import os, requests as req
    key = os.environ.get("ODDS_API_KEY", "dec2a2126df47d603ca05fa8ba33d5f1")
    try:
        r = req.get(
            "https://api.the-odds-api.com/v4/sports/golf_pga_championship_winner/odds",
            params={
                "apiKey": key, "regions": "us,uk,eu",
                "markets": "outrights", "oddsFormat": "american",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return {}
        data = r.json()
        if not isinstance(data, list) or not data:
            return {}

        # Collect best (highest American odds = best payout) per player
        players: dict[str, dict] = {}
        for bm in data[0].get("bookmakers", []):
            book = bm["key"]
            for o in bm["markets"][0]["outcomes"]:
                name  = o["name"]
                price = int(o["price"])
                if name not in players or price > players[name]["best_odds"]:
                    players[name] = {
                        "best_odds":   price,
                        "best_book":   book,
                        "implied_prob": _implied_prob(price),
                    }
        return players
    except Exception as e:
        print(f"  [odds] fetch error: {e}")
        return {}


def run_pga_model(n_sim: int = 100_000) -> list[dict]:
    """
    Full pipeline: fetch odds → build skill ratings → simulate → find edges.
    Returns sorted list of picks with edge data.
    """
    print("  Fetching PGA Championship odds...")
    market_odds = fetch_odds()
    if not market_odds:
        print("  ERROR: Could not fetch odds. Check ODDS_API_KEY.")
        return []

    print(f"  {len(market_odds)} players in market.")

    # Build skill ratings for all players in the market
    skill_ratings: dict[str, float] = {}
    for player, info in market_odds.items():
        if player in PLAYER_DB:
            skill_ratings[player] = _course_adjusted_skill(player, PLAYER_DB)
        else:
            # Use odds-implied skill for players not in DB
            skill_ratings[player] = _field_default_skill(info["best_odds"])

    players = list(market_odds.keys())

    print(f"  Running {n_sim:,} simulations for {len(players)} players...")
    sim_results = run_simulation(players, skill_ratings, n_sim=n_sim)

    # Build picks list with edges
    picks = []
    # Market overround — total implied prob > 100% due to vig; normalize
    total_impl = sum(v["implied_prob"] for v in market_odds.values())
    vig_factor = total_impl  # typically ~1.20 for outrights

    for player in players:
        odds_info = market_odds[player]
        sim       = sim_results[player]

        raw_impl  = odds_info["implied_prob"]
        fair_impl = raw_impl / vig_factor   # remove overround

        model_win = sim["win_prob"]
        edge_pct  = round((model_win - fair_impl) * 100, 2)

        picks.append({
            "player":       player,
            "best_odds":    odds_info["best_odds"],
            "best_book":    odds_info["best_book"],
            "model_win":    round(model_win * 100, 2),
            "market_impl":  round(fair_impl * 100, 2),
            "edge_pct":     edge_pct,
            "top5_prob":    round(sim["top5_prob"] * 100, 1),
            "top10_prob":   round(sim["top10_prob"] * 100, 1),
            "top20_prob":   round(sim["top20_prob"] * 100, 1),
            "skill_rating": round(sim["skill"], 3),
        })

    # Sort by edge descending
    picks.sort(key=lambda x: x["edge_pct"], reverse=True)
    return picks


def print_report(picks: list[dict], top_n: int = 20) -> None:
    """Print human-readable edge report — modelled players only."""
    modelled = [p for p in picks if p["player"] in PLAYER_DB]
    modelled_by_edge = sorted(modelled, key=lambda x: x["edge_pct"], reverse=True)

    print("\n" + "=" * 82)
    print("  PGA CHAMPIONSHIP 2026 — QUAIL HOLLOW · MAY 14–17")
    print("  ChefTonyBets AI  |  Course-fit Monte Carlo  |  100k simulations")
    print("=" * 82)
    hdr = f"  {'PLAYER':<26} {'ODDS':>7} {'MODEL%':>7} {'MKT%':>6} {'EDGE':>7} {'TOP5%':>6} {'TOP10%':>7}"
    print(f"\n{hdr}")
    print("-" * 82)
    for p in modelled_by_edge[:top_n]:
        edge_str = f"+{p['edge_pct']:.1f}%" if p['edge_pct'] > 0 else f"{p['edge_pct']:.1f}%"
        flag = "  ★" if p["edge_pct"] >= 2.0 else ("  ·" if p["edge_pct"] >= 0 else "")
        print(
            f"  {p['player']:<26} {p['best_odds']:>+7d}  "
            f"{p['model_win']:>5.1f}%  {p['market_impl']:>4.1f}%  "
            f"{edge_str:>6}  {p['top5_prob']:>5.1f}%  {p['top10_prob']:>6.1f}%{flag}"
        )
    print("-" * 82)
    stars = [p for p in modelled if p["edge_pct"] >= 2.0]
    print(f"\n  ★ = edge ≥ +2.0%  |  {len(stars)} strong plays found")
    if stars:
        print("\n  TOP PLAYS:")
        for p in stars:
            print(f"    {p['player']} {p['best_odds']:+d}  — model {p['model_win']:.1f}% vs market {p['market_impl']:.1f}%  (+{p['edge_pct']:.1f}% edge)")
            print(f"      Top 5: {p['top5_prob']:.0f}%  |  Top 10: {p['top10_prob']:.0f}%  |  Top 20: {p['top20_prob']:.0f}%  |  Book: {p['best_book']}")


def save_picks(picks: list[dict], d: date | None = None) -> Path:
    d = d or date.today()
    out_dir = Path("output/picks/golf_pga") / d.strftime("%Y%m%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "picks.json"
    with open(out_path, "w") as f:
        json.dump(picks, f, indent=2)
    print(f"\n  Saved → {out_path}")
    return out_path


if __name__ == "__main__":
    picks = run_pga_model(n_sim=100_000)
    if picks:
        print_report(picks, top_n=25)
        save_picks(picks)
