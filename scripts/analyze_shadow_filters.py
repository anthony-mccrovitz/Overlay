#!/usr/bin/env python3
"""Shadow A/B analyzer — compare LIVE record vs filter-applied record.

For each shadow filter (mlb_ml_neutral_skip, mlb_f5_one_cold_only, mlb_ks_one_hot_only),
shows:
  • Baseline   — what the model actually bet (card_pick=True, settled)
  • Filter on  — same set with shadow_filter recommendation='skip' rows removed
  • Delta      — projected ROI lift from running the filter

The filter never gates real money in shadow mode. This script is the proof
artifact for whether to flip it live in Phase 3.

Usage:
    python3 scripts/analyze_shadow_filters.py
    python3 scripts/analyze_shadow_filters.py --include-shadow  # include card_pick=False
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"


FILTER_MARKETS = {
    "mlb_ml_neutral_skip":  ("mlb", ["moneyline"]),
    "mlb_f5_one_cold_only": ("mlb", ["f5_total"]),
    "mlb_ks_one_hot_only":  ("mlb", ["pitcher_strikeouts"]),
}


def _summary(rows: list[dict]) -> dict:
    w = sum(1 for r in rows if r["result"] == "win")
    l = sum(1 for r in rows if r["result"] == "loss")
    p = sum(1 for r in rows if r["result"] == "push")
    pnl = sum(r.get("profit") or 0 for r in rows)
    n = w + l
    return {
        "n":   n + p,
        "w":   w,
        "l":   l,
        "p":   p,
        "wr":  (w / n * 100) if n else 0.0,
        "pnl": pnl,
        "roi": (pnl / n * 100) if n else 0.0,
    }


def _fmt(label: str, s: dict) -> str:
    return (f"  {label:<14}  {s['w']}W-{s['l']}L"
            f"{('-' + str(s['p']) + 'P') if s['p'] else '':<5}"
            f"  WR {s['wr']:>5.1f}%  P/L {s['pnl']:>+7.2f}u  ROI {s['roi']:>+6.1f}%  n={s['n']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-shadow", action="store_true",
                    help="Include card_pick=False picks (shadow market evaluation)")
    args = ap.parse_args()

    data = json.loads(PICKS_FILE.read_text())
    picks = data.get("picks", data) if isinstance(data, dict) else data

    print("═" * 84)
    print("  SHADOW A/B FILTER ANALYSIS")
    print("  Baseline = picks actually bet (card_pick=True, settled)")
    print("  Filter on = same set with shadow_filter.recommendation='skip' rows removed")
    print("═" * 84)
    print()

    by_filter: dict[str, list[dict]] = defaultdict(list)
    for p in picks:
        sf = p.get("shadow_filter") or {}
        name = sf.get("name")
        if not name:
            continue
        if p.get("result") not in ("win", "loss", "push"):
            continue
        if not args.include_shadow and not p.get("card_pick"):
            continue
        by_filter[name].append(p)

    totals_baseline = {"n":0,"w":0,"l":0,"p":0,"pnl":0.0}
    totals_filtered = {"n":0,"w":0,"l":0,"p":0,"pnl":0.0}

    for fname, (_sport, _markets) in FILTER_MARKETS.items():
        rows = by_filter.get(fname, [])
        kept = [p for p in rows if (p.get("shadow_filter") or {}).get("recommendation") != "skip"]
        skipped = [p for p in rows if (p.get("shadow_filter") or {}).get("recommendation") == "skip"]
        if not rows:
            print(f"── {fname} ──  (no settled picks yet)\n")
            continue

        base   = _summary(rows)
        filt   = _summary(kept)
        avoid  = _summary(skipped)
        delta_roi = filt["roi"] - base["roi"]
        delta_pnl = filt["pnl"] - base["pnl"]
        # Wait — pnl_delta should reflect cost of running filter: kept_pnl - base_pnl = -avoid_pnl
        # If avoided picks lost money, removing them adds pnl
        markets_str = ", ".join(_markets)
        print(f"── {fname}  ({markets_str}) ──")
        print(_fmt("BASELINE",  base))
        print(_fmt("FILTER ON",  filt))
        print(_fmt("AVOIDED",    avoid))
        verdict = ("✅ FILTER WINS" if delta_roi > 1 else
                   "🟡 NEUTRAL" if abs(delta_roi) <= 1 else
                   "❌ FILTER LOSES")
        print(f"  Δ ROI: {delta_roi:+.1f}pp  |  Δ P/L: {delta_pnl:+.2f}u  |  {verdict}")
        print()

        for tot, src in [(totals_baseline, base), (totals_filtered, filt)]:
            tot["n"] += src["n"]; tot["w"] += src["w"]; tot["l"] += src["l"]
            tot["p"] += src["p"]; tot["pnl"] += src["pnl"]

    if totals_baseline["n"]:
        base_n = totals_baseline["w"] + totals_baseline["l"]
        filt_n = totals_filtered["w"] + totals_filtered["l"]
        base_roi = totals_baseline["pnl"]/base_n*100 if base_n else 0
        filt_roi = totals_filtered["pnl"]/filt_n*100 if filt_n else 0
        print("─" * 84)
        print(f"  COMBINED BASELINE   n={base_n:>3}   P/L {totals_baseline['pnl']:>+7.2f}u   ROI {base_roi:>+6.1f}%")
        print(f"  COMBINED FILTER ON  n={filt_n:>3}   P/L {totals_filtered['pnl']:>+7.2f}u   ROI {filt_roi:>+6.1f}%")
        print(f"  Δ                                    {(totals_filtered['pnl']-totals_baseline['pnl']):>+7.2f}u           {(filt_roi-base_roi):>+6.1f}pp")
        print("─" * 84)

    print()
    print("Filters are SHADOW only — card_pick logic unchanged. Decide at Phase 3 review")
    print("(2026-06-20 to 06-30) whether each filter's Δ is large + stable enough to ship live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
