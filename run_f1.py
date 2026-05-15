"""
Formula 1 Daily Picks Pipeline — ChefTonyBets

Wrapper around run_nascar.py with F1 sport key.

Run:
    python3 run_f1.py
    python3 run_f1.py --n-sim 100000
    python3 run_f1.py --date 20260524
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run_nascar import run_motorsport

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="F1 picks pipeline")
    parser.add_argument("--sport",    type=str, default="auto_racing_formula_one")
    parser.add_argument("--n-sim",   type=int, default=50_000)
    parser.add_argument("--min-edge", type=float, default=3.0)
    parser.add_argument("--date",    type=str, help="Date YYYYMMDD (default: today)")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    sys.exit(run_motorsport(args))
