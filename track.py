#!/usr/bin/env python3
"""
EdgeFinder Paper Trading Tracker
─────────────────────────────────
Usage:
  python3 track.py bet  "Team" "Opponent" --odds 140 --stake 1     # log a paper bet
  python3 track.py win  "Team"                                      # mark as won
  python3 track.py loss "Team"                                      # mark as lost
  python3 track.py status                                           # P&L dashboard
  python3 track.py history                                          # all bets
  python3 track.py card                                             # record string for pick card
  python3 track.py delete "Team"                                    # remove a pending bet
  python3 track.py analytics                                        # full quant dashboard + CLV
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, date
from pathlib import Path

DATA_FILE = Path("data/pnl/picks.json")
DEFAULT_STAKE = 1.0   # 1 unit


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


def _profit(stake: float, odds: float, won: bool) -> float:
    if not won:
        return -stake
    if odds > 0:
        return stake * odds / 100
    return stake * 100 / abs(odds)


def _load() -> dict:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        return {"picks": []}
    try:
        data = json.loads(DATA_FILE.read_text())
        if "picks" not in data:
            raise ValueError
        return data
    except (json.JSONDecodeError, ValueError):
        backup = DATA_FILE.with_suffix(".corrupt.json")
        DATA_FILE.replace(backup)
        print(f"  ⚠️  Corrupted data backed up to {backup}")
        return {"picks": []}


def _save(data: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2))


def _match(pick: dict, team: str) -> bool:
    return pick["team"].lower().strip() == team.lower().strip()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_bet(args):
    team     = args.team
    opponent = args.opponent or "?"
    odds     = args.odds
    stake    = args.stake
    market   = args.market or "moneyline"

    data = _load()
    # Check for duplicate
    pending = [p for p in data["picks"] if _match(p, team) and p["result"] is None]
    if pending:
        print(f"  ⚠️  Already have a pending bet on {team}. Use 'win' or 'loss' first.")
        return

    pick = {
        "date":       _today(),
        "team":       team,
        "opponent":   opponent,
        "market":     market,
        "odds":       float(odds),
        "stake":      float(stake),
        "result":     None,
        "profit":     None,
        "recorded_at": _now(),
        "resulted_at": None,
    }
    data["picks"].append(pick)
    _save(data)

    sign = "+" if odds > 0 else ""
    print(f"\n  ✅ Logged: {team} ML  {sign}{odds}  ({stake}u stake)")
    print(f"     Win pays: +{_profit(stake, odds, True):.2f}u  |  Loss: -{stake:.2f}u")
    print(f"     vs {opponent}  ·  {market.upper()}\n")


def cmd_result(args, won: bool):
    team = args.team
    data = _load()

    for pick in reversed(data["picks"]):
        if _match(pick, team) and pick["result"] is None:
            pick["result"]     = "win" if won else "loss"
            pick["profit"]     = round(_profit(pick["stake"], pick["odds"], won), 4)
            pick["resulted_at"] = _now()
            _save(data)
            emoji  = "🟢 WIN" if won else "🔴 LOSS"
            profit = pick["profit"]
            sign   = "+" if profit >= 0 else ""
            print(f"\n  {emoji}  {team}  →  {sign}{profit:.2f}u\n")
            cmd_status_inline(data)
            return

    print(f"  ⚠️  No pending bet found for '{team}'.")
    print(f"     Tip: names are case-insensitive but must match what you logged.\n")


def _card_picks(picks: list) -> list:
    """Return only card picks (stake > 0 / top-5 posted picks). Excludes analytics-only rows."""
    return [p for p in picks if float(p.get("stake", p.get("bet_size", 1.0)) or 0) > 0]


def cmd_status_inline(data: dict):
    picks   = _card_picks(data["picks"])
    settled = [p for p in picks if p["result"] in ("win", "loss")]
    pending = [p for p in picks if p["result"] is None]

    wins   = sum(1 for p in settled if p["result"] == "win")
    losses = sum(1 for p in settled if p["result"] == "loss")
    staked = sum(p.get("stake", p.get("bet_size", 1.0)) for p in settled)
    profit = sum(p.get("profit", 0.0) or 0.0 for p in settled)
    roi    = (profit / staked * 100) if staked > 0 else 0.0

    # Current streak
    streak_str = ""
    if settled:
        ordered = sorted(settled, key=lambda p: p.get("resulted_at") or p["recorded_at"])
        direction = ordered[-1]["result"]
        streak = 0
        for p in reversed(ordered):
            if p["result"] == direction:
                streak += 1
            else:
                break
        emoji = "🔥" if direction == "win" else "❄️"
        streak_str = f"  {emoji} {streak} {direction} streak"

    profit_sign = "+" if profit >= 0 else ""

    print(f"  ─────────────────────────────────────────")
    print(f"  RECORD   {wins}W – {losses}L{streak_str}")
    print(f"  PROFIT   {profit_sign}{profit:.2f}u  |  ROI  {profit_sign}{roi:.1f}%")
    if pending:
        print(f"  PENDING  {len(pending)} bet(s): {', '.join(p['team'] for p in pending)}")
    print(f"  ─────────────────────────────────────────\n")


def cmd_status(args):
    data = _load()
    picks = _card_picks(data["picks"])
    if not picks:
        print("\n  No bets recorded yet.")
        print("  Run:  python3 track.py bet \"Team\" \"Opponent\" --odds 140\n")
        return

    print()
    cmd_status_inline(data)

    # Today's pending bets
    today   = _today()
    pending = [p for p in picks if p["result"] is None and p["date"] == today]
    if pending:
        print(f"  TODAY'S PENDING BETS:")
        for p in pending:
            sign = "+" if p["odds"] > 0 else ""
            print(f"    {p['team']:<28} ML  {sign}{int(p['odds'])}  ({p['stake']}u)")
        print()


def cmd_history(args):
    data  = _load()
    picks = _card_picks(data["picks"])
    if not picks:
        print("\n  No bets recorded yet.\n")
        return

    print(f"\n  {'DATE':<11} {'TEAM':<28} {'ODDS':>6}  {'STAKE':>5}  {'RESULT':<8}  {'PROFIT':>7}")
    print(f"  {'─'*72}")
    total_profit = 0.0
    for p in picks:
        res      = p.get("result") or "pending"
        profit   = p.get("profit")
        prof_str = f"{profit:+.2f}u" if profit is not None else "  —"
        odds     = float(p.get("odds", 0))
        sign     = "+" if odds > 0 else ""
        stake    = float(p.get("stake", p.get("bet_size", 1.0)))
        # Handle both new schema (date) and old schema (recorded_at)
        rec_date = p.get("date") or (p.get("recorded_at", "")[:10] if p.get("recorded_at") else "?")
        team     = p.get("team", "?")
        if profit is not None:
            total_profit += profit
        print(f"  {rec_date:<11} {team:<28} {sign}{int(odds):>5}  {stake:>4.1f}u  {res:<8}  {prof_str:>7}")

    print(f"  {'─'*72}")
    s = "+" if total_profit >= 0 else ""
    print(f"  {'TOTAL':>47}  {s}{total_profit:.2f}u\n")


def cmd_card(args):
    data  = _load()
    picks = _card_picks(data["picks"])
    settled = [p for p in picks if p["result"] in ("win", "loss")]
    if not settled:
        print("  0-0 (no settled bets yet)")
        return

    # Break out by market so the public record is clearly labeled
    ml_settled    = [p for p in settled if p.get("market", "moneyline") == "moneyline"]
    other_settled = [p for p in settled if p.get("market", "moneyline") != "moneyline"]

    def _summary(bets):
        wins   = sum(1 for p in bets if p["result"] == "win")
        losses = len(bets) - wins
        staked = sum(p.get("stake", p.get("bet_size", 1.0)) for p in bets)
        profit = sum(p.get("profit", 0.0) or 0.0 for p in bets)
        roi    = (profit / staked * 100) if staked > 0 else 0.0
        return wins, losses, profit, roi

    ml_w, ml_l, ml_profit, ml_roi = _summary(ml_settled) if ml_settled else (0,0,0.0,0.0)
    all_w, all_l, all_profit, all_roi = _summary(settled)

    profit_sign = "+" if ml_profit >= 0 else ""
    print(f"\n  MONEYLINE  {ml_w}-{ml_l}  |  {profit_sign}{ml_profit:.2f}u  |  {ml_roi:+.1f}% ROI")
    if other_settled:
        ow, ol, op, oroi = _summary(other_settled)
        print(f"  OTHER      {ow}-{ol}  |  {op:+.2f}u  |  {oroi:+.1f}% ROI")
        print(f"  COMBINED   {all_w}-{all_l}  |  {all_profit:+.2f}u  |  {all_roi:+.1f}% ROI")

    # Card string uses ML record (what you post publicly)
    card_str = f"{ml_w}-{ml_l}  ·  {profit_sign}{ml_profit:.2f}u  ·  {ml_roi:+.1f}% ROI"
    print(f"\n  Card string: \"{card_str}\"")
    print(f"\n  Use with: python3 predict.py --daily --record \"{card_str}\"")


def cmd_delete(args):
    team = args.team
    data = _load()
    before = len(data["picks"])
    data["picks"] = [p for p in data["picks"] if not (_match(p, team) and p["result"] is None)]
    if len(data["picks"]) < before:
        _save(data)
        print(f"  Removed pending bet for '{team}'.")
    else:
        print(f"  No pending bet found for '{team}'.")


def cmd_analytics(args):
    """Full quant dashboard: performance analytics + CLV report."""
    try:
        from src.analytics.performance import full_dashboard
    except ImportError as e:
        print(f"  Could not import performance module: {e}")
        return

    try:
        from src.analytics.clv_tracker import print_clv_report
    except ImportError as e:
        print(f"  Could not import clv_tracker module: {e}")
        print_clv_report = None

    full_dashboard(str(DATA_FILE))

    if print_clv_report is not None:
        print_clv_report()


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="track", description="EdgeFinder paper tracker")
    sub    = parser.add_subparsers(dest="cmd")

    # bet
    p_bet = sub.add_parser("bet", help="Log a paper bet")
    p_bet.add_argument("team")
    p_bet.add_argument("opponent", nargs="?", default="?")
    p_bet.add_argument("--odds",   type=float, required=True, help="American odds e.g. 140 or -126")
    p_bet.add_argument("--stake",  type=float, default=DEFAULT_STAKE, help="Units (default 1)")
    p_bet.add_argument("--market", default="moneyline", help="moneyline|spread|total")

    # win / loss
    p_win  = sub.add_parser("win",  help="Mark a bet as won")
    p_win.add_argument("team")
    p_loss = sub.add_parser("loss", help="Mark a bet as lost")
    p_loss.add_argument("team")

    # status / history / card / delete / analytics
    sub.add_parser("status",    help="P&L dashboard")
    sub.add_parser("history",   help="Full bet history")
    sub.add_parser("card",      help="Record string for pick card footer")
    sub.add_parser("analytics", help="Full quant dashboard (ROI, calibration, CLV)")
    p_del = sub.add_parser("delete", help="Remove a pending bet")
    p_del.add_argument("team")

    args = parser.parse_args()

    if args.cmd == "bet":
        cmd_bet(args)
    elif args.cmd == "win":
        cmd_result(args, won=True)
    elif args.cmd == "loss":
        cmd_result(args, won=False)
    elif args.cmd == "status":
        cmd_status(args)
    elif args.cmd == "history":
        cmd_history(args)
    elif args.cmd == "card":
        cmd_card(args)
    elif args.cmd == "delete":
        cmd_delete(args)
    elif args.cmd == "analytics":
        cmd_analytics(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
