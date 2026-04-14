"""Grade picks against actual game results."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from src.grading.auto_grade import grade_picks, fetch_final_scores

router = APIRouter(tags=["grading"])


@router.get("/grade/{sport}")
async def get_grade(
    sport: str,
    grade_date: str | None = Query(None, description="Date to grade (YYYY-MM-DD)"),
    stake: float = Query(100.0, ge=1),
):
    """Grade picks for a date against actual game results."""
    SPORT_MAP = {
        "mlb": "baseball_mlb",
        "nba": "basketball_nba",
        "ncaab": "basketball_ncaab",
        "nfl": "americanfootball_nfl",
    }
    sport_key = SPORT_MAP.get(sport.lower(), sport)
    d = date.fromisoformat(grade_date) if grade_date else date.today()

    report = grade_picks(
        pick_date=d,
        sport=sport_key,
        flat_stake=stake,
        verbose=False,
    )
    return report


@router.get("/scores/{sport}")
async def get_scores(
    sport: str,
    game_date: str | None = Query(None, description="Date (YYYY-MM-DD)"),
):
    """Get live/final scores from MLB API."""
    d = date.fromisoformat(game_date) if game_date else date.today()

    if sport.lower() in ("mlb", "baseball_mlb"):
        scores = fetch_final_scores(d)
        return {
            "date": d.isoformat(),
            "games": scores,
            "final": sum(1 for s in scores if s["state"] == "Final"),
            "live": sum(1 for s in scores if s["state"] == "Live"),
            "scheduled": sum(1 for s in scores if s["state"] == "Preview"),
        }

    return {"error": f"Score fetching not yet supported for {sport}"}
