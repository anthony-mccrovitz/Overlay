#!/usr/bin/env python3
"""
One screen for the whole Polymarket pilot: chef.py polydash.

Pulls together what is otherwise five commands — today's board, what is still
open, whether resting orders filled, the paper bankroll, the CLV verdict, and
when we entered relative to kickoff. It composes the existing modules rather
than recomputing anything, so there is one implementation of each number.

Reading order matters, so the layout enforces it. CLV comes before P&L
because at these sample sizes P&L is noise: a +5% edge on a 20% shot needs
thousands of settled bets before realised profit separates from zero, and
eleven picks can show +19% ROI while losing money in expectation. Entry lead
is last because it is the question the pilot is really trying to answer —
whether we are looking at the right moment.

Usage:
  python3 scripts/polymarket_dashboard.py
  python3 scripts/polymarket_dashboard.py --date 2026-07-20
  python3 scripts/polymarket_dashboard.py --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date as _date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PICKS_FILE = Path("data/pnl/picks.json")
FILLS_FILE = Path("data/clv/polymarket_fills.json")
TIMING_FILE = Path("data/clv/polymarket_timing.json")

W = 74


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _picks() -> list[dict]:
    raw = _load(PICKS_FILE)
    if raw is None:
        return []
    ps = raw.get("picks", raw) if isinstance(raw, dict) else raw
    return [p for p in ps if p.get("strategy") == "polymarket_ev"]


def _hours_before_start(pick: dict) -> float | None:
    """How early we entered, relative to kickoff."""
    def _e(ts):
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(
                str(ts).replace("Z", "+00:00").replace(" ", "T"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
    rec, start = _e(pick.get("recorded_at")), _e(pick.get("poly_game_start"))
    if rec is None or start is None:
        return None
    return round((start - rec).total_seconds() / 3600.0, 2)


def _rule(title: str = "") -> None:
    print("  " + "─" * W)
    if title:
        print(f"  {title}")
        print("  " + "─" * W)


def build(eff_date: str) -> dict:
    picks = _picks()
    today = [p for p in picks if str(p.get("date")) == eff_date]
    settled = [p for p in picks if str(p.get("result") or "").lower()
               in ("win", "loss", "push", "void")]
    open_ = [p for p in picks if p not in settled]

    leads = [h for h in (_hours_before_start(p) for p in picks) if h is not None]
    filled = [p for p in picks if p.get("poly_filled") is True]
    unfilled = [p for p in picks if p.get("poly_filled") is False]

    return {"date": eff_date, "picks": picks, "today": today,
            "settled": settled, "open": open_, "leads": leads,
            "filled": filled, "unfilled": unfilled}


def run(eff_date: str | None = None, as_json: bool = False) -> dict:
    eff_date = eff_date or _date.today().isoformat()
    d = build(eff_date)

    if as_json:
        out = {k: (len(v) if isinstance(v, list) else v)
               for k, v in d.items() if k != "picks"}
        print(json.dumps(out, indent=2, default=str))
        return d

    print(f"\n  POLYMARKET PILOT — {eff_date}")
    _rule()

    # ── 1. today's board ────────────────────────────────────────────────
    print(f"  TODAY   {len(d['today'])} pick(s) logged")
    for p in sorted(d["today"], key=lambda x: -(x.get("edge_pct") or 0))[:12]:
        lead = _hours_before_start(p)
        size = p.get("poly_max_stake_usd")
        size_s = (f"${size:,.0f}" if size else "thin" if size == 0 else "?")
        print(f"    {p.get('edge_pct', 0):>+6.1f}%  {str(p.get('team'))[:22]:22} "
              f"@{p.get('poly_cost', 0):.3f}  lead "
              f"{f'{lead:.1f}h' if lead is not None else '  ?  '}  size {size_s}")
    if not d["today"]:
        print("    (nothing cleared the bar — the normal state)")

    # ── 2. open exposure ────────────────────────────────────────────────
    _rule()
    print(f"  OPEN    {len(d['open'])} unsettled")
    if d["open"]:
        # Capital a live account would have tied up right now.
        locked = sum(4.48 for _ in d["open"])
        print(f"    ~${locked:,.2f} would be locked in a live account "
              f"(flat $4.48, no cap yet)")

    # ── 3. fills ────────────────────────────────────────────────────────
    _rule()
    fills = _load(FILLS_FILE) or {}
    fs = fills.get("summary") or {}
    if fs:
        print(f"  FILLS   {fs.get('fill_rate_pct')}% "
              f"({fs.get('n_filled')}/{fs.get('n')})   "
              f"drift {fs.get('mean_post_fill_drift')}")
        ef, eu = fs.get("claimed_ev_filled"), fs.get("claimed_ev_unfilled")
        if ef is not None and eu is not None:
            flag = "  ← paper EV is in the orders that DON'T fill" if ef < eu else ""
            print(f"          claimed EV  filled {ef}%  vs unfilled {eu}%{flag}")
        print("          (price-history proxy — an UPPER bound on filling)")
    else:
        print("  FILLS   not measured yet — needs picks with post-entry history")

    # ── 4. CLV before P&L, deliberately ─────────────────────────────────
    _rule()
    try:
        from src.analytics.clv_tracker import get_clv_by_strategy
        row = (get_clv_by_strategy() or {}).get("polymarket_ev")
    except Exception:
        row = None
    if row:
        print(f"  CLV     {row.get('scored', 0)}/{row.get('picks', 0)} scored   "
              f"{row.get('verdict', '')}")
    else:
        print("  CLV     no scored snapshots yet")
    print("          CLV is the signal to read at low n — not P&L.")

    # ── 5. paper P&L ────────────────────────────────────────────────────
    _rule()
    try:
        from scripts.paper_trader import _significance, run as paper_run
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pl = paper_run()
    except Exception:
        pl = {}
    if pl and pl.get("n_settled"):
        print(f"  PAPER   ${pl['start_bankroll']:.2f} → ${pl['end_bankroll']:.2f}   "
              f"{pl['wins']}W-{pl['losses']}L   ROI {pl['roi_pct']}%")
        print(f"          realised {pl['pnl']:+.2f} vs expected "
              f"{pl['expected_pnl']:+.2f}   maxDD ${pl['max_drawdown']:.2f}")
        sig = pl.get("significance") or {}
        if sig.get("n_for_2sigma"):
            print(f"          needs ~{sig['n_for_2sigma']:,} settled bets before "
                  f"this P&L means anything")
    else:
        print("  PAPER   nothing settled yet (no money at risk — the point)")

    # ── 6. timing ───────────────────────────────────────────────────────
    _rule()
    if d["leads"]:
        print(f"  ENTRY   our leads: median {statistics.median(d['leads']):.1f}h "
              f"before kickoff (n={len(d['leads'])}, "
              f"{min(d['leads']):.1f}–{max(d['leads']):.1f}h)")
    tm = _load(TIMING_FILE) or {}
    rows = tm.get("rows") or []
    if rows:
        print(f"  MARKET  price discovery over {tm.get('n_markets')} played games:")
        for r in rows:
            if r["lead_hours"] in (48, 24, 12, 6, 3, 1):
                print(f"            {r['lead_hours']:>4}h out  "
                      f"{r['move_remaining']:.4f} still to move  "
                      f"({r['pct_moving_over_2c']:.0f}% move >2c)")
        print("          Run scripts/polymarket_timing.py to refresh.")
    else:
        print("  MARKET  timing not measured — run scripts/polymarket_timing.py")

    _rule()
    print("  Shadow only. Nothing here has risked money.")
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="slate date YYYY-MM-DD (default: today)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()
    run(eff_date=a.date, as_json=a.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
