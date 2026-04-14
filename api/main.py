"""
EdgeFinder API — FastAPI backend wrapping the existing prediction engine.

Run locally:
  uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import picks, odds, record, backtest, sizing, verify, line_shop, grade, paper_trade

app = FastAPI(
    title="EdgeFinder API",
    description="AI-powered sports betting edge detection",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(picks.router, prefix="/api")
app.include_router(odds.router, prefix="/api")
app.include_router(record.router, prefix="/api")
app.include_router(backtest.router, prefix="/api")
app.include_router(sizing.router, prefix="/api")
app.include_router(verify.router, prefix="/api")
app.include_router(line_shop.router, prefix="/api")
app.include_router(grade.router, prefix="/api")
app.include_router(paper_trade.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "edgefinder"}
