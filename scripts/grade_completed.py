#!/usr/bin/env python3
"""
Per-game post-game grader.

Designed to run every 10-15 min via cron. Grades any completed game from
today's slate. Idempotent — already-graded picks are skipped by the
underlying graders.

Picks up:
  - MLB picks (moneyline, run line, totals, NRFI, props)
  - NBA picks (moneyline, spread, totals, props)
  - NHL picks (when grader is wired up — Tier 3)

Usage:
    python3 scripts/grade_completed.py            # today
    python3 scripts/grade_completed.py --date 20260424
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "logs" / "grade_completed.log"


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYYMMDD (default: today)")
    args = ap.parse_args()

    target = args.date or date.today().strftime("%Y%m%d")

    # Sports with real-time auto-grading via grade.py subprocess.
    # Outrights (pga/nascar/f1/indycar) require --winner flag — handled by grade_outrights.py.
    SPORTS = ("mlb", "nba", "nhl", "wnba", "soccer", "tennis", "ufc")

    rc_total = 0
    any_graded = False
    for sport in SPORTS:
        cmd = [sys.executable, str(ROOT / "grade.py"), "--date", target, "--sport", sport]
        try:
            result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                _log(f"  {sport.upper()} grader exit {result.returncode}: {result.stderr[:200]}")
                rc_total += 1
            else:
                if "WIN" in result.stdout or "LOSS" in result.stdout or "win" in result.stdout or "loss" in result.stdout:
                    last_lines = "\n".join(result.stdout.strip().splitlines()[-3:])
                    _log(f"  {sport.upper()} graded: {last_lines}")
                    any_graded = True
        except subprocess.TimeoutExpired:
            _log(f"  {sport.upper()} grader TIMEOUT after 120s")
            rc_total += 1

    # Generate result cards immediately after grading — no waiting until 4 AM
    if any_graded:
        try:
            card_date = f"{target[:4]}-{target[4:6]}-{target[6:]}"
            result_card_cmd = [sys.executable, str(ROOT / "scripts" / "gen_result_cards.py"), "--date", card_date]
            subprocess.run(result_card_cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
            _log(f"  Result cards generated for {card_date}")
        except Exception as e:
            _log(f"  Result cards failed: {e}")

    return rc_total


if __name__ == "__main__":
    sys.exit(main())
