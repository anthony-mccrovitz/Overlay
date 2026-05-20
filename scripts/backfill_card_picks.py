"""Retroactive card_pick alignment to match the 2026-05-19 research plan.

Three operations:
  1. PROMOTE: NBA Totals with edge ≥ 8% → card_pick=True
     (model is T1 live per plan, but 62/80 historical picks have card_pick=False
     due to a stale model_tier flag — fix the historical record.)

  2. DEMOTE: MLB Run Line (spread) → card_pick=False on all historical entries
     (plan: PAUSED. Currently 27/158 are card_pick=True dragging the public record.)

  3. CLEAN: Any pick with stake=0.0 → set stake=1.0
     (PNL convention is 1u flat; stake=0 picks aren't bettable and shouldn't have
     been logged with a profit calculation.)

Idempotent — safe to re-run. Always backs up before modifying.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICKS = ROOT / "data" / "pnl" / "picks.json"


def main() -> None:
    # Belt-and-braces backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = PICKS.with_suffix(f".json.bak_backfill_{ts}")
    shutil.copy2(PICKS, bak)
    print(f"[backup] {bak.name}")

    data = json.loads(PICKS.read_text())
    picks = data["picks"]

    promoted = 0
    demoted = 0
    staked = 0

    for p in picks:
        sport = (p.get("sport") or "").lower()
        market = (p.get("market") or "").lower()

        # Normalize sport
        if sport in ("baseball_mlb",): sport_n = "mlb"
        elif sport in ("basketball_nba",): sport_n = "nba"
        else: sport_n = sport

        # 1. Promote NBA Totals with edge >= 8% → card_pick=True
        if sport_n == "nba" and market == "total":
            edge = p.get("edge_pct") or 0
            if edge >= 8.0 and not p.get("card_pick"):
                p["card_pick"] = True
                promoted += 1

        # 2. Demote MLB Run Line (spread) → card_pick=False
        if sport_n == "mlb" and market == "spread":
            if p.get("card_pick"):
                p["card_pick"] = False
                demoted += 1

        # 3. Stake sanity — any 0-stake pick gets 1.0u
        if p.get("stake") == 0.0:
            p["stake"] = 1.0
            staked += 1

    PICKS.write_text(json.dumps(data, indent=2, default=str))
    print(f"[promote] {promoted} NBA Totals → card_pick=True")
    print(f"[demote]  {demoted} MLB Run Line → card_pick=False")
    print(f"[stake]   {staked} picks set stake 0.0 → 1.0u")
    print(f"[done] {len(picks)} picks in file")


if __name__ == "__main__":
    main()
