"""
PGA Tour Major Picks Pipeline — ChefTonyBets

Runs Monte Carlo simulation for the current major, finds edges vs book odds.
Output saved to output/picks/golf_pga/YYYYMMDD/picks.json

Run:
    python3 run_pga.py
    python3 run_pga.py --n-sim 200000     # more sims = better accuracy
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from src.models.pga_championship import run_pga_model, print_report, save_picks


def main(args: argparse.Namespace) -> int:
    print(f"\n{'='*60}")
    print(f"  PGA Tour Major Picks")
    print(f"{'='*60}")

    picks = run_pga_model(n_sim=getattr(args, "n_sim", 100_000))
    if not picks:
        print("  No picks generated.")
        return 1

    print_report(picks, top_n=20)
    out = save_picks(picks)
    print(f"\n  Full output → {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PGA major picks pipeline")
    parser.add_argument("--n-sim", type=int, default=100_000, help="Monte Carlo simulations (default 100k)")
    sys.exit(main(parser.parse_args()))
