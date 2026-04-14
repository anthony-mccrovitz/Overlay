"""Paper trading validation API endpoints."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter(tags=["paper_trade"])

PICKS_DIR = Path("output/picks")


@router.get("/paper-trade/summary")
async def paper_trade_summary():
    """Full paper trading validation stats for the dashboard."""
    from src.validation.stats import validate

    v = validate()
    result = asdict(v)

    # Add daily P&L series for charting
    pnl_path = Path("data/pnl/picks.json")
    daily_series = []
    if pnl_path.exists():
        with open(pnl_path) as f:
            data = json.load(f)
        settled = [p for p in data.get("picks", []) if p.get("result") in ("win", "loss")]

        by_date: dict[str, dict] = {}
        for p in settled:
            d = (p.get("resulted_at") or p.get("recorded_at") or "")[:10]
            if not d:
                continue
            if d not in by_date:
                by_date[d] = {"date": d, "profit": 0, "bets": 0, "wins": 0}
            by_date[d]["profit"] += float(p.get("profit", 0) or 0)
            by_date[d]["bets"] += 1
            if p.get("result") == "win":
                by_date[d]["wins"] += 1

        cumulative = 0
        for d in sorted(by_date.keys()):
            entry = by_date[d]
            cumulative += entry["profit"]
            daily_series.append({
                "date": entry["date"],
                "daily_profit": round(entry["profit"], 2),
                "cumulative_profit": round(cumulative, 2),
                "bets": entry["bets"],
                "wins": entry["wins"],
            })

    result["daily_series"] = daily_series

    # Add recent picks
    clv_path = Path("data/clv/clv_records.json")
    recent = []
    if clv_path.exists():
        with open(clv_path) as f:
            clv_data = json.load(f)
        recent = clv_data.get("picks", [])[-20:]

    result["recent_picks"] = recent

    return result


@router.get("/paper-trade/today")
async def paper_trade_today():
    """Today's picks with live status."""
    from src.grading.auto_grade import load_picks, fetch_final_scores, _match_team_to_result

    today = date.today()
    picks = load_picks("baseball_mlb", today)

    try:
        results = fetch_final_scores(today)
    except Exception:
        results = []

    enriched = []
    for pick in picks:
        team = pick.get("Team", "")
        result = _match_team_to_result(team, results) if results else None

        status = "scheduled"
        score = None
        if result:
            if result["state"] == "Final":
                status = "final"
                score = f"{result['away_score']}-{result['home_score']}"
            elif result["state"] == "Live":
                status = "live"
                score = f"{result.get('away_score', 0)}-{result.get('home_score', 0)}"

        enriched.append({
            **pick,
            "game_status": status,
            "score": score,
        })

    return {
        "date": today.isoformat(),
        "picks": enriched,
        "total": len(enriched),
    }
