#!/usr/bin/env python3
"""
chef.py — ChefTonyBets unified CLI

DAILY WORKFLOW (just two commands)
──────────────────────────────────────────────────────────────────────
  Morning:   python3 chef.py morning           # generates ALL picks + cards
  Evening:   python3 chef.py evening           # grades yesterday + shows record

INDIVIDUAL COMMANDS
──────────────────────────────────────────────────────────────────────
  python3 chef.py picks mlb                    # MLB picks only
  python3 chef.py picks nba                    # NBA picks only
  python3 chef.py grade                        # grade both MLB + NBA
  python3 chef.py grade --date 20260417        # grade specific date
  python3 chef.py record                       # full P&L breakdown
  python3 chef.py record --market nrfi         # NRFI record only
  python3 chef.py record --sport nba           # NBA record only
  python3 chef.py migrate                      # normalize picks.json schema
  python3 chef.py test                         # run grading unit tests
  python3 chef.py stats                        # refresh public_stats.json
──────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_PNL_FILE = Path("data/pnl/picks.json")

# ─────────────────────────── Helpers ─────────────────────────────────────────

def _run(cmd: list[str]) -> int:
    """Run a subprocess, stream output, return exit code."""
    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    return result.returncode


def _load_picks() -> list[dict]:
    if not _PNL_FILE.exists():
        return []
    try:
        return json.loads(_PNL_FILE.read_text()).get("picks", [])
    except (json.JSONDecodeError, OSError):
        return []


def _profit_str(val: float | None) -> str:
    if val is None:
        return "  —  "
    return f"{val:+.2f}u"


def _pct(a: int, b: int) -> str:
    return f"{a/b:.1%}" if b else "  —  "


# ─────────────────────────── picks ───────────────────────────────────────────

def cmd_picks(args: argparse.Namespace) -> int:
    sport = args.sport.lower()
    if sport == "mlb":
        cmd = [sys.executable, "predict.py", "--daily", "--sport", "mlb"]
        if getattr(args, "refresh", False):
            cmd.append("--refresh")
        return _run(cmd)
    elif sport == "nba":
        cmd = [sys.executable, "run_nba.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False):
            cmd.append("--refresh")
        return _run(cmd)
    else:
        print(f"Unknown sport: {sport}. Use 'mlb' or 'nba'.")
        return 1


# ─────────────────────────── grade ───────────────────────────────────────────

def cmd_grade(args: argparse.Namespace) -> int:
    grade_date = getattr(args, "date", None)
    if not grade_date:
        yesterday  = datetime.now() - timedelta(days=1)
        grade_date = yesterday.strftime("%Y%m%d")

    sport = getattr(args, "sport", "all")
    cmd   = [sys.executable, "grade.py", "--date", grade_date, "--sport", sport]
    return _run(cmd)


# ─────────────────────────── record ──────────────────────────────────────────

_MARKET_LABEL = {
    "moneyline": "Moneyline",
    "spread":    "Spread   ",
    "total":     "Totals   ",
    "nrfi":      "NRFI     ",
    "prop":      "Props    ",
}

_SPORT_LABEL = {"mlb": "MLB", "nba": "NBA"}


def cmd_record(args: argparse.Namespace) -> int:
    picks = _load_picks()
    if not picks:
        print("  No picks found. Run: python3 chef.py picks mlb")
        return 0

    filter_market = getattr(args, "market", "all")
    filter_sport  = getattr(args, "sport",  "all")

    card_picks = [p for p in picks if p.get("card_pick")]
    if filter_market != "all":
        card_picks = [p for p in card_picks if p.get("market") == filter_market]
    if filter_sport != "all":
        card_picks = [p for p in card_picks if p.get("sport") == filter_sport]

    settled  = [p for p in card_picks if p.get("result") in ("win", "loss", "push")]
    non_push = [p for p in settled if p.get("result") != "push"]
    wins     = [p for p in non_push if p.get("result") == "win"]
    losses   = [p for p in non_push if p.get("result") == "loss"]
    pending  = [p for p in card_picks if not p.get("result")]
    profit   = sum(float(p.get("profit") or 0) for p in non_push)
    staked   = sum(float(p.get("stake") or 1) for p in non_push)
    wr       = len(wins) / len(non_push) if non_push else 0.0
    roi      = profit / staked if staked > 0 else 0.0

    # Streak
    streak = 0
    for p in sorted(non_push, key=lambda x: x.get("resulted_at") or x.get("date") or ""):
        r = p.get("result")
        if r == "win":
            streak = streak + 1 if streak >= 0 else 1
        elif r == "loss":
            streak = streak - 1 if streak <= 0 else -1

    streak_str = (f"+{streak} WIN streak" if streak > 0 else
                  f"{streak} LOSS streak" if streak < 0 else "—")

    sep = "═" * 60
    print(f"\n  {sep}")
    title = "ChefTonyBets — RECORD"
    if filter_sport != "all":
        title += f" ({filter_sport.upper()})"
    if filter_market != "all":
        title += f" [{filter_market}]"
    print(f"  {title}")
    print(f"  {date.today().strftime('%B %d, %Y')}")
    print(f"  {'─'*58}")
    print(f"  OVERALL   {len(wins)}-{len(losses)}  ({wr:.1%} WR)  "
          f"{_profit_str(profit)}  ROI {roi:+.1%}")
    print(f"  Streak    {streak_str}")
    print(f"  Pending   {len(pending)} picks")
    print(f"  {'─'*58}")

    if filter_market == "all":
        # Per-market breakdown
        print(f"  {'MARKET':<12} {'W-L':>8}  {'WR':>7}  {'PROFIT':>8}  {'ROI':>7}")
        print(f"  {'─'*56}")
        for market_key, label in _MARKET_LABEL.items():
            mp = [p for p in card_picks if p.get("market") == market_key]
            ms = [p for p in mp if p.get("result") in ("win", "loss", "push")]
            mnp = [p for p in ms if p.get("result") != "push"]
            mw = sum(1 for p in mnp if p.get("result") == "win")
            ml = len(mnp) - mw
            mpr = sum(float(p.get("profit") or 0) for p in mnp)
            mst = sum(float(p.get("stake") or 1) for p in mnp)
            mwr = mw / len(mnp) if mnp else 0.0
            mroi = mpr / mst if mst > 0 else 0.0
            if not mp:
                continue
            print(f"  {label:<12} {mw}-{ml:>2}  {_pct(mw,len(mnp)):>7}  "
                  f"{_profit_str(mpr):>8}  {mroi:>+6.1%}")

        print(f"  {'─'*56}")

        # Per-sport breakdown
        print(f"\n  {'SPORT':<12} {'W-L':>8}  {'WR':>7}  {'PROFIT':>8}  {'ROI':>7}")
        print(f"  {'─'*56}")
        for sport_key, slabel in _SPORT_LABEL.items():
            sp = [p for p in card_picks if p.get("sport") == sport_key]
            ss = [p for p in sp if p.get("result") in ("win", "loss", "push")]
            snp = [p for p in ss if p.get("result") != "push"]
            sw = sum(1 for p in snp if p.get("result") == "win")
            sl = len(snp) - sw
            spr = sum(float(p.get("profit") or 0) for p in snp)
            sst = sum(float(p.get("stake") or 1) for p in snp)
            swr = sw / len(snp) if snp else 0.0
            sroi = spr / sst if sst > 0 else 0.0
            if not sp:
                continue
            print(f"  {slabel:<12} {sw}-{sl:>2}  {_pct(sw,len(snp)):>7}  "
                  f"{_profit_str(spr):>8}  {sroi:>+6.1%}")

    # Recent 10 settled picks
    recent = sorted(
        non_push,
        key=lambda x: x.get("resulted_at") or x.get("date") or "",
        reverse=True,
    )[:10]

    if recent:
        print(f"\n  {'─'*58}")
        print(f"  RECENT PICKS")
        print(f"  {'DATE':<12} {'SPORT':<5} {'MKT':<11} {'TEAM':<26} {'RESULT':<6} {'P/L':>6}")
        print(f"  {'─'*56}")
        for p in recent:
            d    = str(p.get("date") or "")[:10]
            sp   = str(p.get("sport") or "?").upper()
            mkt  = str(p.get("market") or "?")[:10]
            team = str(p.get("team") or "?")[:25]
            res  = str(p.get("result") or "?").upper()
            pstr = _profit_str(p.get("profit"))
            col  = "" if res == "WIN" else ""
            print(f"  {d:<12} {sp:<5} {mkt:<11} {team:<26} {res:<6} {pstr:>6}")

    print(f"\n  {sep}\n")
    return 0


# ─────────────────────────── migrate ─────────────────────────────────────────

def cmd_migrate(args: argparse.Namespace) -> int:
    from src.tracking.schema import migrate_picks_file
    import shutil

    if not _PNL_FILE.exists():
        print("  picks.json not found — nothing to migrate.")
        return 0

    backup = _PNL_FILE.with_suffix(".json.bak")
    shutil.copy(_PNL_FILE, backup)
    print(f"  Backup: {backup}")

    result = migrate_picks_file(str(_PNL_FILE))
    if "error" in result:
        print(f"  Error: {result['error']}")
        return 1

    print(f"  Migration complete:")
    print(f"    Input picks:   {result['total_in']}")
    print(f"    Removed (corrupt): {result['removed']}")
    print(f"    Deduplicated:  {result['deduplicated']}")
    print(f"    Output picks:  {result['total_out']}")

    # Validate all picks
    from src.tracking.schema import validate_pick
    picks = json.loads(_PNL_FILE.read_text()).get("picks", [])
    errors = [(p.get("pick_id"), validate_pick(p)) for p in picks if validate_pick(p)]
    if errors:
        print(f"\n  ⚠  {len(errors)} validation issues after migration:")
        for pid, iss in errors[:5]:
            print(f"    {pid}: {iss}")
    else:
        print(f"  ✓  All {result['total_out']} picks valid.")

    return 0


# ─────────────────────────── test ────────────────────────────────────────────

def cmd_test(args: argparse.Namespace) -> int:
    return _run([sys.executable, "-m", "pytest", "tests/test_grading.py", "-v"])


# ─────────────────────────── stats ───────────────────────────────────────────

def cmd_stats(args: argparse.Namespace) -> int:
    """Refresh public_stats.json from current picks.json."""
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
        return 0
    except Exception as e:
        print(f"  Error: {e}")
        return 1


# ─────────────────────────── morning ───────────────────────────────────────

def cmd_morning(args: argparse.Namespace) -> int:
    """Run full morning pipeline: MLB picks + NBA picks + open cards folder."""
    import platform

    today = datetime.now().strftime("%Y%m%d")
    sep = "═" * 60
    print(f"\n  {sep}")
    print(f"  ChefTonyBets — MORNING PIPELINE — {datetime.now().strftime('%B %d, %Y')}")
    print(f"  {sep}\n")

    # 1) MLB picks + cards
    print("  ▸ Generating MLB picks + cards...")
    rc = _run([sys.executable, "predict.py", "--daily", "--sport", "mlb"])
    if rc != 0:
        print("  ✗ MLB picks failed")
        return rc
    print("  ✓ MLB picks done\n")

    # 2) NBA picks + cards
    print("  ▸ Generating NBA picks + cards...")
    rc = _run([sys.executable, "run_nba.py"])
    if rc != 0:
        print(f"  ✗ NBA picks failed (may be off-season)")
    else:
        print("  ✓ NBA picks done\n")

    # 3) Show where cards are
    mlb_dir = Path(f"output/picks/baseball_mlb/{today}")
    nba_dir = Path(f"output/picks/basketball_nba/{today}")

    print(f"\n  {sep}")
    print(f"  CARDS READY — post these to IG/X/TikTok:")
    print(f"  {'─'*58}")
    if mlb_dir.exists():
        for f in sorted(mlb_dir.glob("*.png")):
            print(f"    MLB  {f.name}")
    if nba_dir.exists():
        for f in sorted(nba_dir.glob("*.png")):
            print(f"    NBA  {f.name}")
    print(f"  {'─'*58}")
    print(f"  Captions in same folders (caption_*.txt)")
    print(f"  {sep}\n")

    # 4) Open cards folder on macOS
    if platform.system() == "Darwin" and mlb_dir.exists():
        subprocess.run(["open", str(mlb_dir)], check=False)

    return 0


# ─────────────────────────── evening ───────────────────────────────────────

def cmd_evening(args: argparse.Namespace) -> int:
    """Grade yesterday's picks, show record, refresh stats."""
    grade_date = getattr(args, "date", None)
    if not grade_date:
        yesterday = datetime.now() - timedelta(days=1)
        grade_date = yesterday.strftime("%Y%m%d")

    sep = "═" * 60
    print(f"\n  {sep}")
    print(f"  ChefTonyBets — EVENING GRADING — {datetime.now().strftime('%B %d, %Y')}")
    print(f"  Grading picks from: {grade_date}")
    print(f"  {sep}\n")

    # 1) Grade
    print("  ▸ Grading picks...")
    rc = _run([sys.executable, "grade.py", "--date", grade_date, "--sport", "all"])
    if rc != 0:
        print("  ✗ Grading failed")
        return rc
    print("  ✓ Grading done\n")

    # 2) Record
    print("  ▸ Full record:\n")
    cmd_record(argparse.Namespace(market="all", sport="all"))

    # 3) Refresh public stats
    print("  ▸ Refreshing public_stats.json...")
    cmd_stats(argparse.Namespace())

    return 0


# ─────────────────────────── Entry point ─────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="chef",
        description="ChefTonyBets unified picks + grading CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # picks mlb / picks nba
    p_picks = sub.add_parser("picks", help="Generate picks for a sport")
    p_picks.add_argument("sport", choices=["mlb", "nba"], help="Sport to generate picks for")
    p_picks.add_argument("--date",    help="Date YYYYMMDD (NBA only; MLB always uses today)")
    p_picks.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")

    # grade
    p_grade = sub.add_parser("grade", help="Grade picks against actual results")
    p_grade.add_argument("--sport", default="all", choices=["all", "mlb", "nba"])
    p_grade.add_argument("--date",  help="Date YYYYMMDD (default: yesterday)")

    # record
    p_record = sub.add_parser("record", help="Show P&L record and breakdown")
    p_record.add_argument("--market", default="all",
                          choices=["all", "moneyline", "spread", "total", "nrfi", "prop"])
    p_record.add_argument("--sport",  default="all", choices=["all", "mlb", "nba"])

    # migrate
    sub.add_parser("migrate", help="Normalize picks.json to canonical schema")

    # test
    sub.add_parser("test", help="Run grading unit tests")

    # stats
    sub.add_parser("stats", help="Refresh public_stats.json")

    # morning — full morning pipeline
    sub.add_parser("morning", help="Morning pipeline: MLB + NBA picks, generate all cards")

    # evening — grade + record + stats
    p_evening = sub.add_parser("evening", help="Evening: grade yesterday, show record, refresh stats")
    p_evening.add_argument("--date", help="Date YYYYMMDD to grade (default: yesterday)")

    args = parser.parse_args()

    dispatch = {
        "picks":   cmd_picks,
        "grade":   cmd_grade,
        "record":  cmd_record,
        "migrate": cmd_migrate,
        "test":    cmd_test,
        "stats":   cmd_stats,
        "morning": cmd_morning,
        "evening": cmd_evening,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
