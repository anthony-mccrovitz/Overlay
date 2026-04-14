"""Odds endpoint — raw sportsbook odds for a sport."""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(tags=["odds"])

SPORT_MAP = {
    "mlb": "baseball_mlb",
    "nba": "basketball_nba",
    "ncaab": "basketball_ncaab",
    "nfl": "americanfootball_nfl",
}


@router.get("/odds/{sport}")
async def get_odds(
    sport: str,
    refresh: bool = Query(False),
):
    from src.data.odds_api import fetch_odds, get_best_odds

    sport_key = SPORT_MAP.get(sport, sport)
    raw = fetch_odds(sport=sport_key, refresh=refresh)

    if raw.empty:
        return {"sport": sport_key, "odds": [], "best_odds": []}

    best = get_best_odds(raw)

    return {
        "sport": sport_key,
        "odds": raw.fillna("").to_dict(orient="records"),
        "best_odds": best.fillna("").to_dict(orient="records"),
    }
