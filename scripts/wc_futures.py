"""
World Cup 2026 futures report — model vs market.

Runs the Monte Carlo simulator for the model's championship/advance odds, pulls
the live FIFA World Cup Winner market from The Odds API, de-vigs it, and builds
a content-ready comparison: model %, market %, a blended ("credible") number,
and the biggest model-vs-Vegas disagreements (the contrarian-take candidates).

Saves output/picks/soccer/futures_2026.json for the web app / content pipeline.

Run:
    python3 scripts/wc_futures.py
    python3 scripts/wc_futures.py --sims 30000 --blend 0.35
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.soccer_data import normalize_team_name
from src.models.soccer_model_v2 import load_or_fit_model_v2
from src.models.wc_simulator import WorldCup2026

OUT = Path("output/picks/soccer/futures_2026.json")


def _american_to_imp(o: float) -> float:
    return 100.0 / (o + 100.0) if o >= 0 else abs(o) / (abs(o) + 100.0)


def fetch_market_futures() -> dict[str, float]:
    """Return de-vigged market P(win World Cup) per team (best price across books)."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return {}
    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup_winner/odds",
            params={"apiKey": key, "regions": "us,us2", "markets": "outrights",
                    "oddsFormat": "american"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [futures] market fetch failed: {e}")
        return {}
    if not data:
        return {}

    # Best (longest) price per team across books → least-vig estimate per team
    best: dict[str, float] = {}
    for ev in data:
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for o in mk.get("outcomes", []):
                    team = normalize_team_name(o["name"])
                    imp = _american_to_imp(o["price"])
                    if team not in best or imp < best[team]:
                        best[team] = imp  # lowest implied prob = longest price
    # De-vig: normalise so probabilities sum to 1
    total = sum(best.values())
    if total <= 0:
        return {}
    return {t: p / total for t, p in best.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--blend", type=float, default=0.35,
                    help="Model weight in the blended number (0=all market, 1=all model)")
    args = ap.parse_args()

    print("Loading model + seeding live Elo...")
    model = load_or_fit_model_v2(verbose=False)
    model.seed_from_eloratings()

    print(f"Simulating {args.sims:,} tournaments...")
    wc = WorldCup2026(model)
    fut = wc.simulate(n_sims=args.sims)
    model_champ = fut["champion"]

    print("Fetching market futures...")
    market = fetch_market_futures()
    w = args.blend

    # Merge: union of teams, blended where both exist
    teams = set(model_champ) | set(market)
    rows = []
    for t in teams:
        mp = model_champ.get(t, 0.0)
        kp = market.get(t)
        if kp is None:
            blend = mp
        else:
            blend = w * mp + (1 - w) * kp
        rows.append({
            "team": t,
            "model": round(mp, 4),
            "market": round(kp, 4) if kp is not None else None,
            "blend": round(blend, 4),
            "advance": round(fut["advance"].get(t, 0.0), 4),
            "reach_final": round(fut["reach_final"].get(t, 0.0), 4),
            "edge_pp": round((mp - kp) * 100, 1) if kp is not None else None,
        })
    rows.sort(key=lambda r: r["blend"], reverse=True)

    print("\n" + "=" * 72)
    print("WORLD CUP 2026 — CHAMPIONSHIP ODDS (model vs market)")
    print("=" * 72)
    print(f"  {'Team':<18} {'Model':>7} {'Market':>7} {'Blend':>7} {'Δpp':>6}  {'Final%':>6}")
    for r in rows[:16]:
        mk = f"{r['market']*100:5.1f}%" if r["market"] is not None else "   —  "
        dpp = f"{r['edge_pp']:+5.1f}" if r["edge_pp"] is not None else "   — "
        print(f"  {r['team']:<18} {r['model']*100:6.1f}% {mk:>7} "
              f"{r['blend']*100:6.1f}% {dpp:>6}  {r['reach_final']*100:5.1f}%")

    # Biggest disagreements (content candidates), among teams the market rates ≥2%
    disagree = [r for r in rows if r["edge_pp"] is not None and (r["market"] or 0) >= 0.02]
    over = sorted(disagree, key=lambda r: r["edge_pp"], reverse=True)[:3]
    under = sorted(disagree, key=lambda r: r["edge_pp"])[:3]
    print("\n  MODEL-vs-VEGAS DISAGREEMENTS (contrarian-take candidates):")
    print("    Model HIGHER than market:")
    for r in over:
        print(f"      {r['team']:<16} model {r['model']*100:.1f}% vs market {r['market']*100:.1f}%  (+{r['edge_pp']:.1f}pp)")
    print("    Model LOWER than market:")
    for r in under:
        print(f"      {r['team']:<16} model {r['model']*100:.1f}% vs market {r['market']*100:.1f}%  ({r['edge_pp']:.1f}pp)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated": date.today().isoformat(),
        "n_sims": args.sims,
        "blend_model_weight": w,
        "teams": rows,
    }, indent=2))
    print(f"\n  Saved → {OUT}")

    # Ready-to-post content (Engine B): captions per platform.
    try:
        from src.output.captions_sports import wc_futures_captions, write_sport_captions
        caps = wc_futures_captions(rows, w, date.today(), n_sims=args.sims)
        cap_dir = OUT.parent / "futures_captions"
        write_sport_captions(caps, cap_dir)
        print(f"  Captions → {cap_dir}/")
        print("\n  ── X/TWITTER PREVIEW ──")
        print("  " + caps["x_twitter"].replace("\n", "\n  "))
    except Exception as e:
        print(f"  [captions] {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
