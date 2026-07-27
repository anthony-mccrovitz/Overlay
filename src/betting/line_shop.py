"""
Line shopping engine — finds the best available odds across all sportsbooks
for each model pick, stacking model edge + line value.

This is the OddsJam approach: compare odds across books to find where
a sportsbook is offering +EV relative to the sharp market or your model.

Combined edge = model edge + line shopping edge:
  - Model edge: your probability > consensus market probability
  - Line edge: one book is offering better odds than others
  - Stacking both: your probability > best available implied probability
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data.odds_api import _american_to_prob


@dataclass
class LineShopResult:
    game_id: str
    team: str
    opponent: str
    model_prob: float
    # Consensus market
    consensus_implied: float
    consensus_odds: int
    # Best available
    best_odds: int
    best_implied: float
    best_sportsbook: str
    # All books
    all_books: list[dict]
    # Edge breakdown
    model_edge: float  # model_prob - consensus_implied
    line_edge: float   # consensus_implied - best_implied (positive = best book is soft)
    combined_edge: float  # model_prob - best_implied (total edge)
    # Game metadata
    commence_time: str = ""
    home_team: str = ""
    away_team: str = ""


def _prob_to_american(prob: float) -> int:
    if prob <= 0 or prob >= 1:
        return 0
    if prob >= 0.5:
        return int(round(-prob / (1 - prob) * 100))
    return int(round((1 - prob) / prob * 100))


def shop_lines(
    predictions: dict[tuple[str, str], float],
    raw_odds: pd.DataFrame,
    min_combined_edge: float = 0.02,
) -> list[LineShopResult]:
    """
    For each model prediction, compare against ALL sportsbooks to find
    the best available line and calculate combined edge.

    Args:
        predictions: Dict of (home_team, away_team) -> P(home wins)
        raw_odds: Full odds DataFrame (all sportsbooks, not just best)
        min_combined_edge: Minimum combined edge to include in results

    Returns:
        List of LineShopResult sorted by combined edge (highest first)
    """
    if raw_odds.empty or not predictions:
        return []

    results: list[LineShopResult] = []

    for game_id in raw_odds["GameID"].dropna().unique():
        game_rows = raw_odds[raw_odds["GameID"] == game_id]
        if "HomeMoneyline" not in game_rows.columns:
            continue

        home_raw = game_rows["HomeTeamCanonical"].iloc[0] or game_rows["HomeTeam"].iloc[0]
        away_raw = game_rows["AwayTeamCanonical"].iloc[0] or game_rows["AwayTeam"].iloc[0]
        commence = game_rows["CommenceTime"].iloc[0] if "CommenceTime" in game_rows.columns else ""

        model_prob_home = None
        if (home_raw, away_raw) in predictions:
            model_prob_home = predictions[(home_raw, away_raw)]
        elif (away_raw, home_raw) in predictions:
            model_prob_home = 1 - predictions[(away_raw, home_raw)]
        else:
            continue

        valid = game_rows.dropna(subset=["HomeMoneyline", "AwayMoneyline"])
        if valid.empty:
            continue

        # Consensus market probability (remove vig via power method)
        home_probs = valid["HomeMoneyline"].apply(_american_to_prob)
        away_probs = valid["AwayMoneyline"].apply(_american_to_prob)
        vig_sums = home_probs + away_probs
        fair_home_probs = home_probs / vig_sums
        consensus_home = float(fair_home_probs.median())
        consensus_away = 1 - consensus_home

        for side in ["home", "away"]:
            if side == "home":
                model_prob = model_prob_home
                team, opponent = home_raw, away_raw
                ml_col, opp_col = "HomeMoneyline", "AwayMoneyline"
                consensus = consensus_home
            else:
                model_prob = 1 - model_prob_home
                team, opponent = away_raw, home_raw
                ml_col, opp_col = "AwayMoneyline", "HomeMoneyline"
                consensus = consensus_away

            books = []
            for _, row in valid.iterrows():
                odds = row[ml_col]
                implied = _american_to_prob(odds)
                fair_implied = implied / (implied + _american_to_prob(row[opp_col]))
                edge = model_prob - fair_implied
                books.append({
                    "sportsbook": row.get("Sportsbook", ""),
                    "odds": int(odds),
                    "implied_prob": round(fair_implied, 4),
                    "edge_vs_model": round(edge, 4),
                })

            books.sort(key=lambda b: b["odds"], reverse=True)

            best = books[0]
            best_odds = best["odds"]
            best_implied = best["implied_prob"]
            best_book = best["sportsbook"]

            model_edge = model_prob - consensus
            line_edge = consensus - best_implied
            combined_edge = model_prob - best_implied

            if combined_edge >= min_combined_edge:
                results.append(LineShopResult(
                    game_id=game_id,
                    team=team,
                    opponent=opponent,
                    model_prob=round(model_prob, 4),
                    consensus_implied=round(consensus, 4),
                    consensus_odds=_prob_to_american(consensus),
                    best_odds=best_odds,
                    best_implied=round(best_implied, 4),
                    best_sportsbook=best_book,
                    all_books=books,
                    model_edge=round(model_edge, 4),
                    line_edge=round(line_edge, 4),
                    combined_edge=round(combined_edge, 4),
                    commence_time=commence,
                    home_team=home_raw,
                    away_team=away_raw,
                ))

    results.sort(key=lambda r: r.combined_edge, reverse=True)
    return results


def line_shop_to_dicts(results: list[LineShopResult]) -> list[dict]:
    """Convert results to JSON-serializable dicts for the API."""
    out = []
    for r in results:
        out.append({
            "game_id": r.game_id,
            "team": r.team,
            "opponent": r.opponent,
            "model_prob": r.model_prob,
            "consensus_implied": r.consensus_implied,
            "consensus_odds": r.consensus_odds,
            "best_odds": r.best_odds,
            "best_implied": r.best_implied,
            "best_sportsbook": r.best_sportsbook,
            "model_edge": r.model_edge,
            "line_edge": r.line_edge,
            "combined_edge": r.combined_edge,
            "edge_breakdown": f"Model +{r.model_edge:.1%} + Line +{r.line_edge:.1%} = Total +{r.combined_edge:.1%}",
            "all_books": r.all_books[:8],
            "commence_time": r.commence_time,
        })
    return out


