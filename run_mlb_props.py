"""
MLB Player Props Pipeline — ChefTonyBets

Fetches live player prop odds, enriches with MLB Stats API stats,
runs through the Negative Binomial model, and finds edges.

Output: output/picks/baseball_mlb/YYYYMMDD/props.json

Run:
    python3 run_mlb_props.py
    python3 run_mlb_props.py --refresh
    python3 run_mlb_props.py --markets pitcher_strikeouts
    python3 run_mlb_props.py --min-edge 3.0
    python3 run_mlb_props.py --date 20260515
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from src.data.mlb_props_fetcher import fetch_all_mlb_props, enrich_props_with_stats
from src.models.mlb_props_nb import NegBinPropModel, PROP_CONFIGS
from src.tracking.schema import normalize_pick
from src.config.models import is_live, shadow_stake

PNL_FILE = Path("data/pnl/picks.json")


def _load_or_skip_model(prop_type: str) -> NegBinPropModel | None:
    model = NegBinPropModel(prop_type)
    if model.model_path.exists():
        model.load()
        return model
    return None


def _auto_log_picks(edges: list[dict], game_date: date) -> int:
    if not edges:
        return 0

    pnl_data: dict = {}
    if PNL_FILE.exists():
        try:
            pnl_data = json.loads(PNL_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pnl_data = {}

    picks = pnl_data.get("picks", [])
    existing_ids = {p.get("pick_id") for p in picks if isinstance(p, dict)}

    now   = datetime.now(timezone.utc).isoformat()
    added = 0

    for e in edges:
        direction = e.get("direction", "OVER")
        market    = e.get("market", "pitcher_strikeouts")
        raw = {
            "date":        game_date.isoformat(),
            "sport":       "baseball_mlb",
            "market":      market,
            "direction":   direction,
            "team":        f"{e.get('player', '')} {direction} {e.get('line', '')}",
            "matchup":     e.get("matchup", ""),
            "odds":        e.get("odds", -110),
            "line":        e.get("line"),
            "sportsbook":  e.get("sportsbook", ""),
            "model_prob":  e.get("model_prob"),
            "edge_pct":    e.get("edge_pct"),
            "stake":       shadow_stake("baseball_mlb", market),
            "card_pick":   is_live("baseball_mlb", market),
            "result":      None,
            "profit":      None,
            "recorded_at": now,
        }
        norm = normalize_pick(raw)
        pid  = norm.get("pick_id")
        if pid and pid in existing_ids:
            continue
        picks.append(norm)
        if pid:
            existing_ids.add(pid)
        added += 1

    pnl_data["picks"] = picks
    PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
    PNL_FILE.write_text(json.dumps(pnl_data, indent=2))
    return added


def run_mlb_props(args: argparse.Namespace) -> int:
    markets   = getattr(args, "markets", None) or list(PROP_CONFIGS.keys())
    if isinstance(markets, str):
        markets = [markets]
    min_edge  = getattr(args, "min_edge", 3.0)
    refresh   = getattr(args, "refresh", False)
    date_str  = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    game_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
    today_str = game_date.strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print(f"  MLB Player Props — Edge Detection")
    print(f"  {game_date.strftime('%B %d, %Y')}  |  markets: {', '.join(markets)}")
    print(f"{'='*60}")

    # 1. Load NB models
    models: dict[str, NegBinPropModel] = {}
    for m in markets:
        model = _load_or_skip_model(m)
        if model:
            models[m] = model
            print(f"  [model] {m} — loaded (alpha={model._alpha:.3f})")
        else:
            print(f"  [model] {m} — not fitted, skipping")

    if not models:
        print("  No fitted models available. Run: python3 -c \"from src.models.mlb_props_nb import train_all_prop_models; train_all_prop_models()\"")
        return 1

    active_markets = list(models.keys())

    # 2. Fetch props
    print(f"\n  Fetching live props...")
    props = fetch_all_mlb_props(markets=active_markets, refresh=refresh, verbose=True)
    if not props:
        print("  No props found.")
        return 0

    # 3. Enrich with MLB Stats API
    print(f"\n  Enriching {len(props)} props with MLB Stats API...")
    enriched = enrich_props_with_stats(props, verbose=True)

    # 4. Find edges per model
    all_edges: list[dict] = []
    for market, model in models.items():
        market_props = [p for p in enriched if p.get("market") == market]
        if not market_props:
            continue
        edges = model.find_edges(market_props, min_edge_pct=min_edge)
        print(f"  {market}: {len(market_props)} props → {len(edges)} edge(s)")
        all_edges.extend(edges)

    all_edges.sort(key=lambda x: x["edge_pct"], reverse=True)

    if not all_edges:
        print(f"\n  No edges ≥ {min_edge}% found today.")
    else:
        print(f"\n  Top edges:")
        for e in all_edges[:15]:
            print(
                f"    {e['player']:25s}  {e['direction']} {e['line']}  "
                f"edge={e['edge_pct']:+.1f}%  odds={e['odds']:+d}  "
                f"model={e['model_prob']:.1%}  mu={e['model_mu']:.1f}  "
                f"[{e['sportsbook']}]"
            )

    # Pinnacle disagreement guard
    try:
        from src.betting.value_bets import flag_high_edge_picks
        high_edge = flag_high_edge_picks(all_edges, threshold_pct=8.0)
        if high_edge:
            print(f"\n  WARNING: {len(high_edge)} prop(s) with edge >8% — verify player stats are current:")
            for e in high_edge[:5]:
                print(f"    {e['player']} {e['direction']} {e['line']}  edge={e['edge_pct']:+.1f}%")
    except Exception:
        pass

    # 5. Save output
    out_dir = Path("output/picks/baseball_mlb") / today_str
    out_dir.mkdir(parents=True, exist_ok=True)
    props_path = out_dir / "props.json"
    props_path.write_text(json.dumps(all_edges, indent=2, default=str))
    print(f"\n  Props saved → {props_path}")

    # 6. Auto-log (only pitcher Ks currently, others pending NB training)
    card_markets = {"pitcher_strikeouts"}
    log_edges = [e for e in all_edges if e.get("market") in card_markets]
    added = _auto_log_picks(log_edges, game_date)
    if added:
        print(f"  Logged {added} pitcher K edge(s) to PnL.")

    # 7. CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} prop pick(s)")
    except Exception as err:
        print(f"  [CLV snapshot] {err}")

    print(f"\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLB player props picks pipeline")
    parser.add_argument("--markets",  type=str, nargs="+",
                        choices=list(PROP_CONFIGS.keys()),
                        help="Prop markets to run (default: all)")
    parser.add_argument("--min-edge", type=float, default=3.0,
                        help="Minimum edge %% threshold (default: 3.0)")
    parser.add_argument("--date",     type=str, help="Date YYYYMMDD (default: today)")
    parser.add_argument("--refresh",  action="store_true",
                        help="Force-refresh props cache")
    args = parser.parse_args()
    sys.exit(run_mlb_props(args))
