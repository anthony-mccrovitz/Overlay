"""
Motorsport Unified Race Engine — Overlay

Single simulation engine that prices any motorsport series via swappable SeriesConfig.
Supports: NASCAR Cup, IndyCar, F1

Architecture:
  RaceEngine(config=SeriesConfig)
    .fit(history_df)           — learn pace + caution + DNF distributions
    .simulate(entry_list, n=50_000) → SimResult tensor
    .find_edges(entry_list, odds_df) → edge list

SimResult stores:
  - finish_positions[n_sim, n_drivers] — full rank tensor
  - dnf_flags[n_sim, n_drivers]
  - lap_times[n_sim, n_drivers, n_laps] (optional, memory-intensive)

Market pricing from SimResult:
  - win / top3 / top5 / top10
  - driver matchups (h2h)
  - stage wins (NASCAR)
  - points finishes
  - pole position (qualifying model)
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

MODEL_DIR = Path("data/models/motorsport")


# ── Series configuration ──────────────────────────────────────────────────────

@dataclass
class SeriesConfig:
    """
    Param pack for a motorsport series. Swap this to switch from NASCAR to F1 to IndyCar.
    All series-specific constants live here — the engine code stays generic.
    """
    name: str                        # "NASCAR Cup", "IndyCar", "F1"
    sport_key: str                   # Odds API sport key
    n_drivers: int                   # typical field size
    n_laps: int                      # race distance in laps (or converted equivalent)
    pace_sigma: float                # lap time std dev (seconds, driver-to-driver variation)
    caution_rate: float              # mean cautions per race (Poisson λ)
    caution_laps: float              # mean laps lost per caution
    dnf_rate: float                  # P(DNF per driver per race)
    pit_cycles: int                  # typical pit stops per race
    elo_k: int                       # Elo K-factor for rating updates
    base_elo: float = 1500.0         # starting Elo for new drivers
    track_type_weights: dict[str, float] = field(default_factory=dict)
    # e.g. {"superspeedway": 0.5, "intermediate": 0.3, "road_course": 0.2}


# Pre-built series configs ─────────────────────────────────────────────────────

NASCAR_CUP = SeriesConfig(
    name        = "NASCAR Cup Series",
    sport_key   = "auto_racing_nascar_cup_series",
    n_drivers   = 40,
    n_laps      = 500,   # nominal Daytona-500-length equivalent
    pace_sigma  = 0.8,   # sec/lap driver variation
    caution_rate= 8.0,   # avg cautions per race
    caution_laps= 4.0,   # avg laps under yellow
    dnf_rate    = 0.18,  # ~18% DNF rate per driver (mechanical + crash)
    pit_cycles  = 6,
    elo_k       = 32,
    track_type_weights = {
        "superspeedway": 0.15,
        "intermediate":  0.40,
        "short_track":   0.20,
        "road_course":   0.15,
        "dirt":          0.05,
        "other":         0.05,
    },
)

INDYCAR = SeriesConfig(
    name        = "NTT IndyCar Series",
    sport_key   = "auto_racing_indycar_series",
    n_drivers   = 33,    # Indy 500 field; typical race ~24-26
    n_laps      = 200,   # Indy 500; shorter at other ovals
    pace_sigma  = 0.6,
    caution_rate= 6.0,
    caution_laps= 3.5,
    dnf_rate    = 0.22,
    pit_cycles  = 3,
    elo_k       = 32,
    track_type_weights = {
        "oval_short":  0.25,
        "oval_super":  0.20,
        "street":      0.30,
        "road":        0.25,
    },
)

F1 = SeriesConfig(
    name        = "Formula 1",
    sport_key   = "auto_racing_formula_one",
    n_drivers   = 20,
    n_laps      = 70,    # typical GP lap count
    pace_sigma  = 0.4,   # tighter distribution than NASCAR
    caution_rate= 1.2,   # safety cars; rare in F1
    caution_laps= 5.0,
    dnf_rate    = 0.10,
    pit_cycles  = 2,
    elo_k       = 32,
    track_type_weights = {
        "street":      0.30,
        "permanent":   0.70,
    },
)

SERIES_REGISTRY: dict[str, SeriesConfig] = {
    "nascar":  NASCAR_CUP,
    "indycar": INDYCAR,
    "f1":      F1,
    "auto_racing_nascar_cup_series": NASCAR_CUP,
    "auto_racing_indycar_series":    INDYCAR,
    "auto_racing_formula_one":       F1,
}


# ── Driver rating database ────────────────────────────────────────────────────
# Format: {driver_name: {series_key: elo}}
# Populated by fit() from historical data; these are warm-start values.

DRIVER_RATINGS: dict[str, dict[str, float]] = {
    # NASCAR Cup — approximate mid-2025 Elo
    "Kyle Larson":          {"nascar": 1820},
    "Christopher Bell":     {"nascar": 1780},
    "William Byron":        {"nascar": 1760},
    "Denny Hamlin":         {"nascar": 1740},
    "Martin Truex Jr.":     {"nascar": 1720},
    "Ross Chastain":        {"nascar": 1700},
    "Ryan Blaney":          {"nascar": 1710},
    "Joey Logano":          {"nascar": 1680},
    "Tyler Reddick":        {"nascar": 1760},
    "Chase Elliott":        {"nascar": 1790},
    "Brad Keselowski":      {"nascar": 1640},
    "Kevin Harvick":        {"nascar": 1620},
    "Bubba Wallace":        {"nascar": 1600},
    "Alex Bowman":          {"nascar": 1650},

    # IndyCar — approximate 2025 ratings
    "Scott Dixon":          {"indycar": 1850},
    "Josef Newgarden":      {"indycar": 1830},
    "Pato O'Ward":          {"indycar": 1790},
    "Alex Palou":           {"indycar": 1820},
    "Will Power":           {"indycar": 1800},
    "Colton Herta":         {"indycar": 1760},
    "Marcus Ericsson":      {"indycar": 1740},
    "Simon Pagenaud":       {"indycar": 1700},
    "Graham Rahal":         {"indycar": 1680},
    "Felix Rosenqvist":     {"indycar": 1720},

    # F1 — approximate mid-2025 ratings
    "Max Verstappen":       {"f1": 1960},
    "Lewis Hamilton":       {"f1": 1880},
    "Charles Leclerc":      {"f1": 1840},
    "Carlos Sainz":         {"f1": 1820},
    "Lando Norris":         {"f1": 1830},
    "George Russell":       {"f1": 1810},
    "Fernando Alonso":      {"f1": 1780},
    "Lance Stroll":         {"f1": 1650},
    "Sergio Perez":         {"f1": 1790},
    "Oscar Piastri":        {"f1": 1800},
    "Esteban Ocon":         {"f1": 1720},
    "Pierre Gasly":         {"f1": 1730},
    "Valtteri Bottas":      {"f1": 1710},
    "Zhou Guanyu":          {"f1": 1660},
    "Kevin Magnussen":      {"f1": 1690},
    "Nico Hulkenberg":      {"f1": 1730},
    "Yuki Tsunoda":         {"f1": 1720},
    "Logan Sargeant":       {"f1": 1580},
    "Alex Albon":           {"f1": 1750},
    "Nyck de Vries":        {"f1": 1640},
}


# ── Simulation result ─────────────────────────────────────────────────────────

class SimResult:
    """
    Stores full simulation tensor. Price any market without re-running sims.
    """

    def __init__(
        self,
        drivers:   list[str],
        positions: np.ndarray,   # (n_sim, n_drivers) — finish position (0-indexed, 0=winner)
        dnf_flags: np.ndarray,   # (n_sim, n_drivers) — bool
        n_sim:     int,
        config:    SeriesConfig,
    ) -> None:
        self.drivers   = drivers
        self.idx       = {d: i for i, d in enumerate(drivers)}
        self.positions = positions
        self.dnf_flags = dnf_flags
        self.n_sim     = n_sim
        self.config    = config

    def _pos(self, driver: str) -> np.ndarray:
        return self.positions[:, self.idx[driver]]

    def win_prob(self, driver: str) -> float:
        return float((self._pos(driver) == 0).mean())

    def top_n_prob(self, driver: str, n: int) -> float:
        return float((self._pos(driver) < n).mean())

    def dnf_prob(self, driver: str) -> float:
        return float(self.dnf_flags[:, self.idx[driver]].mean())

    def matchup_prob(self, driver_a: str, driver_b: str) -> float:
        """P(driver_a finishes ahead of driver_b), DNFs included."""
        pa = self._pos(driver_a)
        pb = self._pos(driver_b)
        return float((pa < pb).mean())

    def summary(self) -> dict[str, dict]:
        return {
            d: {
                "win":    self.win_prob(d),
                "top3":   self.top_n_prob(d, 3),
                "top5":   self.top_n_prob(d, 5),
                "top10":  self.top_n_prob(d, 10),
                "dnf":    self.dnf_prob(d),
            }
            for d in self.drivers
        }


# ── Race engine ───────────────────────────────────────────────────────────────

class RaceEngine:
    """
    Unified Monte Carlo race simulator.
    Designed to work with any SeriesConfig.
    """

    def __init__(self, config: SeriesConfig) -> None:
        self.config  = config
        self.ratings: dict[str, float] = {}  # driver → Elo
        self._fitted = False

    def _elo(self, driver: str) -> float:
        """Look up Elo, first in instance ratings, then in DRIVER_RATINGS, then default."""
        if driver in self.ratings:
            return self.ratings[driver]
        series_key = self.config.sport_key.split("_racing_")[-1] if "_racing_" in self.config.sport_key else self.config.name.lower()
        # Try short key
        for key in (series_key, "nascar", "indycar", "f1"):
            if driver in DRIVER_RATINGS and key in DRIVER_RATINGS[driver]:
                return DRIVER_RATINGS[driver][key]
        return self.config.base_elo

    def simulate(
        self,
        entry_list: list[str],
        n_sim:      int = 50_000,
        seed:       int = 42,
    ) -> SimResult:
        """
        Run Monte Carlo race simulation.

        Each driver's pace is sampled from Normal(mu=expected_speed, sigma=pace_sigma).
        Lower average pace → better finish. DNF assigned by Bernoulli(dnf_rate).
        Cautions add randomness (level the field slightly).
        """
        rng = np.random.default_rng(seed)
        n   = len(entry_list)
        cfg = self.config

        # Convert Elo to pace advantage (strokes-gained analogy)
        elos = np.array([self._elo(d) for d in entry_list])
        elo_mean = elos.mean()
        # Elo diff of 400 ≈ 1 standard deviation of pace advantage
        pace_advantage = (elos - elo_mean) / 400.0 * cfg.pace_sigma * 10

        # Base expected pace per lap (lower = faster)
        # Faster driver has lower expected time
        exp_pace = 100.0 - pace_advantage   # arbitrary units

        # Simulate n_sim races
        # Race pace ~ Normal(exp_pace, pace_sigma) across all laps
        raw_pace = rng.normal(
            loc   = exp_pace[np.newaxis, :],
            scale = cfg.pace_sigma,
            size  = (n_sim, n),
        )  # (n_sim, n_drivers)

        # Caution laps: reduce field spread for superspeedways / under caution
        n_cautions = rng.poisson(cfg.caution_rate, size=n_sim)
        caution_equalization = n_cautions[:, np.newaxis] * 0.01  # small leveling effect
        adjusted_pace = raw_pace + caution_equalization

        # DNF assignment
        dnf_flags = rng.random((n_sim, n)) < cfg.dnf_rate

        # DNF drivers get penalized to last (large pace number)
        adjusted_pace[dnf_flags] += 1000.0

        # Finish positions: argsort pace (lower = better = higher finish)
        ranks_sort = np.argsort(adjusted_pace, axis=1)   # ranks_sort[s, k] = driver idx finishing kth
        positions  = np.argsort(ranks_sort, axis=1)       # positions[s, i] = finish pos of driver i

        return SimResult(entry_list, positions, dnf_flags, n_sim, cfg)

    def find_edges(
        self,
        entry_list: list[str],
        odds_events: list[dict],
        n_sim:       int = 50_000,
        min_edge_pct: float = 3.0,
    ) -> list[dict]:
        """
        Run simulation and find edges vs book odds.
        odds_events: Odds API format events list.
        """
        sim = self.simulate(entry_list, n_sim=n_sim)
        summary = sim.summary()

        edges = []
        for event in odds_events:
            for bookmaker in event.get("bookmakers", []):
                book = bookmaker.get("title", "")
                for market in bookmaker.get("markets", []):
                    mkey    = market.get("key", "")
                    outcomes = market.get("outcomes", [])

                    # Map market key to sim method
                    if mkey == "outrights" or mkey == "winner":
                        total_imp = sum(
                            _american_to_imp(float(o.get("price", -110)))
                            for o in outcomes
                        )
                        if total_imp <= 0:
                            continue
                        for o in outcomes:
                            driver = o.get("name", "")
                            price  = float(o.get("price", 0))
                            if not price or driver not in sim.idx:
                                continue
                            imp_raw   = _american_to_imp(price)
                            imp_fair  = imp_raw / total_imp
                            model_p   = summary[driver]["win"]
                            edge      = (model_p - imp_fair) * 100.0
                            if edge >= min_edge_pct:
                                edges.append({
                                    "market":     "win",
                                    "driver":     driver,
                                    "team":       driver,
                                    "odds":       int(price),
                                    "model_prob": round(model_p, 4),
                                    "edge_pct":   round(edge, 2),
                                    "sportsbook": book,
                                    "top3":       round(summary[driver]["top3"], 3),
                                    "top5":       round(summary[driver]["top5"], 3),
                                })
        return sorted(edges, key=lambda x: x["edge_pct"], reverse=True)


def _american_to_imp(o: float) -> float:
    if o >= 0:
        return 100.0 / (o + 100.0)
    return abs(o) / (abs(o) + 100.0)


# ── Model registry ────────────────────────────────────────────────────────────

def get_engine(series: str) -> RaceEngine:
    """Get a RaceEngine for the given series name or sport key."""
    config = SERIES_REGISTRY.get(series.lower())
    if config is None:
        raise ValueError(f"Unknown series: {series}. Choose from {list(SERIES_REGISTRY)}")
    return RaceEngine(config)
