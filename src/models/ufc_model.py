"""
UFC Fight Model — Overlay

Glicko-2 ratings + style-matchup factors + Monte Carlo fight simulator.

Architecture:
  GlickoRating(mu, phi, sigma) — skill, deviation, volatility
  StyleProfile — reach, stance, ground/stand/clinch preference scores
  FightSimulator(n_sim) — samples outcomes from fighter distributions

Markets priced:
  - moneyline (win/loss/draw)
  - method of victory: KO/TKO, submission, decision (split/unanimous)
  - round betting: winner in round 1/2/3/4/5

Rating update formula (Glicko-2):
  See: http://www.glicko.net/glicko/glicko2.pdf

Style matchup factors:
  striker_vs_wrestler, wrestler_vs_striker, grappler_vs_grappler, etc.
  Applied as multipliers on finish probability.
"""
from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

MODEL_DIR = Path("data/models/ufc")

# ── Glicko-2 constants ────────────────────────────────────────────────────────

GLICKO_MU0    = 1500.0   # starting rating
GLICKO_PHI0   = 350.0    # starting RD (rating deviation)
GLICKO_SIGMA0 = 0.06     # starting volatility
GLICKO_TAU    = 0.5      # system constant (constrains volatility change)
GLICKO_Q      = math.log(10) / 400.0   # scaling constant


@dataclass
class GlickoRating:
    mu: float    = GLICKO_MU0
    phi: float   = GLICKO_PHI0
    sigma: float = GLICKO_SIGMA0

    def win_prob_vs(self, opponent: "GlickoRating") -> float:
        """P(self beats opponent) ignoring RD uncertainty (point estimate)."""
        return 1.0 / (1.0 + 10.0 ** ((opponent.mu - self.mu) / 400.0))


# ── Style profiles ────────────────────────────────────────────────────────────

@dataclass
class StyleProfile:
    """Fighter style encoding. Scores are 0–1 normalized."""
    striking:     float = 0.5   # striking skill (SLpM, sig_str_acc)
    wrestling:    float = 0.5   # takedown offense (TD avg, TD acc)
    grappling:    float = 0.5   # submission skill (sub avg)
    cardio:       float = 0.5   # pace/late-round strength
    chin:         float = 0.5   # knockdown resistance
    defense:      float = 0.5   # SApM, TD def, str def

    @property
    def style_label(self) -> str:
        scores = {
            "striker":  self.striking,
            "wrestler": self.wrestling,
            "grappler": self.grappling,
        }
        return max(scores, key=scores.get)


# Warm-start ratings for UFC fighters (approximate mid-2025)
FIGHTER_RATINGS: dict[str, dict] = {
    # UFC Champions / top contenders per division (May 2025)
    # Format: {"mu": elo, "style": {"striking": x, "wrestling": x, "grappling": x}}

    # Heavyweight
    "Jon Jones":         {"mu": 2050, "style": {"striking": 0.85, "wrestling": 0.80, "grappling": 0.85}},
    "Stipe Miocic":      {"mu": 1880, "style": {"striking": 0.80, "wrestling": 0.75, "grappling": 0.60}},
    "Tom Aspinall":      {"mu": 1930, "style": {"striking": 0.82, "wrestling": 0.65, "grappling": 0.75}},
    "Ciryl Gane":        {"mu": 1890, "style": {"striking": 0.85, "wrestling": 0.55, "grappling": 0.60}},
    "Sergei Pavlovich":  {"mu": 1860, "style": {"striking": 0.90, "wrestling": 0.40, "grappling": 0.35}},

    # Light Heavyweight
    "Alex Pereira":      {"mu": 1980, "style": {"striking": 0.92, "wrestling": 0.45, "grappling": 0.50}},
    "Jiri Prochazka":    {"mu": 1900, "style": {"striking": 0.88, "wrestling": 0.50, "grappling": 0.65}},
    "Magomed Ankalaev":  {"mu": 1880, "style": {"striking": 0.75, "wrestling": 0.80, "grappling": 0.72}},
    "Jamahal Hill":      {"mu": 1870, "style": {"striking": 0.85, "wrestling": 0.50, "grappling": 0.50}},

    # Middleweight
    "Dricus du Plessis": {"mu": 1960, "style": {"striking": 0.82, "wrestling": 0.75, "grappling": 0.80}},
    "Israel Adesanya":   {"mu": 1920, "style": {"striking": 0.93, "wrestling": 0.40, "grappling": 0.45}},
    "Sean Strickland":   {"mu": 1890, "style": {"striking": 0.83, "wrestling": 0.70, "grappling": 0.60}},
    "Robert Whittaker":  {"mu": 1900, "style": {"striking": 0.85, "wrestling": 0.65, "grappling": 0.55}},

    # Welterweight
    "Leon Edwards":      {"mu": 1950, "style": {"striking": 0.83, "wrestling": 0.70, "grappling": 0.65}},
    "Belal Muhammad":    {"mu": 1930, "style": {"striking": 0.72, "wrestling": 0.85, "grappling": 0.70}},
    "Colby Covington":   {"mu": 1880, "style": {"striking": 0.75, "wrestling": 0.90, "grappling": 0.65}},
    "Kamaru Usman":      {"mu": 1900, "style": {"striking": 0.80, "wrestling": 0.88, "grappling": 0.65}},
    "Sean Brady":        {"mu": 1850, "style": {"striking": 0.72, "wrestling": 0.85, "grappling": 0.80}},

    # Lightweight
    "Islam Makhachev":   {"mu": 2020, "style": {"striking": 0.80, "wrestling": 0.95, "grappling": 0.92}},
    "Dustin Poirier":    {"mu": 1900, "style": {"striking": 0.87, "wrestling": 0.65, "grappling": 0.70}},
    "Justin Gaethje":    {"mu": 1870, "style": {"striking": 0.90, "wrestling": 0.70, "grappling": 0.55}},
    "Charles Oliveira":  {"mu": 1920, "style": {"striking": 0.78, "wrestling": 0.72, "grappling": 0.95}},
    "Arman Tsarukyan":   {"mu": 1890, "style": {"striking": 0.80, "wrestling": 0.88, "grappling": 0.80}},

    # Featherweight
    "Ilia Topuria":      {"mu": 1970, "style": {"striking": 0.88, "wrestling": 0.72, "grappling": 0.82}},
    "Max Holloway":      {"mu": 1950, "style": {"striking": 0.90, "wrestling": 0.65, "grappling": 0.60}},
    "Alexander Volkanovski": {"mu": 1960, "style": {"striking": 0.87, "wrestling": 0.82, "grappling": 0.70}},
    "Brian Ortega":      {"mu": 1840, "style": {"striking": 0.75, "wrestling": 0.65, "grappling": 0.95}},

    # Bantamweight
    "Sean O'Malley":     {"mu": 1940, "style": {"striking": 0.90, "wrestling": 0.55, "grappling": 0.50}},
    "Merab Dvalishvili": {"mu": 1920, "style": {"striking": 0.72, "wrestling": 0.95, "grappling": 0.75}},
    "Petr Yan":          {"mu": 1880, "style": {"striking": 0.88, "wrestling": 0.78, "grappling": 0.70}},

    # Flyweight
    "Alexandre Pantoja": {"mu": 1920, "style": {"striking": 0.78, "wrestling": 0.80, "grappling": 0.90}},
    "Brandon Royval":    {"mu": 1860, "style": {"striking": 0.75, "wrestling": 0.70, "grappling": 0.88}},
    "Amir Albazi":       {"mu": 1850, "style": {"striking": 0.72, "wrestling": 0.78, "grappling": 0.85}},

    # Expanded roster (Tier 2 contenders / regular card fighters) — added 2026-06-12
    # Heavyweight
    "Curtis Blaydes":    {"mu": 1850, "style": {"striking": 0.70, "wrestling": 0.92, "grappling": 0.70}},
    "Alexander Volkov":  {"mu": 1830, "style": {"striking": 0.78, "wrestling": 0.55, "grappling": 0.60}},
    "Derrick Lewis":     {"mu": 1780, "style": {"striking": 0.85, "wrestling": 0.45, "grappling": 0.40}},
    "Jailton Almeida":   {"mu": 1820, "style": {"striking": 0.55, "wrestling": 0.88, "grappling": 0.92}},
    # Light Heavy
    "Carlos Ulberg":     {"mu": 1840, "style": {"striking": 0.86, "wrestling": 0.50, "grappling": 0.50}},
    "Khalil Rountree":   {"mu": 1830, "style": {"striking": 0.88, "wrestling": 0.45, "grappling": 0.45}},
    "Aleksandar Rakic":  {"mu": 1810, "style": {"striking": 0.82, "wrestling": 0.55, "grappling": 0.55}},
    # Middleweight
    "Khamzat Chimaev":   {"mu": 1980, "style": {"striking": 0.82, "wrestling": 0.92, "grappling": 0.88}},
    "Nassourdine Imavov": {"mu": 1870, "style": {"striking": 0.83, "wrestling": 0.72, "grappling": 0.68}},
    "Caio Borralho":     {"mu": 1860, "style": {"striking": 0.75, "wrestling": 0.80, "grappling": 0.80}},
    "Roman Dolidze":     {"mu": 1820, "style": {"striking": 0.78, "wrestling": 0.72, "grappling": 0.72}},
    # Welterweight
    "Shavkat Rakhmonov": {"mu": 1950, "style": {"striking": 0.82, "wrestling": 0.85, "grappling": 0.92}},
    "Ian Machado Garry": {"mu": 1860, "style": {"striking": 0.85, "wrestling": 0.65, "grappling": 0.65}},
    "Jack Della Maddalena": {"mu": 1900, "style": {"striking": 0.88, "wrestling": 0.65, "grappling": 0.65}},
    "Gilbert Burns":     {"mu": 1840, "style": {"striking": 0.78, "wrestling": 0.75, "grappling": 0.90}},
    "Michael Page":      {"mu": 1820, "style": {"striking": 0.92, "wrestling": 0.45, "grappling": 0.50}},
    "Carlos Prates":     {"mu": 1830, "style": {"striking": 0.90, "wrestling": 0.50, "grappling": 0.55}},
    # Lightweight
    "Paddy Pimblett":    {"mu": 1820, "style": {"striking": 0.75, "wrestling": 0.68, "grappling": 0.85}},
    "Renato Moicano":    {"mu": 1840, "style": {"striking": 0.78, "wrestling": 0.65, "grappling": 0.85}},
    "Mateusz Gamrot":    {"mu": 1850, "style": {"striking": 0.75, "wrestling": 0.90, "grappling": 0.78}},
    "Beneil Dariush":    {"mu": 1830, "style": {"striking": 0.75, "wrestling": 0.70, "grappling": 0.88}},
    "Rafael Fiziev":     {"mu": 1830, "style": {"striking": 0.88, "wrestling": 0.55, "grappling": 0.55}},
    # Featherweight
    "Movsar Evloev":     {"mu": 1900, "style": {"striking": 0.72, "wrestling": 0.92, "grappling": 0.80}},
    "Diego Lopes":       {"mu": 1880, "style": {"striking": 0.85, "wrestling": 0.65, "grappling": 0.85}},
    "Arnold Allen":      {"mu": 1860, "style": {"striking": 0.85, "wrestling": 0.60, "grappling": 0.60}},
    "Yair Rodriguez":    {"mu": 1840, "style": {"striking": 0.88, "wrestling": 0.55, "grappling": 0.65}},
    "Lerone Murphy":     {"mu": 1830, "style": {"striking": 0.82, "wrestling": 0.65, "grappling": 0.62}},
    # Bantamweight
    "Umar Nurmagomedov": {"mu": 1900, "style": {"striking": 0.80, "wrestling": 0.92, "grappling": 0.85}},
    "Cory Sandhagen":    {"mu": 1880, "style": {"striking": 0.85, "wrestling": 0.65, "grappling": 0.70}},
    "Deiveson Figueiredo": {"mu": 1850, "style": {"striking": 0.82, "wrestling": 0.65, "grappling": 0.78}},
    "Henry Cejudo":      {"mu": 1830, "style": {"striking": 0.78, "wrestling": 0.95, "grappling": 0.60}},
    "Marlon Vera":       {"mu": 1820, "style": {"striking": 0.82, "wrestling": 0.60, "grappling": 0.78}},
    # Flyweight
    "Brandon Moreno":    {"mu": 1900, "style": {"striking": 0.78, "wrestling": 0.72, "grappling": 0.82}},
    "Kai Kara-France":   {"mu": 1820, "style": {"striking": 0.85, "wrestling": 0.55, "grappling": 0.55}},
    "Manel Kape":        {"mu": 1820, "style": {"striking": 0.85, "wrestling": 0.55, "grappling": 0.60}},

    # Mid-card / specific upcoming-card fighters (June 2026 White House show + adj.)
    "Michael Chandler":  {"mu": 1850, "style": {"striking": 0.82, "wrestling": 0.82, "grappling": 0.65}},
    "Mauricio Ruffy":    {"mu": 1810, "style": {"striking": 0.87, "wrestling": 0.55, "grappling": 0.55}},
    "Bo Nickal":         {"mu": 1850, "style": {"striking": 0.65, "wrestling": 0.95, "grappling": 0.85}},
    "Kyle Daukaus":      {"mu": 1750, "style": {"striking": 0.65, "wrestling": 0.78, "grappling": 0.82}},
    "Tony Ferguson":     {"mu": 1720, "style": {"striking": 0.80, "wrestling": 0.55, "grappling": 0.78}},
    "Aiemann Zahabi":    {"mu": 1760, "style": {"striking": 0.75, "wrestling": 0.65, "grappling": 0.65}},
    "Josh Hokit":        {"mu": 1700, "style": {"striking": 0.65, "wrestling": 0.75, "grappling": 0.55}},
    "Steve Garcia Jr.":  {"mu": 1810, "style": {"striking": 0.82, "wrestling": 0.62, "grappling": 0.65}},
    "Steve Garcia":      {"mu": 1810, "style": {"striking": 0.82, "wrestling": 0.62, "grappling": 0.65}},
    "Mauricio Lopes":    {"mu": 1810, "style": {"striking": 0.87, "wrestling": 0.55, "grappling": 0.55}},   # alias for Ruffy
}

# Base finish probabilities by weight class (from historical UFC data)
BASE_FINISH_RATES: dict[str, dict[str, float]] = {
    "heavyweight":       {"ko_tko": 0.55, "submission": 0.12, "decision": 0.33},
    "light_heavyweight": {"ko_tko": 0.48, "submission": 0.16, "decision": 0.36},
    "middleweight":      {"ko_tko": 0.38, "submission": 0.20, "decision": 0.42},
    "welterweight":      {"ko_tko": 0.32, "submission": 0.22, "decision": 0.46},
    "lightweight":       {"ko_tko": 0.30, "submission": 0.24, "decision": 0.46},
    "featherweight":     {"ko_tko": 0.28, "submission": 0.25, "decision": 0.47},
    "bantamweight":      {"ko_tko": 0.25, "submission": 0.22, "decision": 0.53},
    "flyweight":         {"ko_tko": 0.20, "submission": 0.25, "decision": 0.55},
    "default":           {"ko_tko": 0.32, "submission": 0.22, "decision": 0.46},
}

# Style matchup multipliers: (attacker_style, defender_style) → finish_probability_modifier
# Values > 1 increase finish probability for that method
STYLE_MATCHUP: dict[tuple[str, str], dict[str, float]] = {
    ("striker",  "striker"):  {"ko_tko": 1.20, "submission": 0.70},
    ("striker",  "wrestler"): {"ko_tko": 0.90, "submission": 0.80, "decision": 1.15},
    ("striker",  "grappler"): {"ko_tko": 1.05, "submission": 1.15},
    ("wrestler", "striker"):  {"ko_tko": 0.80, "submission": 1.10, "decision": 1.15},
    ("wrestler", "wrestler"): {"ko_tko": 0.85, "submission": 0.90, "decision": 1.20},
    ("wrestler", "grappler"): {"ko_tko": 0.80, "submission": 1.25, "decision": 1.10},
    ("grappler", "striker"):  {"ko_tko": 0.75, "submission": 1.30},
    ("grappler", "wrestler"): {"ko_tko": 0.80, "submission": 1.20},
    ("grappler", "grappler"): {"ko_tko": 0.70, "submission": 1.30, "decision": 1.10},
}


# ── Fight outcome simulator ───────────────────────────────────────────────────

class FightResult:
    """
    Holds simulation output for a single matchup.
    Prices moneyline, method, and round props.
    """

    def __init__(
        self,
        fighter_a: str,
        fighter_b: str,
        a_wins:   np.ndarray,   # (n_sim,) bool
        methods:  np.ndarray,   # (n_sim,) str: ko_tko | submission | decision
        rounds:   np.ndarray,   # (n_sim,) int: 1..5
        n_sim:    int,
        n_rounds: int,
    ) -> None:
        self.fighter_a = fighter_a
        self.fighter_b = fighter_b
        self.a_wins    = a_wins
        self.methods   = methods
        self.rounds    = rounds
        self.n_sim     = n_sim
        self.n_rounds  = n_rounds

    def win_prob(self, fighter: str) -> float:
        if fighter == self.fighter_a:
            return float(self.a_wins.mean())
        return float((~self.a_wins).mean())

    def method_prob(self, method: str) -> float:
        """P(fight ends by method), winner-agnostic."""
        return float((self.methods == method).mean())

    def round_prob(self, r: int) -> float:
        """P(fight ends in round r)."""
        return float((self.rounds == r).mean())

    def win_by_method_prob(self, fighter: str, method: str) -> float:
        """P(fighter wins AND by method)."""
        wins = self.a_wins if fighter == self.fighter_a else ~self.a_wins
        return float((wins & (self.methods == method)).mean())

    def win_in_round_prob(self, fighter: str, r: int) -> float:
        """P(fighter wins AND in round r)."""
        wins = self.a_wins if fighter == self.fighter_a else ~self.a_wins
        return float((wins & (self.rounds == r)).mean())

    def goes_distance_prob(self) -> float:
        return self.method_prob("decision")

    def summary(self) -> dict[str, Any]:
        return {
            self.fighter_a: {
                "win":       self.win_prob(self.fighter_a),
                "ko_tko":    self.win_by_method_prob(self.fighter_a, "ko_tko"),
                "submission": self.win_by_method_prob(self.fighter_a, "submission"),
                "decision":  self.win_by_method_prob(self.fighter_a, "decision"),
            },
            self.fighter_b: {
                "win":       self.win_prob(self.fighter_b),
                "ko_tko":    self.win_by_method_prob(self.fighter_b, "ko_tko"),
                "submission": self.win_by_method_prob(self.fighter_b, "submission"),
                "decision":  self.win_by_method_prob(self.fighter_b, "decision"),
            },
            "goes_distance": self.goes_distance_prob(),
            "method_probs": {
                "ko_tko":     self.method_prob("ko_tko"),
                "submission": self.method_prob("submission"),
                "decision":   self.method_prob("decision"),
            },
            "round_probs": {r: self.round_prob(r) for r in range(1, self.n_rounds + 1)},
        }


class UFCModel:
    """
    UFC fight outcome model using Glicko-2 + style matchup + Monte Carlo simulation.
    """

    def __init__(self) -> None:
        self.ratings: dict[str, GlickoRating] = {}
        self.styles:  dict[str, StyleProfile]  = {}
        self._load_warm_start()

    def _load_warm_start(self) -> None:
        for name, data in FIGHTER_RATINGS.items():
            self.ratings[name] = GlickoRating(mu=data["mu"])
            s = data.get("style", {})
            self.styles[name] = StyleProfile(
                striking  = s.get("striking", 0.5),
                wrestling = s.get("wrestling", 0.5),
                grappling = s.get("grappling", 0.5),
            )

    def _fuzzy_match(self, fighter: str) -> str | None:
        """
        Match last-name only — first-name collisions like "Michael Chandler" vs
        "Michael Page" silently grabbed the wrong rating before this fix.
        Two-step: exact, then last-name strict equality.
        """
        if fighter in self.ratings:
            return fighter
        parts = fighter.strip().split()
        if not parts:
            return None
        target_last = parts[-1].lower().strip(".")
        for name in self.ratings:
            cand_last = name.split()[-1].lower().strip(".")
            if cand_last == target_last and len(cand_last) > 3:
                return name
        return None

    def _get_rating(self, fighter: str) -> GlickoRating:
        name = self._fuzzy_match(fighter)
        return self.ratings[name] if name else GlickoRating()

    def _is_known_fighter(self, fighter: str) -> bool:
        return self._fuzzy_match(fighter) is not None

    def _get_style(self, fighter: str) -> StyleProfile:
        name = self._fuzzy_match(fighter)
        return self.styles[name] if name and name in self.styles else StyleProfile()

    def simulate_fight(
        self,
        fighter_a: str,
        fighter_b: str,
        weight_class: str = "default",
        n_rounds:  int  = 3,
        n_sim:     int  = 50_000,
        seed:      int  = 42,
    ) -> FightResult:
        """
        Monte Carlo fight simulation.

        Method:
          1. Compute win probability from Glicko ratings
          2. Adjust method/round distributions by style matchup
          3. Sample outcomes
        """
        rng = np.random.default_rng(seed)

        # 1. Win probability from Glicko
        ra = self._get_rating(fighter_a)
        rb = self._get_rating(fighter_b)
        p_a_wins = ra.win_prob_vs(rb)

        # Uncertainty: add RD-based noise
        elo_std = math.sqrt(ra.phi ** 2 + rb.phi ** 2) / 400.0
        noise   = rng.normal(0, elo_std, n_sim)
        p_a_base = 1.0 / (1.0 + np.exp(-4.0 * (p_a_wins - 0.5 + noise)))

        a_wins = rng.random(n_sim) < p_a_base

        # 2. Method distribution from base rates + style matchup
        wc_key  = weight_class.lower().replace(" ", "_")
        base    = BASE_FINISH_RATES.get(wc_key, BASE_FINISH_RATES["default"])
        p_ko    = base["ko_tko"]
        p_sub   = base["submission"]
        p_dec   = base["decision"]

        sa = self._get_style(fighter_a)
        sb = self._get_style(fighter_b)

        # Apply style matchup modifiers (symmetric avg of both directions)
        mods_ab = STYLE_MATCHUP.get((sa.style_label, sb.style_label), {})
        mods_ba = STYLE_MATCHUP.get((sb.style_label, sa.style_label), {})
        ko_mult  = (mods_ab.get("ko_tko", 1.0) + mods_ba.get("ko_tko", 1.0)) / 2.0
        sub_mult = (mods_ab.get("submission", 1.0) + mods_ba.get("submission", 1.0)) / 2.0
        dec_mult = (mods_ab.get("decision", 1.0) + mods_ba.get("decision", 1.0)) / 2.0

        p_ko  *= ko_mult
        p_sub *= sub_mult
        p_dec *= dec_mult
        total  = p_ko + p_sub + p_dec
        p_ko, p_sub, p_dec = p_ko / total, p_sub / total, p_dec / total

        method_roll = rng.random(n_sim)
        methods = np.where(
            method_roll < p_ko,  "ko_tko",
            np.where(method_roll < p_ko + p_sub, "submission", "decision")
        )

        # 3. Round distribution
        # Finishes: early rounds more likely for KO/TKO (front-loaded)
        # Decisions always go to the max round
        rounds = np.full(n_sim, n_rounds, dtype=int)
        finish_mask = methods != "decision"
        n_finish    = finish_mask.sum()
        if n_finish > 0:
            # Geometric-ish distribution skewed to early rounds
            weights = np.array([1.0 / r for r in range(1, n_rounds + 1)])
            # KO finishes: heavier early (rounds 1-2)
            ko_mask = (methods == "ko_tko") & finish_mask
            sub_mask = (methods == "submission") & finish_mask
            if ko_mask.sum() > 0:
                ko_weights = weights.copy()
                ko_weights[0] *= 1.8  # R1 spike
                ko_weights /= ko_weights.sum()
                rounds[ko_mask] = rng.choice(
                    range(1, n_rounds + 1), size=ko_mask.sum(), p=ko_weights
                )
            if sub_mask.sum() > 0:
                sub_weights = weights.copy()
                sub_weights /= sub_weights.sum()
                rounds[sub_mask] = rng.choice(
                    range(1, n_rounds + 1), size=sub_mask.sum(), p=sub_weights
                )

        return FightResult(fighter_a, fighter_b, a_wins, methods, rounds, n_sim, n_rounds)

    def find_edges(
        self,
        events: list[dict],
        weight_classes: dict[str, str] | None = None,
        n_sim:          int   = 50_000,
        min_edge_pct:   float = 3.0,
        is_main_card:   bool  = True,
        blend_alpha:    float = 0.40,
    ) -> list[dict]:
        """
        Find edges in UFC card odds — moneyline, method-of-victory, round props.

        events: Odds API format events list with h2h (and optionally
                fight_result_method, total_rounds) markets.
        weight_classes: {"{fighter_a} vs {fighter_b}": "lightweight"} — optional.

        Calibration: until a fitted MMA calibrator exists, raw model probs are
        shrunk toward market via blend (alpha=0.40). Same analytic Platt-equivalent
        used by the WC pipeline (see scripts/wc_data.py). The model_prob written
        to picks.json is the BLENDED value so edge math and downstream calibrator
        training agree. Raw simulation output preserved as model_prob_raw.
        """
        wc_map = weight_classes or {}
        edges  = []

        # Calibrator — works once recalibrate_all() has fit a fileset; until then
        # it's a no-op pass-through (graceful degradation).
        try:
            from src.analytics.calibration import apply_calibration
        except Exception:
            apply_calibration = lambda p, s, m: p   # noqa: E731

        for event in events:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            if not home or not away:
                continue

            wc_key = wc_map.get(f"{away} vs {home}", wc_map.get(f"{home} vs {away}", "default"))
            n_rounds = 5 if is_main_card else 3

            home_known = self._is_known_fighter(home)
            away_known = self._is_known_fighter(away)
            both_unknown = not home_known and not away_known

            sim = self.simulate_fight(home, away, weight_class=wc_key, n_rounds=n_rounds, n_sim=n_sim)

            # Discover all market types this event has so we can attach prop edges
            mkt_by_key: dict[str, dict] = {}   # market_key -> {book: outcomes_list}
            for bookmaker in event.get("bookmakers", []):
                book = bookmaker.get("title", "")
                for market in bookmaker.get("markets", []):
                    k = market.get("key")
                    mkt_by_key.setdefault(k, {})[book] = market.get("outcomes", [])

            # ── Moneyline ─────────────────────────────────────────────────────
            for book, outcomes in mkt_by_key.get("h2h", {}).items():
                if len(outcomes) < 2:
                    continue
                total_imp = sum(_american_to_imp(float(o.get("price", -110))) for o in outcomes)
                if total_imp <= 0:
                    continue
                for o in outcomes:
                    fighter = o.get("name", "")
                    price   = float(o.get("price", 0))
                    if not price:
                        continue
                    imp_fair = _american_to_imp(price) / total_imp
                    raw_p    = sim.win_prob(fighter)
                    # Calibrate then blend toward market (cascade: file calibrator wins,
                    # falls back to market-blend shrinkage)
                    cal_p    = apply_calibration(raw_p, "mma", "moneyline")
                    if cal_p == raw_p:   # no fitted calibrator yet → fall back to blend
                        model_p = blend_alpha * raw_p + (1 - blend_alpha) * imp_fair
                    else:
                        model_p = cal_p
                    edge = (model_p - imp_fair) * 100.0
                    if edge < min_edge_pct:
                        continue
                    if both_unknown:
                        print(f"  [UFC] SKIP {fighter} edge={edge:+.1f}% — both fighters unknown")
                        continue
                    summ = sim.summary()
                    fighter_summ = summ.get(fighter, {})
                    fighter_known = self._is_known_fighter(fighter)
                    edges.append({
                        "market":         "moneyline",
                        "direction":      "WIN",
                        "fighter":        fighter,
                        "team":           fighter,
                        "matchup":        f"{away} vs {home}",
                        "odds":           int(price),
                        "model_prob":     round(model_p, 4),
                        "model_prob_raw": round(raw_p, 4),
                        "implied_prob":   round(imp_fair, 4),
                        "edge_pct":       round(edge, 2),
                        "sportsbook":     book,
                        "ko_tko":         round(fighter_summ.get("ko_tko", 0), 3),
                        "submission":     round(fighter_summ.get("submission", 0), 3),
                        "decision":       round(fighter_summ.get("decision", 0), 3),
                        "data_quality":   "known" if fighter_known else "unknown_fighter",
                    })

            # ── Method-of-victory props (Fighter X by KO/sub/decision) ────────
            # Market key: "fight_result_method" — outcomes are "{fighter} - {method}"
            for book, outcomes in mkt_by_key.get("fight_result_method", {}).items():
                if not outcomes:
                    continue
                total_imp = sum(_american_to_imp(float(o.get("price", -110))) for o in outcomes)
                if total_imp <= 0:
                    continue
                summ = sim.summary()
                for o in outcomes:
                    nm = o.get("name", "") or o.get("description", "")
                    price = float(o.get("price", 0))
                    if not (nm and price):
                        continue
                    # Parse "Fighter - Method" — varies by book
                    parts = nm.split(" - ") if " - " in nm else nm.rsplit(" by ", 1)
                    if len(parts) != 2:
                        continue
                    fighter, method_raw = parts[0].strip(), parts[1].strip().lower()
                    method = ("ko_tko" if any(k in method_raw for k in ("ko", "tko", "knockout"))
                              else "submission" if "sub" in method_raw
                              else "decision" if "decision" in method_raw or "points" in method_raw
                              else None)
                    if method is None:
                        continue
                    raw_p = summ.get(fighter, {}).get(method, 0.0)
                    if raw_p <= 0:
                        continue
                    imp_fair = _american_to_imp(price) / total_imp
                    cal_p = apply_calibration(raw_p, "mma", "prop")
                    if cal_p == raw_p:
                        model_p = blend_alpha * raw_p + (1 - blend_alpha) * imp_fair
                    else:
                        model_p = cal_p
                    edge = (model_p - imp_fair) * 100.0
                    if edge < min_edge_pct or both_unknown:
                        continue
                    edges.append({
                        "market":         "method_of_victory",
                        "direction":      method.upper(),
                        "fighter":        fighter,
                        "team":           fighter,
                        "matchup":        f"{away} vs {home}",
                        "odds":           int(price),
                        "model_prob":     round(model_p, 4),
                        "model_prob_raw": round(raw_p, 4),
                        "implied_prob":   round(imp_fair, 4),
                        "edge_pct":       round(edge, 2),
                        "sportsbook":     book,
                        "data_quality":   "known" if self._is_known_fighter(fighter) else "unknown_fighter",
                    })

            # ── Total rounds / Goes-the-distance ─────────────────────────────
            # Market key: "total_rounds" (Over/Under {1.5,2.5,3.5})
            for book, outcomes in mkt_by_key.get("total_rounds", {}).items():
                if len(outcomes) < 2:
                    continue
                pairs: dict[float, dict] = {}
                for o in outcomes:
                    pt = o.get("point")
                    if pt is None: continue
                    pairs.setdefault(float(pt), {})[o.get("name", "").lower()] = float(o.get("price", -110))
                for pt, sides in pairs.items():
                    if "over" not in sides or "under" not in sides:
                        continue
                    o_p, u_p = sides["over"], sides["under"]
                    total_imp = _american_to_imp(o_p) + _american_to_imp(u_p)
                    if total_imp <= 0: continue
                    # Model P(over): fight goes past round pt → ends in round > pt
                    # sim records ko_round / sub_round / decision (full distance)
                    raw_p_over = sim.goes_distance_prob() if pt >= n_rounds - 0.5 else _prob_past_round(sim, pt)
                    for side, price in (("OVER", o_p), ("UNDER", u_p)):
                        raw_p = raw_p_over if side == "OVER" else 1 - raw_p_over
                        if raw_p <= 0: continue
                        imp_fair = _american_to_imp(price) / total_imp
                        cal_p = apply_calibration(raw_p, "mma", "total")
                        if cal_p == raw_p:
                            model_p = blend_alpha * raw_p + (1 - blend_alpha) * imp_fair
                        else:
                            model_p = cal_p
                        edge = (model_p - imp_fair) * 100.0
                        if edge < min_edge_pct or both_unknown:
                            continue
                        edges.append({
                            "market":         "total_rounds",
                            "direction":      side,
                            "fighter":        f"{away} vs {home}",   # no fighter — fight-level
                            "team":           f"{side} {pt} rounds",
                            "matchup":        f"{away} vs {home}",
                            "line":           pt,
                            "odds":           int(price),
                            "model_prob":     round(model_p, 4),
                            "model_prob_raw": round(raw_p, 4),
                            "implied_prob":   round(imp_fair, 4),
                            "edge_pct":       round(edge, 2),
                            "sportsbook":     book,
                            "data_quality":   "known" if (home_known and away_known) else "partial_unknown",
                        })

        return sorted(edges, key=lambda x: x["edge_pct"], reverse=True)


def _american_to_imp(o: float) -> float:
    if o >= 0:
        return 100.0 / (o + 100.0)
    return abs(o) / (abs(o) + 100.0)


def _prob_past_round(sim: "FightResult", point: float) -> float:
    """
    P(fight ends in a round strictly after `point`).
    A 1.5-round line cashes OVER iff the fight reaches round 2 or later.
    Decision-fights (rounds == n_rounds with full distance) count as past every line.
    """
    import math as _m
    cutoff = int(_m.floor(point)) + 1   # 1.5 → past round 1 means round ≥ 2
    return float((sim.rounds >= cutoff).mean())


def get_ufc_model() -> UFCModel:
    return UFCModel()
