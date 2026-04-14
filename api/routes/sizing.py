"""Kelly sizing endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["sizing"])


class SizingRequest(BaseModel):
    model_prob: float
    american_odds: float
    bankroll: float
    kelly_fraction: float = 0.5


@router.post("/sizing")
async def calculate_sizing(req: SizingRequest):
    from src.betting.kelly import kelly_fraction as calc_kelly, _expected_profit

    frac = calc_kelly(
        model_prob=req.model_prob,
        american_odds=req.american_odds,
        fraction=req.kelly_fraction,
    )
    bet_size = round(frac * req.bankroll, 2)
    ev = round(_expected_profit(bet_size, req.model_prob, req.american_odds), 2)

    return {
        "kelly_fraction": round(frac, 4),
        "bet_size": bet_size,
        "expected_profit": ev,
        "bankroll": req.bankroll,
    }
