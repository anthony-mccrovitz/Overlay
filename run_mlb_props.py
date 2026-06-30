"""
MLB Player Props Pipeline — Overlay

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

from src.data.mlb_props_fetcher import fetch_all_mlb_props, enrich_props_with_stats, PROP_MARKETS as _ODDS_MARKETS
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

    from src.tracking.schema import append_picks_safe

    existing_ids: set[str] = set()
    now     = datetime.now(timezone.utc).isoformat()
    entries: list[dict] = []

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
        entries.append(norm)
        if pid:
            existing_ids.add(pid)

    PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
    return append_picks_safe(PNL_FILE, entries)


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

    # 2. Fetch props — only markets the Odds API actually carries
    fetch_markets = [m for m in active_markets if m in _ODDS_MARKETS]
    if not fetch_markets:
        print("  No active models have Odds API coverage. Cannot fetch props.")
        return 0

    print(f"\n  Fetching live props...")
    props = fetch_all_mlb_props(markets=fetch_markets, refresh=refresh, verbose=True)
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

    # Combined props.json (backward compat)
    props_path = out_dir / "props.json"
    props_path.write_text(json.dumps(all_edges, indent=2, default=str))
    print(f"\n  Props saved → {props_path}")

    # Per-market files: props_pitcher_strikeouts.json, props_batter_hits.json, etc.
    markets_in_output = {e.get("market") for e in all_edges if e.get("market")}
    for market in markets_in_output:
        market_edges = [e for e in all_edges if e.get("market") == market]
        fname = f"props_{market}.json"
        market_path = out_dir / fname
        market_path.write_text(json.dumps(market_edges, indent=2, default=str))
        print(f"  {market:40s} → {fname}  ({len(market_edges)} edge(s))")

    # Write empty files for ran markets that had no edges
    for market in active_markets:
        if market not in markets_in_output:
            fname = f"props_{market}.json"
            market_path = out_dir / fname
            if not market_path.exists():
                market_path.write_text("[]")

    # 6. Auto-log every prop market the model priced. Each market's tier decides
    #    how it lands: is_live() → card_pick (real record), else shadow (card_pick
    #    =False, excluded from the public record) — so logging batter props here is
    #    safe, it just gives them the OPENING line that prop CLV needs. We capture
    #    their closings every day already; without an opening snapshot they could
    #    never be scored. collapse_board() reduces the full multi-book/both-sides
    #    edge board to ONE lean per (matchup, market, player) so we log the model's
    #    actual pick, not hundreds of duplicate book rows.
    from src.analytics.clv_tracker import collapse_board
    log_edges = collapse_board(all_edges)
    added = _auto_log_picks(log_edges, game_date)
    if added:
        from collections import Counter
        by_mkt = Counter(e.get("market") for e in log_edges)
        summary = ", ".join(f"{n} {m}" for m, n in by_mkt.most_common())
        print(f"  Logged {added} prop edge(s) to PnL (shadow unless live): {summary}")

    # 7. CLV snapshot
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(game_date.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted {n_snapped} prop pick(s)")
    except Exception as err:
        print(f"  [CLV snapshot] {err}")

    # 7b. Render batter prop cards (HR, RBI, Total Bases, Hits)
    batter_markets = {
        "batter_home_runs", "batter_rbis", "batter_total_bases",
        "batter_hits", "batter_runs_scored",
    }
    batter_props = [e for e in all_edges if e.get("market") in batter_markets]
    pitcher_props = [e for e in all_edges if e.get("market") not in batter_markets]
    try:
        from src.output.card_html import render_props_cards_by_type
        if batter_props:
            batter_cards = render_props_cards_by_type(
                batter_props, sport="baseball_mlb", card_date=game_date
            )
            for mkt, p in batter_cards.items():
                print(f"  Card: {mkt} → {p.name}")
        if pitcher_props:
            pitcher_cards = render_props_cards_by_type(
                pitcher_props, sport="baseball_mlb", card_date=game_date
            )
            for mkt, p in pitcher_cards.items():
                print(f"  Card: {mkt} → {p.name}")
    except Exception as err:
        print(f"  [prop cards] {err}")

    # 8. Best pick per market
    if all_edges:
        try:
            from src.analytics.best_picks import best_pick_per_market, best_picks_report
            best = best_pick_per_market(all_edges)
            label = f"MLB Props — Best Pick Per Market  ({game_date.strftime('%b %d, %Y')})"
            print(best_picks_report(best, date_label=label))
            best_path = out_dir / "props_best_picks.json"
            best_path.write_text(json.dumps(
                {m: picks for m, picks in best.items()}, indent=2, default=str
            ))
            print(f"  Best picks saved → {best_path}")
        except Exception as err:
            print(f"  [best_picks] {err}")

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
