#!/usr/bin/env python3
"""
Paper Trading Orchestrator — automated daily prediction, closing line
capture, grading, and statistical validation.

Usage:
  python -m src.paper_trade morning              # Generate picks + record CLV
  python -m src.paper_trade close                # Capture closing lines (~30min before first pitch)
  python -m src.paper_trade grade                # Grade finished games
  python -m src.paper_trade report               # Print validation report
  python -m src.paper_trade run-all              # Morning + close + grade in one pass
  python -m src.paper_trade status               # Quick status check
  python -m src.paper_trade tier-report          # ROI by edge tier (HIGH/MED/LOW)

Cron schedule (Eastern Time):
  0 10 * * *  morning   # 10am ET — generate picks
  0 18 * * *  close     # 6pm ET — capture closing lines
  0  1 * * *  grade     # 1am ET — grade yesterday's games
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SPORT = "baseball_mlb"
SPORT_SHORT = "mlb"
FLAT_STAKE = 100.0
# Settled bets before ROI / win rate is statistically meaningful (paper trading plan).
VALIDATION_BETS_MIN = 100
VALIDATION_BETS_MAX = 200


def _save_multimarket(
    matchups,
    predictions: dict,
    raw_odds,
    picks_dir: Path,
    today: date,
    min_edge_spread: float,
    min_edge_total_runs: float,
) -> None:
    """Write picks_spreads.json and picks_totals.json for paper trading + grading."""
    from src.models.mlb_spreads import find_spread_edges
    from src.models.mlb_totals import find_totals_edges

    spreads = find_spread_edges(
        predictions, raw_odds, min_edge_runs=min_edge_spread
    )
    for s in spreads:
        tid = s.get("team", "UNK").replace(" ", "_")
        s["bet_type"] = "spread"
        s["pick_date"] = today.isoformat()
        s["game_id_paper"] = f"{SPORT_SHORT}_{today.strftime('%Y%m%d')}_{tid}_spread_{s.get('game_id', '')[:8]}"

    totals = find_totals_edges(
        matchups, raw_odds, min_edge_runs=min_edge_total_runs
    )
    for t in totals:
        t["bet_type"] = "total"
        t["pick_date"] = today.isoformat()
        gid = str(t.get("game_id", "x"))[:12]
        t["game_id_paper"] = f"{SPORT_SHORT}_{today.strftime('%Y%m%d')}_total_{gid}"

    with open(picks_dir / "picks_spreads.json", "w", encoding="utf-8") as f:
        json.dump(spreads, f, indent=2)
    with open(picks_dir / "picks_totals.json", "w", encoding="utf-8") as f:
        json.dump(totals, f, indent=2)

    print(f"\n  Multimarket: {len(spreads)} spread edges, {len(totals)} total (O/U) edges → picks_spreads.json, picks_totals.json")


def _write_picks_manifest(picks_dir: Path, today: date) -> None:
    """
    One audit file per day: row counts per market + unique game_ids for completeness checks.
    Grading reads picks.json, picks_spreads.json, picks_totals.json; manifest ties them together.
    """
    files = {
        "moneyline": "picks.json",
        "spreads": "picks_spreads.json",
        "totals": "picks_totals.json",
    }
    counts: dict[str, int] = {}
    unique_spread_games: set[str] = set()
    unique_total_games: set[str] = set()
    for key, fname in files.items():
        path = picks_dir / fname
        if not path.exists():
            counts[key] = 0
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            counts[key] = 0
            continue
        counts[key] = len(data)
        for row in data:
            gid = row.get("game_id")
            if gid:
                if key == "spreads":
                    unique_spread_games.add(str(gid))
                elif key == "totals":
                    unique_total_games.add(str(gid))
    manifest = {
        "pick_date": today.isoformat(),
        "sport": SPORT,
        "row_counts": counts,
        "total_rows_all_markets": sum(counts.values()),
        "unique_games_with_spread_pick": len(unique_spread_games),
        "unique_games_with_total_pick": len(unique_total_games),
        "source_files": {k: str((picks_dir / v).resolve()) for k, v in files.items()},
    }
    with open(picks_dir / "picks_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def cmd_morning(args):
    """Generate today's picks and record them in the CLV tracker."""
    from src.data.mlb_stats import get_todays_matchups
    from src.data import odds_api
    from src.models.mlb_ensemble import predict_all_ensemble, ensemble_to_dict
    from src.models.mlb_model import predict_all_games, predictions_to_dict
    from src.models.mlb_xgboost import load_mlb_model
    from src.betting.value_bets import find_value_bets
    from src.tracking.clv import CLVTracker
    from src.tracking.ids import make_game_id
    from src.output.pick_card import generate_pick_card_text, generate_pick_card_image

    today = date.today()
    print(f"\n{'='*60}")
    print(f"  PAPER TRADE — MORNING — {today.isoformat()}")
    print(f"{'='*60}\n")

    picks_dir = Path("output/picks") / SPORT / today.strftime("%Y%m%d")
    picks_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch matchups
    print("Step 1: Fetching MLB schedule...")
    matchups = get_todays_matchups()
    if not matchups:
        print("  No games today. Skipping.")
        return
    print(f"  {len(matchups)} games found")

    # Step 2: Run model
    loaded = load_mlb_model()
    if loaded is not None:
        n_models = len([m for m in loaded[2:5] if m is not None]) + 1
        print(f"\nStep 2: Running v3 stacking ensemble ({n_models} models)...")
        preds = predict_all_ensemble(matchups)
        predictions = ensemble_to_dict(preds)
        why_lookup = {
            (ep.home_team, ep.away_team): ep.edge_drivers[0] if ep.edge_drivers else ""
            for ep in preds
        }
    else:
        print("\nStep 2: Running Pythagorean model...")
        preds = predict_all_games(matchups)
        predictions = predictions_to_dict(preds)
        why_lookup = {
            (gp.home_team, gp.away_team): gp.edge_drivers[0] if gp.edge_drivers else ""
            for gp in preds
        }

    # Step 3: Fetch odds
    print("\nStep 3: Fetching odds and finding edges...")
    raw_odds = odds_api.fetch_odds(refresh=True, sport=SPORT)
    if raw_odds.empty:
        print("  No odds data. Set ODDS_API_KEY. Saving model-only picks.")
        _save_model_only(predictions, why_lookup, today)
        return

    # Multimarket (spreads + totals) — always refresh when we have odds
    try:
        _save_multimarket(
            matchups,
            predictions,
            raw_odds,
            picks_dir,
            today,
            min_edge_spread=getattr(args, "min_edge_spread", 0.4),
            min_edge_total_runs=getattr(args, "min_edge_total", 0.5),
        )
    except Exception as e:
        print(f"  Warning: multimarket save failed ({e})")

    if (picks_dir / "picks.json").exists():
        _write_picks_manifest(picks_dir, today)
        print(f"\n  Moneyline picks already exist for {today.isoformat()} — skipped ML regeneration.")
        print(f"  Delete {picks_dir}/picks.json to regenerate moneyline picks.")
        print(f"  Audit: {picks_dir / 'picks_manifest.json'}")
        print(f"  Morning job complete.\n")
        return

    best_odds = odds_api.get_best_odds(raw_odds, market="h2h")
    value_bets = find_value_bets(predictions, best_odds, min_edge=args.min_edge)

    if value_bets.empty:
        print("  No moneyline edges above threshold today.")
        _save_model_only(predictions, why_lookup, today)
        return

    # Add explanations
    import pandas as pd
    value_bets = value_bets.copy()
    value_bets["Why"] = value_bets.apply(
        lambda row: why_lookup.get(
            (row.get("Team", ""), row.get("Opponent", "")),
            why_lookup.get(
                (row.get("Opponent", ""), row.get("Team", "")),
                f"Edge: {row['Edge'] * 100:.1f}%",
            ),
        ),
        axis=1,
    )

    # Step 4: Save moneyline picks
    value_bets.to_json(picks_dir / "picks.json", orient="records", indent=2)

    picks_list = value_bets.to_dict(orient="records")
    text = generate_pick_card_text(picks_list, sport=SPORT_SHORT)
    (picks_dir / "picks.md").write_text(text, encoding="utf-8")

    try:
        generate_pick_card_image(picks_list, sport=SPORT_SHORT)
    except Exception:
        pass

    # Step 5: Record in CLV tracker (moneyline only — closing line benchmark)
    print(f"\nStep 4: Recording {len(picks_list)} ML picks in CLV tracker...")
    clv = CLVTracker()
    for pick in picks_list:
        team = pick.get("Team", "")
        game_id = make_game_id(today, team)
        try:
            clv.record_pick(
                game_id=game_id,
                team=team,
                pick_odds=pick.get("BestOdds", 0),
                model_prob=pick.get("ModelProb", 0.5),
                sport=SPORT_SHORT,
                sportsbook=pick.get("Sportsbook", ""),
            )
            print(f"  {team}: {pick.get('BestOdds', 0):+d} | edge {pick.get('Edge', 0)*100:.1f}%")
        except Exception as e:
            print(f"  {team}: already recorded ({e})")

    _write_picks_manifest(picks_dir, today)
    print(f"\n  Picks saved to {picks_dir}/")
    print(f"  Audit manifest: {picks_dir / 'picks_manifest.json'}")
    print(f"  Morning job complete.\n")


def _save_model_only(predictions, why_lookup, today):
    """Save model-only predictions when no odds available."""
    picks_dir = Path("output/picks") / SPORT / today.strftime("%Y%m%d")
    picks_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for (home, away), prob in predictions.items():
        if prob >= 0.5:
            rows.append({"Team": home, "Opponent": away, "ModelProb": prob,
                         "ImpliedProb": None, "Edge": 0, "BestOdds": 0, "Sportsbook": ""})
        else:
            rows.append({"Team": away, "Opponent": home, "ModelProb": 1 - prob,
                         "ImpliedProb": None, "Edge": 0, "BestOdds": 0, "Sportsbook": ""})
    with open(picks_dir / "picks.json", "w") as f:
        json.dump(rows, f, indent=2)
    _write_picks_manifest(picks_dir, today)
    print(f"  Saved {len(rows)} model-only picks to {picks_dir}/")


def cmd_close(args):
    """Capture closing lines for today's picks."""
    from src.grading.auto_grade import capture_closing_lines

    target = date.fromisoformat(args.date) if args.date else date.today()
    print(f"\n{'='*60}")
    print(f"  PAPER TRADE — CLOSING LINES — {target.isoformat()}")
    print(f"{'='*60}\n")

    n = capture_closing_lines(pick_date=target, sport=SPORT, verbose=True)
    if n > 0:
        print(f"\n  Closing line capture complete.")
    else:
        print(f"\n  No closing lines captured. Games may not have odds yet.")


def cmd_grade(args):
    """Grade picks against actual results."""
    from src.grading.auto_grade import grade_picks

    target = date.fromisoformat(args.date) if args.date else date.today()
    print(f"\n{'='*60}")
    print(f"  PAPER TRADE — GRADING — {target.isoformat()}")
    print(f"{'='*60}")

    report = grade_picks(
        pick_date=target,
        sport=SPORT,
        flat_stake=FLAT_STAKE,
        capture_closing=not args.no_closing,
        verbose=True,
    )

    graded = report.get("graded", 0)
    pending = report.get("pending", 0)

    if graded > 0:
        print("  Grading complete.")
    if pending > 0:
        print(f"  {pending} games pending — run again later.")


def cmd_report(args):
    """Print full statistical validation report."""
    from src.validation.stats import validate, print_validation

    v = validate(flat_stake=FLAT_STAKE)
    print(print_validation(v))


def cmd_tier_report(args):
    """ROI and win rate by model edge tier (from all grades.json files)."""
    from src.validation.tier_report import print_tier_report

    root = Path("output/picks") / SPORT
    if getattr(args, "picks_root", None):
        root = Path(args.picks_root)
    print_tier_report(root)


def cmd_status(args):
    """Quick status check — how many days tracked, pending games, etc."""
    from src.tracking.clv import CLVTracker
    from src.tracking.pnl import PnLTracker

    clv = CLVTracker()
    pnl = PnLTracker()
    pnl_summary = pnl.get_summary()
    clv_summary = clv.get_clv_summary(sport=SPORT_SHORT)

    today = date.today()
    today_picks_path = Path("output/picks") / SPORT / today.strftime("%Y%m%d") / "picks.json"
    has_today = today_picks_path.exists()

    # Count days with picks
    picks_root = Path("output/picks") / SPORT
    days_with_picks = 0
    if picks_root.exists():
        days_with_picks = sum(
            1 for d in picks_root.iterdir()
            if d.is_dir() and (d / "picks.json").exists()
        )

    print(f"\n{'='*60}")
    print(f"  PAPER TRADE STATUS")
    print(f"{'='*60}")
    print(f"  Today:           {'Picks generated' if has_today else 'No picks yet'}")
    print(f"  Days tracked:    {days_with_picks}")
    print(f"  Total picks:     {pnl_summary['total_picks']}")
    print(f"  Settled:         {pnl_summary['settled_picks']}")
    sml = pnl_summary.get("settled_moneyline", pnl_summary["settled_picks"])
    print(f"  Settled (ML):    {sml}  ← use this count for model edge (ignore spread/total duplicates)")
    print(f"  Record:          {pnl_summary['wins']}W-{pnl_summary['losses']}L")
    if pnl_summary['settled_picks'] > 0:
        print(f"  Win rate:        {pnl_summary['win_rate']:.1%}")
        print(f"  ROI:             {pnl_summary['roi']*100:+.1f}%")
        print(f"  Units profit:    {pnl_summary['units_profit']:+.2f}")
    need = max(0, VALIDATION_BETS_MIN - sml)
    print(f"  Validation:      aim for {VALIDATION_BETS_MIN}–{VALIDATION_BETS_MAX} settled moneyline bets")
    if sml < VALIDATION_BETS_MIN:
        print(f"                   {sml}/{VALIDATION_BETS_MIN} to first milestone (~{need} ML left)")
    elif sml < VALIDATION_BETS_MAX:
        print(f"                   {sml}/{VALIDATION_BETS_MAX} toward strong sample (keep logging)")
    else:
        print(f"                   {sml} ML — enough for a first profitability read (still watch CI)")
    print(f"  CLV picks:       {clv_summary['total_picks']}")
    print(f"  CLV w/ closing:  {clv_summary.get('with_closing_line', 0)}")
    if clv_summary.get('with_closing_line', 0) > 0:
        print(f"  CLV mean:        {clv_summary['clv_mean_cents']:+.1f} cents")
    print(f"  {'='*50}\n")


def cmd_run_all(args):
    """Run all three phases: morning, close, grade."""
    print("Running full paper trade cycle...\n")
    cmd_morning(args)
    cmd_close(args)
    cmd_grade(args)
    cmd_report(args)


def main():
    parser = argparse.ArgumentParser(
        description="Paper Trading Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", help="Paper trading command")

    p_morning = sub.add_parser("morning", help="Generate picks and record in CLV")
    p_morning.add_argument("--min-edge", type=float, default=0.03, help="Min edge for moneyline (0-1)")
    p_morning.add_argument("--min-edge-spread", type=float, default=0.4, help="Min |model−line| runs for run line")
    p_morning.add_argument("--min-edge-total", type=float, default=0.5, help="Min |pred−line| runs for O/U")

    p_close = sub.add_parser("close", help="Capture closing lines")
    p_close.add_argument("--date", type=str, default=None, help="YYYY-MM-DD")

    p_grade = sub.add_parser("grade", help="Grade picks against results")
    p_grade.add_argument("--date", type=str, default=None, help="YYYY-MM-DD")
    p_grade.add_argument("--no-closing", action="store_true")

    p_report = sub.add_parser("report", help="Statistical validation report")

    p_status = sub.add_parser("status", help="Quick status check")

    p_tier = sub.add_parser(
        "tier-report",
        help="Tiered ROI from grades (ML ≥6%/4%/3% edge; spread/total by edge_runs)",
    )
    p_tier.add_argument(
        "--picks-root",
        type=str,
        default=None,
        help="Override picks folder (default: output/picks/baseball_mlb)",
    )

    p_all = sub.add_parser("run-all", help="Morning + close + grade + report")
    p_all.add_argument("--min-edge", type=float, default=0.03)
    p_all.add_argument("--min-edge-spread", type=float, default=0.4)
    p_all.add_argument("--min-edge-total", type=float, default=0.5)
    p_all.add_argument("--date", type=str, default=None)
    p_all.add_argument("--no-closing", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "morning": cmd_morning,
        "close": cmd_close,
        "grade": cmd_grade,
        "report": cmd_report,
        "status": cmd_status,
        "tier-report": cmd_tier_report,
        "run-all": cmd_run_all,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
