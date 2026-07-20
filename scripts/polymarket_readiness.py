#!/usr/bin/env python3
"""
Is the Polymarket experiment finished, and what did it conclude?

One command that grades the experiment against criteria fixed in advance
(src/config/polymarket_protocol.py) instead of against whatever the numbers
happen to look like today. Every gate below was written before the data
existed, which is the only reason its answer is worth anything.

Gates, all of which must pass before real money is defensible:

  1. SAMPLE      n scored picks at the current protocol version
  2. ANCHOR      Pinnacle's devigged price must actually be calibrated —
                 the whole edge is measured against it, and it is the least
                 verified assumption in the system
  3. FILLS       enough maker fills to know the resting orders trade at all
  4. CLV         positive closing-line value, the house 300-bet rule
  5. DRAWDOWN    paper bankroll never breached the stop

Verdict is one of:
  WAIT     — gates still open, keep collecting; says which and how long
  RETIRE   — a gate failed conclusively. This is a SUCCESS: it cost nothing
             and closed off a plausible idea.
  PROMOTE  — every gate passed; a small real stake is defensible

Usage:
  python3 scripts/polymarket_readiness.py
  python3 scripts/polymarket_readiness.py --json
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import polymarket_protocol as PROTO   # noqa: E402

PICKS_FILE = Path("data/pnl/picks.json")
SNAPSHOTS_FILE = Path("data/clv/snapshots.json")
OUT_FILE = Path("data/clv/polymarket_readiness.json")


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _rows(raw, key):
    if raw is None:
        return []
    return raw.get(key, raw) if isinstance(raw, dict) else raw


def anchor_calibration() -> dict:
    """Do Pinnacle's devigged probabilities match reality?

    Buckets every graded moneyline pick that carried a sharp fair by predicted
    probability and compares against realised win rate. If 20% shots do not
    win about 20% of the time, the anchor is unfit and every edge measured
    against it is measurement error — no amount of CLV rescues that.
    """
    picks = _rows(_load(PICKS_FILE), "picks")
    snaps = _rows(_load(SNAPSHOTS_FILE), "snapshots")
    res = {(p.get("date"), p.get("team"), p.get("market"), p.get("direction")):
           p.get("result") for p in picks if p.get("result") in ("win", "loss")}

    buckets: dict[float, list[int]] = collections.defaultdict(list)
    n = 0
    for s in snaps:
        if s.get("market") != "moneyline":
            continue
        fair = s.get("opening_fair_sharp")
        if fair is None:
            continue
        r = res.get((s.get("date"), s.get("team"),
                     s.get("market"), s.get("direction")))
        if r is None:
            continue
        buckets[min(int(float(fair) * 10) / 10, 0.9)].append(1 if r == "win" else 0)
        n += 1

    rows, worst = [], 0.0
    for b in sorted(buckets):
        v = buckets[b]
        if len(v) < 25:            # too few to read; ignore rather than mislead
            continue
        actual, predicted = sum(v) / len(v), b + 0.05
        rows.append({"bucket": round(b, 1), "n": len(v),
                     "predicted": round(predicted, 3),
                     "actual": round(actual, 3),
                     "gap": round(actual - predicted, 3)})
        worst = max(worst, abs(actual - predicted))
    return {"n": n, "buckets": rows, "worst_gap": round(worst, 3)}


def evaluate() -> dict:
    picks = [p for p in _rows(_load(PICKS_FILE), "picks")
             if p.get("strategy") == "polymarket_ev"
             and p.get("poly_protocol") == PROTO.PROTOCOL_VERSION]
    snaps = [s for s in _rows(_load(SNAPSHOTS_FILE), "snapshots")
             if s.get("strategy") == "polymarket_ev"
             and s.get("poly_filled") is not False]
    scored = [s for s in snaps if s.get("clv_pct") is not None]
    filled = [p for p in picks if p.get("poly_filled") is True]
    checked = [p for p in picks if p.get("poly_filled") is not None]

    clv_vals = [float(s["clv_pct"]) for s in scored]
    avg_clv = (sum(clv_vals) / len(clv_vals)) if clv_vals else None
    anchor = anchor_calibration()

    try:
        from scripts.paper_trader import run as paper_run
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            paper = paper_run(bankroll=PROTO.BANKROLL_USD)
    except Exception:
        paper = {}
    dd = (paper.get("max_drawdown") or 0.0) / PROTO.BANKROLL_USD

    gates = [
        {"gate": "SAMPLE", "have": len(scored), "need": PROTO.VERDICT_MIN_SCORED,
         "pass": len(scored) >= PROTO.VERDICT_MIN_SCORED,
         "detail": f"{len(scored)} scored of {len(picks)} logged "
                   f"(protocol {PROTO.PROTOCOL_VERSION})"},
        {"gate": "ANCHOR", "have": anchor["n"], "need": PROTO.ANCHOR_MIN_SAMPLE,
         "pass": (anchor["n"] >= PROTO.ANCHOR_MIN_SAMPLE
                  and anchor["worst_gap"] <= PROTO.ANCHOR_MAX_MISCALIBRATION),
         "detail": (f"{anchor['n']} graded sharp-fair picks; worst bucket gap "
                    f"{anchor['worst_gap']:.3f} vs max "
                    f"{PROTO.ANCHOR_MAX_MISCALIBRATION}")},
        {"gate": "FILLS", "have": len(filled), "need": PROTO.VERDICT_MIN_FILLED,
         "pass": len(filled) >= PROTO.VERDICT_MIN_FILLED,
         "detail": f"{len(filled)} filled of {len(checked)} checked"},
        {"gate": "CLV", "have": round(avg_clv, 3) if avg_clv is not None else None,
         "need": "> 0",
         "pass": bool(clv_vals) and avg_clv is not None and avg_clv > 0,
         "detail": (f"avg {avg_clv:+.3f}% over {len(clv_vals)} scored"
                    if clv_vals else "no scored CLV yet")},
        {"gate": "DRAWDOWN", "have": round(dd, 3), "need": f"< {PROTO.MAX_DRAWDOWN_FRAC}",
         "pass": dd < PROTO.MAX_DRAWDOWN_FRAC,
         "detail": f"paper max drawdown {dd:.1%} of bankroll"},
    ]

    # A gate fails CONCLUSIVELY only once it has the sample to say so. Before
    # then it is merely open — the distinction between "no" and "not yet".
    conclusive_fail = (
        (len(scored) >= PROTO.VERDICT_MIN_SCORED and avg_clv is not None and avg_clv <= 0)
        or (anchor["n"] >= PROTO.ANCHOR_MIN_SAMPLE
            and anchor["worst_gap"] > PROTO.ANCHOR_MAX_MISCALIBRATION)
        or dd >= PROTO.MAX_DRAWDOWN_FRAC
    )
    if conclusive_fail:
        verdict = "RETIRE"
    elif all(g["pass"] for g in gates):
        verdict = "PROMOTE"
    else:
        verdict = "WAIT"

    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "protocol": PROTO.as_dict(), "verdict": verdict,
            "gates": gates, "anchor": anchor,
            "n_logged": len(picks), "n_scored": len(scored)}


def run(as_json: bool = False) -> dict:
    out = evaluate()
    if as_json:
        print(json.dumps(out, indent=2))
        return out

    print(f"\n  POLYMARKET EXPERIMENT — protocol {PROTO.PROTOCOL_VERSION}")
    print("  " + "─" * 74)
    for g in out["gates"]:
        mark = "PASS" if g["pass"] else "open"
        print(f"  [{mark:4}] {g['gate']:9} {g['detail']}")
    print("  " + "─" * 74)
    print(f"  VERDICT: {out['verdict']}")

    if out["verdict"] == "WAIT":
        blocking = [g["gate"] for g in out["gates"] if not g["pass"]]
        print(f"  Waiting on: {', '.join(blocking)}")
        scored, need = out["n_scored"], PROTO.VERDICT_MIN_SCORED
        logged = out["n_logged"]
        if logged and scored < need:
            print(f"  {scored}/{need} scored. Nothing here is a result yet —")
            print("  read CLV when it arrives, never the paper P&L.")
    elif out["verdict"] == "RETIRE":
        print("  A gate failed with the sample to back it. This is a SUCCESS:")
        print("  the idea is closed off and it cost nothing to find out.")
    else:
        print("  Every pre-registered gate passed. A small real stake is")
        print("  defensible — start at one flat unit and re-check weekly.")

    anchor = out["anchor"]
    if anchor["buckets"]:
        print("\n  ANCHOR CALIBRATION (Pinnacle sharp fair vs reality)")
        for b in anchor["buckets"]:
            print(f"    {b['bucket']:.1f}-{b['bucket'] + 0.1:.1f}  n={b['n']:>4}  "
                  f"predicted {b['predicted']:.0%}  actual {b['actual']:.0%}  "
                  f"gap {b['gap']:+.3f}")
    else:
        print(f"\n  ANCHOR: only {anchor['n']} graded sharp-fair picks — too few")
        print("  to test the assumption the entire edge rests on.")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()
    run(as_json=a.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
