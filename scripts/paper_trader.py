#!/usr/bin/env python3
"""
Paper-trading ledger for the Polymarket pilot — run the $112 without the $112.

Most of what a real trade would teach can be simulated exactly, and this does
that: it replays every logged polymarket_ev pick at its recorded fill price,
settles it against the real game result, and tracks a virtual bankroll with
the same flat staking a live account would use.

What paper trading proves, and what it cannot
---------------------------------------------
TAKER entries simulate almost perfectly. Crossing the spread fills at the
quoted ask up to the depth that was sitting there, and the depth is recorded
at entry, so the only real-money unknowns are latency and Polymarket handing
you a different price than its API advertised. Those are small. Paper ≈ live.

MAKER entries do NOT simulate. A resting order fills only when someone chooses
to trade against it, and you cannot observe your own queue position without
being in the queue. polymarket_fills.py approximates this from the price track
(an UPPER bound — it assumes you were first in line), and this ledger uses
that flag. If the strategy fails even under that generous assumption it is
dead, which is worth knowing for free. If it passes, the pass is provisional.

So: paper answers "is the edge real?" for free. It cannot answer "can I get
filled?" for maker orders. That, and only that, is what money buys.

The variance point this is really for
-------------------------------------
The edge is ~1 cent per contract. Single results are noise: a +5% EV bet on a
20% shot loses four times in five, and a losing week says nothing. The report
prints the standard error and how many bets are needed before realized P&L
could distinguish the claimed edge from zero — usually a number that makes it
obvious why nobody should be reading tea leaves at n=11.

Usage:
  python3 scripts/paper_trader.py                  # full ledger
  python3 scripts/paper_trader.py --bankroll 112
  python3 scripts/paper_trader.py --mode take      # taker-only (high confidence)
  python3 scripts/paper_trader.py --json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PICKS_FILE = Path("data/pnl/picks.json")
OUT_FILE = Path("data/pnl/paper_polymarket.json")

from src.config import polymarket_protocol as PROTO   # noqa: E402

DEFAULT_BANKROLL = PROTO.BANKROLL_USD
STAKE_FRAC = PROTO.STAKE_FRAC
MAX_EXPOSURE_FRAC = PROTO.MAX_CONCURRENT_EXPOSURE_FRAC


def _load_picks() -> list[dict]:
    if not PICKS_FILE.exists():
        return []
    raw = json.loads(PICKS_FILE.read_text())
    return raw.get("picks", raw) if isinstance(raw, dict) else raw


def fill_price(pick: dict) -> tuple[float | None, str]:
    """(all-in cost per share, confidence) for this pick, or (None, reason).

    Taker fills are priced at the size-aware walked cost when the depth ladder
    was captured, falling back to top-of-book. Maker fills require
    polymarket_fills to have judged the resting order actually hit.
    """
    mode = pick.get("poly_entry_mode") or "take"
    if mode == "make":
        filled = pick.get("poly_filled")
        if filled is None:
            return None, "fill not checked yet"
        if filled is False:
            return None, "resting order never filled"
        return pick.get("poly_cost"), "low — maker fill is an upper-bound estimate"
    cost = pick.get("poly_taker_cost_at_size") or pick.get("poly_taker_cost") \
        or pick.get("poly_cost")
    return cost, "high — taker fills at the quoted ask within depth"


def settle(pick: dict, stake: float) -> dict | None:
    """Realised P&L for one pick at a virtual stake. None if not yet settled."""
    result = str(pick.get("result") or "").lower()
    if result not in ("win", "loss", "push", "void"):
        return None
    cost, conf = fill_price(pick)
    if cost is None or cost <= 0:
        return None

    shares = stake / cost
    if result in ("push", "void"):
        pnl = 0.0
    elif result == "win":
        pnl = shares * 1.0 - stake      # each share pays $1
    else:
        pnl = -stake

    fair = pick.get("model_prob")
    ev = (stake * (fair / cost - 1.0)) if fair else None
    return {
        "pick_id": pick.get("pick_id"),
        "date": pick.get("date"),
        "team": pick.get("team"),
        "sport": pick.get("sport"),
        "mode": pick.get("poly_entry_mode") or "take",
        "confidence": conf,
        "cost": round(float(cost), 4),
        "fair": fair,
        "stake": round(stake, 2),
        "shares": round(shares, 2),
        "result": result,
        "pnl": round(pnl, 2),
        "expected_pnl": round(ev, 3) if ev is not None else None,
    }


def _significance(rows: list[dict]) -> dict:
    """How many bets before realised P&L could tell this edge from zero?

    Per-bet return is a Bernoulli payout: win (1/cost - 1) with prob fair,
    else -1. The mean is the edge; the SD is dominated by the payout spread.
    n* = (2 * sd / edge)^2 is the rough count for a 2-sigma separation.
    """
    edges, sds = [], []
    for r in rows:
        fair, cost = r.get("fair"), r.get("cost")
        if not fair or not cost:
            continue
        win_ret = 1.0 / cost - 1.0
        mean = fair * win_ret - (1 - fair)
        var = fair * (win_ret - mean) ** 2 + (1 - fair) * (-1 - mean) ** 2
        edges.append(mean)
        sds.append(math.sqrt(var))
    if not edges:
        return {}
    edge = sum(edges) / len(edges)
    sd = sum(sds) / len(sds)
    n_needed = int((2 * sd / edge) ** 2) if edge > 0 else None
    return {"mean_edge_per_unit": round(edge, 4),
            "sd_per_unit": round(sd, 4),
            "n_for_2sigma": n_needed}


def run(bankroll: float = DEFAULT_BANKROLL, mode: str | None = None,
        as_json: bool = False) -> dict:
    picks = [p for p in _load_picks() if p.get("strategy") == "polymarket_ev"]
    if mode:
        picks = [p for p in picks if (p.get("poly_entry_mode") or "take") == mode]
    picks.sort(key=lambda p: (str(p.get("date")), str(p.get("recorded_at"))))

    equity = float(bankroll)
    peak, max_dd = equity, 0.0
    rows, skipped = [], {}
    open_exposure = 0.0
    prev_date = None
    for p in picks:
        # Capital lock: a maker order ties up USDC from post until the game
        # resolves, so same-slate picks are held SIMULTANEOUSLY. 11 picks at a
        # flat 4% is already 44% of the bankroll; without a cap the ledger
        # would happily "stake" money a live account would not have had.
        if p.get("date") != prev_date:
            open_exposure, prev_date = 0.0, p.get("date")
        stake = round(equity * STAKE_FRAC, 2)
        if open_exposure + stake > equity * MAX_EXPOSURE_FRAC:
            skipped["exposure cap reached for the slate"] = \
                skipped.get("exposure cap reached for the slate", 0) + 1
            continue
        open_exposure += stake
        r = settle(p, stake)
        if r is None:
            why = (fill_price(p)[1] if p.get("result") else "not settled yet")
            skipped[why] = skipped.get(why, 0) + 1
            continue
        equity += r["pnl"]
        r["equity"] = round(equity, 2)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        rows.append(r)

    staked = sum(r["stake"] for r in rows)
    pnl = sum(r["pnl"] for r in rows)
    exp = sum(r["expected_pnl"] or 0 for r in rows)
    wins = sum(1 for r in rows if r["result"] == "win")
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_bankroll": bankroll,
        "end_bankroll": round(equity, 2),
        "n_settled": len(rows),
        "n_pending": len(picks) - len(rows),
        "wins": wins,
        "losses": sum(1 for r in rows if r["result"] == "loss"),
        "staked": round(staked, 2),
        "pnl": round(pnl, 2),
        "expected_pnl": round(exp, 2),
        "roi_pct": round(100 * pnl / staked, 2) if staked else None,
        "max_drawdown": round(max_dd, 2),
        "skipped": skipped,
        "significance": _significance(rows),
        "rows": rows,
    }

    if as_json:
        print(json.dumps(out, indent=2))
        return out

    print(f"\n  PAPER LEDGER — polymarket_ev"
          f"{f' ({mode} only)' if mode else ''}")
    print("  " + "─" * 74)
    if not rows:
        print(f"  Nothing settled yet ({len(picks)} pick(s) logged).")
        for why, n in sorted(skipped.items(), key=lambda x: -x[1]):
            print(f"    {n:3} — {why}")
        print("\n  No money was risked to learn this, which is the point.")
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(out, indent=2))
        return out

    for r in rows:
        icon = {"win": "🟢", "loss": "🔴"}.get(r["result"], "⚫")
        print(f"  {icon} {r['date']}  {r['team'][:22]:22} @{r['cost']:.3f} "
              f"${r['stake']:>5.2f} → {r['pnl']:>+7.2f}   bank ${r['equity']:>7.2f}")
    print("  " + "─" * 74)
    print(f"  Settled {len(rows)}  ({wins}W-{out['losses']}L)   "
          f"staked ${staked:.2f}")
    print(f"  P&L  realised {pnl:+.2f}   expected {exp:+.2f}   "
          f"ROI {out['roi_pct']}%")
    print(f"  Bankroll ${bankroll:.2f} → ${equity:.2f}   max drawdown "
          f"${max_dd:.2f}")
    if out["n_pending"]:
        print(f"  ({out['n_pending']} not settled/filled — see skipped below)")
    for why, n in sorted(skipped.items(), key=lambda x: -x[1]):
        print(f"    {n:3} — {why}")

    sig = out["significance"]
    if sig.get("n_for_2sigma"):
        print("  " + "─" * 74)
        print(f"  Edge {sig['mean_edge_per_unit']:+.4f}/unit vs SD "
              f"{sig['sd_per_unit']:.2f}/unit.")
        print(f"  Need ~{sig['n_for_2sigma']:,} settled bets before realised P&L")
        print(f"  could separate this edge from zero. At n={len(rows)}, the")
        print(f"  realised number above is noise — read CLV, not P&L.")
    print("  " + "─" * 74)
    print("  Paper only. Taker rows simulate faithfully; maker rows assume a")
    print("  fill that only real orders can prove.")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2))
    print(f"  wrote {OUT_FILE}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bankroll", type=float, default=DEFAULT_BANKROLL)
    ap.add_argument("--mode", choices=["make", "take"],
                    help="only simulate this execution style")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()
    run(bankroll=a.bankroll, mode=a.mode, as_json=a.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
