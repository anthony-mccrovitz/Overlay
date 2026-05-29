#!/usr/bin/env python3
"""
Monte Carlo simulation of the 2026 FIFA World Cup.

Runs N tournament simulations using the fitted Dixon-Coles model to estimate:
  - Win probability per team (implied odds for outright futures)
  - Reach Final / SF / QF / R16 / R32 probabilities
  - Expected goals (proxy for Golden Boot likelihood)
  - Group-stage qualification probability

2026 format: 48 teams, 12 groups of 4.
  - Top 2 from each group advance (24 teams)
  - 8 best 3rd-place teams also advance (32 total)
  - R32 → R16 → QF → SF → Final

Usage:
    python3 scripts/simulate_wc2026.py
    python3 scripts/simulate_wc2026.py --sims 100000  # more sims = tighter CIs
    python3 scripts/simulate_wc2026.py --group I      # show only one group's picks
    python3 scripts/simulate_wc2026.py --top 20       # show top-N by win prob
    python3 scripts/simulate_wc2026.py --golden-boot  # show Golden Boot estimates
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from scipy.stats import poisson

from src.models.soccer_model import EnsembleSoccerModel, SoccerModel
from src.data.soccer_data import normalize_team_name

# ─────────────────────────── WC 2026 Groups ──────────────────────────────────
# Source: openfootball/world-cup.json 2026 fixture data
GROUPS: dict[str, list[str]] = {
    "A": ["Mexico",      "South Africa", "South Korea",         "Czech Republic"],
    "B": ["Canada",      "Bosnia & Herzegovina", "Qatar",       "Switzerland"],
    "C": ["Brazil",      "Morocco",      "Haiti",               "Scotland"],
    "D": ["USA",         "Paraguay",     "Australia",           "Turkey"],
    "E": ["Germany",     "Curaçao",      "Ivory Coast",         "Ecuador"],
    "F": ["Netherlands", "Japan",        "Sweden",              "Tunisia"],
    "G": ["Belgium",     "Egypt",        "Iran",                "New Zealand"],
    "H": ["Spain",       "Cape Verde",   "Saudi Arabia",        "Uruguay"],
    "I": ["France",      "Senegal",      "Iraq",                "Norway"],
    "J": ["Argentina",   "Algeria",      "Austria",             "Jordan"],
    "K": ["Portugal",    "DR Congo",     "Uzbekistan",          "Colombia"],
    "L": ["England",     "Croatia",      "Ghana",               "Panama"],
}

# R32 bracket: list of (team_A_descriptor, team_B_descriptor)
# Descriptors: "1X" = winner of group X, "2X" = runner-up, "3rd" = best 3rd-place slot
# Format follows FIFA's published 2026 knockout bracket structure
# 3rd-place team slots are assigned by rank of all 12 third-place finishers
# (simplified: first 8 3rd-place slots fill in order of their final group ranking)
R32_BRACKET = [
    # Match 49-64 (simplified symmetrical bracket avoiding same-group clashes)
    # Left half of bracket
    ("1A", "2B"),   # 49
    ("1C", "2D"),   # 50
    ("1B", "2A"),   # 51
    ("1D", "2C"),   # 52
    ("1E", "2F"),   # 53
    ("1G", "2H"),   # 54
    ("1F", "2E"),   # 55
    ("1H", "2G"),   # 56
    # Right half
    ("1I", "2J"),   # 57
    ("1K", "2L"),   # 58
    ("1J", "2I"),   # 59
    ("1L", "2K"),   # 60
    # 3rd-place slots: paired with worst-seeded group winners in each quadrant
    # Best 3rd vs 4th-best group winner in that quadrant (approximation)
    ("3rd_1", "3rd_2"),  # 61
    ("3rd_3", "3rd_4"),  # 62
    ("3rd_5", "3rd_6"),  # 63
    ("3rd_7", "3rd_8"),  # 64
]

# Which R32 match feeds which R16 match (match index → pair of R32 indices)
# This creates 4 sub-brackets that meet at QF
R16_PAIRS  = [(0,1), (2,3), (4,5), (6,7), (8,9), (10,11), (12,13), (14,15)]
QF_PAIRS   = [(0,1), (2,3), (4,5), (6,7)]
SF_PAIRS   = [(0,1), (2,3)]
FINAL_PAIR = [(0,1)]

# Name aliases: openfootball names → DC model names
TEAM_ALIASES = {
    "Ivory Coast":         "Côte d'Ivoire",
    "Bosnia & Herzegovina":"Bosnia-Herzegovina",
    "DR Congo":            "Congo DR",
    "Curaçao":             "Curaçao",
    "Cape Verde":          "Cape Verde",
    "Czech Republic":      "Czechia",
    "South Korea":         "Korea Republic",
}

rng = np.random.default_rng()


# ─────────────────────────── Simulation helpers ───────────────────────────────

def _model_name(team: str) -> str:
    """Map display name → DC model's internal name."""
    name = TEAM_ALIASES.get(team, team)
    return normalize_team_name(name)


def simulate_match(
    model: SoccerModel,
    home: str,
    away: str,
    neutral: bool = True,
) -> tuple[int, int]:
    """
    Sample a match scoreline from the Dixon-Coles score grid.
    Returns (home_goals, away_goals).
    """
    hm = _model_name(home)
    am = _model_name(away)

    atk_h = model.attack.get(hm, 0.0)
    def_h = model.defense.get(hm, 0.0)
    atk_a = model.attack.get(am, 0.0)
    def_a = model.defense.get(am, 0.0)
    boost = model.home_adv if not neutral else 0.0

    lam_h = math.exp(atk_h - def_a + boost)
    lam_a = math.exp(atk_a - def_h)

    # Draw directly from Poisson (much faster than full score grid in a hot loop)
    h = int(rng.poisson(lam_h))
    a = int(rng.poisson(lam_a))
    return h, a


def simulate_knockout_match(
    model: SoccerModel,
    home: str,
    away: str,
) -> tuple[str, int, int]:
    """
    Simulate a knockout match. Draws go to 50/50 penalties.
    Returns (winner, home_goals, away_goals).
    """
    h, a = simulate_match(model, home, away, neutral=True)
    if h > a:
        return home, h, a
    if a > h:
        return away, h, a
    # Draw → penalties (50/50)
    return (home if random.random() < 0.5 else away), h, a


# ─────────────────────────── Group stage ─────────────────────────────────────

def simulate_group(
    model: SoccerModel,
    teams: list[str],
) -> list[dict]:
    """
    Simulate a 4-team group (6 matches). Returns standings sorted by
    points → goal_diff → goals_for → alphabetical.
    """
    stats = {t: {"pts": 0, "gd": 0, "gf": 0, "ga": 0} for t in teams}

    # Round-robin: all C(4,2) = 6 pairings
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            home, away = teams[i], teams[j]
            h, a = simulate_match(model, home, away, neutral=True)
            stats[home]["gf"] += h
            stats[home]["ga"] += a
            stats[away]["gf"] += a
            stats[away]["ga"] += h
            stats[home]["gd"] += h - a
            stats[away]["gd"] += a - h
            if h > a:
                stats[home]["pts"] += 3
            elif a > h:
                stats[away]["pts"] += 3
            else:
                stats[home]["pts"] += 1
                stats[away]["pts"] += 1

    standings = [
        {"team": t, **stats[t]}
        for t in teams
    ]
    standings.sort(
        key=lambda x: (x["pts"], x["gd"], x["gf"], x["team"]),
        reverse=True,
    )
    for rank, row in enumerate(standings):
        row["rank"] = rank + 1  # 1=winner, 2=runner-up, 3=3rd, 4=4th
    return standings


# ─────────────────────────── Bracket resolution ──────────────────────────────

def _best_third(all_thirds: list[dict]) -> list[dict]:
    """
    From all 12 third-place finishers, return the 8 that advance.
    Ranked by pts → gd → gf.
    """
    ranked = sorted(
        all_thirds,
        key=lambda x: (x["pts"], x["gd"], x["gf"]),
        reverse=True,
    )
    return ranked[:8]


def _resolve_descriptor(
    desc: str,
    group_results: dict[str, list[dict]],
    thirds: list[dict],
    third_slot: dict,
) -> str:
    """
    Resolve a bracket descriptor like '1A', '2B', '3rd_1' to a team name.
    """
    if desc.startswith("3rd_"):
        idx = int(desc.split("_")[1]) - 1
        if idx < len(thirds):
            return thirds[idx]["team"]
        return "_BYE_"
    rank = int(desc[0])     # 1 or 2
    group = desc[1]         # A-L
    standing = group_results[group]
    for row in standing:
        if row["rank"] == rank:
            return row["team"]
    return "_BYE_"


def simulate_tournament(
    model: SoccerModel,
    groups: dict[str, list[str]],
) -> dict:
    """
    Run one complete WC2026 simulation.
    Returns dict mapping team → {"stage": max_stage_reached, "goals": int}
    Stages: "group"=0, "r32"=1, "r16"=2, "qf"=3, "sf"=4, "final"=5, "winner"=6
    """
    results: dict[str, dict] = {
        t: {"stage": 0, "goals": 0}
        for grp in groups.values()
        for t in grp
    }

    # ── Group stage ───────────────────────────────────────────────────────────
    group_results: dict[str, list[dict]] = {}
    all_thirds: list[dict] = []

    for grp_name, teams in groups.items():
        standing = simulate_group(model, teams)
        group_results[grp_name] = standing
        for row in standing:
            t = row["team"]
            results[t]["goals"] += row["gf"]
            if row["rank"] <= 2:
                results[t]["stage"] = 1   # qualified for R32
            else:
                results[t]["stage"] = 0   # eliminated at group stage
        all_thirds.append(standing[2])    # 3rd-place finisher

    # Best 8 third-place teams
    advancing_thirds = _best_third(all_thirds)
    for row in advancing_thirds:
        results[row["team"]]["stage"] = 1

    # ── Knockout bracket ──────────────────────────────────────────────────────
    third_slot: dict = {}  # unused slot lookup

    def play_round(matchups: list[tuple[str, str]], stage_on_win: int) -> list[str]:
        winners = []
        for a, b in matchups:
            if a == "_BYE_":
                winners.append(b); continue
            if b == "_BYE_":
                winners.append(a); continue
            winner, hg, ag = simulate_knockout_match(model, a, b)
            loser = b if winner == a else a
            results[winner]["stage"] = max(results[winner]["stage"], stage_on_win)
            results[loser]["stage"] = max(results[loser]["stage"], stage_on_win - 1)
            results[winner]["goals"] += hg
            results[loser]["goals"] += ag
            winners.append(winner)
        return winners

    # R32: resolve descriptors → actual team names
    r32_teams = []
    for i, (da, db) in enumerate(R32_BRACKET):
        ta = _resolve_descriptor(da, group_results, advancing_thirds, third_slot)
        tb = _resolve_descriptor(db, group_results, advancing_thirds, third_slot)
        r32_teams.append((ta, tb))

    r32_winners = play_round(r32_teams, stage_on_win=2)      # winners reach R16

    # Pair R32 winners for R16
    r16_teams = [(r32_winners[i], r32_winners[i + 1]) for i in range(0, 16, 2)]
    r16_winners = play_round(r16_teams, stage_on_win=3)       # winners reach QF

    # QF
    qf_teams = [(r16_winners[i], r16_winners[i + 1]) for i in range(0, 8, 2)]
    qf_winners = play_round(qf_teams, stage_on_win=4)         # winners reach SF

    # SF
    sf_teams = [(qf_winners[i], qf_winners[i + 1]) for i in range(0, 4, 2)]
    sf_winners = play_round(sf_teams, stage_on_win=5)         # winners reach Final

    # Final
    final_winner, _, _ = simulate_knockout_match(model, sf_winners[0], sf_winners[1])
    final_loser = sf_winners[1] if final_winner == sf_winners[0] else sf_winners[0]
    results[final_winner]["stage"] = 6
    results[final_loser]["stage"] = 5

    return results


# ─────────────────────────── Aggregation ─────────────────────────────────────

STAGE_LABELS = {0: "Group", 1: "R32", 2: "R16", 3: "QF", 4: "SF", 5: "Final", 6: "WINNER"}


def _prob_to_american(p: float) -> str:
    if p <= 0:
        return "N/A"
    if p >= 1:
        return "-∞"
    if p >= 0.5:
        ml = -round((p / (1 - p)) * 100)
        return f"{ml:+d}"
    ml = round(((1 - p) / p) * 100)
    return f"+{ml}"


def aggregate_and_print(
    all_results: list[dict],
    args,
) -> None:
    n = len(all_results)
    teams = list(all_results[0].keys())

    # Accumulate
    win_count    = defaultdict(int)
    final_count  = defaultdict(int)
    sf_count     = defaultdict(int)
    qf_count     = defaultdict(int)
    r16_count    = defaultdict(int)
    r32_count    = defaultdict(int)
    total_goals  = defaultdict(int)

    for res in all_results:
        for team, data in res.items():
            stage = data["stage"]
            if stage >= 6: win_count[team]   += 1
            if stage >= 5: final_count[team]  += 1
            if stage >= 4: sf_count[team]     += 1
            if stage >= 3: qf_count[team]     += 1
            if stage >= 2: r16_count[team]    += 1
            if stage >= 1: r32_count[team]    += 1
            total_goals[team] += data["goals"]

    # Sort by win probability
    sorted_teams = sorted(teams, key=lambda t: win_count[t], reverse=True)
    if args.group:
        g = args.group.upper()
        sorted_teams = [t for t in sorted_teams if t in GROUPS.get(g, [])]
    if args.top:
        sorted_teams = sorted_teams[:args.top]

    # ── Outright futures table ────────────────────────────────────────────────
    print(f"\n{'─'*90}")
    print(f"  WC2026 Monte Carlo Simulation  ({n:,} runs)")
    print(f"{'─'*90}")
    print(f"  {'Team':<22} {'Group':<6} {'Win%':>6}  {'Final%':>7}  {'SF%':>6}  {'QF%':>6}  {'R16%':>6}  {'Odds':>8}  {'Exp G':>6}")
    print(f"{'─'*90}")

    team_to_group = {t: g for g, ts in GROUPS.items() for t in ts}

    for team in sorted_teams:
        wp    = win_count[team]   / n * 100
        fp    = final_count[team] / n * 100
        sp    = sf_count[team]    / n * 100
        qp    = qf_count[team]    / n * 100
        r16p  = r16_count[team]   / n * 100
        odds  = _prob_to_american(win_count[team] / n)
        eg    = total_goals[team] / n
        grp   = team_to_group.get(team, "?")
        print(f"  {team:<22} {grp:<6} {wp:>5.1f}%  {fp:>6.1f}%  {sp:>5.1f}%  {qp:>5.1f}%  {r16p:>5.1f}%  {odds:>8}  {eg:>5.2f}")

    print(f"{'─'*90}")

    # ── Golden Boot ───────────────────────────────────────────────────────────
    if args.golden_boot:
        print(f"\n  Golden Boot estimates (top scorer accounts for ~22% of team goals)")
        print(f"{'─'*55}")
        print(f"  {'Team':<22} {'Exp Goals/tourney':>18}  {'~Top scorer':>12}  {'GB odds':>8}")
        print(f"{'─'*55}")

        gb_teams = sorted(sorted_teams, key=lambda t: total_goals[t], reverse=True)[:20]
        for team in gb_teams:
            eg_total = total_goals[team] / n
            top_scorer_goals = eg_total * 0.22
            # GB prob proportional to expected top-scorer goals × tournament reach
            gb_odds_raw = _prob_to_american(min(0.99, top_scorer_goals / 12.0))
            print(f"  {team:<22} {eg_total:>18.2f}  {top_scorer_goals:>11.2f}  {gb_odds_raw:>8}")
        print(f"{'─'*55}")
        print("  Note: GB model is rough — score markets (player props) require roster data.\n")

    # ── Group stage win probabilities ─────────────────────────────────────────
    if not args.group and not args.top:
        print(f"\n  Group stage summary (qualify % = advance from group)")
        print(f"{'─'*60}")
        for grp, grp_teams in sorted(GROUPS.items()):
            print(f"  Group {grp}:")
            grp_sorted = sorted(grp_teams, key=lambda t: r32_count[t], reverse=True)
            for t in grp_sorted:
                qp = r32_count[t] / n * 100
                bar = "█" * int(qp / 5)
                print(f"    {t:<25} {qp:5.1f}%  {bar}")
        print()


# ─────────────────────────── Entry point ─────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims",        type=int,  default=50_000, help="Number of simulations (default: 50000)")
    ap.add_argument("--group",       type=str,  default="",    help="Filter output to one group (A-L)")
    ap.add_argument("--top",         type=int,  default=0,     help="Show top-N teams by win probability")
    ap.add_argument("--golden-boot", action="store_true",      help="Show Golden Boot probability estimates")
    ap.add_argument("--seed",        type=int,  default=42,    help="Random seed for reproducibility")
    args = ap.parse_args()

    global rng
    rng = np.random.default_rng(args.seed)
    random.seed(args.seed)

    # Load model — EnsembleSoccerModel (DC + Elo blend, dc_weight=0.35)
    print("Loading Ensemble soccer model (DC + Elo)...")
    from src.models.soccer_model import load_or_fit_model
    model = load_or_fit_model(min_year=2020, min_elo=1650, use_ensemble=True, verbose=True)

    # Verify key WC teams are in model
    model_team_set = set(model.teams)
    missing = []
    for grp_teams in GROUPS.values():
        for t in grp_teams:
            if _model_name(t) not in model_team_set:
                missing.append(t)
    if missing:
        print(f"  Warning: {len(missing)} teams not in model (using average strength): {missing}")

    # Run simulations
    print(f"\nRunning {args.sims:,} tournament simulations...")
    all_results = []
    checkpoint = args.sims // 10
    for i in range(args.sims):
        all_results.append(simulate_tournament(model, GROUPS))
        if (i + 1) % checkpoint == 0:
            pct = (i + 1) / args.sims * 100
            print(f"  {pct:.0f}% ({i+1:,}/{args.sims:,})", end="\r", flush=True)
    print()

    aggregate_and_print(all_results, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
