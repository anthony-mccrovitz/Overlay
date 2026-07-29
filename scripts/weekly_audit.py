"""Weekly algo audit — runs every Sunday, prints promotion/demotion recommendations.

Cron: 0 9 * * 0 cd /path/to/march-madness && python3 scripts/weekly_audit.py >> logs/weekly_audit.log 2>&1
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"
LOG_FILE   = ROOT / "logs" / "weekly_audit.log"

PROMOTE_MIN_PICKS = 30
PROMOTE_MIN_WR    = 0.55
DEMOTE_WINDOW     = 60
DEMOTE_MAX_ROI    = 0.0

# Canonical lane key. Delegated to src.config.models._key rather than
# hand-mapped: this file previously carried its own copy, and the copies across
# the repo had each drifted to a DIFFERENT answer for the same sport — one said
# "mma", one "ufc"; one collapsed every club league to "soccer", another invented
# "soccer_mls". A report keyed differently from the registry silently fails to
# join it.
def _canon_sport(s) -> str:
    try:
        from src.config.models import _key
        return _key(str(s or ""), "")[0]
    except Exception:
        return str(s or "?")




def _load() -> list[dict]:
    raw = json.loads(PICKS_FILE.read_text())
    picks = raw if isinstance(raw, list) else raw.get("picks", [])
    return [p for p in picks if isinstance(p, dict)]


def _sport(p: dict) -> str:
    return _canon_sport(p.get("sport", ""))


def _stats(picks: list[dict]) -> dict:
    settled = [p for p in picks if p.get("result") in ("win", "loss", "push")]
    wins    = sum(1 for p in settled if p["result"] == "win")
    losses  = sum(1 for p in settled if p["result"] == "loss")
    profit  = sum(p.get("profit") or 0 for p in settled)
    wl      = wins + losses
    return {"w": wins, "l": losses, "n": len(settled), "profit": profit,
            "wr": wins / wl if wl else 0, "roi": profit / wl if wl else 0}


def run() -> None:
    today = date.today()
    week_start = today - timedelta(days=7)
    picks = _load()

    shadow  = [p for p in picks if not p.get("card_pick")]
    card    = [p for p in picks if p.get("card_pick")]

    # Group shadow by sport/market
    shadow_grid: dict[str, list] = defaultdict(list)
    for p in shadow:
        shadow_grid[f"{_sport(p)}/{p.get('market','?')}"].append(p)

    card_grid: dict[str, list] = defaultdict(list)
    for p in card:
        card_grid[f"{_sport(p)}/{p.get('market','?')}"].append(p)

    lines = []
    lines.append(f"\n{'='*65}")
    lines.append(f"  WEEKLY ALGO AUDIT — {today.strftime('%B %d, %Y')}")
    lines.append(f"{'='*65}")

    # ── Shadow models: promotion candidates ──────────────────────────────────
    lines.append("\n📈 SHADOW MODELS (promotion check — need ≥30 picks, ≥55% WR, +ROI)")
    lines.append(f"  {'Model':<35} {'W':>4} {'L':>4} {'WR%':>7} {'Profit':>9}  Verdict")
    lines.append("  " + "-"*62)
    for key, ps in sorted(shadow_grid.items()):
        s = _stats(ps)
        if s["n"] < 5:
            continue
        if s["n"] >= PROMOTE_MIN_PICKS and s["wr"] >= PROMOTE_MIN_WR and s["profit"] > 0:
            verdict = "✅ READY TO PROMOTE"
        elif s["n"] >= PROMOTE_MIN_PICKS and s["profit"] > 0:
            verdict = "👀 Watch (WR low)"
        elif s["profit"] < -5:
            verdict = "❌ Shelve"
        else:
            verdict = "— building sample"
        lines.append(f"  {key:<35} {s['w']:>4} {s['l']:>4} {s['wr']*100:>6.1f}% {s['profit']:>+9.2f}u  {verdict}")

    # ── Live models: demotion check (rolling last 60) ─────────────────────────
    lines.append("\n📉 LIVE MODELS (demotion check — rolling last 60 picks)")
    lines.append(f"  {'Model':<35} {'W':>4} {'L':>4} {'WR%':>7} {'Profit':>9}  Status")
    lines.append("  " + "-"*62)
    for key, ps in sorted(card_grid.items()):
        recent = sorted([p for p in ps if p.get("result") in ("win","loss","push")],
                        key=lambda x: x.get("date",""), reverse=True)[:DEMOTE_WINDOW]
        if len(recent) < 10:
            lines.append(f"  {key:<35}  (< 10 settled — too early to judge)")
            continue
        s = _stats(recent)
        if s["roi"] < DEMOTE_MAX_ROI:
            status = f"⚠️  ROI {s['roi']*100:+.1f}% — CONSIDER DEMOTING"
        else:
            status = f"✅ Healthy (ROI {s['roi']*100:+.1f}%)"
        lines.append(f"  {key:<35} {s['w']:>4} {s['l']:>4} {s['wr']*100:>6.1f}% {s['profit']:>+9.2f}u  {status}")

    # ── This week's card record ───────────────────────────────────────────────
    week_card = [p for p in card
                 if p.get("result") in ("win","loss","push")
                 and (p.get("date") or "") >= str(week_start)]
    ws = _stats(week_card)
    lines.append(f"\n📅 THIS WEEK ({week_start} → {today})")
    lines.append(f"   Card picks: {ws['w']}W-{ws['l']}L  {ws['profit']:+.2f}u  WR {ws['wr']*100:.1f}%")

    # ── Season card record ────────────────────────────────────────────────────
    ss = _stats([p for p in card if p.get("result") in ("win","loss","push")])
    lines.append(f"\n🏆 SEASON TO DATE")
    lines.append(f"   {ss['w']}W-{ss['l']}L  {ss['profit']:+.2f}u  WR {ss['wr']*100:.1f}%  ROI {ss['roi']*100:+.1f}%")
    lines.append(f"{'='*65}\n")

    report = "\n".join(lines)
    print(report)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(report)


if __name__ == "__main__":
    run()

    # Print coming week's sports calendar
    try:
        from scripts.weekly_sports_calendar import run as run_calendar
        run_calendar()
    except Exception as e:
        print(f"  [calendar] {e}")

    # Generate weekly recap card
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from src.output.result_cards import render_weekly_recap_card
        path = render_weekly_recap_card()
        if path:
            print(f"  Weekly recap card → {path}")
    except Exception as e:
        print(f"  [recap card] {e}")

    # Generate algo stockboard (summary table + per-algo drilldowns)
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from src.output.algo_stockboard import (
            compute_algo_grid, render_stockboard_card, render_all_detail_cards,
        )
        rows = compute_algo_grid()
        board = render_stockboard_card(rows)
        if board:
            print(f"  Algo stockboard → {board}")
        details = render_all_detail_cards(rows)
        print(f"  Per-algo drilldowns → {len(details)} cards in {board.parent / 'detail' if board else '?'}")
    except Exception as e:
        print(f"  [stockboard] {e}")
