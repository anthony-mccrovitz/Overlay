"""Picks endpoint — today's model predictions + value bets."""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(tags=["picks"])

SPORT_MAP = {
    "mlb": "baseball_mlb",
    "nba": "basketball_nba",
    "ncaab": "basketball_ncaab",
    "nfl": "americanfootball_nfl",
}


@router.get("/picks/{sport}")
async def get_picks(
    sport: str,
    min_edge: float = Query(0.03, ge=0, le=1),
    bankroll: float = Query(0, ge=0),
):
    sport_key = SPORT_MAP.get(sport, sport)

    if sport_key == "baseball_mlb":
        return _get_mlb_picks(sport_key, min_edge, bankroll)

    return _get_generic_picks(sport_key, min_edge, bankroll)


def _get_mlb_picks(sport_key: str, min_edge: float, bankroll: float) -> dict:
    from src.data.mlb_stats import get_todays_matchups
    from src.models.mlb_model import predict_all_games, predictions_to_dict
    from src.data.odds_api import fetch_odds, get_best_odds
    from src.betting.value_bets import find_value_bets
    from src.betting.kelly import size_bets

    matchups = get_todays_matchups()
    if not matchups:
        return {"sport": sport_key, "games": [], "picks": [], "message": "No games today"}

    preds = predict_all_games(matchups)
    predictions = predictions_to_dict(preds)

    games = []
    for p in preds:
        games.append({
            "game_id": p.game_id,
            "home_team": p.home_team,
            "away_team": p.away_team,
            "home_win_prob": round(p.home_win_prob, 4),
            "home_pitcher": p.home_pitcher,
            "away_pitcher": p.away_pitcher,
            "home_pyth": round(p.home_pyth, 4),
            "away_pyth": round(p.away_pyth, 4),
            "edge_drivers": p.edge_drivers,
        })

    raw_odds = fetch_odds(sport=sport_key)
    picks = []

    if not raw_odds.empty:
        best_odds = get_best_odds(raw_odds)
        value_bets = find_value_bets(predictions, best_odds, min_edge=min_edge)

        if not value_bets.empty:
            if bankroll > 0:
                value_bets = size_bets(value_bets, bankroll=bankroll)

            picks = value_bets.to_dict(orient="records")

    return {"sport": sport_key, "games": games, "picks": picks}


def _get_generic_picks(sport_key: str, min_edge: float, bankroll: float) -> dict:
    import numpy as np
    from src.data.odds_api import fetch_odds, get_best_odds
    from src.betting.value_bets import find_value_bets
    from src.betting.kelly import size_bets

    raw_odds = fetch_odds(sport=sport_key)
    if raw_odds.empty:
        return {"sport": sport_key, "games": [], "picks": [], "message": "No odds available"}

    best_odds = get_best_odds(raw_odds)

    # Market consensus predictions (line-shopping mode)
    predictions = {}
    for game_id in raw_odds["GameID"].dropna().unique():
        game = raw_odds[raw_odds["GameID"] == game_id]
        if "HomeImpliedProb" not in game.columns:
            continue
        probs = game[["HomeImpliedProb", "AwayImpliedProb"]].dropna()
        if probs.empty:
            continue
        sums = probs["HomeImpliedProb"] + probs["AwayImpliedProb"]
        fair_home = (probs["HomeImpliedProb"] / sums.replace(0, np.nan)).dropna()
        if fair_home.empty:
            continue
        home = game["HomeTeamCanonical"].iloc[0] or game["HomeTeam"].iloc[0]
        away = game["AwayTeamCanonical"].iloc[0] or game["AwayTeam"].iloc[0]
        predictions[(home, away)] = float(fair_home.median())

    value_bets = find_value_bets(predictions, best_odds, min_edge=min_edge)
    picks = []
    if not value_bets.empty:
        if bankroll > 0:
            value_bets = size_bets(value_bets, bankroll=bankroll)
        picks = value_bets.to_dict(orient="records")

    return {"sport": sport_key, "games": [], "picks": picks}
