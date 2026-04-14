"""Track record endpoint — P&L summary, pick history, and CLV metrics."""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(tags=["record"])


@router.get("/record")
async def get_record():
    from src.tracking.pnl import PnLTracker

    tracker = PnLTracker()
    summary = tracker.get_summary()
    card = tracker.get_record_card()

    data = tracker._load()
    history = data.get("picks", [])

    return {
        "summary": summary,
        "record_card": card,
        "picks": history,
    }


@router.get("/record/clv")
async def get_clv(sport: str = Query(None)):
    from src.tracking.clv import CLVTracker

    tracker = CLVTracker()
    summary = tracker.get_clv_summary(sport=sport)
    recent = tracker.get_recent_picks(20)

    return {
        "clv_summary": summary,
        "recent_picks": recent,
    }
