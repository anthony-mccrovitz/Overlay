#!/usr/bin/env python3
"""
Taint picks produced by known-broken model mechanisms (2026-07-19 audit).

Tainted picks KEEP their graded results in picks.json — they are the audit
trail of what the broken mechanisms did — but carry `tainted: "<reason>"` so
every honest consumer excludes them:
  - public stats / the record   (public_stats.py, chef.py record)
  - the edge-shrink gate table  (calibration_gate.compute_table)
  - calibrator fitting          (calibration.recalibrate_all)

Idempotent: rules are pinned to fixed date ranges (all ending on the fix ship
date 2026-07-19) and exact signatures, so re-running never taints post-fix
picks and never un-taints. Safe to run nightly.

Mechanisms (root causes fixed in the same PR that adds this script):
  asymmetric_calibrator  MLB moneyline: Platt calibrator applied to the home
                         side only (away = 1 − f(home)); f(0.50) ≈ 0.42-0.44
                         tilted EVERY pick to the away team. All-AWAY streak:
                         2026-05-31 → 2026-07-18 (138+ picks, 100% away).
  degenerate_calibrator  MLB NRFI: collapsed Platt pinned P(NRFI) ≈ 0.44 below
                         every market price → all-YRFI streak 2026-07-01 →
                         2026-07-18. MLB F5 totals: collapsed isotonic pinned
                         entire slates to constant plateau probabilities.
  team_blind_ratings     WNBA: ratings source returned league-average NET 0
                         for every team on many days 2026-06-19 → 2026-07-18;
                         every game priced as the same coin flip
                         (home 0.5879 = Φ(2/9), away 0.4121).
  in_progress_pricing    Golf outrights: pregame Monte Carlo (no leaderboard
                         state) priced tournaments mid-play — days AFTER the
                         scheduled start.

Usage:
  python3 scripts/taint_bad_picks.py --dry-run   # counts only, no writes
  python3 scripts/taint_bad_picks.py             # stamp + atomic rewrite
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tracking.schema import load_picks_safe, rewrite_picks_safe  # noqa: E402

PICKS_PATH = Path("data/pnl/picks.json")

# All rules are bounded by the fix ship date — nothing after it can be tainted
# by these historical mechanisms (their root causes are fixed in code).
FIX_DATE = "2026-07-19"

# Pinned streak boundaries (measured on the 2026-07-19 audit data).
ML_AWAY_START   = "2026-05-31"
NRFI_YRFI_START = "2026-07-01"
WNBA_BLIND_START = "2026-06-19"

# WNBA team-blind signature: with every team at NET 0, home prob is exactly
# Φ(HOME_COURT/spread_std) = Φ(2.0/9.0) = 0.5879 (away 0.4121).
WNBA_BLIND_PROBS = {0.4121, 0.5879}

# F5 plateau rails: a per-game probability that repeats ≥ this many times at
# 4 decimal places is a calibrator plateau, not a projection.
F5_PLATEAU_MIN_COUNT = 8

# Odds API golf key → scheduled tournament start (2026). A pick DATED AFTER
# the start was priced mid-tournament by a pregame simulator.
GOLF_STARTS = {
    "golf_the_players_championship_winner": "2026-03-12",
    "golf_masters_tournament_winner":       "2026-04-09",
    "golf_pga_championship_winner":         "2026-05-14",
    "golf_us_open_winner":                  "2026-06-18",
    "golf_the_open_championship_winner":    "2026-07-16",
}

_MLB = ("mlb", "baseball_mlb")


def _is_model_pick(p: dict) -> bool:
    return not p.get("strategy")


def build_rule_context(picks: list[dict]) -> tuple[set, set]:
    """Precompute the F5 plateau rails and the WNBA blind days."""
    # F5 plateau rails: model_prob values repeated across the F5 history
    f5_probs = Counter(
        round(float(p.get("model_prob") or 0), 4)
        for p in picks
        if p.get("market") == "f5_total" and p.get("sport") in _MLB
        and p.get("model_prob") is not None
    )
    f5_rails = {v for v, n in f5_probs.items() if n >= F5_PLATEAU_MIN_COUNT}
    f5_rails |= {0.0, 1.0}   # calibrator saturation rails are always bogus

    # WNBA blind DAYS: the ratings table is fetched once per run, so if the ML
    # signature appears on a date, every WNBA game market that day was priced
    # off the same blind table.
    wnba_blind_days = {
        p.get("date")
        for p in picks
        if p.get("sport") in ("wnba", "basketball_wnba")
        and p.get("market") == "moneyline" and _is_model_pick(p)
        and WNBA_BLIND_START <= str(p.get("date")) <= FIX_DATE
        and round(float(p.get("model_prob") or 0), 4) in WNBA_BLIND_PROBS
    }
    return f5_rails, wnba_blind_days


def classify_pick(p: dict, f5_rails: set, wnba_blind_days: set) -> str | None:
    """Return the taint reason for a pick, or None. Keyed on the pick's own
    fields (never pick_id — some legacy rows don't have one)."""
    sport  = str(p.get("sport") or "")
    market = str(p.get("market") or "")
    date_  = str(p.get("date") or "")
    if not date_ or date_ > FIX_DATE:
        return None

    if (sport in _MLB and market == "moneyline" and _is_model_pick(p)
            and p.get("direction") == "AWAY" and date_ >= ML_AWAY_START):
        return "asymmetric_calibrator"

    if (sport in _MLB and market == "nrfi" and _is_model_pick(p)
            and p.get("direction") == "YRFI" and date_ >= NRFI_YRFI_START):
        return "degenerate_calibrator"

    if (sport in _MLB and market == "f5_total" and _is_model_pick(p)
            and p.get("model_prob") is not None
            and round(float(p["model_prob"]), 4) in f5_rails):
        return "degenerate_calibrator"

    if (sport in ("wnba", "basketball_wnba") and _is_model_pick(p)
            and market in ("moneyline", "spread", "total")
            and date_ in wnba_blind_days):
        return "team_blind_ratings"

    if sport in GOLF_STARTS and date_ > GOLF_STARTS[sport]:
        return "in_progress_pricing"

    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dry-run", action="store_true",
                    help="report counts without writing")
    ap.add_argument("--picks", default=str(PICKS_PATH))
    args = ap.parse_args()

    path = Path(args.picks)
    data = load_picks_safe(path)
    picks = data["picks"]
    if not picks:
        print("no picks found")
        return 1

    f5_rails, wnba_blind_days = build_rule_context(picks)

    stamped = 0
    by_reason: Counter = Counter()
    for p in picks:
        reason = classify_pick(p, f5_rails, wnba_blind_days)
        if reason:
            by_reason[reason] += 1
            if p.get("tainted") != reason:
                p["tainted"] = reason
                stamped += 1

    print(f"picks scanned : {len(picks)}")
    print(f"taint matches : {sum(by_reason.values())}")
    for reason, n in by_reason.most_common():
        print(f"  {reason:24} {n}")
    print(f"newly stamped : {stamped}")

    if args.dry_run:
        print("(dry run — nothing written)")
        return 0
    if stamped == 0:
        print("nothing to write")
        return 0

    rewrite_picks_safe(path, data)
    print(f"written → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
