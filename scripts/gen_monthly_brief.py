#!/usr/bin/env python3
"""
gen_monthly_brief.py — Monthly performance report for Overlay.

Output: output/briefs/monthly_YYYYMM.md

Sections:
  1. Monthly P&L Summary (overall + by sport)
  2. By Market Breakdown (W-L, ROI, avg edge, avg CLV)
  3. Model Performance Trend (monthly ROI for last 3 months per model)
  4. Best Picks of the Month (top 5 wins by profit)
  5. Worst Picks (top 3 losses)
  6. CLV Analysis (beat rate + avg CLV by sport)
  7. Model Recommendations (based on ROI over 20+ picks)
  8. Next Month Outlook (upcoming events)

Usage:
    python3 scripts/gen_monthly_brief.py             # current month
    python3 scripts/gen_monthly_brief.py 202605      # specific month YYYYMM
"""
from __future__ import annotations

import json
import sys
from calendar import month_name
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"
BRIEFS_DIR = ROOT / "output" / "briefs"


# ─────────────────────────── Loaders ─────────────────────────────────────────

def _load_picks() -> list[dict]:
    if not PICKS_FILE.exists():
        return []
    try:
        return json.loads(PICKS_FILE.read_text()).get("picks", [])
    except (json.JSONDecodeError, OSError):
        return []


def _month_picks(picks: list[dict], year: int, month: int) -> list[dict]:
    prefix = f"{year}-{month:02d}-"
    return [p for p in picks if (p.get("date") or "").startswith(prefix)]


def _card_settled(picks: list[dict]) -> list[dict]:
    return [
        p for p in picks
        if p.get("card_pick") and p.get("result") in ("win", "loss", "push")
    ]


# ─────────────────────────── Stats helpers ───────────────────────────────────

def _wl_stats(picks: list[dict]) -> dict:
    """Compute wins, losses, pushes, profit, ROI from a list of picks."""
    settled  = [p for p in picks if p.get("result") in ("win", "loss", "push")]
    non_push = [p for p in settled if p.get("result") != "push"]
    wins     = [p for p in non_push if p.get("result") == "win"]
    losses   = [p for p in non_push if p.get("result") == "loss"]
    profit   = sum(float(p.get("profit") or 0) for p in non_push)
    staked   = sum(float(p.get("stake") or 1) for p in non_push) or 1.0
    win_rate = len(wins) / len(non_push) if non_push else 0.0
    roi      = profit / staked if non_push else 0.0
    return {
        "wins":     len(wins),
        "losses":   len(losses),
        "pushes":   len(settled) - len(non_push),
        "settled":  len(non_push),
        "profit":   profit,
        "staked":   staked,
        "win_rate": win_rate,
        "roi":      roi,
    }


def _avg_field(picks: list[dict], field: str) -> float | None:
    vals = [float(p[field]) for p in picks if p.get(field) is not None]
    return sum(vals) / len(vals) if vals else None


def _fmt_pct(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.{decimals}f}%"


def _fmt_float(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:+.{decimals}f}"


# ─────────────────────────── Sections ────────────────────────────────────────

_ACTIVE_SPORTS = [
    ("mlb",    "MLB"),
    ("nba",    "NBA"),
    ("tennis", "Tennis"),
    ("soccer", "Soccer"),
    ("golf",   "PGA / Golf"),
]


def _section_pnl_summary(picks: list[dict], year: int, month: int) -> list[str]:
    month_picks = _month_picks(picks, year, month)
    card = _card_settled(month_picks)
    overall = _wl_stats(card)

    lines = [
        "## 1. Monthly P&L Summary",
        "",
        f"Month: **{month_name[month]} {year}**",
        "",
        (
            f"Overall: **{overall['wins']}-{overall['losses']}** "
            f"({overall['win_rate']:.1%} WR)  "
            f"Profit: **{overall['profit']:+.2f}u**  "
            f"ROI: **{overall['roi'] * 100:+.1f}%**  "
            f"Staked: {overall['staked']:.1f}u"
        ),
        "",
        "| Sport | W-L | Win% | Profit | ROI | Staked |",
        "|-------|-----|------|--------|-----|--------|",
    ]

    for prefix, label in _ACTIVE_SPORTS:
        sp = [p for p in card if (p.get("sport") or "").lower().startswith(prefix)]
        if not sp:
            continue
        s = _wl_stats(sp)
        lines.append(
            f"| {label} | {s['wins']}-{s['losses']} | {s['win_rate']:.1%} "
            f"| {s['profit']:+.2f}u | {s['roi'] * 100:+.1f}% | {s['staked']:.1f}u |"
        )

    lines += [""]
    return lines


def _section_market_breakdown(picks: list[dict], year: int, month: int) -> list[str]:
    month_picks = _month_picks(picks, year, month)
    card = _card_settled(month_picks)

    market_keys = sorted({(p.get("market") or "").lower() for p in card if p.get("market")})

    lines = [
        "## 2. By Market Breakdown",
        "",
        "| Market | W-L | ROI% | Avg Edge% | Avg CLV% |",
        "|--------|-----|------|-----------|----------|",
    ]

    for mkt in market_keys:
        mp = [p for p in card if (p.get("market") or "").lower() == mkt]
        s  = _wl_stats(mp)
        avg_edge = _avg_field(mp, "edge_pct")
        avg_clv  = _avg_field(mp, "clv_pct")
        edge_str = f"{avg_edge:+.1f}%" if avg_edge is not None else "—"
        clv_str  = f"{avg_clv:+.1f}%" if avg_clv is not None else "—"
        lines.append(
            f"| {mkt} | {s['wins']}-{s['losses']} | {s['roi'] * 100:+.1f}% "
            f"| {edge_str} | {clv_str} |"
        )

    lines += [""]
    return lines


def _section_model_trend(picks: list[dict], year: int, month: int) -> list[str]:
    """Show monthly ROI for last 3 months per active model."""
    # Build the 3 months ending at (year, month)
    months = []
    y, m = year, month
    for _ in range(3):
        months.insert(0, (y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1

    _MODEL_DEFS = [
        ("MLB Totals",    "mlb",    "total"),
        ("MLB Moneyline", "mlb",    "moneyline"),
        ("NBA Totals",    "nba",    "total"),
        ("Tennis",        "tennis", None),
        ("Soccer",        "soccer", None),
        ("PGA / Golf",    "golf",   None),
    ]

    header = ["Model"] + [f"{month_name[m][:3]} {y}" for y, m in months]
    lines  = [
        "## 3. Model Performance Trend (Monthly ROI)",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]

    card = [p for p in picks if p.get("card_pick") and p.get("result") in ("win", "loss")]

    for model_name, sport_prefix, market in _MODEL_DEFS:
        row = [model_name]
        has_data = False
        for y, m in months:
            mp = _month_picks(card, y, m)
            mp = [p for p in mp if (p.get("sport") or "").lower().startswith(sport_prefix)]
            if market:
                mp = [p for p in mp if (p.get("market") or "").lower() == market]
            if not mp:
                row.append("—")
                continue
            has_data = True
            s = _wl_stats(mp)
            row.append(f"{s['roi'] * 100:+.1f}% ({s['wins']}-{s['losses']})")
        if has_data:
            lines.append("| " + " | ".join(row) + " |")

    lines += [""]
    return lines


def _section_best_picks(picks: list[dict], year: int, month: int, n: int = 5) -> list[str]:
    month_picks = _month_picks(picks, year, month)
    card = _card_settled(month_picks)
    wins = sorted(
        [p for p in card if p.get("result") == "win"],
        key=lambda x: float(x.get("profit") or 0),
        reverse=True,
    )[:n]

    lines = [
        "## 4. Best Picks of the Month",
        "",
        "| Date | Sport | Pick | Market | Odds | Profit | Edge% |",
        "|------|-------|------|--------|------|--------|-------|",
    ]

    for p in wins:
        d   = (p.get("date") or "")[:10]
        sp  = (p.get("sport") or "").upper()[:12]
        tm  = (p.get("team") or "")[:30]
        mkt = (p.get("market") or "").upper()
        odds = p.get("odds")
        odds_s = f"{int(float(odds)):+d}" if odds is not None else "—"
        prf = float(p.get("profit") or 0)
        edge = p.get("edge_pct")
        edge_s = f"{float(edge):+.1f}%" if edge is not None else "—"
        lines.append(f"| {d} | {sp} | {tm} | {mkt} | {odds_s} | {prf:+.2f}u | {edge_s} |")

    lines += [""]
    return lines


def _section_worst_picks(picks: list[dict], year: int, month: int, n: int = 3) -> list[str]:
    month_picks = _month_picks(picks, year, month)
    card = _card_settled(month_picks)
    losses = sorted(
        [p for p in card if p.get("result") == "loss"],
        key=lambda x: float(x.get("profit") or 0),
    )[:n]

    lines = [
        "## 5. Worst Picks",
        "",
        "| Date | Sport | Pick | Market | Odds | Profit | Edge% |",
        "|------|-------|------|--------|------|--------|-------|",
    ]

    for p in losses:
        d   = (p.get("date") or "")[:10]
        sp  = (p.get("sport") or "").upper()[:12]
        tm  = (p.get("team") or "")[:30]
        mkt = (p.get("market") or "").upper()
        odds = p.get("odds")
        odds_s = f"{int(float(odds)):+d}" if odds is not None else "—"
        prf = float(p.get("profit") or 0)
        edge = p.get("edge_pct")
        edge_s = f"{float(edge):+.1f}%" if edge is not None else "—"
        lines.append(f"| {d} | {sp} | {tm} | {mkt} | {odds_s} | {prf:+.2f}u | {edge_s} |")

    lines += [""]
    return lines


def _section_clv_analysis(picks: list[dict], year: int, month: int) -> list[str]:
    month_picks = _month_picks(picks, year, month)
    card = [p for p in month_picks if p.get("card_pick") and p.get("result") in ("win", "loss")]

    clv_picks = [p for p in card if p.get("clv_pct") is not None]

    lines = ["## 6. CLV Analysis", ""]

    if not clv_picks:
        lines += ["_No CLV data available for this month._", ""]
        return lines

    beaten = [p for p in clv_picks if float(p["clv_pct"]) > 0]
    beat_rate = len(beaten) / len(clv_picks)
    avg_clv   = sum(float(p["clv_pct"]) for p in clv_picks) / len(clv_picks)

    lines += [
        f"**CLV Beat Rate:** {beat_rate:.1%}  ({len(beaten)}/{len(clv_picks)} picks beat closing line)",
        f"**Avg CLV:** {avg_clv:+.2f}%",
        "",
        "| Sport | Picks w/ CLV | Beat Rate | Avg CLV% |",
        "|-------|-------------|-----------|----------|",
    ]

    for prefix, label in _ACTIVE_SPORTS:
        sp = [p for p in clv_picks if (p.get("sport") or "").lower().startswith(prefix)]
        if not sp:
            continue
        sp_beaten   = [p for p in sp if float(p["clv_pct"]) > 0]
        sp_beat_rate = len(sp_beaten) / len(sp)
        sp_avg_clv   = sum(float(p["clv_pct"]) for p in sp) / len(sp)
        lines.append(
            f"| {label} | {len(sp)} | {sp_beat_rate:.1%} | {sp_avg_clv:+.1f}% |"
        )

    lines += [""]
    return lines


def _section_model_recommendations(picks: list[dict], year: int, month: int) -> list[str]:
    """Recommend stake sizing based on recent ROI over 20+ picks."""
    _MODEL_DEFS = [
        ("MLB Totals",    "mlb",    "total"),
        ("MLB Moneyline", "mlb",    "moneyline"),
        ("NBA Totals",    "nba",    "total"),
        ("Tennis",        "tennis", None),
        ("Soccer",        "soccer", None),
        ("PGA / Golf",    "golf",   None),
    ]

    # Look at last 3 months for recommendation sample
    all_card = [p for p in picks if p.get("card_pick") and p.get("result") in ("win", "loss")]
    cutoff_date = date(year if month > 3 else year - 1, (month - 3) % 12 or 12, 1)
    recent_card = [
        p for p in all_card
        if (p.get("date") or "") >= cutoff_date.isoformat()
    ]

    lines = [
        "## 7. Model Recommendations",
        "",
        "Based on last 3 months of settled card picks (min 20 picks for a recommendation).",
        "",
        "| Model | Picks | W-L | ROI | Recommendation |",
        "|-------|-------|-----|-----|----------------|",
    ]

    for model_name, sport_prefix, market in _MODEL_DEFS:
        mp = [p for p in recent_card if (p.get("sport") or "").lower().startswith(sport_prefix)]
        if market:
            mp = [p for p in mp if (p.get("market") or "").lower() == market]
        s = _wl_stats(mp)

        if s["settled"] < 20:
            rec = f"Need more sample ({s['settled']} picks, need 20+)"
        elif s["roi"] > 0.05:
            rec = "Continue / consider increasing stake"
        elif s["roi"] >= -0.05:
            rec = "Maintain current stake — need more sample"
        else:
            rec = "Reduce to shadow-only until it recovers"

        lines.append(
            f"| {model_name} | {s['settled']} | {s['wins']}-{s['losses']} "
            f"| {s['roi'] * 100:+.1f}% | {rec} |"
        )

    lines += [""]
    return lines


def _section_next_month_outlook(year: int, month: int) -> list[str]:
    """Static upcoming events lookup — update as calendar changes."""
    # Compute next month
    next_month = month + 1
    next_year  = year
    if next_month > 12:
        next_month = 1
        next_year  += 1

    nm_name = month_name[next_month]

    _CALENDAR: dict[str, list[str]] = {
        "2026-06": [
            "Roland-Garros Finals — June 5-7 (clay, ATP/WTA)",
            "MLB regular season in full swing",
            "FIFA World Cup 2026 kicks off — June 11",
            "NBA Finals (if applicable)",
        ],
        "2026-07": [
            "Wimbledon — July 1-14 (grass, ATP/WTA)",
            "FIFA World Cup 2026 knockout rounds",
            "MLB All-Star break mid-July",
        ],
        "2026-08": [
            "PGA Championship / The Open Championship",
            "MLB second half — pennant race",
            "Wimbledon WTA finals",
        ],
    }

    key = f"{next_year}-{next_month:02d}"
    events = _CALENDAR.get(key, [])

    lines = [
        "## 8. Next Month Outlook",
        "",
        f"**{nm_name} {next_year}**",
        "",
    ]

    if events:
        for ev in events:
            lines.append(f"- {ev}")
    else:
        lines += [
            "- MLB regular season continues",
            "- Monitor active tennis/golf calendars",
            "- Soccer leagues: check fixture schedule for active leagues",
        ]

    lines += [
        "",
        "_Active models: MLB Totals (Tier 1), NBA Totals (Tier 1), Tennis Elo (Tier 1), "
        "Dixon-Coles Soccer (Tier 1), PGA SG Monte Carlo (Tier 2)_",
        "",
    ]
    return lines


# ─────────────────────────── Build report ────────────────────────────────────

def build_monthly_brief(year: int, month: int) -> str:
    picks = _load_picks()
    month_label = f"{month_name[month]} {year}"

    header = [
        f"# Overlay — Monthly Report: {month_label}",
        "",
        f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M ET')}_",
        "",
        "---",
        "",
    ]

    body: list[str] = []
    body += _section_pnl_summary(picks, year, month)
    body += ["---", ""]
    body += _section_market_breakdown(picks, year, month)
    body += ["---", ""]
    body += _section_model_trend(picks, year, month)
    body += ["---", ""]
    body += _section_best_picks(picks, year, month)
    body += ["---", ""]
    body += _section_worst_picks(picks, year, month)
    body += ["---", ""]
    body += _section_clv_analysis(picks, year, month)
    body += ["---", ""]
    body += _section_model_recommendations(picks, year, month)
    body += ["---", ""]
    body += _section_next_month_outlook(year, month)

    return "\n".join(header + body)


# ─────────────────────────── Main ────────────────────────────────────────────

def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg:
        if len(arg) != 6 or not arg.isdigit():
            print(f"Usage: gen_monthly_brief.py [YYYYMM]")
            return 1
        year  = int(arg[:4])
        month = int(arg[4:])
    else:
        today = date.today()
        year  = today.year
        month = today.month

    if not (1 <= month <= 12):
        print(f"Invalid month: {month}")
        return 1

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEFS_DIR / f"monthly_{year}{month:02d}.md"

    body = build_monthly_brief(year, month)
    out_path.write_text(body, encoding="utf-8")

    print(f"Wrote monthly brief: {out_path.relative_to(ROOT)}")
    print(f"   Open with: open {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
