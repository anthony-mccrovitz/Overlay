"""
MLB model backtester.

Replays full MLB seasons game-by-game in chronological order.
At each game, predictions use ONLY stats accumulated up to that point —
no look-ahead bias. This is the honest test of whether the Pythagorean +
pitcher model has real predictive value.

Baselines to beat:
  - Coin flip: 50.0%
  - Always pick home team: ~53.8%
  - Always pick the team with better record: ~57%
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from src.data.mlb_stats import API_BASE, CACHE_DIR, _cached_get, _safe_float
from src.models.mlb_model import (
    pythagorean_win_pct,
    log5,
    HOME_FIELD_ADVANTAGE,
)


@dataclass
class CumulativeTeamStats:
    games: int = 0
    runs_scored: int = 0
    runs_allowed: int = 0

    @property
    def rs_per_game(self) -> float:
        return self.runs_scored / max(self.games, 1)

    @property
    def ra_per_game(self) -> float:
        return self.runs_allowed / max(self.games, 1)


@dataclass
class BettingSimResult:
    """Results of edge-filtered flat-stake betting simulation at one threshold."""
    min_edge: float
    bets: int = 0
    wins: int = 0
    units_wagered: float = 0.0
    units_profit: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / max(self.bets, 1)

    @property
    def roi(self) -> float:
        return self.units_profit / max(self.units_wagered, 1)

    @property
    def breakeven_rate(self) -> float:
        """Win rate needed to break even at -110 juice."""
        return 110 / (110 + 100)   # 52.38%


@dataclass
class BacktestResult:
    season: int
    total_games: int = 0
    correct: int = 0
    home_wins: int = 0
    home_correct: int = 0
    confident_games: int = 0
    confident_correct: int = 0
    brier_sum: float = 0.0
    monthly: dict = field(default_factory=dict)
    betting: dict = field(default_factory=dict)  # min_edge (str) -> BettingSimResult

    @property
    def accuracy(self) -> float:
        return self.correct / max(self.total_games, 1)

    @property
    def home_baseline(self) -> float:
        return self.home_wins / max(self.total_games, 1)

    @property
    def always_home_accuracy(self) -> float:
        return self.home_wins / max(self.total_games, 1)

    @property
    def confident_accuracy(self) -> float:
        return self.confident_correct / max(self.confident_games, 1)

    @property
    def brier_score(self) -> float:
        return self.brier_sum / max(self.total_games, 1)


def _fetch_season_schedule(season: int) -> list[dict]:
    """
    Fetch all regular-season games with final scores for a given year.
    """
    start = f"{season}-03-20"
    end = f"{season}-10-01"
    cache_key = f"backtest_schedule_{season}"

    data = _cached_get(
        cache_key,
        f"{API_BASE}/schedule",
        {
            "startDate": start,
            "endDate": end,
            "sportId": 1,
            "gameType": "R",
            "fields": (
                "dates,date,games,gamePk,gameDate,"
                "status,abstractGameState,"
                "teams,home,away,team,id,name,score,"
                "probablePitcher,id,fullName"
            ),
        },
        max_age_s=86400 * 30,
    )

    games = []
    for date_entry in data.get("dates", []):
        game_date = date_entry.get("date", "")
        for game in date_entry.get("games", []):
            state = game.get("status", {}).get("abstractGameState", "")
            if state != "Final":
                continue

            home_info = game.get("teams", {}).get("home", {})
            away_info = game.get("teams", {}).get("away", {})

            home_score = home_info.get("score")
            away_score = away_info.get("score")
            if home_score is None or away_score is None:
                continue

            games.append({
                "game_pk": game.get("gamePk"),
                "date": game_date,
                "home_id": home_info.get("team", {}).get("id"),
                "away_id": away_info.get("team", {}).get("id"),
                "home_name": home_info.get("team", {}).get("name", ""),
                "away_name": away_info.get("team", {}).get("name", ""),
                "home_score": int(home_score),
                "away_score": int(away_score),
            })

    games.sort(key=lambda g: (g["date"], g["game_pk"] or 0))
    return games


def _predict_with_cumulative(
    home_stats: CumulativeTeamStats,
    away_stats: CumulativeTeamStats,
    min_games: int = 10,
) -> float:
    """
    Predict P(home wins) using only cumulative stats.
    Returns 0.538 (home baseline) if either team has < min_games.
    """
    if home_stats.games < min_games or away_stats.games < min_games:
        return 0.5 + HOME_FIELD_ADVANTAGE

    home_pyth = pythagorean_win_pct(home_stats.rs_per_game, home_stats.ra_per_game)
    away_pyth = pythagorean_win_pct(away_stats.rs_per_game, away_stats.ra_per_game)

    raw = log5(home_pyth, away_pyth)
    return max(0.05, min(0.95, raw + HOME_FIELD_ADVANTAGE))


def run_mlb_backtest(
    seasons: list[int] | None = None,
    verbose: bool = False,
) -> list[BacktestResult]:
    """
    Backtest the Pythagorean model on historical MLB seasons.

    For each game played in chronological order:
      1. Predict outcome using only stats accumulated BEFORE this game
      2. Record prediction vs actual result
      3. Update cumulative stats with this game's result

    No look-ahead bias. Honest test.
    """
    if seasons is None:
        seasons = [2024, 2025]

    results = []

    for season in seasons:
        print(f"\n  Backtesting {season} MLB season...")
        games = _fetch_season_schedule(season)
        if not games:
            print(f"    No games found for {season}")
            continue

        print(f"    {len(games)} regular season games loaded")

        team_stats: dict[int, CumulativeTeamStats] = defaultdict(CumulativeTeamStats)
        result = BacktestResult(season=season)

        # Initialise betting sims at multiple edge thresholds (assume flat -110 juice)
        edge_thresholds = [0.03, 0.05, 0.08]
        for thresh in edge_thresholds:
            result.betting[str(thresh)] = BettingSimResult(min_edge=thresh)

        # Breakeven implied prob at -110
        _breakeven = 110 / 210   # 0.52381

        for game in games:
            home_id = game["home_id"]
            away_id = game["away_id"]
            home_score = game["home_score"]
            away_score = game["away_score"]

            if home_score == away_score:
                # Tie (shouldn't happen in MLB, but skip if it does)
                continue

            home_won = home_score > away_score

            # Predict BEFORE updating stats
            prob_home = _predict_with_cumulative(
                team_stats[home_id],
                team_stats[away_id],
            )

            predicted_home = prob_home >= 0.5
            correct = predicted_home == home_won

            result.total_games += 1
            if correct:
                result.correct += 1
            if home_won:
                result.home_wins += 1
            if prob_home >= 0.5 == home_won:
                result.home_correct += 1

            # High confidence picks (>= 58% either way)
            if prob_home >= 0.58 or prob_home <= 0.42:
                result.confident_games += 1
                if correct:
                    result.confident_correct += 1

            # Brier score: (prediction - outcome)^2
            outcome = 1.0 if home_won else 0.0
            result.brier_sum += (prob_home - outcome) ** 2

            # Betting simulation — flat -110 juice, 1 unit per bet
            # Edge = model_prob_of_chosen_side - breakeven_implied_prob_at_-110
            # Bet home if model favors home, away otherwise.
            if prob_home >= 0.5:
                model_side_prob = prob_home
                side_won = home_won
            else:
                model_side_prob = 1.0 - prob_home
                side_won = not home_won

            edge_vs_market = model_side_prob - _breakeven
            payout_per_unit = 100 / 110   # ~0.909 at -110

            for thresh in edge_thresholds:
                if edge_vs_market >= thresh:
                    sim = result.betting[str(thresh)]
                    sim.bets += 1
                    sim.units_wagered += 1.0
                    if side_won:
                        sim.wins += 1
                        sim.units_profit += payout_per_unit
                    else:
                        sim.units_profit -= 1.0

            # Monthly breakdown
            month = game["date"][:7]  # "2025-04"
            if month not in result.monthly:
                result.monthly[month] = {"games": 0, "correct": 0}
            result.monthly[month]["games"] += 1
            if correct:
                result.monthly[month]["correct"] += 1

            # Update cumulative stats AFTER prediction
            team_stats[home_id].games += 1
            team_stats[home_id].runs_scored += home_score
            team_stats[home_id].runs_allowed += away_score

            team_stats[away_id].games += 1
            team_stats[away_id].runs_scored += away_score
            team_stats[away_id].runs_allowed += home_score

        results.append(result)

    return results


def print_backtest_results(results: list[BacktestResult]) -> str:
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append("  MLB MODEL BACKTEST RESULTS")
    lines.append(f"{'='*70}")

    total_games = 0
    total_correct = 0
    total_home_wins = 0
    total_confident = 0
    total_confident_correct = 0
    total_brier = 0.0

    for r in results:
        total_games += r.total_games
        total_correct += r.correct
        total_home_wins += r.home_wins
        total_confident += r.confident_games
        total_confident_correct += r.confident_correct
        total_brier += r.brier_sum

        lines.append(f"\n  {r.season} Season")
        lines.append(f"  {'─'*40}")
        lines.append(f"  Games tested:        {r.total_games}")
        lines.append(f"  Model accuracy:      {r.accuracy:.1%}")
        lines.append(f"  Always-home baseline:{r.always_home_accuracy:.1%}")
        lift = r.accuracy - r.always_home_accuracy
        lines.append(f"  Model lift vs home:  {lift:+.1%}")
        lines.append(f"  Brier score:         {r.brier_score:.4f}")
        if r.confident_games > 0:
            lines.append(
                f"  High-confidence picks:{r.confident_accuracy:.1%} "
                f"({r.confident_games} games, {r.confident_correct} correct)"
            )

        lines.append(f"\n  Monthly breakdown:")
        for month in sorted(r.monthly.keys()):
            m = r.monthly[month]
            acc = m["correct"] / max(m["games"], 1)
            lines.append(f"    {month}: {acc:.1%} ({m['correct']}/{m['games']})")

    if len(results) > 1:
        overall_acc = total_correct / max(total_games, 1)
        overall_home = total_home_wins / max(total_games, 1)
        overall_brier = total_brier / max(total_games, 1)
        lift = overall_acc - overall_home

        lines.append(f"\n  {'='*40}")
        lines.append(f"  COMBINED ({total_games} games)")
        lines.append(f"  {'='*40}")
        lines.append(f"  Model accuracy:      {overall_acc:.1%}")
        lines.append(f"  Always-home baseline:{overall_home:.1%}")
        lines.append(f"  Model lift:          {lift:+.1%}")
        lines.append(f"  Brier score:         {overall_brier:.4f}")
        if total_confident > 0:
            conf_acc = total_confident_correct / total_confident
            lines.append(
                f"  High-confidence:     {conf_acc:.1%} "
                f"({total_confident} games)"
            )

    # Betting simulation summary (aggregate across all seasons)
    lines.append(f"\n  {'='*40}")
    lines.append("  EDGE-FILTERED BETTING SIMULATION")
    lines.append("  (flat -110 juice, 1 unit per bet)")
    lines.append(f"  {'─'*40}")
    lines.append(f"  {'Min Edge':>10}  {'Bets':>6}  {'Win%':>7}  {'ROI':>8}  {'Profit':>8}")
    lines.append(f"  {'─'*40}")

    # Aggregate betting results across seasons
    agg_betting: dict[str, BettingSimResult] = {}
    for r in results:
        for key, sim in r.betting.items():
            if key not in agg_betting:
                agg_betting[key] = BettingSimResult(min_edge=sim.min_edge)
            agg = agg_betting[key]
            agg.bets += sim.bets
            agg.wins += sim.wins
            agg.units_wagered += sim.units_wagered
            agg.units_profit += sim.units_profit

    for key in sorted(agg_betting.keys(), key=float):
        sim = agg_betting[key]
        if sim.bets == 0:
            continue
        roi_str = f"{sim.roi:+.1%}"
        profit_str = f"{sim.units_profit:+.1f}u"
        lines.append(
            f"  {sim.min_edge:>9.0%}  {sim.bets:>6}  "
            f"{sim.win_rate:>7.1%}  {roi_str:>8}  {profit_str:>8}"
        )
    lines.append(f"  Breakeven win rate at -110: {110/210:.1%}")

    # Verdict
    lines.append(f"\n  {'='*40}")
    overall_acc = total_correct / max(total_games, 1)
    overall_home = total_home_wins / max(total_games, 1)

    if overall_acc >= 0.56:
        lines.append("  VERDICT: STRONG — Model shows real predictive edge.")
        lines.append("  Safe to use for daily picks with proper bankroll management.")
    elif overall_acc >= 0.54:
        lines.append("  VERDICT: PROMISING — Model beats baselines.")
        lines.append("  Consider paper-trading for 2 weeks before real money.")
    elif overall_acc > overall_home + 0.005:
        lines.append("  VERDICT: MARGINAL — Slight edge over home baseline.")
        lines.append("  Need pitcher adjustment or more features to improve.")
    else:
        lines.append("  VERDICT: INSUFFICIENT — Model doesn't beat always-pick-home.")
        lines.append("  Need significant model improvements before using.")

    lines.append(f"{'='*70}\n")
    return "\n".join(lines)
