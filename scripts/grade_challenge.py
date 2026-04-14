#!/usr/bin/env python3
"""
Grade the $50→$500 challenge bets against actual MLB results.

Usage:
  python scripts/grade_challenge.py
  python scripts/grade_challenge.py --date 2026-04-09
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.grading.auto_grade import fetch_final_scores

CHALLENGE_FILE = Path("data/challenge/bankroll.json")


def _load() -> dict:
    with open(CHALLENGE_FILE) as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(CHALLENGE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _american_payout(bet_amount: float, odds: int, won: bool) -> float:
    if not won:
        return -bet_amount
    if odds > 0:
        return bet_amount * (odds / 100.0)
    return bet_amount * (100.0 / abs(odds))


def _name_matches(game_team: str, bet_team: str) -> bool:
    """Fuzzy team name matching."""
    g = game_team.lower().strip()
    b = bet_team.lower().strip()
    # Check if any word in bet_team appears in game_team
    for word in b.split():
        if len(word) > 3 and word in g:
            return True
    return g == b or b in g or g in b


def grade_challenge(target_date: date | None = None) -> None:
    d = target_date or date.today()
    data = _load()
    bets = data["bets"]

    pending = [b for b in bets if b.get("result") == "pending"]
    if not pending:
        print("No pending bets to grade.")
        _print_summary(data)
        return

    print(f"\nFetching MLB results for {d.isoformat()}...")
    results = fetch_final_scores(d)
    final_games = [r for r in results if r["state"] == "Final"]

    if not final_games:
        print(f"  No final games yet for {d.isoformat()}.")
        pending_count = len(results) - len(final_games)
        print(f"  {len(results)} games scheduled, {pending_count} not finished yet.")
        return

    print(f"  {len(final_games)} final games found.\n")

    graded_count = 0
    for bet in pending:
        bet_team = bet["team"]
        market = bet["market"]

        matched = None
        for game in final_games:
            if _name_matches(game["home_team"], bet_team) or _name_matches(game["away_team"], bet_team):
                matched = game
                break

        if matched is None:
            print(f"  SKIP  {bet_team} — game not found or not finished")
            continue

        home = matched["home_team"]
        away = matched["away_team"]
        hs = matched["home_score"]
        aws = matched["away_score"]

        if hs is None or aws is None:
            print(f"  SKIP  {bet_team} — no score yet ({home} vs {away})")
            continue

        # Determine win/loss
        team_is_home = _name_matches(home, bet_team)
        team_score = hs if team_is_home else aws
        opp_score = aws if team_is_home else hs

        won = False
        if market == "moneyline":
            won = team_score > opp_score
        elif market == "spread":
            spread = float(bet.get("spread", 1.5))
            won = (team_score + spread) > opp_score
        elif market == "total":
            line = float(bet.get("line", 8.0))
            direction = bet.get("direction", "OVER").upper()
            total = hs + aws
            won = (total > line) if direction == "OVER" else (total < line)

        profit = round(_american_payout(bet["bet_amount"], bet["odds"], won), 2)
        bet["result"] = "win" if won else "loss"
        bet["profit"] = profit
        bet["resulted_at"] = datetime.now(tz=timezone.utc).isoformat()
        bet["final_score"] = f"{away} {aws} @ {home} {hs}"

        status = "WIN " if won else "LOSS"
        profit_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
        print(f"  {status}  {bet_team} ML {bet['odds']:+d} @ {bet['sportsbook']} "
              f"  [{away} {aws} @ {home} {hs}]  {profit_str}")
        graded_count += 1

    # Update current bankroll
    total_profit = sum(b.get("profit", 0) or 0 for b in bets if b.get("result") != "pending")
    data["current_bankroll"] = round(data["starting_bankroll"] + total_profit, 2)

    _save(data)

    if graded_count:
        print(f"\n  Graded {graded_count} bets.")
        _print_summary(data)
    else:
        print("  No bets matched final games yet.")


def _print_summary(data: dict) -> None:
    bets = data["bets"]
    settled = [b for b in bets if b.get("result") not in (None, "pending")]
    wins = sum(1 for b in settled if b["result"] == "win")
    losses = sum(1 for b in settled if b["result"] == "loss")
    pending = sum(1 for b in bets if b.get("result") == "pending")
    total_profit = sum(b.get("profit", 0) or 0 for b in settled)
    start = data["starting_bankroll"]
    current = data["current_bankroll"]
    pct_gain = (current - start) / start * 100

    print(f"\n{'='*50}")
    print(f"  $50 → $500 CHALLENGE TRACKER")
    print(f"{'='*50}")
    print(f"  Record:   {wins}W - {losses}L  ({pending} pending)")
    print(f"  P&L:      {'+' if total_profit >= 0 else ''}{total_profit:.2f} units")
    print(f"  Bankroll: ${current:.2f}  ({'+' if pct_gain >= 0 else ''}{pct_gain:.1f}% vs ${start:.0f} start)")
    target = data.get("target", 500)
    print(f"  Target:   ${target:.0f}  "
          f"(${(target - current):.2f} to go)")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grade $50→$500 challenge bets")
    parser.add_argument("--date", type=str, help="Date to grade (YYYY-MM-DD, default today)")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else None
    grade_challenge(target_date)
