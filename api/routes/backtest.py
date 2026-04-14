"""Backtest results endpoint."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["backtest"])


@router.get("/backtest/{sport}")
async def get_backtest(sport: str):
    import pandas as pd

    if sport in ("mlb", "baseball_mlb"):
        path = Path("output/mlb_backtest_results.csv")
    elif sport in ("ncaab", "basketball_ncaab"):
        path = Path("output/backtest_results.csv")
    else:
        return {"sport": sport, "results": [], "message": "No backtest data for this sport"}

    if not path.exists():
        return {"sport": sport, "results": [], "message": "Run backtest first"}

    df = pd.read_csv(path)
    return {
        "sport": sport,
        "results": df.to_dict(orient="records"),
    }
