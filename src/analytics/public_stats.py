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

    if isinstance(data, list):
        all_picks = data
    else:
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

    # ── By market — dynamic so new markets auto-appear ───────────────────────
    _market_keys = sorted({p.get("market", "") for p in card_picks if p.get("market")})
    markets = {m: _market_stats(card_picks, m) for m in _market_keys}

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

    # All sports present in card picks — new sports auto-appear without code changes
    _sport_keys = sorted({p.get("sport", "") for p in card_picks if p.get("sport")})
    by_sport = {sport: _sport_stats(sport) for sport in _sport_keys}

    # ── Today's picks + yesterday's results — served to dashboard ───────────────
    from datetime import date as _date, timedelta as _td
    _today_str     = _date.today().isoformat()               # "2026-05-27"
    _yesterday_str = (_date.today() - _td(days=1)).isoformat()  # "2026-05-26"

    def _fmt_pick(p: dict) -> dict:
        odds = p.get("odds", 0) or 0
        return {
            "pick_id":    p.get("pick_id", ""),
            "date":       p.get("date", ""),
            "sport":      p.get("sport", ""),
            "market":     p.get("market", ""),
            "team":       p.get("team", ""),
            "matchup":    p.get("matchup", ""),
            "direction":  p.get("direction", ""),
            "line":       p.get("line"),
            "odds":       odds,
            "odds_fmt":   f"+{odds}" if odds > 0 else str(odds),
            "sportsbook": p.get("sportsbook", ""),
            "edge_pct":   p.get("edge_pct", 0),
            "model_prob": p.get("model_prob", 0),
            "result":     p.get("result"),
            "profit":     round(float(p.get("profit") or 0), 2),
        }

    today_card = [_fmt_pick(p) for p in card_picks
                  if str(p.get("date", "")).startswith(_today_str)
                  and not p.get("result")]

    yesterday_graded = [_fmt_pick(p) for p in card_picks
                        if str(p.get("date", "")).startswith(_yesterday_str)
                        and p.get("result") in ("win", "loss", "void")]

    # Pick of the day: highest-edge pending ML pick today (not totals/F5/shadow)
    # Falls back to best win yesterday if nothing pending today
    _potd = None
    _ml_today = [p for p in today_card
                 if p.get("market") in ("moneyline", "ml")
                 and (p.get("edge_pct") or 0) >= 5]
    if _ml_today:
        _potd = max(_ml_today, key=lambda x: x.get("edge_pct") or 0)
    elif today_card:
        _potd = max(today_card, key=lambda x: x.get("edge_pct") or 0)
    elif yesterday_graded:
        _wins = [p for p in yesterday_graded if p.get("result") == "win"
                 and p.get("market") in ("moneyline", "ml")]
        if _wins:
            _potd = max(_wins, key=lambda x: x.get("profit") or 0)

    _today_meta = {
        "date":      _today_str,
        "picks":     sorted(today_card,     key=lambda x: -(x.get("edge_pct") or 0)),
        "potd":      _potd,
        "count":     len(today_card),
        "by_sport":  {},
    }
    for p in today_card:
        sp = p.get("sport", "other")
        _today_meta["by_sport"].setdefault(sp, []).append(p)

    _yesterday_meta = {
        "date":        _yesterday_str,
        "picks":       sorted(yesterday_graded, key=lambda x: x.get("date", "")),
        "wins":        sum(1 for p in yesterday_graded if p.get("result") == "win"),
        "losses":      sum(1 for p in yesterday_graded if p.get("result") == "loss"),
        "pl":          round(sum(float(p.get("profit") or 0) for p in yesterday_graded), 2),
        "count":       len(yesterday_graded),
    }

    # Write to web/public/data/ so Vercel can serve them
    for fname, obj in [
        ("today_picks.json",     _today_meta),
        ("yesterday_results.json", _yesterday_meta),
    ]:
        try:
            out = _WEB_OUT_FILE.parent / fname
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as _f:
                import json as _json
                _json.dump(obj, _f, indent=2)
        except Exception as _we:
            print(f"  [stats] warning: {fname} write failed: {_we}")

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

    # ── Algo status — surface live/shadow/paused to the web app ─────────────────
    try:
        from src.config.models import MODELS
        algo_status = {
            f"{sport}_{market}": {
                "status": cfg.get("status", "unknown"),
                "tier":   cfg.get("tier", "shadow"),
                "label":  cfg.get("label", f"{sport} {market}"),
            }
            for (sport, market), cfg in MODELS.items()
        }
    except Exception:
        algo_status = {}

    stats = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "algo_status": algo_status,
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


def model_heat(
    picks: list[dict],
    market: str,
    sport: str | None = None,
    n: int = 10,
) -> dict:
    """
    Compute rolling performance for a specific model.

    Filters card_pick=True picks by market (and optionally sport prefix),
    takes the last N settled non-push picks, and returns a heat dict.

    Returns:
        {
            'record':         '7-3',
            'win_rate':       0.70,
            'roi':            0.142,
            'status':         'HOT',   # HOT / WARM / COLD
            'n':              10,
            'avg_clv':        1.2,     # if available, else None
            'recommendation': 'Consider bumping stake to 1.5u',
        }

    Thresholds:
        HOT:  win_rate >= 0.60
        WARM: win_rate 0.50 – 0.59
        COLD: win_rate < 0.50
    """
    _MIN_PICKS = 5

    card = [
        p for p in picks
        if p.get("card_pick")
        and (p.get("market") or "").lower() == market.lower()
        and p.get("result") in ("win", "loss")
    ]
    if sport:
        card = [p for p in card if (p.get("sport") or "").lower().startswith(sport.lower())]

    if len(card) < _MIN_PICKS:
        return {
            "record":         None,
            "win_rate":       None,
            "roi":            None,
            "status":         None,
            "n":              len(card),
            "avg_clv":        None,
            "recommendation": f"Insufficient data ({len(card)} picks, need {_MIN_PICKS}+)",
        }

    # Sort by date/resulted_at and take last N
    def _sort_key(p: dict) -> str:
        return p.get("resulted_at") or p.get("date") or ""

    last_n = sorted(card, key=_sort_key)[-n:]

    wins   = sum(1 for p in last_n if p.get("result") == "win")
    total  = len(last_n)
    profit = sum(float(p.get("profit") or 0) for p in last_n)
    staked = sum(float(p.get("stake") or 1) for p in last_n) or 1.0
    win_rate = wins / total
    roi      = profit / staked

    # CLV average
    clv_vals = [float(p["clv_pct"]) for p in last_n if p.get("clv_pct") is not None]
    avg_clv  = round(sum(clv_vals) / len(clv_vals), 2) if clv_vals else None

    # Status + recommendation
    if win_rate >= 0.60:
        status = "HOT"
        recommendation = "Consider bumping stake to 1.5u"
    elif win_rate >= 0.50:
        status = "WARM"
        recommendation = "Maintain current stake"
    else:
        status = "COLD"
        # Check if cold for 15+ picks
        if len(card) >= 15 and win_rate < 0.50:
            recommendation = "Consider shadow-only until it recovers"
        else:
            recommendation = "Monitor — need more sample before reducing stake"

    return {
        "record":         f"{wins}-{total - wins}",
        "win_rate":       round(win_rate, 4),
        "roi":            round(roi, 4),
        "status":         status,
        "n":              total,
        "avg_clv":        avg_clv,
        "recommendation": recommendation,
    }
