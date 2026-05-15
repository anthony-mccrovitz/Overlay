"""
Write data/public_stats.json after each grade run.

Read by the Next.js API routes (/api/record) to serve the public track record
page. All profits are in units (1u = 1 unit staked flat per pick).

Counts only card_pick=True entries — those are the officially posted picks.
Reports overall composite record plus breakdowns by market and sport.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_PNL_FILE    = Path("data/pnl/picks.json")
_OUT_FILE    = Path("data/public_stats.json")
_WEB_OUT_FILE = Path("web/public/data/public_stats.json")


def _streak(picks: list[dict]) -> int:
    """Current streak: positive = win streak, negative = loss streak."""
    s = 0
    for p in sorted(picks, key=lambda x: x.get("resulted_at") or x.get("date") or ""):
        r = p.get("result")
        if r == "win":
            s = s + 1 if s >= 0 else 1
        elif r == "loss":
            s = s - 1 if s <= 0 else -1
    return s


def _market_stats(picks: list[dict], market: str) -> dict:
    """Compute record for a single market among card picks."""
    cat     = [p for p in picks if p.get("market") == market]
    settled = [p for p in cat if p.get("result") in ("win", "loss", "push")]
    wins    = [p for p in settled if p.get("result") == "win"]
    losses  = [p for p in settled if p.get("result") == "loss"]
    pending = [p for p in cat if not p.get("result")]

    non_push    = [p for p in settled if p.get("result") != "push"]
    profit      = sum(float(p.get("profit") or 0) for p in non_push)
    staked      = sum(float(p.get("stake") or 1) for p in non_push)
    win_rate    = len(wins) / len(non_push) if non_push else 0.0
    roi         = profit / staked if staked > 0 else 0.0

    return {
        "total":    len(cat),
        "settled":  len(settled),
        "pending":  len(pending),
        "wins":     len(wins),
        "losses":   len(losses),
        "pushes":   len(settled) - len(wins) - len(losses),
        "win_rate": round(win_rate, 4),
        "units_profit": round(profit, 2),
        "roi":      round(roi, 4),
        "streak":   _streak(settled),
    }


def write_public_stats() -> None:
    """Compute and write public_stats.json from canonical picks.json."""
    if not _PNL_FILE.exists():
        return

    with open(_PNL_FILE, encoding="utf-8") as f:
        data = json.load(f)

    all_picks = data.get("picks", [])
    card_picks = [p for p in all_picks if p.get("card_pick")]

    # ── Composite record (all markets, all sports) ────────────────────────────
    settled  = [p for p in card_picks if p.get("result") in ("win", "loss", "push")]
    wins     = [p for p in settled if p.get("result") == "win"]
    losses   = [p for p in settled if p.get("result") == "loss"]
    pending  = [p for p in card_picks if not p.get("result")]
    non_push = [p for p in settled if p.get("result") != "push"]

    total_profit = sum(float(p.get("profit") or 0) for p in non_push)
    total_staked = sum(float(p.get("stake") or 1) for p in non_push)
    win_rate     = len(wins) / len(non_push) if non_push else 0.0
    roi          = total_profit / total_staked if total_staked > 0 else 0.0

    # ── NRFI — hero metric shown prominently ──────────────────────────────────
    nrfi_picks   = [p for p in card_picks if p.get("market") == "nrfi"]
    nrfi_settled = [p for p in nrfi_picks if p.get("result") in ("win", "loss")]
    nrfi_wins    = sum(1 for p in nrfi_settled if p.get("result") == "win")
    nrfi_losses  = sum(1 for p in nrfi_settled if p.get("result") == "loss")
    nrfi_pending = [p for p in nrfi_picks if not p.get("result")]
    nrfi_wr      = nrfi_wins / len(nrfi_settled) if nrfi_settled else 0.0

    # ── By market ─────────────────────────────────────────────────────────────
    markets = {
        "moneyline": _market_stats(card_picks, "moneyline"),
        "spread":    _market_stats(card_picks, "spread"),
        "total":     _market_stats(card_picks, "total"),
        "nrfi":      _market_stats(card_picks, "nrfi"),
        "prop":      _market_stats(card_picks, "prop"),
    }

    # ── By sport ──────────────────────────────────────────────────────────────
    def _sport_stats(sport: str) -> dict:
        sp      = [p for p in card_picks if p.get("sport") == sport]
        sp_set  = [p for p in sp if p.get("result") in ("win", "loss", "push")]
        sp_np   = [p for p in sp_set if p.get("result") != "push"]
        sp_w    = sum(1 for p in sp_np if p.get("result") == "win")
        sp_l    = len(sp_np) - sp_w
        sp_prof = sum(float(p.get("profit") or 0) for p in sp_np)
        sp_stk  = sum(float(p.get("stake") or 1) for p in sp_np)
        sp_wr   = sp_w / len(sp_np) if sp_np else 0.0
        sp_roi  = sp_prof / sp_stk if sp_stk > 0 else 0.0
        return {
            "total":        len(sp),
            "settled":      len(sp_set),
            "pending":      len(sp) - len(sp_set),
            "wins":         sp_w,
            "losses":       sp_l,
            "win_rate":     round(sp_wr, 4),
            "units_profit": round(sp_prof, 2),
            "roi":          round(sp_roi, 4),
        }

    by_sport = {
        "mlb":  _sport_stats("mlb"),
        "nba":  _sport_stats("nba"),
        "nhl":  _sport_stats("nhl"),
        "wnba": _sport_stats("wnba"),
    }

    # ── Recent picks — last 10 settled card picks, newest first ───────────────
    recent_settled = sorted(
        non_push,
        key=lambda x: x.get("resulted_at") or x.get("date") or "",
        reverse=True,
    )[:10]

    recent_picks = [
        {
            "date":    p.get("date"),
            "sport":   p.get("sport"),
            "market":  p.get("market"),
            "team":    p.get("team"),
            "matchup": p.get("matchup"),
            "odds":    p.get("odds"),
            "result":  p.get("result"),
            "profit":  round(float(p.get("profit") or 0), 2),
            "edge_pct": p.get("edge_pct"),
        }
        for p in recent_settled
    ]

    # ── Backtest data — static, updated at each training run ─────────────────
    backtest_mlb = [
        {"season": 2025, "accuracy": 0.541, "high_conf": 0.583, "games": 2432, "edge_pct": 8},
        {"season": 2024, "accuracy": 0.538, "high_conf": 0.571, "games": 2430, "edge_pct": 8},
    ]

    stats = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_picks":    len(card_picks),
            "settled":        len(settled),
            "pending":        len(pending),
            "wins":           len(wins),
            "losses":         len(losses),
            "pushes":         len(settled) - len(wins) - len(losses),
            "win_rate":       round(win_rate, 4),
            "units_profit":   round(total_profit, 2),
            "roi":            round(roi, 4),
            "streak":         _streak(non_push),
        },
        "nrfi": {
            "total":    len(nrfi_picks),
            "settled":  len(nrfi_settled),
            "pending":  len(nrfi_pending),
            "wins":     nrfi_wins,
            "losses":   nrfi_losses,
            "win_rate": round(nrfi_wr, 4),
            "streak":   _streak(nrfi_settled),
        },
        "by_market":     markets,
        "by_sport":      by_sport,
        "backtest_mlb":  backtest_mlb,
        "recent_picks":  recent_picks,
    }

    _OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # Mirror for Vercel — web app reads from public/data/
    try:
        _WEB_OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_WEB_OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        print(f"  [stats] warning: web mirror failed: {e}")

    w, l = len(wins), len(losses)
    print(
        f"  [stats] updated — {w}W-{l}L ({win_rate:.1%} WR)  "
        f"{total_profit:+.2f}u  ROI {roi:+.1%}  "
        f"| NRFI {nrfi_wins}-{nrfi_losses} ({nrfi_wr:.1%})"
    )
