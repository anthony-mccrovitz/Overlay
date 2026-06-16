#!/usr/bin/env python3
"""
scripts/deploy_picks.py — Push picks to Vercel so subscribers can see them live

Runs after picks are generated to:
  1. Refresh public_stats.json (both local + web mirror)
  2. Stage all new/modified pick files + stats
  3. git commit + push → triggers Vercel auto-deploy from GitHub

Usage:
    python3 scripts/deploy_picks.py                    # deploy today's picks
    python3 scripts/deploy_picks.py --date 20260527    # specific date
    python3 scripts/deploy_picks.py --sport mlb        # after MLB picks only
    python3 scripts/deploy_picks.py --message "picks: 2026-05-27 NBA added"

Cron (run after each sport's picks pipeline):
    # After MLB night pipeline (~9:35 PM ET)
    35 1 * * * cd /path && python3 scripts/deploy_picks.py --sport mlb >> logs/deploy.log 2>&1
    # After NBA night pipeline (~9:40 PM ET)
    40 1 * * * cd /path && python3 scripts/deploy_picks.py --sport nba >> logs/deploy.log 2>&1
    # Morning full deploy (after tennis/soccer/caption ~9:15 AM ET)
    15 13 * * * cd /path && python3 scripts/deploy_picks.py >> logs/deploy.log 2>&1
    # Evening after grading (~12:05 AM ET)
    5 4 * * * cd /path && python3 scripts/deploy_picks.py --message "grades updated" >> logs/deploy.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


def run(cmd: list[str], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=check)


def refresh_stats() -> bool:
    """Refresh public_stats.json and copy to web mirror."""
    print("  ▸ Refreshing public_stats.json...")
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "chef.py"), "stats"],
            cwd=str(ROOT), capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  ⚠  stats refresh failed: {result.stderr[:200]}")
            return False

        # web/ frontend archived to legacy/ (overlay is the live app); no mirror.
        print(f"  ✓ Stats refreshed → data/public_stats.json")
        return True
    except Exception as e:
        print(f"  ⚠  Stats refresh error: {e}")
        return False


def get_changed_files(date_str: str, sport: str | None = None) -> list[str]:
    """Return list of pick-related files changed/untracked for git staging."""
    files_to_stage = [
        "data/public_stats.json",
        "data/pnl/picks.json",
    ]

    # Add all output/picks files for the date
    output_root = ROOT / "output" / "picks"
    if date_str:
        for sport_dir in output_root.iterdir():
            if not sport_dir.is_dir():
                continue
            if sport and sport.lower() not in sport_dir.name.lower():
                continue
            date_dir = sport_dir / date_str
            if date_dir.exists():
                for f in date_dir.rglob("*"):
                    if f.is_file():
                        files_to_stage.append(str(f.relative_to(ROOT)))

    return files_to_stage


def git_deploy(date_str: str, sport: str | None, message: str | None) -> bool:
    """Stage changed pick files, commit, and push to trigger Vercel deploy."""

    # Check if inside git repo
    try:
        run(["git", "rev-parse", "--git-dir"])
    except subprocess.CalledProcessError:
        print("  ✗ Not in a git repo — cannot deploy")
        return False

    # Stage files
    files = get_changed_files(date_str, sport)
    staged = 0
    for f in files:
        full = ROOT / f
        if full.exists():
            try:
                run(["git", "add", f])
                staged += 1
            except subprocess.CalledProcessError:
                pass

    # Also stage any untracked output/picks files for the date
    try:
        run(["git", "add", f"output/picks/*/{date_str}/"])
    except Exception:
        pass

    # Check if anything actually changed
    status = run(["git", "status", "--porcelain"], check=False)
    if not status.stdout.strip():
        print("  ℹ  No changes to commit — Vercel already up to date")
        return True

    # Build commit message
    if not message:
        sport_tag = f" {sport.upper()}" if sport else ""
        message = f"picks: {date_str[:4]}-{date_str[4:6]}-{date_str[6:]}{sport_tag}"

    # Commit
    try:
        run(["git", "commit", "-m", message])
        print(f"  ✓ Committed: {message}")
    except subprocess.CalledProcessError as e:
        print(f"  ✗ Commit failed: {e.stderr[:200]}")
        return False

    # Push
    try:
        result = run(["git", "push", "origin", "main"])
        print(f"  ✓ Pushed → GitHub (Vercel deploy triggered)")
        print(f"  🌐 Site updating — subscribers will see picks in ~60s")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ✗ Push failed: {e.stderr[:200]}")
        return False


def print_card_picks_summary(date_str: str) -> None:
    """Print a quick summary of what subs will see on the site."""
    pnl = ROOT / "data" / "pnl" / "picks.json"
    if not pnl.exists():
        return
    try:
        raw = json.loads(pnl.read_text())
        picks = raw if isinstance(raw, list) else raw.get("picks", [])
    except Exception:
        return

    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    card = [p for p in picks if p.get("card_pick") and
            str(p.get("date", "")).startswith(date_fmt) and not p.get("result")]

    if not card:
        return

    print(f"\n  📲 {len(card)} picks now live for subscribers:")
    for p in sorted(card, key=lambda x: -(x.get("edge_pct") or 0))[:5]:
        odds = p.get("odds", 0)
        odds_str = f"+{odds}" if odds > 0 else str(odds)
        sport = p.get("sport", "")[:3].upper()
        print(f"     {sport}  {p.get('team','')[:30]:<30}  {odds_str:<7}  edge {p.get('edge_pct',0):.1f}%")
    if len(card) > 5:
        print(f"     ... and {len(card)-5} more")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy picks to Vercel")
    parser.add_argument("--date",    default=date.today().strftime("%Y%m%d"), metavar="YYYYMMDD")
    parser.add_argument("--sport",   default=None, help="Sport tag for commit message")
    parser.add_argument("--message", default=None, help="Custom commit message")
    parser.add_argument("--no-push", action="store_true", help="Refresh stats only, skip git push")
    args = parser.parse_args()

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n  ── Deploy Picks → Vercel  [{now}] ──────────────────────")

    refresh_stats()

    if not args.no_push:
        git_deploy(args.date, args.sport, args.message)
        print_card_picks_summary(args.date)
    else:
        print("  ℹ  --no-push: skipped git deploy")

    print()


if __name__ == "__main__":
    main()
