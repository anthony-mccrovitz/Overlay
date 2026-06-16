#!/usr/bin/env python3
"""Backfill shadow_filter on every existing pick.

Phase 2.5: classify every historical pick with the shadow A/B filter recommendation
so the analyzer can show baseline vs filter-applied performance immediately.

Idempotent — picks already tagged keep their recommendation unless --force.

Usage:
    python3 scripts/backfill_shadow_filter.py
    python3 scripts/backfill_shadow_filter.py --force --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"

sys.path.insert(0, str(ROOT))

from src.analytics.shadow_filters import classify_form_filter  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="Re-classify even picks that already have shadow_filter")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.loads(PICKS_FILE.read_text())
    picks = data.get("picks", data) if isinstance(data, dict) else data
    if isinstance(data, list):
        picks = data
        data = {"picks": picks}

    counts: Counter[str] = Counter()
    n_changed = 0
    for p in picks:
        if p.get("shadow_filter") and not args.force:
            counts["skipped_existing"] += 1
            continue
        rec = classify_form_filter(p)
        p["shadow_filter"] = rec
        counts[rec.get("recommendation", "unknown")] += 1
        n_changed += 1

    print(f"[backfill] classified {n_changed} picks")
    for k, v in counts.most_common():
        print(f"  {k:<18} {v}")

    if not args.dry_run and n_changed > 0:
        PICKS_FILE.write_text(json.dumps(data, indent=2))
        print(f"[backfill] wrote {PICKS_FILE}")
    elif args.dry_run:
        print("[backfill] DRY RUN — no changes written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
