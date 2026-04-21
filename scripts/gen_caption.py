#!/usr/bin/env python3
"""
Print today's ready-to-post social media captions.

The pipeline already generates these when predict.py --daily runs.
This script just finds and prints them in one place.

Usage:
    python scripts/gen_caption.py             # today's picks
    python scripts/gen_caption.py --date 2026-04-17
    python scripts/gen_caption.py --type nrfi  # just the NRFI caption
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

PICKS_ROOT = Path("output/picks/baseball_mlb")

CAPTION_FILES = [
    ("nrfi",     "caption_nrfi.txt",    "NRFI / YRFI"),
    ("picks",    "caption_picks.txt",   "MONEYLINE PICKS"),
    ("props",    "caption_props.txt",   "PROPS"),
    ("totals",   "caption_totals.txt",  "TOTALS"),
    ("runline",  "caption_runline.txt", "RUN LINE"),
]


def find_date_dir(target_date: date) -> Path | None:
    date_str = target_date.strftime("%Y%m%d")
    p = PICKS_ROOT / date_str
    if p.exists():
        return p
    # Fall back to most recent available
    dirs = sorted([d for d in PICKS_ROOT.iterdir() if d.is_dir() and d.name.isdigit()], reverse=True)
    return dirs[0] if dirs else None


def main():
    parser = argparse.ArgumentParser(description="Print today's ready-to-post captions")
    parser.add_argument("--date", type=str, default=None, help="Date (YYYY-MM-DD), default=today")
    parser.add_argument("--type", type=str, default=None,
                        choices=["nrfi", "picks", "props", "totals", "runline"],
                        help="Print only one caption type")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else date.today()
    pick_dir = find_date_dir(target_date)

    if not pick_dir:
        print(f"No picks found for {target_date}. Run predict.py --daily first.")
        return

    W = 70
    print(f"\n{'═'*W}")
    print(f"  CAPTIONS — {target_date.strftime('%B %d, %Y').upper()}")
    print(f"  Source: {pick_dir}")
    print(f"{'═'*W}")

    shown = 0
    for key, filename, label in CAPTION_FILES:
        if args.type and args.type != key:
            continue
        path = pick_dir / filename
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        print(f"\n── {label} {'─' * (W - len(label) - 4)}")
        print()
        print(content)
        shown += 1

    if shown == 0:
        print("\nNo caption files found. Run predict.py --daily to generate them.")
        print("(Expected files like caption_nrfi.txt, caption_picks.txt in output/picks/)")

    print(f"\n{'═'*W}")
    print(f"  Cards (PNG): {pick_dir}/*.png")
    print(f"{'═'*W}\n")


if __name__ == "__main__":
    main()
