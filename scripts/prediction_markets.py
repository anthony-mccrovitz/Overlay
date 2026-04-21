#!/usr/bin/env python3
"""
Prediction market arb scanner — ChefTonyBets.

Scans Kalshi and Polymarket for:
  1. Guaranteed arbs (same event, combined cost < 1.0 across platforms)
  2. Price divergences (same event priced differently — value bet signal)

Usage:
    python scripts/prediction_markets.py                    # live scan
    python scripts/prediction_markets.py --refresh          # force fresh data
    python scripts/prediction_markets.py --category sports  # filter category
    python scripts/prediction_markets.py --bankroll 500     # set bankroll
    python scripts/prediction_markets.py --save             # save results to JSON
    python scripts/prediction_markets.py --top 10           # show top N only

Categories: sports, politics, economics, crypto, entertainment, other
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.prediction_arb import find_all_arbs, format_arb_report, to_json
from src.data.kalshi import fetch_all_markets as kalshi_all, fetch_sports_markets, fetch_politics_markets
from src.data.polymarket import fetch_all_markets as poly_all, fetch_sports_markets as poly_sports, fetch_politics_markets as poly_politics
from src.data.entity_resolver import EntityResolver
from src.data.prediction_arb import (
    find_kalshi_poly_arbs,
    find_divergences,
    format_arb_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prediction market arb scanner")
    parser.add_argument("--refresh", action="store_true", help="Force fresh data")
    parser.add_argument("--category", default=None,
                        choices=["sports", "politics", "economics", "crypto", "entertainment", "other", "all"],
                        help="Filter by category")
    parser.add_argument("--bankroll", type=float, default=1000.0, help="Bankroll for stake calculation")
    parser.add_argument("--save", action="store_true", help="Save results to output/prediction_markets/")
    parser.add_argument("--top", type=int, default=20, help="Show top N arbs")
    parser.add_argument("--min-margin", type=float, default=4.0, help="Minimum arb margin %")
    parser.add_argument("--min-divergence", type=float, default=5.0, help="Minimum divergence %")
    parser.add_argument("--kalshi-only", action="store_true", help="Only fetch Kalshi markets")
    parser.add_argument("--poly-only", action="store_true", help="Only fetch Polymarket markets")
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n  ChefTonyBets — Prediction Market Scanner  ({date_str})")
    print("  " + "─" * 60)

    # --- Fetch markets ---
    cat = args.category

    if not args.poly_only:
        print("\n  Fetching Kalshi...")
        if cat == "sports":
            kalshi_markets = fetch_sports_markets(refresh=args.refresh)
        elif cat == "politics":
            kalshi_markets = fetch_politics_markets(refresh=args.refresh)
        else:
            kalshi_markets = kalshi_all(refresh=args.refresh)
        print(f"  → {len(kalshi_markets)} Kalshi markets loaded")
    else:
        kalshi_markets = []

    if not args.kalshi_only:
        print("\n  Fetching Polymarket...")
        if cat == "sports":
            poly_markets = poly_sports(refresh=args.refresh)
        elif cat == "politics":
            poly_markets = poly_politics(refresh=args.refresh)
        else:
            poly_markets = poly_all(refresh=args.refresh)
        print(f"  → {len(poly_markets)} Polymarket markets loaded")
    else:
        poly_markets = []

    if not kalshi_markets and not poly_markets:
        print("\n  No markets fetched.")
        print("  Polymarket requires no auth but may be temporarily unavailable.")
        print("  For Kalshi: go to kalshi.com/profile/api → generate API key → set KALSHI_API_KEY in .env")
        sys.exit(0)

    if not kalshi_markets:
        print("\n  Kalshi unavailable — showing Polymarket markets only.")
        print("  To enable Kalshi arbs: go to kalshi.com/profile/api → generate API key → set KALSHI_API_KEY in .env\n")
        print(f"  POLYMARKET ({len(poly_markets)} markets):")
        for m in sorted(poly_markets, key=lambda x: x.volume_usd, reverse=True)[:30]:
            print(f"    [{m.category:12s}] YES={m.yes_prob:.3f}  vol=${m.volume_usd:>10,.0f}  {m.question[:60]}")
            print(f"                  {m.url}")
        sys.exit(0)

    if not poly_markets:
        print("\n  Polymarket unavailable — showing Kalshi markets only.\n")
        print(f"  KALSHI ({len(kalshi_markets)} markets):")
        for m in sorted(kalshi_markets, key=lambda x: x.volume, reverse=True)[:30]:
            print(f"    [{m.category:12s}] YES={m.yes_prob:.3f}  vol={m.volume:>8}  {m.title[:60]}")
            print(f"                  {m.url}")
        sys.exit(0)

    # --- Entity resolution + arb finding ---
    resolver = EntityResolver()

    print(f"\n  Matching {len(kalshi_markets)} × {len(poly_markets)} markets...")
    arbs = find_kalshi_poly_arbs(
        kalshi_markets, poly_markets, resolver,
        min_margin=args.min_margin / 100,
    )
    divergences = find_divergences(
        kalshi_markets, poly_markets, resolver,
        min_divergence_pct=args.min_divergence,
    )

    results = {
        "kalshi_poly_arbs": arbs[:args.top],
        "divergences": divergences[:args.top],
        "kalshi_count": len(kalshi_markets),
        "poly_count": len(poly_markets),
    }

    # --- Print report ---
    print(format_arb_report(results, bankroll=args.bankroll))

    # --- Save to disk ---
    if args.save:
        today = datetime.now().strftime("%Y%m%d")
        out_dir = Path(f"output/prediction_markets/{today}")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "arbs.json"

        serializable = to_json(results)
        serializable["generated_at"] = datetime.now().isoformat()
        serializable["bankroll"] = args.bankroll

        with open(out_path, "w") as f:
            json.dump(serializable, f, indent=2)
        print(f"\n  Saved to {out_path}")

    # --- Summary ---
    print(f"\n  SUMMARY")
    print(f"  Arbs found:       {len(arbs)}")
    print(f"  Divergences:      {len(divergences)}")
    if arbs:
        best = arbs[0]
        sa, sb, profit = best.stakes(args.bankroll)
        print(f"  Best arb:         {best.margin_pct:.2f}% margin → +${profit:.2f} on ${args.bankroll:,.0f}")
        print(f"  Best arb title:   {best.title_a[:60]}")
    if divergences:
        best_div = divergences[0]
        print(f"  Biggest diverge:  {best_div.divergence_pct:.1f}% gap on:")
        print(f"    Kalshi:     {best_div.title_a[:55]}")
        print(f"    Polymarket: {best_div.title_b[:55]}")
    print()


if __name__ == "__main__":
    main()
