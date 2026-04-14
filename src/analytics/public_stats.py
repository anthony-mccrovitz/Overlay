"""
Write data/public_stats.json after each grade run.

This file is read by the Next.js API routes (/api/record, /api/backtest/mlb)
to serve the public track record page. No auth required — it's all public data.

Called from predict.py run_grade() at the end of grading.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_PNL_FILE = Path("data/pnl/picks.json")
_OUT_FILE = Path("data/public_stats.json")


def write_public_stats() -> None:
    """Read picks.json, compute stats, write public_stats.json."""
    if not _PNL_FILE.exists():
        return

    with open(_PNL_FILE) as f:
        data = json.load(f)

    picks = data.get("picks", [])

    # Only count moneyline picks for the public record
    ml_picks = [p for p in picks if p.get("market", "moneyline") == "moneyline"]
    settled  = [p for p in ml_picks if p.get("result") in ("win", "loss", "push")]
    wins     = [p for p in settled if p.get("result") == "win"]
    losses   = [p for p in settled if p.get("result") == "loss"]
    pending  = [p for p in ml_picks if not p.get("result")]

    total_profit = sum(float(p.get("profit") or 0) for p in settled)
    total_staked = sum(float(p.get("stake") or 1) for p in settled)

    win_rate = len(wins) / len(settled) if settled else 0.0
    roi      = (total_profit / total_staked) if total_staked > 0 else 0.0

    # Units profit: profit relative to $1 flat stake
    units_profit = round(total_profit / 1.0, 2) if total_staked > 0 else 0.0

    # Current win/loss streak (positive = win streak, negative = loss streak)
    streak = 0
    for p in sorted(settled, key=lambda x: x.get("resulted_at") or x.get("date") or ""):
        r = p.get("result")
        if r == "win":
            streak = streak + 1 if streak >= 0 else 1
        elif r == "loss":
            streak = streak - 1 if streak <= 0 else -1

    # Recent picks — last 10 settled, most recent first
    recent_settled = sorted(
        [p for p in settled],
        key=lambda x: x.get("resulted_at") or x.get("date") or "",
        reverse=True,
    )[:10]

    recent_picks = [
        {
            "date":   p.get("date"),
            "team":   p.get("team"),
            "opponent": p.get("opponent"),
            "odds":   p.get("odds"),
            "result": p.get("result"),
            "profit": round(float(p.get("profit") or 0), 2),
            "edge":   round(float(p.get("edge") or 0) * 100, 1) if p.get("edge") else None,
        }
        for p in recent_settled
    ]

    # Backtest data — static from last training run
    # Update these when you retrain with improved accuracy
    backtest_mlb = [
        {"season": 2025, "accuracy": 0.541, "high_conf": 0.583, "games": 2432, "edge_pct": 8},
        {"season": 2024, "accuracy": 0.538, "high_conf": 0.571, "games": 2430, "edge_pct": 8},
    ]

    stats = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_picks":   len(ml_picks),
            "settled":       len(settled),
            "pending":       len(pending),
            "wins":          len(wins),
            "losses":        len(losses),
            "win_rate":      round(win_rate, 4),
            "units_profit":  units_profit,
            "roi":           round(roi, 4),
            "streak":        streak,
        },
        "backtest_mlb": backtest_mlb,
        "recent_picks": recent_picks,
    }

    _OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT_FILE, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"  [stats] public_stats.json updated — {len(settled)}W/{len(settled)} settled, "
          f"{win_rate:.1%} win rate, {roi:+.1%} ROI")
