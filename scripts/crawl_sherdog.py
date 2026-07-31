#!/usr/bin/env python3
"""Build the global MMA fight graph by snowball-crawling Sherdog.

WHY SNOWBALL. Resolving a fighter by name costs two requests (search, then
fetch) and risks the identity problem. But every fighter page links its
opponents BY SLUG — so once you are inside the graph, expansion is one request
per fighter and involves no name matching at all. Seed with a handful of
resolved UFC fighters, then follow opponents outward.

That is also why the resulting graph is worth having: a UFC fighter averages ~6
UFC bouts but ~20 professional bouts. The UFC-only view discards two thirds of
every fighter's career and all of their pre-UFC opposition.

Polite by construction: 2s between requests (robots.txt sets no crawl-delay;
this is courtesy), permanent on-disk cache, and fully resumable — killing it and
restarting picks up where it stopped, because the cache IS the state.

    python3 scripts/crawl_sherdog.py --seed-from-ufc 40 --max 8000
    python3 scripts/crawl_sherdog.py --status
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import sherdog
from src.models.ufc_features import load_bouts

_FRONTIER = sherdog._CACHE / ".frontier.json"


def cached_slugs() -> set[str]:
    return {p.stem for p in sherdog._CACHE.glob("*.json") if not p.name.startswith(".")}


def seed_from_ufc(n: int) -> list[str]:
    """Resolve the most-active UFC fighters by name to get into the graph.

    Uses date of birth from ufcstats as the identity key, so the seeds are the
    one place name matching happens — and it happens under the strict rule.
    """
    bouts, _stats, tott = load_bouts()
    counts: dict[str, int] = {}
    for b in bouts:
        for f in (b["w"], b["l"]):
            counts[f] = counts.get(f, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])

    seeds: list[str] = []
    for name, _c in ranked:
        if len(seeds) >= n:
            break
        dob = (tott.get(name) or {}).get("dob")
        f = sherdog.resolve(name, dob=dob) if dob else None
        if f is None:
            f = sherdog.resolve(name)
        if f is not None:
            seeds.append(f.slug)
            print(f"  seed {len(seeds):3d}/{n}  {name:28s} -> {f.slug}  {f.record}")
    return seeds


def crawl(seeds: list[str], max_fighters: int) -> int:
    """Breadth-first over opponent links. Returns fighters newly fetched."""
    seen = cached_slugs()
    queue: deque[str] = deque()

    if _FRONTIER.exists():
        try:
            for s in json.loads(_FRONTIER.read_text()):
                queue.append(s)
            print(f"  resumed frontier: {len(queue)} pending")
        except (OSError, ValueError):
            pass
    for s in seeds:
        if s not in seen:
            queue.append(s)

    # Re-expand what we already hold so a resumed run keeps growing rather than
    # stalling on an empty frontier.
    if not queue:
        for slug in list(seen)[:2000]:
            f = sherdog.load_cached(slug)
            if not f:
                continue
            for b in f.bouts:
                if b.opponent_slug and b.opponent_slug not in seen:
                    queue.append(b.opponent_slug)

    fetched = 0
    try:
        while queue and fetched < max_fighters:
            slug = queue.popleft()
            if slug in seen:
                continue
            f = sherdog.fetch_fighter(slug)
            seen.add(slug)
            if f is None:
                continue
            fetched += 1
            for b in f.bouts:
                if b.opponent_slug and b.opponent_slug not in seen:
                    queue.append(b.opponent_slug)
            if fetched % 25 == 0:
                print(f"  {fetched:5d} fetched | {len(queue):6d} queued | "
                      f"{len(seen):6d} cached | last: {f.name[:28]} {f.record}")
                _FRONTIER.write_text(json.dumps(list(queue)[:60000]))
    except KeyboardInterrupt:
        print("\n  interrupted — cache and frontier are intact, rerun to resume")
    _FRONTIER.write_text(json.dumps(list(queue)[:60000]))
    return fetched


def status() -> None:
    slugs = cached_slugs()
    n_bouts = 0
    promos: dict[str, int] = {}
    dated = 0
    for p in list(sherdog._CACHE.glob("*.json"))[:100000]:
        if p.name.startswith("."):
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        for b in d.get("bouts", []):
            n_bouts += 1
            promos[b.get("promotion", "?")] = promos.get(b.get("promotion", "?"), 0) + 1
            if b.get("when"):
                dated += 1
    q = 0
    if _FRONTIER.exists():
        try:
            q = len(json.loads(_FRONTIER.read_text()))
        except (OSError, ValueError):
            pass
    print(f"  fighters cached : {len(slugs):,}")
    print(f"  bout rows       : {n_bouts:,}  ({dated:,} dated)")
    print(f"  frontier queued : {q:,}")
    print("  top promotions  :")
    for name, c in sorted(promos.items(), key=lambda kv: -kv[1])[:12]:
        print(f"      {name:34s} {c:,}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed-from-ufc", type=int, default=0,
                    help="resolve N most-active UFC fighters as crawl seeds")
    ap.add_argument("--max", type=int, default=500, help="max fighters to fetch")
    ap.add_argument("--status", action="store_true", help="report cache state and exit")
    args = ap.parse_args()

    if args.status:
        status()
        return 0

    seeds = seed_from_ufc(args.seed_from_ufc) if args.seed_from_ufc else []
    n = crawl(seeds, args.max)
    print(f"\n  fetched {n} new fighters")
    status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
