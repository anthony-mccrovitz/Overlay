#!/usr/bin/env python3
"""
Overlay — Morning Script
Run this every morning before posting picks.

Usage:
    python3 morning.py             # MLB (default)
    python3 morning.py --sport nba # NBA
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Overlay morning run")
    parser.add_argument("--sport", default="mlb", choices=["mlb", "nba", "nfl"])
    args = parser.parse_args()

    sport_key = {
        "mlb": "baseball_mlb",
        "nba": "basketball_nba",
        "nfl": "americanfootball_nfl",
    }[args.sport]

    today = date.today().strftime("%Y%m%d")
    print(f"\n{'='*60}")
    print(f"  Overlay Morning Run — {args.sport.upper()} — {date.today().strftime('%B %d, %Y')}")
    print(f"{'='*60}\n")

    # Step 1: Run model picks
    print("Step 1/3  Running model + fetching odds...")
    result = subprocess.run(
        [sys.executable, "predict.py", "--daily", "--sport", args.sport],
        capture_output=False
    )
    if result.returncode != 0:
        print("  ⚠️  predict.py failed. Check logs.")
        return

    # Step 2: Generate slate card + cache opening lines
    print("\nStep 2/3  Generating full slate card + caching opening lines...")
    _generate_slate(sport_key, today)

    # Step 3: Show current record
    print("\nStep 3/3  Current record:")
    subprocess.run([sys.executable, "track.py", "status"])

    picks_dir = Path(f"output/picks/{sport_key}/{today}")
    print(f"\n{'='*60}")
    print(f"  Cards saved to: {picks_dir}/")
    print(f"    pick_card.png  — post this to Instagram/X (top 5 picks)")
    print(f"    slate_card.png — share with friends (all games)")
    print(f"\n  Done. Go post. 🍳")
    print(f"{'='*60}\n")


def _generate_slate(sport_key: str, today: str):
    """Generate the full slate card."""
    try:
        from src.data.odds_api import fetch_odds, get_best_odds
        from src.output.slate_card import generate_slate_card
        import pandas as pd
        from datetime import date as _date

        df  = fetch_odds(markets='h2h,spreads,totals', sport=sport_key)
        if df.empty:
            print("  No odds data — skipping slate card.")
            return

        ml  = get_best_odds(df, market='h2h')
        sp  = get_best_odds(df, market='spreads')
        tot = get_best_odds(df, market='totals')

        picks_path = Path(f"output/picks/{sport_key}/{today}/picks.json")
        model_edges = {}
        if picks_path.exists():
            for p in json.loads(picks_path.read_text()):
                model_edges[p.get("Team","").lower()] = p.get("Edge", 0) or 0

        master = ml.merge(
            sp[['GameID','AwaySpread','BestAwaySpreadOdds','HomeSpread','BestHomeSpreadOdds']],
            on='GameID', how='left')
        master = master.merge(
            tot[['GameID','Total','BestOverOdds','BestUnderOdds']],
            on='GameID', how='left')

        rows = []
        for _, r in master.iterrows():
            away, home = r['AwayTeam'], r['HomeTeam']
            aml  = int(r['BestAwayML'])  if pd.notna(r.get('BestAwayML'))  else 0
            hml  = int(r['BestHomeML'])  if pd.notna(r.get('BestHomeML'))  else 0
            aimp = float(r['AwayImpliedProb']) if pd.notna(r.get('AwayImpliedProb')) else 0.5
            himp = float(r['HomeImpliedProb']) if pd.notna(r.get('HomeImpliedProb')) else 0.5
            ae   = model_edges.get(away.lower(), 0)
            he   = model_edges.get(home.lower(), 0)

            if ae > 0.02:   ml_pick, ml_odds = away, aml
            elif he > 0.02: ml_pick, ml_odds = home, hml
            elif himp>aimp: ml_pick, ml_odds = home, hml
            else:           ml_pick, ml_odds = away, aml

            asp = float(r['AwaySpread']) if pd.notna(r.get('AwaySpread')) else -1.5
            hsp = float(r['HomeSpread']) if pd.notna(r.get('HomeSpread')) else 1.5
            aso = int(r['BestAwaySpreadOdds']) if pd.notna(r.get('BestAwaySpreadOdds')) else -110
            hso = int(r['BestHomeSpreadOdds']) if pd.notna(r.get('BestHomeSpreadOdds')) else -110
            bev = max(ae, he)
            bet = away if ae >= he else home

            if bev >= 0.07:
                rl_pick, rl_spread, rl_odds = (away, asp, aso) if bet==away else (home, hsp, hso)
            else:
                rl_pick, rl_spread, rl_odds = (away, hsp if hsp>0 else asp, hso if hsp>0 else aso) if aml>hml else (home, hsp if hsp>0 else asp, hso if hsp>0 else aso)

            total   = float(r['Total'])       if pd.notna(r.get('Total'))       else 7.5
            over_o  = int(r['BestOverOdds'])  if pd.notna(r.get('BestOverOdds'))  else -110
            under_o = int(r['BestUnderOdds']) if pd.notna(r.get('BestUnderOdds')) else -110
            ou_pick = "OVER" if total <= 7.5 else "UNDER"

            rows.append({"away": away, "home": home,
                         "away_ml": aml, "home_ml": hml,
                         "ml_pick": ml_pick, "ml_odds": ml_odds,
                         "rl_pick": rl_pick, "rl_spread": rl_spread, "rl_odds": rl_odds,
                         "total": total, "ou_pick": ou_pick,
                         "ou_odds": over_o if ou_pick=="OVER" else under_o,
                         "model_edge": round(bev, 3),
                         "commence": str(r.get('CommenceTime',''))[:16]})

        sport_lbl = {"baseball_mlb":"MLB","basketball_nba":"NBA","americanfootball_nfl":"NFL"}.get(sport_key,"MLB")
        y, m, d2 = int(today[:4]), int(today[4:6]), int(today[6:8])
        path = generate_slate_card(rows, sport_label=sport_lbl, card_date=_date(y, m, d2))
        print(f"  Slate card saved: {path}  ({len(rows)} games)")

        # Save slate.json — all games + lines for full-slate accuracy grading
        from datetime import datetime, timezone
        slate_dir = Path(f"output/picks/{sport_key}/{today}")
        slate_dir.mkdir(parents=True, exist_ok=True)
        slate_payload = {
            "date": today,
            "sport": sport_key,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "games": rows,
        }
        slate_path = slate_dir / "slate.json"
        slate_path.write_text(json.dumps(slate_payload, indent=2, default=str))
        print(f"  Slate JSON saved:  {slate_path}")

        # Cache opening lines for line-movement detection (first snapshot of the day only)
        _cache_opening_lines(sport_key, today, rows)

    except Exception as e:
        print(f"  ⚠️  Slate card failed: {e}")


def _cache_opening_lines(sport_key: str, today: str, rows: list[dict]):
    """
    Persist today's opening odds snapshot to data/cache/opening_lines/.
    Called once per morning — skips if file already exists (idempotent).
    Used in 2+ weeks to detect line movement vs current odds (SHARP badge).
    """
    cache_dir = Path("data/cache/opening_lines")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{today}_{sport_key}.json"

    if cache_file.exists():
        print(f"  Opening lines already cached for {today}.")
        return

    from datetime import datetime, timezone
    snapshot = {
        "date":      today,
        "sport":     sport_key,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "games": [
            {
                "away":     r["away"],
                "home":     r["home"],
                "away_ml":  r.get("away_ml", 0),
                "home_ml":  r.get("home_ml", 0),
                "spread":   r["rl_spread"],
                "total":    r["total"],
                "commence": r.get("commence", ""),
            }
            for r in rows
        ],
    }
    cache_file.write_text(json.dumps(snapshot, indent=2))
    print(f"  Opening lines cached: {cache_file}  ({len(rows)} games)")


if __name__ == "__main__":
    main()
