"""Generate result cards for card picks that settled today (or a given date).

Run: python3 scripts/gen_result_cards.py
     python3 scripts/gen_result_cards.py --date 20260527
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.output.result_cards import render_result_card, OUTPUT_DIR

# Result cards driven by actual model performance, not arbitrary edge thresholds.
# Only models with verified WR >= 55% on 10+ settled card picks get result cards.
# MLB moneyline is profitable but only 53% WR — included only at high conviction (edge >= 12%).
#
# Model records (as of 2026-05-28):
#   NBA total      51-23  68.9% WR  → always post
#   MLB total      13-7   65.0% WR  → always post
#   MLB moneyline  35-31  53.0% WR  → only if edge >= 12%
#   Soccer ML       4-8   33.3% WR  → never
#   NHL             5 picks          → skip (too small)
def _is_postable(pick: dict) -> bool:
    sport  = (pick.get("sport") or "").lower()
    market = (pick.get("market") or "").lower()
    edge   = float(pick.get("edge_pct") or 0)

    if "nba" in sport and market == "total":
        return True                      # 68.9% WR — best model, always post

    if ("mlb" in sport or "baseball" in sport) and market == "total":
        return True                      # 65.0% WR — solid, always post

    if ("mlb" in sport or "baseball" in sport) and market == "f5_total":
        return True                      # newly live, 57.3% WR — post to build record

    if ("mlb" in sport or "baseball" in sport) and market in ("moneyline", "ml"):
        return edge >= 12.0              # 53% WR overall — only high-conviction edges

    return False                         # everything else: no result card


def _load_picks() -> list[dict]:
    f = ROOT / "data" / "pnl" / "picks.json"
    raw = json.loads(f.read_text())
    picks = raw if isinstance(raw, list) else raw.get("picks", [])
    return [p for p in picks if isinstance(p, dict)]


def run(target_date: str) -> None:
    picks = _load_picks()

    # Card picks that pass the postable threshold and settled on target_date
    settled = [
        p for p in picks
        if p.get("card_pick")
        and p.get("result") in ("win", "loss", "push")
        and (p.get("resulted_at") or p.get("date", ""))[:10] == target_date
        and _is_postable(p)
    ]

    if not settled:
        print(f"  [result_cards] No settled card picks found for {target_date}")
        return

    ts = target_date.replace("-", "")
    out_dir = OUTPUT_DIR / ts
    wins   = [p for p in settled if p["result"] == "win"]
    losses = [p for p in settled if p["result"] == "loss"]

    print(f"  [result_cards] {target_date} — {len(wins)}W {len(losses)}L, generating cards...")

    generated = []
    for p in settled:
        path = render_result_card(p, out_dir=out_dir)
        if path:
            print(f"    {'✅' if p['result']=='win' else '❌' if p['result']=='loss' else '⬜'} {p.get('team','')} → {path.name}")
            generated.append(path)

    print(f"  [result_cards] {len(generated)} card(s) → {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=str(date.today()), help="YYYY-MM-DD or YYYYMMDD")
    args = parser.parse_args()

    d = args.date.strip()
    if len(d) == 8 and d.isdigit():
        d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    run(d)
