#!/usr/bin/env python3
"""
chef.py — Overlay unified CLI

DAILY WORKFLOW (just two commands)
──────────────────────────────────────────────────────────────────────
  Morning:   python3 chef.py morning           # generates ALL picks + cards
  Evening:   python3 chef.py evening           # grades yesterday + shows record

INDIVIDUAL COMMANDS
──────────────────────────────────────────────────────────────────────
  python3 chef.py picks mlb                    # MLB picks only
  python3 chef.py picks nba                    # NBA picks only
  python3 chef.py picks nhl                    # NHL picks only
  python3 chef.py picks wnba                   # WNBA picks only
  python3 chef.py picks soccer                 # World Cup soccer picks
  python3 chef.py picks tennis                 # Tennis (Roland-Garros/Italian Open/Wimbledon)
  python3 chef.py picks pga                    # PGA Tour major picks
  python3 chef.py picks nba-props               # NBA prop edges (all markets)
  python3 chef.py picks nba-props --market player-points  # single prop market
  python3 chef.py picks mlb-props               # MLB prop edges (all markets)
  python3 chef.py picks mlb-props --market pitcher-strikeouts  # single market
  python3 chef.py picks nhl-props               # NHL player props (points/goals/assists/shots)
  python3 chef.py picks nhl-props --market player_goals  # single NHL prop market
  python3 chef.py picks nascar                 # NASCAR Cup Series outrights
  python3 chef.py picks indycar                # NTT IndyCar Series outrights
  python3 chef.py picks f1                     # Formula 1 outrights
  python3 chef.py picks ufc                    # UFC / MMA moneylines
  python3 chef.py grade                        # grade both MLB + NBA
  python3 chef.py grade --date 20260417        # grade specific date
  python3 chef.py record                       # full P&L breakdown
  python3 chef.py record --market nrfi         # NRFI record only
  python3 chef.py record --sport nba           # NBA record only
  python3 chef.py migrate                      # normalize picks.json schema
  python3 chef.py test                         # run grading unit tests
  python3 chef.py stats                        # refresh public_stats.json
  python3 chef.py deploy                       # rebuild feed + push live to overlay-gray.vercel.app
──────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_PNL_FILE          = Path("data/pnl/picks.json")
_PERSONAL_FILE     = Path("data/pnl/personal_picks.json")

# ─────────────────────────── Helpers ─────────────────────────────────────────

def _run(cmd: list[str]) -> int:
    """Run a subprocess, stream output, return exit code."""
    result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    return result.returncode


def _load_picks() -> list[dict]:
    if not _PNL_FILE.exists():
        return []
    try:
        raw = json.loads(_PNL_FILE.read_text())
        return raw if isinstance(raw, list) else raw.get("picks", [])
    except (json.JSONDecodeError, OSError):
        return []


def _profit_str(val: float | None) -> str:
    if val is None:
        return "  —  "
    return f"{val:+.2f}u"


def _pct(a: int, b: int) -> str:
    return f"{a/b:.1%}" if b else "  —  "


# ─────────────────────────── picks ───────────────────────────────────────────

def cmd_picks(args: argparse.Namespace) -> int:
    sport = args.sport.lower()
    late  = getattr(args, "late", False)

    if sport == "mlb":
        cmd = [sys.executable, "predict.py", "--daily", "--sport", "mlb"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        if late:
            print("  [LATE LINE] Refreshing odds 1-2h before first pitch — best CLV window.")
        return _run(cmd)
    elif sport in ("mlb-props", "mlb_props", "props"):
        cmd = [sys.executable, "run_mlb_props.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        # Optional single-market filter: chef.py picks mlb-props pitcher-strikeouts
        market_arg = getattr(args, "market", None)
        if market_arg:
            cmd += ["--markets", market_arg.replace("-", "_")]
        return _run(cmd)
    elif sport in ("nba-props", "nba_props"):
        cmd = [sys.executable, "run_nba_props.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        # Optional single-market filter: chef.py picks nba-props player-points
        market_arg = getattr(args, "market", None)
        if market_arg:
            cmd += ["--market", market_arg]
        return _run(cmd)
    elif sport == "nba":
        cmd = [sys.executable, "run_nba.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        if late:
            print("  [LATE LINE] Refreshing NBA odds — sharpened lines in effect.")
        return _run(cmd)
    elif sport == "nhl":
        cmd = [sys.executable, "run_nhl.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        if late:
            print("  [LATE LINE] Refreshing NHL odds — sharpened lines in effect.")
        return _run(cmd)
    elif sport == "wnba":
        cmd = [sys.executable, "run_wnba.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        return _run(cmd)
    elif sport == "pga":
        cmd = [sys.executable, "run_pga.py"]
        return _run(cmd)
    elif sport in ("tennis", "rg", "roland-garros", "wimbledon"):
        cmd = [sys.executable, "run_tennis.py"]
        sport_map = {
            "rg": "tennis_atp_french_open",
            "roland-garros": "tennis_atp_french_open",
            "wimbledon": "tennis_atp_wimbledon",
        }
        if sport in sport_map:
            cmd += ["--sport", sport_map[sport]]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        return _run(cmd)
    elif sport in ("soccer", "wc", "worldcup"):
        cmd = [sys.executable, "run_soccer.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        if getattr(args, "fit", False):
            cmd.append("--fit")
        return _run(cmd)
    elif sport in ("nascar", "cup", "indycar", "indy", "indy500", "f1", "formula1", "formulaone"):
        print(f"  Racing models (NASCAR/IndyCar/F1) have been retired. No picks generated.")
        return 0
    elif sport in ("nhl-props", "nhl_props"):
        cmd = [sys.executable, "run_nhl_props.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        market_arg = getattr(args, "market", None)
        if market_arg:
            cmd += ["--market", market_arg.replace("-", "_")]
        return _run(cmd)
    elif sport in ("ufc", "mma"):
        cmd = [sys.executable, "run_ufc.py"]
        if getattr(args, "date", None):
            cmd += ["--date", args.date]
        if getattr(args, "refresh", False) or late:
            cmd.append("--refresh")
        return _run(cmd)
    elif sport in ("grid", "all"):
        # The factory sweep: run EVERY registered adapter lane (MLB totals/F5 +
        # all 7 soccer leagues) through the one gate so every shadow lane
        # accumulates the CLV it needs to earn promotion. Dry-run computes
        # without logging.
        from src.pipeline.grid_runner import run_all, _normalize_date
        date_str = _normalize_date(getattr(args, "date", None))
        dry = getattr(args, "dry_run", False)
        results = run_all(date_str, dry_run=dry)
        for r in results:
            print(f"  {r.summary()}")
        total = sum(len(r.picks) for r in results)
        print(f"  [grid] sweep: {total} pick(s) across {len(results)} sport(s)"
              f"{' (dry-run, nothing logged)' if dry else ''}.")
        # Freeze these picks' opening lines so the shadow lanes accrue CLV. Do it
        # here (not in run_sport — tests call that against temp ledgers) for the
        # exact slate we just logged, so the date always matches the picks.
        if not dry and total:
            try:
                from src.analytics.clv_tracker import snapshot_from_pnl
                n = snapshot_from_pnl(date_str)
                print(f"  [grid] opening lines snapshotted: {n}")
            except Exception as e:
                print(f"  [grid] opening-line snapshot skipped: {e}")
        return 0
    else:
        print(f"Unknown sport: {sport}. Use: mlb, mlb-props, nba, nba-props, nhl, nhl-props, wnba, soccer, pga, tennis, ufc, grid.")
        return 1


# ─────────────────────────── grade ───────────────────────────────────────────

def cmd_grade(args: argparse.Namespace) -> int:
    grade_date = getattr(args, "date", None)
    if not grade_date:
        yesterday  = datetime.now() - timedelta(days=1)
        grade_date = yesterday.strftime("%Y%m%d")

    sport  = getattr(args, "sport", "all")
    winner = getattr(args, "winner", None)
    cmd    = [sys.executable, "grade.py", "--date", grade_date, "--sport", sport]
    if winner:
        cmd += ["--winner", winner]
    rc = _run(cmd)

    # Auto-recalibrate probability models after grading
    try:
        from src.analytics.calibration import recalibrate_all
        recalibrate_all(verbose=False)
    except Exception:
        pass

    # June Challenge — auto-generate result card for any graded bet
    try:
        from src.output.june_challenge_card import grade_challenge_bets
        grade_challenge_bets(grade_date=grade_date)
    except Exception as _jc_err:
        print(f"  [june_challenge] skipped: {_jc_err}")

    # Franchise shadow bets — grade yesterday's results
    try:
        from scripts.run_franchise_bets import grade_yesterday
        grade_yesterday(verbose=True)
    except Exception as _fe:
        pass  # non-blocking, franchise tracker is supplementary

    return rc


# ─────────────────────────── record ──────────────────────────────────────────

_MARKET_LABEL = {
    "moneyline": "Moneyline",
    "spread":    "Spread   ",
    "total":     "Totals   ",
    "nrfi":      "NRFI     ",
    "prop":      "Props    ",
}

_SPORT_LABEL = {"mlb": "MLB", "nba": "NBA", "nhl": "NHL", "wnba": "WNBA"}


def _sport_matches(pick_sport: str, filter_sport: str) -> bool:
    """Alias-aware sport comparison — picks have been stamped with both short
    names ('wnba') and Odds API keys ('basketball_wnba') over time."""
    from src.tracking.schema import canonical_sport
    return canonical_sport(pick_sport) == filter_sport


def _cmd_record_shadow(picks: list[dict], filter_market: str, filter_sport: str) -> int:
    """Show model-only (shadow) record — all picks the algo generated, not just card picks."""
    shadow = [p for p in picks if not p.get("card_pick")]
    if filter_market != "all":
        shadow = [p for p in shadow if p.get("market") == filter_market]
    if filter_sport != "all":
        shadow = [p for p in shadow if _sport_matches(p.get("sport"), filter_sport)]

    settled  = [p for p in shadow if p.get("result") in ("win", "loss", "push")]
    non_push = [p for p in settled if p.get("result") != "push"]
    wins     = [p for p in non_push if p.get("result") == "win"]
    losses   = [p for p in non_push if p.get("result") == "loss"]
    pending  = [p for p in shadow if not p.get("result")]
    profit   = sum(float(p.get("profit") or 0) for p in non_push)
    staked   = len(non_push)  # hypothetical 1u each
    wr       = len(wins) / len(non_push) if non_push else 0.0
    roi      = profit / staked if staked > 0 else 0.0

    sep = "═" * 60
    print(f"\n  {sep}")
    print(f"  Overlay — SHADOW RECORD (Model Only / Not Bet)")
    print(f"  {date.today().strftime('%B %d, %Y')}  |  All picks card_pick=False")
    print(f"  {'─'*58}")
    print(f"  OVERALL   {len(wins)}-{len(losses)}  ({wr:.1%} WR)  "
          f"{_profit_str(profit)}  ROI {roi:+.1%}")
    print(f"  Settled   {len(non_push)}  |  Pending  {len(pending)}")
    print(f"  {'─'*58}")

    if filter_market == "all":
        print(f"  {'MARKET':<12} {'W-L':>8}  {'WR':>7}  {'PROFIT':>8}  {'ROI':>7}")
        print(f"  {'─'*56}")
        for market_key, label in _MARKET_LABEL.items():
            mp  = [p for p in shadow if p.get("market") == market_key]
            mnp = [p for p in mp if p.get("result") in ("win", "loss")]
            mw  = sum(1 for p in mnp if p.get("result") == "win")
            ml_ = len(mnp) - mw
            mpr = sum(float(p.get("profit") or 0) for p in mnp)
            mst = len(mnp)
            mwr = mw / mst if mst else 0.0
            mroi = mpr / mst if mst > 0 else 0.0
            if not mp:
                continue
            print(f"  {label:<12} {mw}-{ml_:>2}  {_pct(mw,mst):>7}  "
                  f"{_profit_str(mpr):>8}  {mroi:>+6.1%}")
        print(f"  {'─'*56}")

        print(f"\n  {'SPORT':<12} {'W-L':>8}  {'WR':>7}  {'PROFIT':>8}  {'ROI':>7}")
        print(f"  {'─'*56}")
        for sport_key, slabel in _SPORT_LABEL.items():
            sp  = [p for p in shadow if _sport_matches(p.get("sport"), sport_key)]
            snp = [p for p in sp if p.get("result") in ("win", "loss")]
            sw  = sum(1 for p in snp if p.get("result") == "win")
            sl  = len(snp) - sw
            spr = sum(float(p.get("profit") or 0) for p in snp)
            sst = len(snp)
            swr = sw / sst if sst else 0.0
            sroi = spr / sst if sst > 0 else 0.0
            if not sp:
                continue
            print(f"  {slabel:<12} {sw}-{sl:>2}  {_pct(sw,sst):>7}  "
                  f"{_profit_str(spr):>8}  {sroi:>+6.1%}")

    recent = sorted(
        non_push, key=lambda x: x.get("resulted_at") or x.get("date") or "", reverse=True
    )[:10]
    if recent:
        print(f"\n  RECENT (shadow)")
        print(f"  {'DATE':<12} {'SPORT':<5} {'MKT':<11} {'TEAM':<26} {'RES':<6} {'P/L':>6}")
        print(f"  {'─'*56}")
        for p in recent:
            d_   = str(p.get("date") or "")[:10]
            sp_  = str(p.get("sport") or "?").upper()
            mkt_ = str(p.get("market") or "?")[:10]
            tm_  = str(p.get("team") or "?")[:25]
            res_ = str(p.get("result") or "?").upper()
            print(f"  {d_:<12} {sp_:<5} {mkt_:<11} {tm_:<26} {res_:<6} {_profit_str(p.get('profit')):>6}")

    # The lab just settled, so real bets riding those same games can settle too.
    # Without this the money ledger only updates when `chef.py bankroll` is run
    # by hand, which is how it went stale for six weeks in June.
    try:
        from src.tracking import bankroll as bk
        _bets, _n = bk.autograde()
        if _n:
            bk.save_bets(_bets)
            s = bk.summary(_bets)
            print(f"\n  💰 BANKROLL — auto-graded {_n} real bet(s)")
            print(f"     ${s['balance']:.2f}  ({s['profit']:+.2f})  "
                  f"{s['wins']}-{s['losses']}  ROI {s['roi_pct']:+.1f}%")
    except Exception as _bk_err:
        print(f"  [bankroll] auto-grade skipped: {_bk_err}")

    print(f"\n  {sep}\n")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    picks = _load_picks()
    if not picks:
        print("  No picks found. Run: python3 chef.py picks mlb")
        return 0

    # Tainted picks (known-broken mechanism — scripts/taint_bad_picks.py) are
    # kept in picks.json as an audit trail but excluded from every record view.
    n_tainted = sum(1 for p in picks if p.get("tainted"))
    if n_tainted:
        picks = [p for p in picks if not p.get("tainted")]
        print(f"  (excluding {n_tainted} tainted pick(s) from broken-model periods)")

    filter_market    = getattr(args, "market", "all")
    filter_sport     = getattr(args, "sport",  "all")
    shadow_mode      = getattr(args, "shadow", False)
    exclude_versions = set(getattr(args, "exclude_version", None) or [])

    if exclude_versions:
        picks = [p for p in picks if p.get("model_version") not in exclude_versions]

    if shadow_mode:
        return _cmd_record_shadow(picks, filter_market, filter_sport)

    # The official record is CARD picks only (card_pick=True — the bets actually
    # posted). Without this filter the headline blended in thousands of shadow
    # picks at full stake, reporting a net loss while the real bet record is
    # positive. Shadow/model-only performance lives behind `record --shadow`.
    card_picks = [p for p in picks if p.get("card_pick")]
    if filter_market != "all":
        card_picks = [p for p in card_picks if p.get("market") == filter_market]
    if filter_sport != "all":
        card_picks = [p for p in card_picks if _sport_matches(p.get("sport"), filter_sport)]

    settled  = [p for p in card_picks if p.get("result") in ("win", "loss", "push")]
    non_push = [p for p in settled if p.get("result") != "push"]
    wins     = [p for p in non_push if p.get("result") == "win"]
    losses   = [p for p in non_push if p.get("result") == "loss"]
    pending  = [p for p in card_picks if not p.get("result")]
    profit   = sum(float(p.get("profit") or 0) for p in non_push)
    staked   = sum(float(p.get("stake") or 1) for p in non_push)
    wr       = len(wins) / len(non_push) if non_push else 0.0
    roi      = profit / staked if staked > 0 else 0.0

    # Streak
    streak = 0
    for p in sorted(non_push, key=lambda x: x.get("resulted_at") or x.get("date") or ""):
        r = p.get("result")
        if r == "win":
            streak = streak + 1 if streak >= 0 else 1
        elif r == "loss":
            streak = streak - 1 if streak <= 0 else -1

    streak_str = (f"+{streak} WIN streak" if streak > 0 else
                  f"{streak} LOSS streak" if streak < 0 else "—")

    sep = "═" * 60
    print(f"\n  {sep}")
    title = "Overlay — RECORD"
    if filter_sport != "all":
        title += f" ({filter_sport.upper()})"
    if filter_market != "all":
        title += f" [{filter_market}]"
    print(f"  {title}")
    print(f"  {date.today().strftime('%B %d, %Y')}")
    print(f"  {'─'*58}")
    print(f"  OVERALL   {len(wins)}-{len(losses)}  ({wr:.1%} WR)  "
          f"{_profit_str(profit)}  ROI {roi:+.1%}")
    print(f"  Streak    {streak_str}")
    print(f"  Pending   {len(pending)} picks")
    print(f"  {'─'*58}")

    if filter_market == "all":
        # Per-market breakdown
        print(f"  {'MARKET':<12} {'W-L':>8}  {'WR':>7}  {'PROFIT':>8}  {'ROI':>7}")
        print(f"  {'─'*56}")
        for market_key, label in _MARKET_LABEL.items():
            mp = [p for p in card_picks if p.get("market") == market_key]
            ms = [p for p in mp if p.get("result") in ("win", "loss", "push")]
            mnp = [p for p in ms if p.get("result") != "push"]
            mw = sum(1 for p in mnp if p.get("result") == "win")
            ml = len(mnp) - mw
            mpr = sum(float(p.get("profit") or 0) for p in mnp)
            mst = sum(float(p.get("stake") or 1) for p in mnp)
            mwr = mw / len(mnp) if mnp else 0.0
            mroi = mpr / mst if mst > 0 else 0.0
            if not mp:
                continue
            print(f"  {label:<12} {mw}-{ml:>2}  {_pct(mw,len(mnp)):>7}  "
                  f"{_profit_str(mpr):>8}  {mroi:>+6.1%}")

        print(f"  {'─'*56}")

        # Per-sport breakdown
        print(f"\n  {'SPORT':<12} {'W-L':>8}  {'WR':>7}  {'PROFIT':>8}  {'ROI':>7}")
        print(f"  {'─'*56}")
        for sport_key, slabel in _SPORT_LABEL.items():
            sp = [p for p in card_picks if _sport_matches(p.get("sport"), sport_key)]
            ss = [p for p in sp if p.get("result") in ("win", "loss", "push")]
            snp = [p for p in ss if p.get("result") != "push"]
            sw = sum(1 for p in snp if p.get("result") == "win")
            sl = len(snp) - sw
            spr = sum(float(p.get("profit") or 0) for p in snp)
            sst = sum(float(p.get("stake") or 1) for p in snp)
            swr = sw / len(snp) if snp else 0.0
            sroi = spr / sst if sst > 0 else 0.0
            if not sp:
                continue
            print(f"  {slabel:<12} {sw}-{sl:>2}  {_pct(sw,len(snp)):>7}  "
                  f"{_profit_str(spr):>8}  {sroi:>+6.1%}")

    # Recent 10 settled picks
    recent = sorted(
        non_push,
        key=lambda x: x.get("resulted_at") or x.get("date") or "",
        reverse=True,
    )[:10]

    if recent:
        print(f"\n  {'─'*58}")
        print(f"  RECENT PICKS")
        print(f"  {'DATE':<12} {'SPORT':<5} {'MKT':<11} {'TEAM':<26} {'RESULT':<6} {'P/L':>6}")
        print(f"  {'─'*56}")
        for p in recent:
            d    = str(p.get("date") or "")[:10]
            sp_raw = str(p.get("sport") or "?").lower()
            sp   = sp_raw.replace("baseball_", "").replace("basketball_", "").replace("hockey_", "").upper()[:5]
            mkt  = str(p.get("market") or "?")[:10]
            team = str(p.get("team") or "?")[:25]
            res  = str(p.get("result") or "?").upper()
            pstr = _profit_str(p.get("profit"))
            col  = "" if res == "WIN" else ""
            print(f"  {d:<12} {sp:<5} {mkt:<11} {team:<26} {res:<6} {pstr:>6}")

    # ── Calibration summary ────────────────────────────────────────────────────
    try:
        from src.analytics.calibration import compute_calibration, CALIBRATORS_DIR
        import math as _math
        sports_list  = ["mlb", "nba"] if filter_sport == "all" else [filter_sport]
        markets_list = (["moneyline", "spread", "total", "nrfi", "prop"]
                        if filter_market == "all" else [filter_market])

        cal_rows = []
        for sp in sports_list:
            for mk in markets_list:
                res = compute_calibration(card_picks, sport=sp, market=mk)
                if res.n_picks < 15:
                    continue
                cal_path = CALIBRATORS_DIR / f"{sp}_{mk}.pkl"
                cal_rows.append((sp, mk, res, cal_path.exists()))

        if cal_rows:
            print(f"\n  {'─'*58}")
            print(f"  MODEL CALIBRATION  (Brier < 0.25 = good, coin flip = 0.25)")
            print(f"  {'─'*58}")
            print(f"  {'Segment':<22} {'N':>5}  {'Brier':>7}  {'ECE':>6}  {'Cal?':>5}")
            print(f"  {'─'*58}")
            for sp, mk, res, has_cal in cal_rows:
                b_str = f"{res.brier_score:.4f}" if not _math.isnan(res.brier_score) else "   —"
                e_str = f"{res.ece:.4f}"         if not _math.isnan(res.ece)         else "   —"
                label = f"{sp.upper()} {mk}"
                print(f"  {label:<22} {res.n_picks:>5}  {b_str:>7}  {e_str:>6}  {'YES' if has_cal else 'no':>5}")
    except Exception:
        pass

    # ── CLV dashboard ──────────────────────────────────────────────────────────
    try:
        from src.analytics.clv_tracker import get_clv_summary, print_clv_by_market, get_clv_by_market
        clv = get_clv_summary()
        if clv.get("with_clv", 0) > 0:
            avg  = clv["avg_clv_pct"]
            pos  = clv["positive_clv_pct"]
            sign = "+" if avg >= 0 else ""
            print(f"\n  {'─'*58}")
            print(f"  CLV ANALYSIS  (positive = beating the closing line)")
            print(f"  {'─'*58}")
            print(f"  Avg CLV       {sign}{avg:.2f}%   |   Positive {pos:.0f}% of picks")
            by_sport = clv.get("clv_by_sport", {})
            if by_sport:
                parts = []
                for sp in ("mlb", "nba", "nhl"):
                    if sp in by_sport:
                        d = by_sport[sp]
                        s2 = "+" if d["avg_clv_pct"] >= 0 else ""
                        parts.append(f"{sp.upper()} {s2}{d['avg_clv_pct']:.1f}% ({d['count']})")
                if parts:
                    print(f"  By sport:     {' | '.join(parts)}")
            print(f"  {clv['verdict']}")
        # Per-market split for soccer / World Cup — the moneyline-vs-totals test.
        if get_clv_by_market("soccer"):
            print_clv_by_market("soccer")
    except Exception:
        pass

    print(f"\n  {sep}\n")
    return 0


# ─────────────────────────── personal bankroll ───────────────────────────────

from src.tracking.bankroll import BANKROLL_START as _PERSONAL_BANKROLL_START


def _load_personal() -> list[dict]:
    if not _PERSONAL_FILE.exists():
        return []
    try:
        data = json.loads(_PERSONAL_FILE.read_text())
        return data.get("picks", data) if isinstance(data, dict) else data
    except (json.JSONDecodeError, OSError):
        return []


def _save_personal(picks: list[dict]) -> None:
    _PERSONAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PERSONAL_FILE.write_text(json.dumps({"picks": picks}, indent=2))


def _personal_profit(stake_dollars: float, odds: int, won: bool) -> float:
    if not won:
        return -stake_dollars
    if odds > 0:
        return stake_dollars * odds / 100
    return stake_dollars * 100 / abs(odds)


def cmd_bet(args: argparse.Namespace) -> int:
    """Record a personal bet to data/pnl/personal_picks.json."""
    import re
    from datetime import datetime, timezone

    team      = args.team
    market    = (args.market or "moneyline").lower()
    odds      = int(args.odds)
    stake     = float(args.stake)
    sport     = (args.sport or "mlb").lower()
    sportsbook = getattr(args, "sportsbook", None) or "Unknown"
    bet_date  = getattr(args, "date", None) or datetime.now().strftime("%Y-%m-%d")
    if len(bet_date) == 8 and bet_date.isdigit():
        bet_date = f"{bet_date[:4]}-{bet_date[4:6]}-{bet_date[6:]}"
    matchup   = getattr(args, "matchup", None) or team
    direction = (getattr(args, "direction", None) or "WIN").upper()
    line      = getattr(args, "line", None)

    slug      = re.sub(r"[^a-z0-9]+", "-", team.lower()).strip("-")
    pick_id   = f"personal_{sport}_{bet_date.replace('-','')}_{slug}_{market}"
    now_iso   = datetime.now(timezone.utc).isoformat()

    pick = {
        "pick_id":     pick_id,
        "date":        bet_date,
        "sport":       sport,
        "market":      market,
        "direction":   direction,
        "team":        team,
        "matchup":     matchup,
        "odds":        odds,
        "line":        line,
        "sportsbook":  sportsbook,
        "stake":       stake,
        "stake_dollars": stake,
        "model_prob":  None,
        "edge_pct":    None,
        "card_pick":   False,
        "result":      None,
        "profit":      None,
        "profit_dollars": None,
        "recorded_at": now_iso,
        "resulted_at": None,
    }

    picks = _load_personal()
    # Dedup
    if any(p["pick_id"] == pick_id for p in picks):
        print(f"  Pick already logged: {pick_id}")
        return 0

    picks.append(pick)
    _save_personal(picks)

    print(f"\n  ✓  Personal bet recorded:")
    print(f"     {team} {direction}  {odds:+d}  ${stake:.2f} @ {sportsbook}")
    print(f"     Date: {bet_date}  |  Sport: {sport.upper()}  |  Market: {market}")
    print(f"     ID: {pick_id}")
    print(f"\n  Grade with: python3 chef.py grade-personal --date {bet_date.replace('-','')}\n")
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    """Mark a personal bet as win/loss/push."""
    from datetime import datetime, timezone

    picks = _load_personal()
    if not picks:
        print("  No personal picks found.")
        return 1

    pick_id_or_team = args.pick_id
    result_val = args.result.lower()
    if result_val not in ("win", "loss", "push"):
        print(f"  Invalid result '{result_val}'. Use: win / loss / push")
        return 1

    # Match by exact pick_id, or partial team name on pending picks
    matched = [p for p in picks if p["pick_id"] == pick_id_or_team]
    if not matched:
        matched = [p for p in picks
                   if not p.get("result")
                   and pick_id_or_team.lower() in p.get("team", "").lower()]

    if not matched:
        print(f"  No pending pick found matching '{pick_id_or_team}'")
        print("  Pending picks:")
        for p in picks:
            if not p.get("result"):
                print(f"    {p['pick_id']}  {p['team']}  {p['odds']:+d}")
        return 1

    if len(matched) > 1:
        print(f"  Multiple matches — use exact pick_id:")
        for p in matched:
            print(f"    {p['pick_id']}  {p['team']}")
        return 1

    pick = matched[0]
    won  = result_val == "win"
    push = result_val == "push"

    stake_d = float(pick.get("stake_dollars") or pick.get("stake") or 0)
    odds    = int(pick.get("odds") or 0)
    profit_d = 0.0 if push else _personal_profit(stake_d, odds, won)

    pick["result"]         = result_val
    pick["profit_dollars"] = round(profit_d, 2)
    pick["resulted_at"]    = datetime.now(timezone.utc).isoformat()

    _save_personal(picks)
    sign = "+" if profit_d >= 0 else ""
    print(f"\n  ✓  {pick['team']}  →  {result_val.upper()}")
    print(f"     Stake: ${stake_d:.2f}  |  P/L: {sign}${profit_d:.2f}\n")
    return 0


def cmd_record_personal(args: argparse.Namespace) -> int:
    """Show personal bankroll P&L separate from algo record."""
    from src.tracking import bankroll as bk

    # Settle anything the lab already graded before reporting. This is what
    # keeps the money ledger alive — it died in June because grading was manual.
    picks, n_auto = bk.autograde()
    if n_auto:
        bk.save_bets(picks)
        print(f"\n  ✓  Auto-graded {n_auto} bet(s) from lab results.")

    if not picks:
        print("\n  No personal bets recorded yet.")
        print("  Log a bet with: python3 chef.py bet <team> <odds> <stake_dollars>\n")
        return 0

    filter_sport  = getattr(args, "sport",  "all")
    filter_market = getattr(args, "market", "all")

    if filter_sport != "all":
        picks = [p for p in picks if p.get("sport") == filter_sport]
    if filter_market != "all":
        picks = [p for p in picks if p.get("market") == filter_market]

    settled  = [p for p in picks if p.get("result") in bk.SETTLED]
    non_push = [p for p in settled if p.get("result") != "push"]
    wins     = [p for p in non_push if p.get("result") == "win"]
    losses   = [p for p in non_push if p.get("result") == "loss"]
    # An unsettled bet is anything not in SETTLED — including the literal string
    # "pending", which older rows carry. Testing `not p.get("result")` treated
    # those as graded, so they showed up in neither column and went unnoticed.
    pending  = bk.open_bets(picks)
    summary  = bk.summary(picks, start=_PERSONAL_BANKROLL_START)
    staked   = summary["staked"]
    profit   = summary["profit"]
    wr       = summary["win_rate"] / 100
    roi      = summary["roi_pct"]
    bankroll = summary["balance"]

    sep = "═" * 60
    print(f"\n  {sep}")
    print(f"  Overlay — PERSONAL BANKROLL")
    print(f"  {date.today().strftime('%B %d, %Y')}")
    print(f"  {'─'*58}")
    print(f"  Starting bankroll:  ${_PERSONAL_BANKROLL_START:.2f}")
    print(f"  Current bankroll:   ${bankroll:.2f}  ({'+' if profit>=0 else ''}{profit:.2f})")
    print(f"  {'─'*58}")
    print(f"  RECORD    {len(wins)}-{len(losses)}  ({wr:.1%} WR)")
    print(f"  Staked    ${staked:.2f}  |  P/L  {'+'if profit>=0 else ''}{profit:.2f}  |  ROI  {roi:+.1f}%")
    print(f"  Pending   {len(pending)} bets")

    if non_push:
        print(f"\n  {'─'*58}")
        print(f"  {'DATE':<12} {'SPORT':<5} {'MKT':<11} {'TEAM':<22} {'ODDS':>5} {'STAKE':>6} {'RES':<5} {'P/L':>7}")
        print(f"  {'─'*58}")
        recent = sorted(non_push, key=lambda x: x.get("resulted_at") or x.get("date") or "", reverse=True)[:20]
        for p in recent:
            d_    = str(p.get("date") or "")[:10]
            sp_   = str(p.get("sport") or "?").upper()
            mkt_  = str(p.get("market") or "?")[:10]
            # Totals carry no team — label them by the side actually bet.
            tm_   = str(p.get("team")
                        or f"{p.get('direction','')} {p.get('line','')}".strip()
                        or "?")[:21]
            odds_ = int(p.get("odds") or 0)
            stk_  = float(p.get("stake_dollars") or p.get("stake") or 0)
            res_  = str(p.get("result") or "?").upper()
            pl_   = float(p.get("profit_dollars") or 0)
            print(f"  {d_:<12} {sp_:<5} {mkt_:<11} {tm_:<22} {odds_:>+5} ${stk_:>5.2f} {res_:<5} {'+'if pl_>=0 else ''}{pl_:>6.2f}")

    if pending:
        print(f"\n  PENDING ({len(pending)})")
        print(f"  {'─'*40}")
        for p in pending:
            d_   = str(p.get("date") or "")[:10]
            tm_  = str(p.get("team") or "?")[:25]
            odds_= int(p.get("odds") or 0)
            stk_ = float(p.get("stake_dollars") or p.get("stake") or 0)
            print(f"  {d_:<12} {tm_:<25} {odds_:>+5}  ${stk_:.2f}")
        print(f"\n  Grade with: python3 chef.py result <team_name> win|loss|push")

    print(f"\n  {sep}\n")
    return 0


# ─────────────────────────── reddit ──────────────────────────────────────────

_REDDIT_DIR = Path("output/reddit")

_SUBREDDITS = {
    "daily":    "r/sportsbook — Daily Picks megathread",
    "mlb":      "r/sportsbook — MLB Betting and Picks megathread",
    "mlb_props":"r/sportsbook — MLB Props megathread",
    "nba":      "r/sportsbook — NBA Props Daily megathread",
}


def _reddit_track_record(stats: dict) -> str:
    """Build a compact track record block from public_stats.json."""
    s = stats.get("summary", {})
    bm = stats.get("by_market", {})
    bs = stats.get("by_sport", {})

    w    = s.get("wins", 0)
    l    = s.get("losses", 0)
    wr   = s.get("win_rate", 0)
    roi  = s.get("roi", 0)
    streak = s.get("streak", 0)
    streak_str = f"+{streak}W" if streak > 0 else (f"{streak}L" if streak < 0 else "—")

    tot   = bm.get("total", {})
    tot_w, tot_l, tot_roi = tot.get("wins",0), tot.get("losses",0), tot.get("roi",0)

    mlb   = bs.get("mlb", {})
    mlb_w, mlb_l, mlb_roi = mlb.get("wins",0), mlb.get("losses",0), mlb.get("roi",0)
    mlb_wr = mlb.get("win_rate", 0)

    nba   = bs.get("nba", {})
    nba_w, nba_l = nba.get("wins",0), nba.get("losses",0)

    bt = stats.get("backtest_mlb", [])
    bt_str = ""
    if bt:
        b = bt[0]
        bt_str = f"Backtest ({b.get('season','')}, {b.get('games','')} games, 8%+ edge): **{b.get('high_conf',0):.1%} accuracy**\n\n"

    return (
        f"**Model Track Record** (season-to-date, all picks logged before game time):\n\n"
        f"| Market | Record | ROI |\n"
        f"|--------|--------|-----|\n"
        f"| Overall (excl. NHL*) | {mlb_w+nba_w}-{mlb_l+nba_l} | {(mlb.get('units_profit',0)+nba.get('units_profit',0))/(mlb_w+mlb_l+nba_w+nba_l)*100:+.1f}% |\n"
        f"| MLB | {mlb_w}-{mlb_l} ({mlb_wr:.1%} WR) | {mlb_roi:+.1%} |\n"
        f"| Game Totals (O/U) | {tot_w}-{tot_l} ({tot_w/(tot_w+tot_l):.1%} WR) | {tot_roi:+.1%} |\n"
        f"\n{bt_str}"
        f"*Streak: {streak_str} | NHL disabled after 2-19 run — model was broken, killed it.*\n\n"
        f"*Results posted daily. No paid shills. All picks logged with timestamp before tip-off.*"
    )


def cmd_daily(args: argparse.Namespace) -> int:
    """Daily personal-bet ritual: pick → tweet → video script → record."""
    from datetime import datetime, timedelta
    from src.output import social

    subcmd = (getattr(args, "subcmd", None) or "pre").lower()
    today = (getattr(args, "date", None) or datetime.now().strftime("%Y%m%d"))
    out_dir = Path("output/daily") / today
    out_dir.mkdir(parents=True, exist_ok=True)

    if subcmd in ("status",):
        return _cmd_daily_status()

    if subcmd in ("result", "post", "post-game"):
        return _cmd_daily_result(args)

    # Default: pre-game flow.
    picks_path = Path("output/picks/baseball_mlb") / today / "picks.json"
    if not picks_path.exists():
        print(f"  No MLB picks for {today}. Run: python3 chef.py picks mlb --date {today}")
        return 1

    book_filter = getattr(args, "book", None)
    all_books = bool(getattr(args, "all_books", False))
    top = social.pick_of_day_mlb(
        picks_path, top=5,
        partner_only=not all_books,
        book=book_filter,
    )
    if not top:
        scope = (f"at {book_filter}" if book_filter
                 else "at partner books (FanDuel/DraftKings/BetMGM)" if not all_books
                 else "")
        print(f"  No edges found for {today} {scope}.")
        if not all_books and not book_filter:
            print(f"  Try: python3 chef.py daily --all-books")
        return 1

    print(f"\n  ── TOP MLB EDGES — {today} ──────────────────────────────────")
    for i, p in enumerate(top, 1):
        team = p.get("Team", "?")
        opp = p.get("Opponent", "?")
        market = (p.get("Market") or "").lower()
        odds = int(p.get("BestOdds") or 0)
        book = p.get("Sportsbook", "?")
        mp = (p.get("ModelProb") or 0) * 100
        ip = (p.get("ImpliedProb") or 0) * 100
        edge_pp = mp - ip
        print(f"  {i}.  {team:25}  vs  {opp:20}  {market:9} {odds:+4d}  "
              f"model {mp:4.0f}% / mkt {ip:4.0f}%  edge {edge_pp:+5.1f}pp  ({book})")
    print()

    # Auto-pick mode (--auto N) skips the prompt.
    auto = getattr(args, "auto", None)
    if auto is not None:
        try:
            choice = int(auto)
            if not (1 <= choice <= len(top)):
                raise ValueError()
        except (TypeError, ValueError):
            print(f"  --auto must be 1..{len(top)}")
            return 1
    else:
        try:
            raw = input(f"  Pick one [1-{len(top)}, q to quit]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if raw in ("q", "quit", "exit", ""):
            print("  Skipped — no bet logged.\n")
            return 0
        try:
            choice = int(raw)
            if not (1 <= choice <= len(top)):
                raise ValueError()
        except ValueError:
            print(f"  Invalid pick. Use 1..{len(top)}.")
            return 1

    pick = top[choice - 1]
    stake = float(getattr(args, "stake", None) or 30)
    book = getattr(args, "book", None) or pick.get("Sportsbook") or "FanDuel"

    # Record via the existing personal-bet plumbing.
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", pick["Team"].lower()).strip("-")
    bet_date_iso = f"{today[:4]}-{today[4:6]}-{today[6:]}"
    sport = "mlb"
    market = (pick.get("Market") or "moneyline").lower()
    pick_id = f"personal_{sport}_{today}_{slug}_{market}"
    odds = int(pick.get("BestOdds") or 0)
    matchup = f"{pick.get('Team','')} vs {pick.get('Opponent','')}"
    line_val = pick.get("Spread")
    if line_val is None and pick.get("BetLine") is not None:
        try:
            line_val = float(str(pick["BetLine"]).replace("+", ""))
        except ValueError:
            line_val = None

    picks_existing = _load_personal()
    if not any(p["pick_id"] == pick_id for p in picks_existing):
        from datetime import timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        picks_existing.append({
            "pick_id": pick_id,
            "date": bet_date_iso,
            "sport": sport,
            "market": market,
            "direction": "WIN",
            "team": pick["Team"],
            "matchup": matchup,
            "odds": odds,
            "line": line_val,
            "sportsbook": book,
            "stake": stake,
            "stake_dollars": stake,
            "model_prob": pick.get("ModelProb"),
            "edge_pct": (pick.get("Edge") or 0) * 100,
            "card_pick": False,
            "result": None,
            "profit": None,
            "profit_dollars": None,
            "recorded_at": now_iso,
            "resulted_at": None,
            "source": "daily_personal",
        })
        _save_personal(picks_existing)
        print(f"\n  ✓  Personal bet logged: {pick_id}")
    else:
        print(f"\n  • Already logged: {pick_id}")

    out = social.format_pre_game(pick, stake=stake,
                                 raf_link=social.raf_link_for(book), book=book)

    (out_dir / "tweet_pregame.txt").write_text(out["tweet"])
    (out_dir / "script_pregame.txt").write_text(out["script"])

    print("\n  ── TWEET (pre-game) ──")
    print("  " + out["tweet"].replace("\n", "\n  "))
    print("\n  ── VIDEO SCRIPT (read aloud, ~45-60s) ──")
    print("  " + out["script"].replace("\n", "\n  "))
    print(f"\n  Saved → {out_dir}/")
    print(f"  After the game:  python3 chef.py daily result\n")
    return 0


def _cmd_daily_result(args: argparse.Namespace) -> int:
    """Generate post-game tweet + reaction script for the most recent personal bet."""
    from datetime import datetime
    from src.output import social

    picks = _load_personal()
    if not picks:
        print("  No personal bets logged yet.")
        return 1

    target_id = getattr(args, "pick_id", None)
    if target_id:
        pick = next((p for p in picks if p["pick_id"] == target_id
                     or target_id.lower() in p.get("team", "").lower()), None)
    else:
        # Most recent settled personal bet.
        settled = [p for p in picks if p.get("result") in ("win", "loss", "push")]
        pick = settled[-1] if settled else None

    if not pick:
        print("  No graded personal bet found. Run `chef.py result <team> win|loss|push` first.")
        return 1

    if not pick.get("result"):
        print(f"  Pick is still pending: {pick['pick_id']}")
        print(f"  Grade it: python3 chef.py result {pick['team'].split()[0]} win|loss|push")
        return 1

    running = social.running_record(picks, days=30)
    out = social.format_post_game(pick, running,
                                  raf_link=social.raf_link_for(pick.get("sportsbook")))

    date_compact = pick["date"].replace("-", "")
    out_dir = Path("output/daily") / date_compact
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tweet_postgame.txt").write_text(out["tweet"])
    (out_dir / "script_postgame.txt").write_text(out["script"])

    print("\n  ── TWEET (post-game) ──")
    print("  " + out["tweet"].replace("\n", "\n  "))
    print("\n  ── REACTION SCRIPT (15-30s) ──")
    print("  " + out["script"].replace("\n", "\n  "))
    print(f"\n  Saved → {out_dir}/\n")
    return 0


def _cmd_daily_status() -> int:
    """Show personal record + $ P&L so far."""
    from src.output import social
    picks = _load_personal()
    if not picks:
        print("  No personal bets logged yet.")
        return 0
    r30 = social.running_record(picks, days=30)
    r_all = social.running_record(picks, days=365 * 10)
    pending = [p for p in picks if not p.get("result")]
    sign30 = "+" if r30["pnl"] >= 0 else "-"
    sign_all = "+" if r_all["pnl"] >= 0 else "-"
    print("\n  ── PERSONAL BANKROLL ──")
    print(f"  Last 30 days:  {r30['wins']}-{r30['losses']}"
          f"{'-'+str(r30['pushes']) if r30['pushes'] else ''}  "
          f"{sign30}${abs(r30['pnl']):.2f}")
    print(f"  All-time:      {r_all['wins']}-{r_all['losses']}"
          f"{'-'+str(r_all['pushes']) if r_all['pushes'] else ''}  "
          f"{sign_all}${abs(r_all['pnl']):.2f}")
    print(f"  Pending:       {len(pending)}")
    if pending:
        for p in pending[-3:]:
            print(f"     • {p['date']}  {p['team']}  {p['odds']:+d}  ${float(p.get('stake_dollars') or 0):.0f}")
    print()
    return 0


def cmd_wc_post(args: argparse.Namespace) -> int:
    """Generate a World Cup content post (tweet + video script) for today's marquee match."""
    from datetime import datetime
    from src.output import social

    fixtures_path = Path("output/picks/soccer/wc/fixtures.json")
    if not fixtures_path.exists():
        print(f"  No WC fixtures found. Run: python3 chef.py wc")
        return 1

    date_str = None
    if getattr(args, "date", None):
        d = args.date
        if len(d) == 8 and d.isdigit():
            date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        else:
            date_str = d

    match = social.wc_match_of_day(fixtures_path, date_str=date_str)
    if not match:
        print("  No WC match found for that date.")
        return 1

    product_link = getattr(args, "product_link", None) or social.WC_PRODUCT_LINK
    price = getattr(args, "price", None) or social.WC_PRODUCT_PRICE
    out = social.format_wc_post(match, product_link=product_link, price=price)

    today = (date_str or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    out_dir = Path("output/daily") / today
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tweet_wc.txt").write_text(out["tweet"])
    (out_dir / "script_wc.txt").write_text(out["script"])

    print(f"\n  ── WORLD CUP — {match['date']} · {out['matchup']} ──")
    print("\n  ── TWEET ──")
    print("  " + out["tweet"].replace("\n", "\n  "))
    print("\n  ── VIDEO SCRIPT (~30-45s) ──")
    print("  " + out["script"].replace("\n", "\n  "))
    print(f"\n  Saved → {out_dir}/\n")
    return 0


def cmd_reddit(args: argparse.Namespace) -> int:
    """Generate ready-to-paste Reddit posts for today's picks."""
    import json as _json

    target_date = getattr(args, "date", None)
    d = (datetime.strptime(target_date, "%Y%m%d").date()
         if target_date else date.today())
    ts = d.strftime("%Y%m%d")
    date_str  = d.strftime("%-m/%-d/%y")
    day_str   = d.strftime("%A")
    long_date = d.strftime("%B %d, %Y")

    mlb_dir = Path(f"output/picks/baseball_mlb/{ts}")
    nba_dir = Path(f"output/picks/basketball_nba/{ts}")

    def _load(path: Path) -> list:
        if not path.exists(): return []
        raw = _json.loads(path.read_text())
        return raw if isinstance(raw, list) else raw.get("picks", [])

    # Load all pick sources
    mlb_picks  = _load(mlb_dir / "picks.json")
    f5_picks   = _load(mlb_dir / "f5_totals.json")
    mlb_props  = _load(mlb_dir / "props.json")
    nba_picks  = _load(nba_dir / "picks.json")
    nba_props  = _load(nba_dir / "props.json")

    # Load track record
    stats = {}
    stats_path = Path("data/public_stats.json")
    if stats_path.exists():
        stats = _json.loads(stats_path.read_text())

    record_block = _reddit_track_record(stats) if stats else ""

    # Best picks for pick of the day
    all_picks_scored = []
    for p in mlb_props[:3]:
        all_picks_scored.append(("mlb_prop", p.get("label",""), p.get("odds",0), float(p.get("edge_pct",0) or 0), p.get("book","")))
    for p in f5_picks[:3]:
        all_picks_scored.append(("f5", p.get("label",""), p.get("odds",0), float(p.get("edge_pct",0) or 0), p.get("book","")))
    for p in nba_picks[:3]:
        edge = float(p.get("edge_pct", p.get("Edge", 0)) or 0)
        odds = p.get("best_odds", p.get("odds", p.get("BestOdds", 0)))
        team = p.get("team", p.get("Team", ""))
        book = p.get("sportsbook", p.get("Sportsbook", ""))
        all_picks_scored.append(("nba", team, odds, edge, book))

    all_picks_scored.sort(key=lambda x: x[3], reverse=True)
    pod = all_picks_scored[0] if all_picks_scored else None

    # ── Build each post ────────────────────────────────────────────────────────

    posts = {}

    # 1. Daily megathread — short, pick of day + quick MLB/NBA bullets
    pod_line = ""
    if pod:
        _, pod_team, pod_odds, pod_edge, pod_book = pod
        odds_fmt = f"{int(pod_odds):+d}" if pod_odds else ""
        pod_line = f"**{pod_team} {odds_fmt} @ {pod_book}** — {pod_edge:.1f}% model edge"

    mlb_bullets = ""
    for p in f5_picks[:3]:
        mlb_bullets += f"- {p.get('label','')} {p.get('odds',0):+d} @ {p.get('book','')} ({float(p.get('edge_pct',0)):.1f}% edge)\n"
    if not mlb_bullets:
        for p in mlb_picks[:3]:
            e = float(p.get("Edge",0) or 0)
            edge_pct = e*100 if e < 1 else e
            mlb_bullets += f"- {p.get('Team','')} {int(p.get('BestOdds',0)):+d} @ {p.get('Sportsbook','')} ({edge_pct:.1f}% edge)\n"

    nba_bullets = ""
    for p in nba_picks[:3]:
        edge = float(p.get("edge_pct", p.get("Edge", 0)) or 0)
        odds = p.get("best_odds", p.get("odds", p.get("BestOdds", 0)))
        team = p.get("team", p.get("Team", ""))
        book = p.get("sportsbook", p.get("Sportsbook", ""))
        nba_bullets += f"- {team} {int(odds):+d} @ {book} ({edge:.1f}% edge)\n"

    posts["daily"] = f"""**Overlay AI Model — {day_str} {date_str}**

Running an XGBoost ensemble on MLB + NBA. Picks logged before tip-off, results posted daily.

---

**🎯 Pick of the Day:**
{pod_line}

---

**⚾ MLB Best Edges:**
{mlb_bullets.strip()}

**🏀 NBA Best Edges:**
{nba_bullets.strip()}

---

{record_block}

GL everyone. Drop your plays below."""

    # 2. MLB megathread — full breakdown
    game_rows = ""
    for p in mlb_picks[:6]:
        e = float(p.get("Edge",0) or 0)
        edge_pct = e*100 if e < 1 else e
        mkt = str(p.get("Market","")).upper()
        game_rows += f"| {p.get('Team','')} | {mkt} | {int(p.get('BestOdds',0)):+d} | {p.get('Sportsbook','')} | {edge_pct:.1f}% |\n"

    f5_rows = ""
    for p in f5_picks[:5]:
        f5_rows += f"| {p.get('label','')} | {int(p.get('odds',0)):+d} | {p.get('book','')} | {float(p.get('edge_pct',0)):.1f}% |\n"

    posts["mlb"] = f"""**Overlay AI — MLB {day_str} {date_str}**

XGBoost ensemble (Pythagorean + team efficiency + park factors) vs live lines. Edges calculated post-vig.

---

**Game Picks:**

| Pick | Market | Odds | Book | Edge |
|------|--------|------|------|------|
{game_rows.strip()}

---

**F5 Totals** (first 5 innings — sharpest market, bypasses bullpen noise):

| Pick | Odds | Book | Edge |
|------|------|------|------|
{f5_rows.strip()}

F5 is where the model does its best work. Books post softer lines here vs full-game because volume is lower.

---

{record_block}

GL today. Posting results tomorrow morning."""

    # 3. MLB Props megathread
    prop_rows = ""
    for p in mlb_props[:8]:
        prop_rows += f"| {p.get('label','')} | {int(p.get('odds',0)):+d} | {p.get('book','')} | {float(p.get('edge_pct',0)):.1f}% |\n"

    posts["mlb_props"] = f"""**Overlay AI — MLB Props {day_str} {date_str}**

Pitcher K model: compares K/9 projection to book line using opponent strikeout rate + park factor. Edges calculated post-vig.

| Pick | Odds | Book | Edge |
|------|------|------|------|
{prop_rows.strip()}

**How to read this:** Edge = how much our model disagrees with the book's implied probability. 35% edge means the book says 40% chance, model says 75%. We only post when edge > 8%.

---

{record_block}

GL. Results posted tomorrow."""

    # 4. NBA megathread
    nba_game_rows = ""
    for p in nba_picks[:5]:
        edge = float(p.get("edge_pct", p.get("Edge", 0)) or 0)
        odds = p.get("best_odds", p.get("odds", p.get("BestOdds", 0)))
        team = p.get("team", p.get("Team", ""))
        mkt  = str(p.get("market", p.get("Market",""))).upper()
        book = p.get("sportsbook", p.get("Sportsbook",""))
        matchup = p.get("matchup", p.get("Matchup",""))
        nba_game_rows += f"| {team} | {mkt} | {int(odds):+d} | {book} | {edge:.1f}% | {matchup} |\n"

    nba_prop_rows = ""
    for p in nba_props[:6]:
        nba_prop_rows += f"| {p.get('label','')} | {int(p.get('odds',0)):+d} | {p.get('book','')} | {float(p.get('edge_pct',0)):.1f}% |\n"

    posts["nba"] = f"""**Overlay AI — NBA Playoffs {day_str} {date_str}**

XGBoost model using team efficiency ratings (ORtg/DRtg/Pace) + Platt-calibrated probabilities. Props use Poisson/Normal distribution vs season averages.

---

**Game Picks:**

| Pick | Market | Odds | Book | Edge | Game |
|------|--------|------|------|------|------|
{nba_game_rows.strip()}

---

**Props:**

| Pick | Odds | Book | Edge |
|------|------|------|------|
{nba_prop_rows.strip()}

---

{record_block}

Playoffs slate today — GL all."""

    # ── Save to files + print ──────────────────────────────────────────────────
    _REDDIT_DIR.mkdir(parents=True, exist_ok=True)
    sep = "═" * 70

    print(f"\n  {sep}")
    print(f"  REDDIT POSTS — {long_date}")
    print(f"  {sep}")

    for key, content in posts.items():
        label = _SUBREDDITS[key]
        out_path = _REDDIT_DIR / f"{ts}_{key}.md"
        out_path.write_text(content, encoding="utf-8")
        print(f"\n  ► {label}")
        print(f"    Saved → {out_path}")
        print(f"    Preview (first 2 lines): {content.splitlines()[0][:80]}")

    print(f"\n  {sep}")
    print(f"  All posts saved to output/reddit/")
    print(f"  Copy-paste each file into the corresponding megathread.")
    print(f"\n  WHERE TO POST:")
    print(f"  • r/sportsbook → search 'Daily Picks {date_str}'")
    print(f"  • r/sportsbook → search 'MLB Betting and Picks {date_str}'")
    print(f"  • r/sportsbook → search 'MLB Props {date_str}'")
    print(f"  • r/sportsbook → search 'NBA Props Daily {date_str}'")
    print(f"  {sep}\n")

    return 0


# ─────────────────────────── migrate ─────────────────────────────────────────

def cmd_migrate(args: argparse.Namespace) -> int:
    from src.tracking.schema import migrate_picks_file
    import shutil

    if not _PNL_FILE.exists():
        print("  picks.json not found — nothing to migrate.")
        return 0

    backup = _PNL_FILE.with_suffix(".json.bak")
    shutil.copy(_PNL_FILE, backup)
    print(f"  Backup: {backup}")

    result = migrate_picks_file(str(_PNL_FILE))
    if "error" in result:
        print(f"  Error: {result['error']}")
        return 1

    print(f"  Migration complete:")
    print(f"    Input picks:   {result['total_in']}")
    print(f"    Removed (corrupt): {result['removed']}")
    print(f"    Deduplicated:  {result['deduplicated']}")
    print(f"    Output picks:  {result['total_out']}")

    # ── Post-normalize fixups ─────────────────────────────────────────────────
    data = json.loads(_PNL_FILE.read_text())
    picks = data if isinstance(data, list) else data.get("picks", [])
    fixups = 0

    for p in picks:
        sport = (p.get("sport") or "").lower()

        # Tag pre-retraining NHL picks as v0_heuristic (broken model, wrong puck-line sign)
        if "nhl" in sport and (p.get("date") or "") < "2026-05-14" and not p.get("model_version"):
            p["model_version"] = "v0_heuristic"
            fixups += 1

        # Tag post-retraining NHL picks with v1 version
        if "nhl" in sport and (p.get("date") or "") >= "2026-05-14" and not p.get("model_version"):
            p["model_version"] = "v1_logreg_20260514"
            fixups += 1

        # Backfill stake=0 for May 14 auto-logged picks (logged before stake fix)
        if p.get("date", "").startswith("2026-05-14") and float(p.get("stake") or 0) == 0:
            p["stake"] = 1.0
            fixups += 1

        # Fix direction="NAN" from old prediction bug (pandas NaN stringified)
        if str(p.get("direction", "")).upper() == "NAN":
            market = p.get("market", "moneyline")
            p["direction"] = "COVER" if market == "spread" else "WIN"
            fixups += 1

        # Fix old NHL puck-line direction strings like "HOME -1.5" / "AWAY +1.5"
        direction_str = str(p.get("direction", ""))
        if direction_str.upper().startswith(("HOME ", "AWAY ")):
            p["direction"] = "COVER"
            fixups += 1

    if fixups > 0:
        from src.tracking.schema import rewrite_picks_safe
        rewrite_picks_safe(_PNL_FILE, data)
        print(f"    Fixups applied: {fixups} (NHL v0_heuristic tags + stake=0 backfill)")

    # Validate all picks
    from src.tracking.schema import validate_pick
    _raw = json.loads(_PNL_FILE.read_text())
    picks = _raw if isinstance(_raw, list) else _raw.get("picks", [])
    errors = [(p.get("pick_id"), validate_pick(p)) for p in picks if validate_pick(p)]
    if errors:
        print(f"\n  ⚠  {len(errors)} validation issues after migration:")
        for pid, iss in errors[:5]:
            print(f"    {pid}: {iss}")
    else:
        print(f"  ✓  All {result['total_out']} picks valid.")

    return 0


# ─────────────────────────── test ────────────────────────────────────────────

def cmd_test(args: argparse.Namespace) -> int:
    # Run the FULL suite, not just grading — a daily green/red signal across
    # every guard (model registry, CLV scoring, props, kelly, schema, …).
    # Pass `--grading` to run only the fast grading subset.
    target = "tests/test_grading.py" if getattr(args, "grading", False) else "tests/"
    return _run([sys.executable, "-m", "pytest", target, "-q"])


def cmd_today(args: argparse.Namespace) -> int:
    """The ONE daily driver — one screen: did it run, the record, what to bet.

    Replaces eyeballing status + record + audit + slate. Fast (reads
    picks.json only); deep checks (validate/audit/test) run in CI and alert
    on red, so green here means you don't need them.
    """
    import json as _json
    from datetime import date as _date, timedelta as _td

    today = _date.today().isoformat()
    yday = (_date.today() - _td(days=1)).isoformat()
    try:
        raw = _json.loads(_PNL_FILE.read_text())
        picks = raw if isinstance(raw, list) else raw.get("picks", [])
    except (OSError, ValueError):
        picks = []

    def _settled(ps):
        w = sum(1 for p in ps if p.get("result") == "win")
        l = sum(1 for p in ps if p.get("result") == "loss")
        pu = sum(1 for p in ps if p.get("result") == "push")
        pr = sum((p.get("profit") or 0) for p in ps if p.get("result") in ("win", "loss", "push"))
        return w, l, pu, pr

    card = [p for p in picks if p.get("card_pick")]
    today_card = [p for p in card if p.get("date") == today]
    today_all = [p for p in picks if p.get("date") == today]
    yday_card = [p for p in card if p.get("date") == yday]
    cw, cl, cpu, cpr = _settled([p for p in card if p.get("result") in ("win", "loss", "push")])
    yw, yl, ypu, ypr = _settled(yday_card)

    flags = []
    if not today_all:
        flags.append("pipeline hasn't logged any picks today — run `chef.py morning`")

    line = "═" * 56
    print(f"\n  {line}")
    print(f"  OVERLAY — TODAY   {_date.today():%A, %B %-d}")
    print(f"  {line}")
    verdict = "🟢 ALL GOOD" if not flags else f"🔴 {len(flags)} thing(s) need you"
    print(f"  STATUS   {verdict}")
    print("  " + "─" * 54)
    ran = "✓ ran" if today_all else "✗ NOT run yet"
    print(f"  Pipeline   {ran}  ({len(today_all)} picks logged, {len(today_card)} on card)")
    roi = (cpr / (cw + cl + cpu) * 100) if (cw + cl + cpu) else 0
    print(f"  Record     {cw}-{cl}-{cpu}   {cpr:+.1f}u   ({roi:+.1f}% ROI)")
    if yday_card:
        print(f"  Yesterday  {yw}-{yl}-{ypu}   {ypr:+.1f}u")
    print("  " + "─" * 54)

    # 🟢 LIVE — the only lanes that get real money today.
    print("  🟢 BET THESE  (live lanes — validated)")
    if today_card:
        for p in sorted(today_card, key=lambda x: -(x.get("edge_pct") or 0)):
            o = p.get("odds")
            try:
                o = f"{int(o):+d}"
            except (TypeError, ValueError):
                o = str(o)
            t = (p.get("team") or p.get("direction") or "")[:22]
            r = p.get("result") or "pending"
            print(f"     {p.get('market', '?')[:9]:9} {t:22} {o:>6}  edge {(p.get('edge_pct') or 0):+.1f}%  [{r}]")
    else:
        print("     (nothing cleared a live gate today — a sit-out is a valid play)")
    print("  " + "─" * 54)

    # 🔵 NOT BET — every logged pick that isn't a live card pick, by lane, with
    # WHY it isn't bet: a live lane whose edge fell short today, or a shadow lane
    # still validating, or a paused (known-loser) lane.
    from src.config.models import _key as _mk_key, model_status, model_tier
    watch_today = [p for p in today_all
                   if not p.get("card_pick") and p.get("odds") not in (None, 0)]
    print("  🔵 NOT BET TODAY  (why each lane is held)")
    if watch_today:
        lanes: dict[tuple[str, str], int] = {}
        for p in watch_today:
            k = _mk_key(p.get("sport", ""), p.get("market", ""))
            lanes[k] = lanes.get(k, 0) + 1
        for (sp, mk), n in sorted(lanes.items(), key=lambda kv: -kv[1]):
            status = model_status(sp, mk)
            if status == "live":
                note = "🟢 live · no edge cleared the gate today"
            elif model_tier(sp, mk) == "paused":
                note = "🟡 paused · known loser, logged not bet"
            else:
                note = "🔵 shadow · validating on CLV"
            print(f"     {sp}/{mk:16} {n:>3} pick(s)   {note}")
    else:
        print("     (nothing else logged today)")
    print("  " + "─" * 54)

    if flags:
        print("  ⚠ NEEDS YOU:")
        for f in flags:
            print(f"     • {f}")
        print("  " + "─" * 54)
    print("  Deeper:  chef.py grid · record · validate · audit")
    print(f"  {line}\n")
    return 0 if not flags else 1


# ─────────────────────────── grid ────────────────────────────────────────────

def cmd_grid(args: argparse.Namespace) -> int:
    """The whole model board: every sport×market lane, its state + live health.

    States: 🟢 live (betting) · 🔵 shadow (validating) · 🟡 paused (known loser,
    logged not bet) · ⬜ planned (not built) · ⚫ retired (dropped). ⚙ = migrated
    to the grid_runner (the factory assembly line).
    """
    from src.config.grid import GRID, cell_state, grid_counts, is_prop
    from src.analytics.market_stats import market_stats, MarketStat
    from src.pipeline.grid_runner import ADAPTERS
    core_only = getattr(args, "core", False)

    stats = market_stats()
    glyph = {"live": "🟢", "shadow": "🔵", "paused": "🟡", "planned": "⬜", "retired": "⚫"}

    def _agg(sport: str, keys: list[str]) -> MarketStat:
        agg = MarketStat(sport=sport, market="+".join(keys))
        clv_sum = 0.0
        for k in keys:
            s = stats.get((sport, k))
            if not s:
                continue
            agg.n += s.n
            agg.wins += s.wins
            agg.losses += s.losses
            agg.pushes += s.pushes
            agg.pnl += s.pnl
            agg.total_logged += s.total_logged
            if s.clv is not None:
                clv_sum += s.clv * s.clv_n
                agg.clv_n += s.clv_n
        if agg.n:
            agg.roi = agg.pnl / agg.n * 100
        if agg.clv_n:
            agg.clv = clv_sum / agg.clv_n
        return agg

    counts = grid_counts()
    line = "═" * 72
    print(f"\n  {line}")
    print("  OVERLAY — THE MODEL GRID")
    print(f"  {line}")
    print(f"  🟢 {counts['live']} live   🔵 {counts['shadow']} shadow   "
          f"🟡 {counts['paused']} paused   ⬜ {counts['planned']} planned   "
          f"⚫ {counts['retired']} retired")
    print("  " + "─" * 70)
    only = getattr(args, "sport", None)
    for sport, lanes in GRID.items():
        if only and sport != only.lower():
            continue
        shown = [(l, k) for l, k in lanes if not (core_only and is_prop(k[0]))]
        if not shown:
            continue
        print(f"\n  {sport.upper()}")
        for label, keys in shown:
            state = cell_state(sport, keys)
            a = _agg(sport, keys)
            wired = " ⚙" if any((sport, k) in ADAPTERS for k in keys) else "  "
            if a.n:
                roi = f"{a.roi:+.1f}%".rjust(7)
                rec = a.record.rjust(9)
                clv = (f"CLV {a.clv:+.1f}%({a.clv_n})" if a.clv is not None else "").ljust(16)
                body = f"n={a.n:<4} {rec}  {roi}  {clv}"
            elif state == "planned":
                body = "— not built —"
            else:
                body = f"logged {a.total_logged}, none settled"
            print(f"   {glyph[state]}{wired} {label:11s} {body}")
    print(f"\n  {line}")
    print("  🟢 bet · 🔵 validating on CLV · 🟡 don't bet · ⬜ to build · ⚙ on the factory runner")
    print(f"  {line}\n")
    return 0


def cmd_scoreboard(args: argparse.Namespace) -> int:
    """Promotion scoreboard: how close is every shadow lane to earning its keep?

    Joins the ledger's ROI/record (market_stats) with the sharp-close CLV
    (clv_gate) and scores each lane against the SAME gate the promoter uses —
    beat the sharp close ≥55% AND positive ROI over ≥30 settled bets. Answers
    'which of my algos are becoming bettable, and which are dead?' at a glance.
    """
    from src.config.grid import GRID, cell_state, is_prop
    from src.analytics.market_stats import market_stats, MarketStat
    from src.analytics.clv_gate import clv_gate
    from src.pipeline.promoter import PROMOTE_BEAT_MIN, PROMOTE_ROI_MIN_N

    stats = market_stats()

    # CLV rows keyed by (sport, normalized-market) so they join the registry.
    def _nm(m: str) -> str:
        m = (m or "").lower()
        return {"ml": "moneyline", "h2h": "moneyline", "money_line": "moneyline"}.get(m, m)

    clv_idx: dict[tuple[str, str], dict] = {}
    try:
        rows = clv_gate(1)
        rows = rows[0] if isinstance(rows, tuple) else rows
        for r in rows or []:
            clv_idx[(r.get("sport"), _nm(r.get("market")))] = r
    except Exception:
        pass  # snapshots unreadable → CLV shown as pending, ROI still works

    def _agg(sport: str, keys: list[str]) -> MarketStat:
        agg = MarketStat(sport=sport, market="+".join(keys))
        for k in keys:
            s = stats.get((sport, k))
            if not s:
                continue
            agg.n += s.n; agg.wins += s.wins; agg.losses += s.losses
            agg.pushes += s.pushes; agg.pnl += s.pnl; agg.total_logged += s.total_logged
        if agg.n:
            agg.roi = agg.pnl / agg.n * 100
        return agg

    def _clv_agg(sport: str, keys: list[str]):
        # Returns (moved_sample, beat_pct) — the moved-sample (non-flat) is the
        # real denominator; a beat-rate on <MOVED_FLOOR moves is noise.
        tot = 0; beat_w = 0.0
        for k in keys:
            r = clv_idx.get((sport, _nm(k)))
            if r and r.get("sharp_moved_n"):
                n = r["sharp_moved_n"]; tot += n
                beat_w += (r.get("sharp_beat_pct") or 0) * n
        return (tot, beat_w / tot) if tot else (0, None)

    def _bar(pct: float | None) -> str:
        if pct is None:
            return "░░░░░"
        filled = max(0, min(5, round(pct / PROMOTE_BEAT_MIN * 5)))
        return "▓" * filled + "░" * (5 - filled)

    live, proving, held = [], [], []
    only = getattr(args, "sport", None)
    for sport, lanes in GRID.items():
        if only and sport != only.lower():
            continue
        for label, keys in lanes:
            state = cell_state(sport, keys)
            if state in ("planned", "retired"):
                continue
            a = _agg(sport, keys)
            moved_n, sharp_beat = _clv_agg(sport, keys)
            roi_ok = a.roi is not None and a.n >= PROMOTE_ROI_MIN_N and a.roi > 0
            clv_ok = sharp_beat is not None and sharp_beat >= PROMOTE_BEAT_MIN
            prop = is_prop(keys[0])
            # CLV (beat the sharp close, flats excluded) is the edge test for GAME
            # lines — moneyline/total/spread/f5. PROPS are excluded: they "echo the
            # line" (r≈0.97), so a high prop beat-rate is line-following noise, not
            # edge (batter_total_bases: 91% beat yet −3% ROI). Judge props on ROI.

            if state == "live":
                verdict = "✅ promoted — betting"
            elif state == "paused":
                verdict = "🟡 held — known loser"
            elif prop:  # props: CLV is line-echo noise → judge on outcome
                if a.n < PROMOTE_ROI_MIN_N:
                    verdict = f"⏳ building sample ({a.n}/{PROMOTE_ROI_MIN_N})"
                elif a.roi is not None and a.roi > 0:
                    verdict = f"📈 +{a.roi:.0f}% ROI (CLV n/a — props echo line)"
                else:
                    verdict = f"❌ losing ({a.roi:+.0f}% ROI)"
            elif moved_n == 0:
                verdict = "⏳ no CLV scored yet"
            elif moved_n < PROMOTE_ROI_MIN_N:  # too few line MOVES to trust the rate
                verdict = f"⏳ building CLV ({moved_n}/{PROMOTE_ROI_MIN_N} moved)"
            elif clv_ok and roi_ok:
                verdict = "✅ READY — clears gate"
            elif clv_ok:
                verdict = f"🟠 CLV✓ {sharp_beat:.0f}% · ROI {a.roi:+.0f}% must be >0"
            elif sharp_beat >= 50:
                verdict = f"🟠 close {sharp_beat:.0f}% → {PROMOTE_BEAT_MIN:.0f}%"
            else:
                verdict = f"❌ not beating close ({sharp_beat:.0f}%)"

            roi_s = f"{a.roi:+.1f}%".rjust(7) if a.roi is not None else "   —   "
            # Props show n/a for beat (CLV is line-echo); game lines show real CLV.
            if prop or sharp_beat is None:
                beat_s, bar = " n/a", "·····"
            else:
                beat_s, bar = f"{sharp_beat:.0f}%".rjust(4), _bar(sharp_beat)
            row = (f"   {sport}/{keys[0]:<16} n={a.n:<4} {roi_s}  "
                   f"beat {beat_s} {bar}  {verdict}")
            sort_key = sharp_beat if (not prop and sharp_beat is not None) else (a.roi or -999)/10 - 60
            (live if state == "live" else held if state == "paused" else proving).append(
                (sort_key, row))

    line = "═" * 74
    print(f"\n  {line}")
    print("  OVERLAY — LANE SCOREBOARD   (are my algos earning their keep?)")
    print(f"  {line}")
    print(f"  GATE to go live:  beat sharp close ≥{PROMOTE_BEAT_MIN:.0f}%   AND   "
          f"ROI > 0 over ≥{PROMOTE_ROI_MIN_N} settled bets")
    print("  " + "─" * 72)
    if live:
        print("\n  🟢 LIVE  (earned it — betting real money)")
        for _, r in sorted(live, key=lambda x: -x[0]):
            print(r)
    print("\n  🔵 PROVING  (shadow — climbing toward the gate)")
    for _, r in sorted(proving, key=lambda x: -x[0]):
        print(r)
    if held:
        print("\n  🟡 HELD  (paused — known losers, logged not bet)")
        for _, r in sorted(held, key=lambda x: -x[0]):
            print(r)
    print(f"\n  {line}")
    print("  Every lane is judged on CLV — beating the sharp CLOSE proves the edge")
    print("  is real (winning bets alone can be a lucky run of longshots). Beat-rate")
    print("  EXCLUDES flats (a stuck line is neutral), so sticky totals aren't")
    print("  unfairly punished. PROMOTE needs CLV ≥55% AND positive ROI.")
    print(f"  {line}\n")
    return 0


# ─────────────────────────── experiment ──────────────────────────────────────

def cmd_experiment(args: argparse.Namespace) -> int:
    """The model-tuning ledger: triage every algo, snapshot a baseline, or show
    an algo's version history (baseline → change → re-measure → keep/revert)."""
    from src.analytics import experiment_log as xl
    action = getattr(args, "action", "triage")

    if action == "triage":
        rows = xl.triage(min_n=getattr(args, "min_n", 30))
        line = "═" * 78
        print(f"\n  {line}")
        print("  ALGO TRIAGE — is there real signal to tune? (confidence test)")
        print(f"  {line}")
        print(f"  {'LANE':28s} {'n':>4} {'ROI':>7} {'CLV':>7} {'SIGNAL':>18}  CALL")
        print("  " + "─" * 76)
        for t in rows:
            lane = f"{t.sport}/{t.market}"
            roi = f"{t.roi:+.1f}%" if t.roi is not None else "—"
            clv = f"{t.clv:+.1f}%" if t.clv is not None else "—"
            sig = t.signal + (f"({t.spread:+.0f})" if t.spread is not None else "")
            print(f"  {lane:28s} {t.n:>4} {roi:>7} {clv:>7} {sig:>18}  {t.call}")
        print(f"  {line}")
        print("  SIGNAL = does higher model confidence → higher win rate? "
              "(spread = top−bottom bucket WR, pts)")
        print("  real-signal/noisy = tunable · flat/inverted = rebuild or cut · "
              "insufficient = need more picks")
        print(f"  {line}\n")
        return 0

    if action == "optimize":
        # Sweep a confidence floor for every lane; recommend the robust ones.
        rows = [xl.optimize_floor(t.sport, t.market) for t in xl.triage(min_n=60)]
        rows.sort(key=lambda r: (0 if r.verdict.startswith("TUNE-APPLY") else
                                 1 if r.verdict.startswith("TUNE") else 2,
                                 -(r.roi_kept or -999)))
        line = "═" * 82
        print(f"\n  {line}")
        print("  CONFIDENCE-FLOOR OPTIMIZER — the best robust floor per lane")
        print(f"  {line}")
        print(f"  {'LANE':26s} {'BASE':>7} {'FLOOR':>6} {'KEPT':>10} {'ROI→':>7}  VERDICT")
        print("  " + "─" * 80)
        for r in rows:
            base = f"{r.roi_base:+.1f}%"
            fl = f"{r.floor:.2f}" if r.floor is not None else "—"
            kept = f"{r.n_kept}@{r.wr_kept:.0f}%" if r.floor is not None else "—"
            roi = f"{r.roi_kept:+.1f}%" if r.roi_kept is not None else "—"
            print(f"  {r.sport+'/'+r.market:26s} {base:>7} {fl:>6} {kept:>10} {roi:>7}  {r.verdict}")
        print(f"  {line}")
        print("  TUNE-APPLY = commit the floor · TUNE-THIN/CHECK = forward-validate first · "
              "REBUILD = needs new signal")
        print(f"  {line}\n")
        return 0

    sport = getattr(args, "sport", None)
    market = getattr(args, "market", None)
    if not sport or not market:
        print("  Usage: chef.py experiment snapshot <sport> <market> [--tag T] [--note ...]")
        print("         chef.py experiment history  <sport> <market>")
        return 1

    if action == "snapshot":
        snap = xl.record(sport, market, getattr(args, "tag", None) or "baseline",
                         note=getattr(args, "note", "") or "")
        c = snap.confidence
        print(f"\n  Snapshot {snap.sport}/{snap.market} @ {snap.tag} ({snap.date})")
        print(f"    n={snap.n}  {snap.record}  WR={snap.wr}%  ROI={snap.roi}%  "
              f"CLV={snap.clv}% ({snap.clv_n})  odds={snap.avg_odds}")
        print(f"    confidence signal: {c.get('verdict')} "
              f"(spread {c.get('spread')} pts) — {snap.note}")
        return 0

    if action == "history":
        hist = xl.history(sport, market)
        if not hist:
            print(f"  No experiment history for {sport}/{market} yet.")
            return 0
        print(f"\n  {sport}/{market} — experiment history")
        print(f"  {'TAG':16s} {'DATE':12s} {'n':>4} {'ROI':>7} {'CLV':>7} {'SIGNAL':>16}  NOTE")
        for h in hist:
            c = h.get("confidence", {})
            roi = f"{h['roi']:+.1f}%" if h.get("roi") is not None else "—"
            clv = f"{h['clv']:+.1f}%" if h.get("clv") is not None else "—"
            print(f"  {h['tag']:16s} {h['date']:12s} {h.get('n',0):>4} {roi:>7} {clv:>7} "
                  f"{c.get('verdict','—'):>16}  {h.get('note','')}")
        print()
        return 0

    print(f"  Unknown experiment action: {action}")
    return 1


# ─────────────────────────── shop ────────────────────────────────────────────

def cmd_shop(args: argparse.Namespace) -> int:
    """Pure Monahan-style +EV line shopping: find every bet beating Pinnacle fair line."""
    try:
        from src.data.line_shop import find_ev_bets
        sport = getattr(args, "sport", "all")
        min_ev = getattr(args, "min_ev", 2.0)

        if sport in ("all", "mlb"):
            find_ev_bets(sport="baseball_mlb", min_ev_pct=min_ev)
        if sport in ("all", "nba"):
            find_ev_bets(sport="basketball_nba", min_ev_pct=min_ev)
        # NHL shop disabled — model is broken (2-19, -81.6% ROI)
        return 0
    except Exception as e:
        print(f"  shop error: {e}")
        import traceback; traceback.print_exc()
        return 1


# ─────────────────────────── arb ─────────────────────────────────────────────

def cmd_draft(args: argparse.Namespace) -> int:
    """Fantasy football draft board, and the live assistant during the draft."""
    import time as _t
    from src.fantasy import sleeper as _sl
    from src.fantasy.league import load as _load_league
    from src.fantasy.valuation import build_board, starters_from_settings
    from src.fantasy.draft import load_state, recommend, roster_counts

    cfg = _load_league()
    board = build_board(cfg.scoring_settings, cfg.roster_positions, cfg.teams)
    starters = {k: int(round(v / cfg.teams))
                for k, v in starters_from_settings(cfg.roster_positions, cfg.teams).items()}

    line = "═" * 96
    print(f"\n  {line}")
    print(f"  {cfg.summary()}")
    print(f"  {line}")

    if getattr(args, "handcuffs", False):
        from src.fantasy.roster_risk import handcuffs
        from src.fantasy import sleeper as _s3
        bmap = {v.player_id: v for v in board}
        print("\n  RB HANDCUFFS — the back who inherits a startable role")
        print(f"  {'TM':<5}{'STARTER':<24}{'VORP':>6}   {'BACKUP':<24}{'VORP':>6}")
        print(f"  {'─'*70}")
        for h in handcuffs("RB", _s3.players()):
            sv = bmap.get(h.starter_id)
            bv = bmap.get(h.backup_id)
            print(f"  {h.team:<5}{h.starter:<24}{(sv.vorp if sv else 0):>6.0f}   "
                  f"{h.backup:<24}{(bv.vorp if bv else 0):>6.0f}")
        print("\n  A RB2 is worth almost nothing until the moment he is worth a")
        print("  great deal. Protect the handcuffs behind YOUR backs; the rest are")
        print("  late-round lottery tickets, not roster spots.\n")
        return 0

    if getattr(args, "sim", False):
        from src.fantasy.simulate import compare_openings
        from src.fantasy import sleeper as _s2
        drafts = _s2.league_drafts(cfg.league_id)
        d = _s2.draft(drafts[0]["draft_id"]) if drafts else {}
        me = _s2.user(args.user)["user_id"]
        slot = int(getattr(args, "slot", None)
                   or (d.get("draft_order") or {}).get(me, 1))
        rounds = int((d.get("settings") or {}).get("rounds") or 14)
        openings = [("RB", "RB"), ("WR", "RB"), ("RB", "WR"), ("WR", "WR"),
                    ("RB", "RB", "WR"), ("WR", "RB", "RB"), ("RB", "WR", "WR")]
        print(f"\n  Simulating {args.trials} drafts per opening from slot {slot}…")
        res = compare_openings(board, openings, slot, cfg.teams, rounds,
                               cfg.roster_positions, trials=args.trials)
        print(f"\n  {'OPENING':<20}{'MEAN':>8}{'p25':>8}{'p75':>8}{'WORST':>8}")
        print(f"  {'─'*54}")
        for r in res:
            print(f"  {'-'.join(r.opening):<18}{r.mean_starter_vorp:>8.0f}"
                  f"{r.p25:>8.0f}{r.p75:>8.0f}{r.worst:>8.0f}")
        print(f"\n  Scored on your STARTING lineup, not your roster — a fourth RB")
        print(f"  contributes nothing to a lineup that starts two.")
        print(f"  Opponents draft near ADP with realistic noise, so runs emerge")
        print(f"  naturally. Waivers, trades and injuries are NOT modelled, so this")
        print(f"  ranks openings against each other — it is not a points forecast.\n")
        return 0

    if not getattr(args, "live", False):
        rows = board
        if getattr(args, "pos", None):
            rows = [v for v in rows if v.position == args.pos.upper()]
        print(f"\n  {'#':<4}{'PLAYER':<26}{'POS':<5}{'TM':<4}{'PROJ':>6}{'VORP':>6}"
              f"{'TIER':>5}{'ADP':>6}{'DELTA':>7}  NOTE")
        print(f"  {'─'*94}")
        for i, v in enumerate(rows[:args.top], 1):
            print(f"  {i:<4}{v.name:<26}{v.position:<5}{v.team:<4}{v.proj_points:>6.0f}"
                  f"{v.vorp:>6.0f}{v.tier:>5}{(v.adp or 0):>6.0f}"
                  f"{(v.adp_delta if v.adp_delta is not None else 0):>+7.0f}  {v.note}")
        print(f"\n  DELTA = market ADP minus our rank. Positive = he falls to you.")
        print(f"  Large deltas are a QUESTION, not an instruction — our projections")
        print(f"  don't model team changes, depth charts or coaching.\n")
        return 0

    # ── live ──
    try:
        me = _sl.user(args.user)
        my_id = me.get("user_id")
    except Exception as err:
        print(f"  Could not resolve Sleeper user '{args.user}': {err}")
        return 1

    drafts = _sl.league_drafts(cfg.league_id)
    if not drafts:
        print("  No draft found for this league.")
        return 1
    draft_id = drafts[0]["draft_id"]

    while True:
        st = load_state(draft_id, my_id)
        bmap = {v.player_id: v for v in board}
        have = roster_counts(st.my_players, bmap)
        try:
            from src.fantasy.draft import positional_run, run_alert
            _picks = _sl.draft_picks(draft_id)
            alert = run_alert(positional_run(_picks, bmap))
        except Exception:
            alert = None
        nexts = st.my_next_picks(3)
        on_clock = bool(nexts and nexts[0] == st.current_pick)

        print(f"\n  Pick {st.current_pick} of {st.teams * st.rounds}"
              f"   ·   your slot {st.my_slot}"
              f"   ·   your next: {', '.join(map(str, nexts)) or '—'}"
              f"{'   ← ON THE CLOCK' if on_clock else ''}")
        print(f"  roster: " + "  ".join(f"{k}:{v}" for k, v in have.items() if v))
        if alert:
            print(f"  ⚠  {alert}")

        recs = recommend(board, st, starters, top=args.top)
        print(f"\n  {'':<3}{'PLAYER':<24}{'POS':<5}{'VORP':>6}{'ADJ':>7}{'SURV':>6}{'ADP':>6}  WHY")
        print(f"  {'─'*92}")
        for i, s_ in enumerate(recs, 1):
            v = s_.value
            print(f"  {i:<3}{v.name:<24}{v.position:<5}{v.vorp:>6.0f}{s_.adjusted:>7.0f}"
                  f"{s_.survives:>6.0%}{(v.adp or 0):>6.0f}  {s_.reason}")

        if not getattr(args, "watch", False):
            print()
            return 0
        if st.picks_made >= st.teams * st.rounds:
            print("\n  Draft complete.\n")
            return 0
        _t.sleep(8)


def cmd_filters(args: argparse.Namespace) -> int:
    """Report every registered subgroup filter, in-sample vs out-of-sample.

    A subgroup found by slicing is a description, not a prediction. These are
    registered with a start date and judged only on picks emitted after it.
    """
    from src.analytics.filter_experiment import evaluate_all

    results = evaluate_all()
    if not results:
        print("  No filters registered.")
        return 0

    line = "═" * 78
    print(f"\n  {line}")
    print("  SUBGROUP FILTERS UNDER TEST")
    print(f"  {line}")
    for r in results:
        print(f"\n  {r.name}   [{r.sport}/{r.market}, from {r.start_date}]")
        print(f"    hypothesis: {r.hypothesis}")
        if r.note:
            print(f"    caveat:     {r.note}")
        def fmt(n, wr, roi):
            if not n:
                return "no graded picks yet"
            return f"n={n:<5} WR={wr:>5.1f}%  ROI={roi:>+6.1f}%"
        print(f"    in-sample  (descriptive) : {fmt(r.in_n, r.in_wr, r.in_roi)}")
        print(f"    OUT-OF-SAMPLE (evidence) : {fmt(r.out_n, r.out_wr, r.out_roi)}")
        if r.comp_n:
            print(f"    complement (the bets it skips): n={r.comp_n:<5} "
                  f"ROI={r.comp_roi:>+6.1f}%")
        print(f"    → {r.verdict}")
    print(f"\n  {line}\n")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    """Is the pipeline still running? Per-lane emission + closing-line capture.

    Separates a dead pipeline (the sport logged nothing) from a silent model
    (the sport logged fine, this market produced nothing) — they look identical
    in the ledger and need completely different fixes.
    """
    from src.analytics.coverage import (
        report, capture_rate, healthy, canon_sport, MIN_CAPTURE_RATE,
    )
    from src.config.models import is_live

    days = int(getattr(args, "days", None) or 30)
    only = (getattr(args, "sport", None) or "").lower()
    min_n = int(getattr(args, "min_picks", None) or 1)
    gate  = bool(getattr(args, "gate", False))

    if gate:
        # CI mode: judge ONLY live lanes. A shadow lane going quiet is research
        # drifting; a live lane going quiet means the thing taking real money
        # stopped and its numbers are being quoted from a frozen sample.
        bad = []
        for c in report(days):
            if not is_live(c.sport, c.market):
                continue
            ok, msg = healthy(c)
            n, closed, rate = capture_rate(c.sport, days)
            if not ok:
                bad.append(f"{c.sport}/{c.market}: {msg}")
            elif n and rate < MIN_CAPTURE_RATE:
                bad.append(f"{c.sport}/{c.market}: capture {rate:.0%} "
                           f"({closed}/{n}) — snapshots can't be scored")
        if bad:
            print("\n  ✗ COVERAGE GATE FAILED — a LIVE lane is not healthy:")
            for b in bad:
                print(f"      {b}")
            print("\n  Run `chef.py coverage` for the day-by-day breakdown.\n")
            return 1
        print("  ✓ coverage gate: every live lane is emitting and being captured.")
        return 0

    lanes = report(days)
    if only:
        lanes = [c for c in lanes if canon_sport(c.sport) == canon_sport(only)]
    lanes = [c for c in lanes if c.market_days or c.sport_active_days >= min_n]
    if not lanes:
        print("  No lanes with activity in the window.")
        return 0

    line = "═" * 86
    print(f"\n  {line}")
    print(f"  PIPELINE COVERAGE — last {days} days")
    print(f"  {line}")
    print(f"\n  {'LANE':<30}{'':<4}{'EMITTED':>10}{'COVER':>8}{'GAP':>6}   STATUS")
    print(f"  {'─'*84}")

    unhealthy = 0
    for c in sorted(lanes, key=lambda x: (x.sport, x.market)):
        ok, msg = healthy(c)
        live = is_live(c.sport, c.market)
        if not ok and (live or c.market_days):
            unhealthy += 1
        flag = "🟢" if live else "  "
        mark = "ok" if ok else "✗ "
        print(f"  {c.sport+'/'+c.market:<30}{flag:<4}"
              f"{str(c.market_days)+'/'+str(c.sport_active_days):>10}"
              f"{c.market_coverage:>7.0%}{c.longest_gap:>6}   {mark} "
              f"{'' if ok else msg[:44]}")

    # Detail where it matters: the gaps themselves, split by cause.
    for c in sorted(lanes, key=lambda x: (x.sport, x.market)):
        if not (c.pipeline_gap_days or c.market_gap_days):
            continue
        if not (is_live(c.sport, c.market) or c.market_days >= 5):
            continue
        print(f"\n  {c.sport}/{c.market}" + ("  🟢 LIVE" if is_live(c.sport, c.market) else ""))
        if c.pipeline_gap_days:
            print(f"    PIPELINE DOWN ({len(c.pipeline_gap_days)}d) — sport logged nothing:")
            print(f"      {', '.join(c.pipeline_gap_days[:12])}")
        if c.market_gap_days:
            print(f"    MODEL SILENT ({len(c.market_gap_days)}d) — pipeline ran, this market didn't:")
            print(f"      {', '.join(c.market_gap_days[:12])}")

    print(f"\n  {'─'*84}")
    print(f"  CLOSING-LINE CAPTURE (a snapshot with no close can never be scored)")
    for sport in sorted({canon_sport(c.sport) for c in lanes}):
        n, closed, rate = capture_rate(sport, days)
        if not n:
            continue
        mark = "ok" if rate >= MIN_CAPTURE_RATE else "✗ "
        print(f"    {mark} {sport:<22}{closed:>6}/{n:<6} {rate:>6.0%}")

    print(f"\n  {line}\n")
    return 1 if unhealthy else 0


def cmd_audit_models(args: argparse.Namespace) -> int:
    """Audit every lane against the build standard (src/config/model_standard.py).

    The same checks tests/test_model_standard.py enforces, as a report — so a
    lane's gaps are visible BEFORE you start rebuilding it, and so a shadow lane
    can be measured against the bar it would have to clear to go live.
    """
    from src.config.model_standard import audit, is_exempt, EXEMPTIONS, CHECKS
    from src.config.models import MODELS, is_live

    only  = (getattr(args, "sport", None) or "").lower()
    live_only = bool(getattr(args, "live", False))

    lanes = sorted({(s, m) for (s, m) in MODELS})
    if only:
        lanes = [l for l in lanes if l[0] == only]
    if live_only:
        lanes = [l for l in lanes if is_live(*l)]
    if not lanes:
        print("  No lanes match.")
        return 1

    names = [n for n, _ in CHECKS]
    line = "═" * 92
    print(f"\n  {line}")
    print(f"  BUILD STANDARD AUDIT — {len(lanes)} lane(s)")
    print(f"  {line}")
    print(f"\n  {'LANE':<38}{'':<4}" + "".join(f"{n[:9]:<11}" for n in names))
    print(f"  {'─'*100}")

    failing_live = 0
    for sport, market in lanes:
        results = audit(sport, market)
        live = is_live(sport, market)
        cells = ""
        for c in results:
            if c.ok:
                cells += f"{'  ok':<11}"
            elif is_exempt(sport, market, c.name):
                cells += f"{'  ex':<11}"
            else:
                cells += f"{'  ✗':<11}"
        flag = "🟢" if live else "  "
        print(f"  {sport+'/'+market:<38}{flag:<4}{cells}")
        if live and any(not c.ok and not is_exempt(sport, market, c.name)
                        for c in results):
            failing_live += 1

    print(f"\n  ok = passes · ex = documented exemption · ✗ = gap · 🟢 = LIVE (takes real money)")

    # Detail only where it matters: live lanes, and anything the user asked for.
    detail_lanes = [l for l in lanes if is_live(*l)] if not only else lanes
    for sport, market in detail_lanes:
        results = audit(sport, market)
        gaps = [c for c in results if not c.ok]
        if not gaps:
            continue
        print(f"\n  {sport}/{market}" + ("  🟢 LIVE" if is_live(sport, market) else ""))
        for c in gaps:
            tag = "EXEMPT" if is_exempt(sport, market, c.name) else "GAP   "
            print(f"    {tag}  {c.name:<16} {c.detail}")

    if EXEMPTIONS:
        print(f"\n  {'─'*90}")
        print(f"  EXEMPTIONS ({len(EXEMPTIONS)})")
        for (s, m), ex in EXEMPTIONS.items():
            print(f"    {s}/{m}  [{', '.join(ex['checks'])}]  since {ex['since']}")
            print(f"      why:     {ex['why'][:150]}")
            print(f"      retire:  {ex['retire_when'][:150]}")

    print(f"\n  {line}\n")
    return 1 if failing_live else 0


# Boards the market scan seeds on a cold start (empty cache, e.g. CI). Kept to
# in-season leagues so an off-season key isn't spent on an empty board; each is
# one cheap call and the scan itself is free thereafter.
SCAN_SPORTS = (
    "baseball_mlb", "basketball_wnba", "mma_mixed_martial_arts",
    "soccer_usa_mls", "soccer_mexico_ligamx",
)


def cmd_scan(args: argparse.Namespace) -> int:
    """MARKET track: scan every cached board for books priced off the sharp fair.

    Predicts nothing. Reads the odds cache (zero API credits), de-vigs Pinnacle
    for a true probability, and reports every bettable book offering better than
    that number. Logs shadow-only under strategy=line_shop so the existing CLV
    pipeline proves or kills it before a dollar rides on it.
    """
    from src.strategies.line_shop_scanner import scan_sport, to_pick, MIN_EV_PCT
    from src.tracking.schema import append_picks_safe

    min_ev  = float(getattr(args, "min_ev", None) or MIN_EV_PCT)
    only    = (getattr(args, "sport", None) or "").lower()
    do_log  = bool(getattr(args, "log", False))
    max_age = float(getattr(args, "max_age", None) or 90.0)

    boards = sorted(Path("data/cache/odds").glob("*_latest.json"))
    if only:
        boards = [b for b in boards if only in b.name]

    if not boards and not getattr(args, "refresh", False):
        print("  No cached odds boards. Run: python3 chef.py picks <sport>, "
              "or re-run with --refresh to fetch them.")
        return 1

    if getattr(args, "refresh", False) and not boards:
        # A CI runner starts with an EMPTY cache — data/cache/ is gitignored, so
        # there is nothing to "refresh" and the scan exited 1 on a clean box even
        # though the API key was fine. Seed the in-season board set from scratch.
        from src.data.odds_api import fetch_odds
        print(f"  No cached boards (clean checkout) — seeding {len(SCAN_SPORTS)} board(s)…")
        for sport_key in SCAN_SPORTS:
            try:
                fetch_odds(sport=sport_key, refresh=True)
            except Exception as err:
                print(f"    {sport_key}: skipped ({str(err)[:60]})")
        boards = sorted(Path("data/cache/odds").glob("*_latest.json"))
        if only:
            boards = [b for b in boards if only in b.name]
        if not boards:
            print("  Could not fetch any board — check ODDS_API_KEY and quota.")
            return 1

    if getattr(args, "refresh", False):
        # The scan itself is free — it reads the cache. But a cache is only an
        # entry market while it's fresh, and the pick pipelines refresh boards
        # twice a day while this can run four times, so without this two runs in
        # three would find every board stale and scan nothing. Refresh only the
        # sports whose board is already too old to use.
        from src.data.odds_api import fetch_odds
        import time as _time
        stale = []
        for b in boards:
            age_min = (_time.time() - b.stat().st_mtime) / 60.0
            if age_min > max_age:
                stale.append(b.name.replace("_latest.json", ""))
        if not stale:
            print(f"  All {len(boards)} board(s) fresh — no refresh needed (0 credits).")
        else:
            print(f"  Refreshing {len(stale)} stale board(s)…")
            for sport_key in stale:
                try:
                    fetch_odds(sport=sport_key, refresh=True)
                except Exception as err:
                    print(f"    {sport_key}: skipped ({str(err)[:60]})")
            boards = sorted(Path("data/cache/odds").glob("*_latest.json"))
            if only:
                boards = [b for b in boards if only in b.name]

    all_rows: list[dict] = []
    diags: list[dict] = []
    for b in boards:
        rows, diag = scan_sport(b.name.replace("_latest.json", ""),
                                min_ev=min_ev, max_age_min=max_age)
        all_rows.extend(rows)
        diags.append(diag)

    line = "═" * 78
    print(f"\n  {line}")
    print(f"  MARKET TRACK — line shop  ·  fair = Pinnacle de-vig, consensus fallback")
    print(f"  min EV {min_ev:.1f}%  ·  boards ≤{max_age:.0f}m old  ·  0 API credits")
    print(f"  {line}")

    live = [d for d in diags if d["status"] == "ok"]
    skipped = [d for d in diags if d["status"] != "ok"]
    print(f"\n  BOARDS  {len(live)} scanned, {len(skipped)} skipped")
    n_rejected = sum(d.get("rejected", 0) for d in live)
    for d in sorted(live, key=lambda x: -x.get("found", 0)):
        rej = f"  ⚠ {d['rejected']} over ceiling" if d.get("rejected") else ""
        print(f"    {d['sport']:<34} {d['events']:>3} events  "
              f"{d.get('with_sharp',0):>3} w/ Pinnacle  →  {d.get('found',0):>3} edges{rej}")
    if n_rejected:
        from src.strategies.line_shop_scanner import MAX_EV_PCT
        print(f"\n  ⚠  {n_rejected} row(s) exceeded the {MAX_EV_PCT:.0f}% EV ceiling and were")
        print(f"     DROPPED. Books don't leave that on the table — a double-digit")
        print(f"     edge is a market-structure bug, not a bet. Sample:")
        for d in live:
            for r in d.get("rejected_rows", [])[:2]:
                bet = f"{r['selection']}" + (f" {r['line']}" if r.get("line") is not None else "")
                print(f"       {r['ev_pct']:>+7.1f}%  {bet[:28]:<28} {r['odds']:>+6} "
                      f"{r['book'][:10]:<10} ({r['source']})")
    if skipped:
        stale = ", ".join(f"{d['sport'].replace('_latest','')} ({d['status']})"
                          for d in skipped[:6])
        print(f"    skipped: {stale}{' …' if len(skipped) > 6 else ''}")

    # UNKNOWN ≠ CLEAN. If every board was skipped we scanned nothing at all, and
    # "no +EV opportunities" below would be a lie of omission: it reads as "the
    # market is tight today" when the truth is "this tool did no work." That is
    # how a scanner sits dead for a week behind green CI runs. A scan that
    # examined zero boards is a failure, and says so.
    if not live:
        print(f"\n  ✗ UNKNOWN — 0 boards scanned, {len(skipped)} skipped.")
        print("    NOTHING was checked, so this is NOT 'no edges today'. Every")
        print("    board was missing or older than the "
              f"{max_age:.0f}m freshness limit.")
        print("    Fix: run with --refresh, or check ODDS_API_KEY / quota.")
        print(f"\n  {line}\n")
        return 1

    if not all_rows:
        print(f"\n  No +EV opportunities at {min_ev:.1f}%+.")
        print(f"  ({len(live)} board(s) genuinely scanned — this is a real result.)")
        print("  Zero is the correct and common result — a tight board means the")
        print("  books agree, and inventing an edge there is how bankrolls die.")
        print(f"\n  {line}\n")
        return 0

    # Drop anything already started or outside the requested window — a stale
    # "edge" on a game in progress is not a bet.
    days = float(getattr(args, "days", None) or 3)
    horizon = days * 24.0
    fresh = [r for r in all_rows
             if r.get("hours_out") is not None and 0 <= r["hours_out"] <= horizon]
    dropped = len(all_rows) - len(fresh)
    all_rows = fresh

    if not all_rows:
        print(f"\n  No +EV opportunities starting in the next {days:.0f} day(s).")
        if dropped:
            print(f"  ({dropped} hit(s) fell outside the window — use --days to widen.)")
        print(f"\n  {line}\n")
        return 0

    bankroll = float(getattr(args, "bankroll", None) or 0) or _bankroll_balance()
    by_day: dict[str, list[dict]] = {}
    for r in sorted(all_rows, key=lambda x: (x.get("commence") or "", -x["ev_pct"])):
        by_day.setdefault(r.get("starts_date") or "unknown", []).append(r)

    print(f"\n  {len(all_rows)} OPPORTUNITY(S) — next {days:.0f} day(s), "
          f"times in {_local_tz_label()}")
    if dropped:
        print(f"  ({dropped} outside the window, not shown)")

    for day, rows in by_day.items():
        try:
            pretty = datetime.strptime(day, "%Y-%m-%d").strftime("%A %d %B")
        except ValueError:
            pretty = day
        print(f"\n  ── {pretty} ──")
        print(f"  {'START':<7} {'EV%':>6}  {'SPORT':<17} {'BOOK':<11} "
              f"{'ODDS':>6} {'FAIR':>6} {'¼K$':>7}  BET")
        print(f"  {'─'*120}")
        for r in rows:
            src = "P" if r["fair_source"] == "pinnacle" else f"c{r['n_books']}"
            quarter = r["kelly"] * 0.25 * bankroll
            start = (r.get("starts_local") or "—").split(" ", 1)
            hhmm = start[1] if len(start) > 1 else start[0]
            print(f"  {hhmm:<7} {r['ev_pct']:>+6.2f}  {r['sport_name'][:17]:<17} "
                  f"{r['book']:<11} {r['odds']:>+6} {r['fair_odds']:>+6} "
                  f"${quarter:>6.2f}  {r['bet_label'][:60]}  [{src}]")

    print(f"\n  Fair from: [P] Pinnacle de-vig · [cN] median of N books.")
    print(f"  ¼-Kelly sized against ${bankroll:.2f}.")

    if do_log:
        today = datetime.now().strftime("%Y-%m-%d")
        picks = [to_pick(r, today) for r in all_rows]
        n = append_picks_safe(_PNL_FILE, picks)
        print(f"\n  [pnl] Logged {n} line_shop shadow pick(s) — CLV will judge them.")
    else:
        print(f"\n  Not logged. Re-run with --log to start the CLV proving period.")

    print(f"\n  {line}\n")
    return 0


def _local_tz_label() -> str:
    from src.strategies.line_shop_scanner import LOCAL_TZ
    return LOCAL_TZ.split("/")[-1].replace("_", " ")


def _bankroll_balance() -> float:
    try:
        from src.tracking import bankroll as bk
        return bk.summary()["balance"]
    except Exception:
        return 300.0


def cmd_arb(args: argparse.Namespace) -> int:
    """Scan for guaranteed-profit arbitrage opportunities across all books."""
    try:
        from src.data.arb_finder import find_arbs, format_arb_table
        sport_arg = getattr(args, "sport", "all")
        bankroll  = getattr(args, "bankroll", 1000.0)
        tier1     = getattr(args, "tier1", False)

        sport_map = {
            "mlb": "baseball_mlb",
            "nba": "basketball_nba",
            "nhl": "icehockey_nhl",
        }
        targets = (["mlb", "nba"] if sport_arg == "all" else [sport_arg])
        found_any = False
        for s in targets:
            api_sport = sport_map.get(s, f"baseball_{s}")
            arbs = find_arbs(sport=api_sport, tier1_only=tier1)
            if arbs:
                found_any = True
                print(format_arb_table(arbs, bankroll=bankroll))
            else:
                print(f"  [{s.upper()}] No arbs found right now.")
        if not found_any:
            print("  No arbitrage opportunities detected across all markets.")
        return 0
    except Exception as e:
        print(f"  arb error: {e}")
        import traceback; traceback.print_exc()
        return 1


# ─────────────────────────── clv ─────────────────────────────────────────────

def cmd_clv(args: argparse.Namespace) -> int:
    """Show Closing Line Value dashboard — the signal that proves edge is real."""
    try:
        from src.analytics.clv_tracker import (
            print_clv_report, print_clv_by_market, print_clv_matrix, compute_clv,
            backfill_snapshots_from_pnl, upgrade_snapshots,
            backfill_snapshot_markets, backfill_snapshot_lines,
            reconcile_stragglers, print_clv_by_strategy,
            print_clv_by_entry_hour, print_clv_by_entry_edge,
            print_clv_by_catalyst, print_clv_by_timing,
        )

        refresh = getattr(args, "refresh", False)
        if refresh:
            from pathlib import Path
            # 1. Snapshot every pick across history (no-op for ones already stored)
            backfill_snapshots_from_pnl()
            # 2. Repair legacy prop snapshots missing player/line/direction
            upgrade_snapshots()
            # 2b. Recover market on legacy snapshots that had it unset (spread/total
            #     wrongly scored as moneyline) — clears stale CLV so they re-score.
            backfill_snapshot_markets()
            # 2c. Recover opening_line/direction on total/spread snapshots that had
            #     them null (parsed from the team string) — without these the
            #     totals/spread scorer can't compute line CLV, so they never scored.
            backfill_snapshot_lines()
            # 3. Recompute CLV for every date that has a closing archive — scores
            #    moneyline, spread, total, F5, NRFI, and props in one pass.
            archive_dir = Path("data/clv/closing")
            dates = {f.stem[-10:] for f in archive_dir.glob("*.json") if len(f.stem) >= 10}
            if dates:
                print(f"  Recomputing CLV for {len(dates)} archive dates...")
                for d in sorted(dates):
                    compute_clv(date_str=d)
            # 4. Straggler reconciliation — recover settled picks whose closing was
            #    captured a day off (postponement / picked-a-day-early) and so the
            #    strict gameday join skipped. Closes the last coverage gap toward
            #    the ~99% ceiling without any paid historical-odds calls.
            reconcile_stragglers()

        print_clv_report()
        if getattr(args, "matrix", False):
            print_clv_matrix()      # every sport × market broken out (with gap reasons)
        else:
            print_clv_by_market()   # per-market pooled: which market beats the close
        print_clv_by_strategy()     # PROMOTE/SHADOW/RETIRE verdicts (300-bet rule)
        print_clv_by_entry_hour()   # time-of-bet attribution: when does CLV accrue?
        print_clv_by_timing()       # entry lead time: is earlier-vs-commence better?
        print_clv_by_entry_edge()   # stale-opener validation: entry EV → realized CLV
        print_clv_by_catalyst()     # catalyst vs bare-disagreement split
        return 0
    except Exception as e:
        print(f"  CLV error: {e}")
        import traceback; traceback.print_exc()
        return 1


def cmd_clv_watch(args: argparse.Namespace) -> int:
    """Weekly CLV edge watcher — velocity, ETA to the sample floor, crossing alerts.

    `chef.py edge` is the point-in-time verdict; this adds the time dimension so
    you can see how fast each market is accruing bets and when it will cross into
    (or out of) proven-edge status. Run weekly to build the history.
    """
    try:
        from scripts.clv_watch import build, record, print_report
        report = build(getattr(args, "min_n", None) or 200)
        if not getattr(args, "no_record", False):
            record(report)
        print_report(report)
        return 0
    except Exception as e:
        print(f"  CLV watch error: {e}")
        import traceback; traceback.print_exc()
        return 1


def cmd_dashboard(args: argparse.Namespace) -> int:
    """One-screen model status check: every (sport, market) with its registry
    status, sample size, record, ROI, model EV, avg odds entered, and CLV
    (best price + vs Pinnacle). Joins the settled record (picks.json) with the
    CLV snapshots and the model registry so you can eyeball — at a glance —
    which algos are live, which are shadow, and which are actually earning their
    keep (ROI is realized P&L; CLV is the leading edge signal; EV is the model's
    own claim, which is only trustworthy where CLV agrees)."""
    import json as _json
    from collections import defaultdict
    from pathlib import Path

    def am_imp(o):
        o = float(o); return 100/(o+100) if o > 0 else abs(o)/(abs(o)+100)
    def imp_am(p):
        if not p or p <= 0 or p >= 1: return None
        return -round(p/(1-p)*100) if p >= 0.5 else round((1-p)/p*100)
    def avg(xs): return sum(xs)/len(xs) if xs else None

    try:
        from src.analytics.clv_tracker import _normalize_sport
    except Exception:
        def _normalize_sport(x): return x
    def lbl(sp):
        sp = _normalize_sport(str(sp or "?"))
        return {"baseball_mlb": "mlb", "basketball_nba": "nba", "basketball_wnba": "wnba",
                "icehockey_nhl": "nhl", "mma_mixed_martial_arts": "mma",
                "soccer_fifa_world_cup": "wc"}.get(
            sp, sp.replace("soccer_", "").replace("tennis_atp_", "atp-")
                  .replace("tennis_wta_", "wta-").replace("golf_", "golf-")[:11])

    sport_filter = (getattr(args, "sport", None) or "").lower() or None
    min_n = getattr(args, "min_n", None) or 1
    card_only = getattr(args, "card", False)

    try:
        picks = _json.loads(Path("data/pnl/picks.json").read_text())
        picks = picks.get("picks", picks) if isinstance(picks, dict) else picks
    except (OSError, ValueError):
        print("  ✗ picks.json unreadable"); return 1

    P = defaultdict(lambda: {"n": 0, "card": 0, "w": 0, "l": 0, "p": 0,
                             "stake": 0.0, "profit": 0.0, "imp": [], "ev": []})
    for pk in picks:
        if card_only and not pk.get("card_pick"):
            continue
        k = (lbl(pk.get("sport")), str(pk.get("market") or "?").lower())
        b = P[k]; b["n"] += 1
        if pk.get("card_pick"): b["card"] += 1
        r = pk.get("result")
        if r in ("win", "loss", "push"):
            b["stake"] += float(pk.get("stake") or 0); b["profit"] += float(pk.get("profit") or 0)
            b["w"] += r == "win"; b["l"] += r == "loss"; b["p"] += r == "push"
        o = pk.get("odds")
        if o not in (None, "", 0):
            try: b["imp"].append(am_imp(o))
            except (ValueError, TypeError): pass
        e = pk.get("edge_pct")
        if e is not None:
            try: b["ev"].append(float(e))
            except (ValueError, TypeError): pass

    try:
        snaps = _json.loads(Path("data/clv/snapshots.json").read_text())
        snaps = snaps.get("snapshots", snaps) if isinstance(snaps, dict) else snaps
    except (OSError, ValueError):
        snaps = []
    C = defaultdict(lambda: {"best": [], "sharp": [], "unit": "%"})
    for s in snaps:
        if not isinstance(s, dict): continue
        mk = str(s.get("market") or "?").lower()
        if mk in ("h2h", "ml"): mk = "moneyline"
        elif mk == "totals": mk = "total"
        elif mk in ("run_line", "runline", "puck_line", "puckline"): mk = "spread"
        k = (lbl(s.get("sport")), mk)
        if s.get("clv_pct") is not None:
            C[k]["best"].append(s["clv_pct"]); C[k]["unit"] = "%"
            if s.get("clv_sharp_pct") is not None: C[k]["sharp"].append(s["clv_sharp_pct"])
        elif s.get("line_clv") is not None:
            C[k]["best"].append(s["line_clv"]); C[k]["unit"] = "pt"
            if s.get("line_clv_sharp") is not None: C[k]["sharp"].append(s["line_clv_sharp"])

    try:
        from src.config.models import MODELS
        reg = {(k[0], k[1]): v for k, v in MODELS.items()}
    except Exception:
        reg = {}

    keys = sorted(set(P) | set(C), key=lambda k: -P[k]["n"])
    print(f"\n  ─ MODEL DASHBOARD ─ status · realized P&L · CLV (best │ vs Pinnacle) ─")
    if card_only: print("  [card picks only]")
    print(f"  {'sport':8}{'market':19}{'stat':5}{'n':>5}{'crd':>4}{'W-L-P':>12}"
          f"{'ROI':>8}{'EV':>7}{'odds':>6}{'CLVbest':>9}{'CLVpinn':>9}")
    print(f"  {'─'*98}")
    for k in keys:
        sp, mk = k
        if sport_filter and sport_filter not in sp: continue
        b = P[k]
        if card_only and b["n"] == 0: continue   # no card picks here → skip
        if b["n"] < min_n and not C[k]["best"]: continue
        c = C[k]
        settled = b["w"] + b["l"] + b["p"]
        roi = (b["profit"]/b["stake"]*100) if b["stake"] > 0 else None
        ev, imp = avg(b["ev"]), avg(b["imp"])
        odds = imp_am(imp) if imp else None
        cb, cs = avg(c["best"]), avg(c["sharp"])
        st = reg.get(k, {}).get("status", "—"); tier = reg.get(k, {}).get("tier", "")
        stat = {"live": "LIVE", "incubating": "shad", "retired": "ret"}.get(st, "—")
        if tier == "paused": stat = "paus"
        rec = f"{b['w']}-{b['l']}-{b['p']}" if settled else "—"
        roi_s = f"{roi:+.1f}%" if roi is not None else "—"
        ev_s = f"{ev:+.1f}%" if ev is not None else "—"
        od_s = f"{odds:+d}" if odds is not None else "—"
        cb_s = f"{cb:+.2f}{c['unit']}" if cb is not None else "—"
        cs_s = f"{cs:+.2f}{c['unit']}" if cs is not None else "—"
        print(f"  {sp[:7]:8}{mk[:18]:19}{stat:5}{b['n']:>5}{b['card']:>4}{rec:>12}"
              f"{roi_s:>8}{ev_s:>7}{od_s:>6}{cb_s:>9}{cs_s:>9}")
    print(f"  {'─'*98}")
    print(f"  stat: LIVE=posting cards · shad=shadow (tracking) · paus=paused")
    print(f"  ROI=realized P&L on settled bets · EV=model's claimed edge · "
          f"CLV=closing-line value (the truth)")
    print(f"  odds=avg price entered (implied-prob space) · crd=# card picks")
    return 0


def cmd_slate(args: argparse.Namespace) -> int:
    """Show every pick the algos logged for a day — the actual bet, book, and odds
    entered — grouped by sport → market. The 'see it myself' view: what was picked,
    at which sportsbook, at what price, and the model's edge. ★ = card pick (officially
    posted, counts toward the record); the rest are shadow (tracked, not bet)."""
    import json as _json
    from collections import defaultdict
    from datetime import date as _date
    from pathlib import Path

    target = getattr(args, "date", None)
    if target:
        # accept YYYYMMDD or YYYY-MM-DD
        t = target.replace("-", "")
        target = f"{t[:4]}-{t[4:6]}-{t[6:]}" if len(t) == 8 else target
    else:
        target = _date.today().isoformat()
    sport_filter = (getattr(args, "sport", None) or "").lower() or None
    card_only = getattr(args, "card", False)

    try:
        picks = _json.loads(Path("data/pnl/picks.json").read_text())
        picks = picks.get("picks", picks) if isinstance(picks, dict) else picks
    except (OSError, ValueError):
        print("  ✗ picks.json unreadable"); return 1

    day = [p for p in picks if p.get("date") == target]
    if sport_filter:
        day = [p for p in day if sport_filter in str(p.get("sport", "")).lower()]
    if card_only:
        day = [p for p in day if p.get("card_pick")]
    if not day:
        print(f"\n  No picks logged for {target}" +
              (f" ({sport_filter})" if sport_filter else "") +
              (" [card only]" if card_only else "") + ".")
        return 0

    # group: sport -> market -> [picks]
    grp: dict = defaultdict(lambda: defaultdict(list))
    for p in day:
        grp[str(p.get("sport") or "?")][str(p.get("market") or "?")].append(p)

    def desc(p):
        # human label for the actual selection
        base = str(p.get("player") or p.get("team") or "").strip()
        direction = str(p.get("direction") or "")
        line = p.get("line")
        mk = str(p.get("market") or "").lower()
        # Props/totals often store the full bet in the team string ("Name UNDER 4.5")
        # — if the direction is already there, don't re-append it.
        if direction and direction.lower() in base.lower():
            return base
        if mk in ("total", "totals", "f5_total", "f5_totals") and line is not None:
            return f"{base} {direction} {line}".strip()
        if mk in ("spread", "run_line", "runline", "puck_line", "puckline") and line is not None:
            try: return f"{base} {line:+g}".strip()
            except (ValueError, TypeError): return f"{base} {line}".strip()
        if direction in ("OVER", "UNDER") and line is not None:
            return f"{base} {direction} {line}".strip()
        if direction in ("AWAY", "HOME") and base:
            return f"{base} {direction}"
        return base or direction or "—"

    def odds_str(o):
        if o in (None, "", 0): return "—"
        try: o = int(o)
        except (ValueError, TypeError): return str(o)
        return f"{o:+d}"

    def matchup(p):
        # Moneyline picks store a truncated matchup (just the OPPONENT, e.g. an
        # AWAY pick on "NY Yankees" stores matchup="Detroit Tigers"). Reconstruct
        # the canonical "Away @ Home" from team + direction so every market for a
        # game shows the same full matchup string.
        mu = str(p.get("matchup") or "").strip()
        if "@" in mu:
            return mu
        team = str(p.get("team") or "").strip()
        d = str(p.get("direction") or "").upper()
        if mu and team:
            if d == "AWAY":
                return f"{team} @ {mu}"   # team is away, stored matchup is the home side
            if d == "HOME":
                return f"{mu} @ {team}"   # team is home, stored matchup is the away side
        return mu or team or ""

    n_card = sum(1 for p in day if p.get("card_pick"))
    print(f"\n  ─ SLATE {target} ─ {len(day)} picks ({n_card} card ★, {len(day)-n_card} shadow) ─")
    if card_only: print("  [card picks only]")
    for sport in sorted(grp, key=lambda s: -sum(len(v) for v in grp[s].values())):
        for market in sorted(grp[sport], key=lambda m: -len(grp[sport][m])):
            rows = sorted(grp[sport][market], key=lambda p: -(p.get("edge_pct") or -999))
            print(f"\n  {sport.upper()} · {market}")
            print(f"    {'':1}{'pick':30}{'book':18}{'odds':>7}{'edge':>9}  {'matchup'}")
            for p in rows:
                star = "★" if p.get("card_pick") else " "
                e = p.get("edge_pct")
                e_s = f"{e:+.1f}%" if e is not None else "—"
                mu = matchup(p)
                book = str(p.get("sportsbook") or "—")
                print(f"    {star}{desc(p)[:29]:30}{book[:17]:18}{odds_str(p.get('odds')):>7}"
                      f"{e_s:>9}  {mu[:38]}")
    print(f"\n  ★ = card pick (posted, counts toward record) · others are shadow (tracked only)")
    return 0


def cmd_wc_breakdown(args: argparse.Namespace) -> int:
    """Show the full World Cup market breakdown — every game's model lean on
    moneyline / total / spread / anytime-scorer, including sub-threshold leans.
    Reads the breakdown the daily pipeline saves (output/picks/.../breakdown.json)."""
    import json as _json
    from datetime import date as _date
    from pathlib import Path
    from src.output.wc_breakdown import render

    target = getattr(args, "date", None)
    target = (target.replace("-", "") if target else _date.today().strftime("%Y%m%d"))
    path = Path("output/picks/soccer_fifa_world_cup") / target / "breakdown.json"
    if not path.exists():
        print(f"\n  No WC breakdown saved for {target}.")
        print(f"  (Generated by the daily soccer pipeline: run `python3 run_soccer.py "
              f"--league worldcup --date {target} --refresh`)")
        return 1
    try:
        bd = _json.loads(path.read_text())
    except (ValueError, OSError) as e:
        print(f"  ✗ could not read breakdown: {e}")
        return 1
    print()
    print(render(bd, date_str=target))
    return 0


# ─────────────────────────── stats ───────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> int:
    """Show which sport pipelines have produced picks today (or for a given date).

    Quick morning sanity check — verifies cron fired and every sport has its
    daily output dir + picks file. Flags anything missing so you can re-run
    just that one pipeline manually.
    """
    from datetime import date as _date, datetime as _dt
    import os

    target = args.date or _date.today().strftime("%Y%m%d")
    try:
        target_dt = _date(int(target[:4]), int(target[4:6]), int(target[6:]))
    except (ValueError, IndexError):
        print(f"Invalid date: {target}. Use YYYYMMDD.")
        return 1

    # Each sport maps to one or more output dir prefixes — tennis/soccer/golf
    # rotate dir names by tournament, so we match by prefix.
    sports = [
        ("MLB",     ["baseball_mlb"],             "chef.py picks mlb"),
        ("NBA",     ["basketball_nba"],           "chef.py picks nba"),
        ("NHL",     ["icehockey_nhl"],            "run_nhl.py"),
        ("WNBA",    ["basketball_wnba"],          "run_wnba.py"),
        ("Tennis",  ["tennis_atp", "tennis_wta", "tennis"], "run_tennis.py"),
        ("Soccer",  ["soccer_"],                  "run_soccer.py"),
        ("UFC/MMA", ["mma_mixed_martial_arts"],   "run_ufc.py"),
        ("PGA",     ["golf_pga", "golf_masters", "golf_us_open"], "run_pga.py"),
    ]

    print(f"\n  Overlay Pipeline Status — {target_dt.strftime('%A %B %d, %Y')}")
    print(f"  Current time: {_dt.now().strftime('%H:%M:%S %Z')}")
    print(f"  {'─' * 70}")
    print(f"  {'Sport':<10} {'Status':<10} {'Picks':>7}  {'Files':>6}  Re-run command")
    print(f"  {'─' * 70}")

    missing = []
    picks_root = Path("output/picks")
    for label, prefixes, runner in sports:
        # Find any output dir matching one of the prefixes that has today's date
        found_dir = None
        for child in picks_root.iterdir() if picks_root.exists() else []:
            if not child.is_dir():
                continue
            if not any(child.name.startswith(p) for p in prefixes):
                continue
            candidate = child / target
            if candidate.exists():
                found_dir = candidate
                break

        if not found_dir:
            print(f"  {label:<10} {'✗ MISSING':<10} {'—':>7}  {'—':>6}  python3 {runner}")
            missing.append((label, runner))
            continue
        try:
            files = os.listdir(found_dir)
        except OSError:
            files = []
        # Count actual picks if picks.json exists
        n_picks = 0
        picks_path = found_dir / "picks.json"
        if picks_path.exists():
            try:
                data = json.loads(picks_path.read_text())
                n_picks = len(data) if isinstance(data, list) else len(data.get("picks", []))
            except (json.JSONDecodeError, ValueError):
                pass
        status = "✓ ran" if n_picks else "🟡 empty"
        print(f"  {label:<10} {status:<10} {n_picks:>7}  {len(files):>6}  {found_dir.parent.name}")

    print(f"  {'─' * 70}")
    if missing:
        print(f"\n  {len(missing)} sport(s) missing — re-run with the commands above.")
        print(f"  Quick fire-everything: ./scripts/setup_cron.sh && bash <(crontab -l | grep picks | awk '{{print $6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18}}')")
    else:
        print(f"\n  All {len(sports)} sport pipelines ran successfully ✓")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Daily 30-second health check — is the instrument still recording?

    The automation runs without you but fails silently. This answers one
    question: did today's data actually get collected, and is CLV fresh?
    Each line is ✓ (good), 🟡 (check), or ✗ (broken) with the fix.
    """
    from datetime import date as _date, timedelta
    import os, glob

    today = _date.today()
    yest  = today - timedelta(days=1)
    print(f"\n  ─ Daily Health — {today.strftime('%A %b %d, %Y')} ─────────────────────")
    issues = 0

    # 1. Picks generated today (any sport)
    picks_root = Path("output/picks")
    sport_dirs = [d for d in (picks_root.iterdir() if picks_root.exists() else [])
                  if d.is_dir() and (d / today.strftime("%Y%m%d") / "picks.json").exists()]
    n_today = 0
    for d in sport_dirs:
        try:
            blob = json.loads((d / today.strftime("%Y%m%d") / "picks.json").read_text())
            n_today += len(blob) if isinstance(blob, list) else len(blob.get("picks", []))
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    if sport_dirs:
        print(f"  ✓ Picks today        {len(sport_dirs)} sport(s), {n_today} picks")
    else:
        print(f"  🟡 Picks today        none yet  →  chef.py morning  (or wait for AM cron)")
        issues += 1

    # 2. Closing-line capture today (the irreplaceable data — the moat)
    close_files = glob.glob("data/clv/closing/*.json")
    today_iso = today.isoformat()
    todays = [f for f in close_files if Path(f).stem[-10:] == today_iso]
    events = 0
    for f in todays:
        try:
            d = json.loads(Path(f).read_text().replace("NaN", "null"))
            events += len(d) if isinstance(d, list) else 0
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    newest = max(close_files, key=os.path.getmtime) if close_files else None
    if todays and events:
        print(f"  ✓ Closing capture    {events} events across {len(todays)} sport file(s) today")
    elif newest:
        age = (today - _date.fromtimestamp(os.path.getmtime(newest))).days
        print(f"  ✗ Closing capture    NONE today (newest archive {age}d old)  →  check capture-closing.yml Action")
        issues += 1
    else:
        print(f"  ✗ Closing capture    no archives at all  →  check capture-closing.yml Action")
        issues += 1

    # 3. CLV freshness (snapshots scored)
    try:
        snaps = json.loads(Path("data/clv/snapshots.json").read_text())
        scored = [s for s in snaps if s.get("clv_pct") is not None or s.get("line_clv") is not None]
        last_dates = sorted({s.get("date") for s in scored if s.get("date")})
        last = last_dates[-1] if last_dates else None
        if last and last >= yest.isoformat():
            print(f"  ✓ CLV fresh          {len(scored)} scored, latest {last}")
        elif last:
            print(f"  🟡 CLV stale          latest scored {last}  →  chef.py clv --refresh")
            issues += 1
        else:
            print(f"  🟡 CLV                no scored snapshots yet")
            issues += 1
    except (json.JSONDecodeError, ValueError, OSError):
        print(f"  ✗ CLV                snapshots.json unreadable")
        issues += 1

    # 4. Grading current (yesterday settled?)
    try:
        allp = json.loads(Path("data/pnl/picks.json").read_text())
        allp = allp.get("picks", allp) if isinstance(allp, dict) else allp
        graded_dates = {p.get("date") for p in allp
                        if isinstance(p, dict) and p.get("result") in ("win", "loss", "push")}
        if yest.isoformat() in graded_dates:
            print(f"  ✓ Grading current    {yest.isoformat()} settled")
        else:
            print(f"  🟡 Grading            {yest.isoformat()} not graded yet  →  chef.py grade --date {yest.strftime('%Y%m%d')}")
            issues += 1
    except (json.JSONDecodeError, ValueError, OSError):
        print(f"  ✗ Grading            picks.json unreadable")
        issues += 1

    print(f"  {'─' * 58}")
    print(f"  {'✓ ALL GREEN — instrument recording' if issues == 0 else f'⚠ {issues} item(s) need a look (see → fixes above)'}")
    return 0


def _monitor_run(emit=print) -> tuple[int, list[str]]:
    """Run every integrity check, sending each output line to `emit`.

    Split out of cmd_monitor so the daily heartbeat reports the SAME verdict
    the alarm does. When the digest and the alarm each had their own notion of
    "healthy" they would eventually disagree, and the one you read every day
    would be the one that was wrong. Returns (gap_count, unverifiable_reasons).
    """
    from datetime import date as _date, timedelta
    from collections import defaultdict
    import os, glob

    today  = _date.today()
    cutoff = (today - timedelta(days=2)).isoformat()
    emit(f"\n  ─ Integrity Monitor — {today.strftime('%A %b %d, %Y')} ────────────────")

    # 1. Ground truth: what's actually in season (Odds API active-sports list).
    #    `unknown` tracks checks that could not be RUN, as opposed to checks that
    #    ran and failed. Both are red (see the exit at the bottom) — an alarm that
    #    can't see is not an all-clear — but they're reported separately so the
    #    fix is obvious: a gap means a pipeline broke, an UNKNOWN means the
    #    monitor itself is blind and every "✓" below is unverified.
    unknown: list[str] = []
    active: set = set()
    try:
        import requests
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            unknown.append("ODDS_API_KEY is not set — cannot tell which sports "
                           "are in season, so no market can be checked")
        else:
            r = requests.get("https://api.the-odds-api.com/v4/sports",
                             params={"apiKey": key}, timeout=15)
            if r.ok:
                # Quota exhaustion does NOT look like an error. /v4/sports keeps
                # returning 200 with a full sports list (it's a free endpoint)
                # while every paid odds call 401s, and the fetch layer turns that
                # into an empty DataFrame — which capture_closing reads as "no
                # odds for this game" and skips. On 2026-07-29 the key sat at
                # 0/500 remaining and the day's closing lines were simply never
                # archived, with nothing anywhere reporting a problem. Read the
                # credit header and treat empty as blind, not as healthy.
                try:
                    remaining = int(r.headers.get("x-requests-remaining", "-1"))
                except (TypeError, ValueError):
                    remaining = -1
                if remaining == 0:
                    unknown.append(
                        "Odds API quota EXHAUSTED (0 requests remaining) — odds "
                        "calls are 401ing, so closing lines are NOT being captured "
                        "and today's CLV is being lost permanently")
                elif 0 < remaining <= 250:
                    unknown.append(f"Odds API quota nearly gone ({remaining} left) "
                                   f"— capture will start failing silently")
                active = {s["key"] for s in r.json() if s.get("active")}
                if not active:
                    unknown.append("Odds API returned an EMPTY active-sports list "
                                   "(quota exhausted or upstream outage)")
            else:
                unknown.append(f"Odds API active-sports call failed "
                               f"(HTTP {r.status_code}) — season check impossible")
    except Exception as e:
        unknown.append(f"could not fetch active sports ({e}) — season check impossible")

    # 2. Last pick date per (sport, market) from the canonical record
    try:
        allp = json.loads(Path("data/pnl/picks.json").read_text())
        allp = allp.get("picks", allp) if isinstance(allp, dict) else allp
    except (json.JSONDecodeError, ValueError, OSError):
        allp = []
    last: dict = defaultdict(str)
    for p in allp:
        if not isinstance(p, dict):
            continue
        k = (str(p.get("sport", "")), str(p.get("market", "")))
        d = p.get("date", "")
        if d > last[k]:
            last[k] = d

    def _last_for(sport_test, market) -> str:
        best = ""
        for (sp, mk), d in last.items():
            if mk == market and sport_test(sp) and d > best:
                best = d
        return best

    # 3. What we model per sport + how to tell its season is live. Off-season
    #    sports (no active key) are skipped, so this never false-alarms.
    #
    #    Which markets to EXPECT comes from the model registry, not a list kept by
    #    hand here. The hand-kept list had drifted: it still demanded daily output
    #    from mlb/pitcher_strikeouts and nhl/puck_line, both deliberately RETIRED
    #    in ba820633 — so the monitor spent every day reporting that lanes we
    #    chose to kill were not producing. Same lesson as models._key: one source
    #    of truth, delegated to, never re-typed.
    #
    #    A lane is expected to produce when it is (a) not retired and (b) has
    #    logged at least once, i.e. actually wired up. Never-logged lanes are
    #    unbuilt, not broken — `chef.py grid` is where "to build" belongs, and
    #    dumping them into the daily alarm is how the alarm loses its meaning.
    try:
        from src.config.models import MODELS as _REG, model_status as _rstatus
    except Exception as _e:                       # registry unreadable → say so,
        _REG, _rstatus = {}, None                 # rather than silently expecting
        unknown.append(f"model registry unreadable ({_e}) — cannot tell which "  # nothing
                       f"lanes are supposed to be producing")

    def _expected(reg_sports, sport_test) -> list[str]:
        if not _rstatus:
            return []
        out = []
        for (s, m) in sorted(_REG):
            if s not in reg_sports or _rstatus(s, m) == "retired":
                continue
            if not _last_for(sport_test, m):
                continue                          # never wired — not a regression
            out.append(m)
        return out

    _specs_raw = [
        ("MLB",        lambda a: "baseball_mlb" in a,
                       lambda s: s in ("mlb", "baseball_mlb"),            ("mlb",)),
        ("NBA",        lambda a: "basketball_nba" in a,
                       lambda s: s in ("nba", "basketball_nba"),          ("nba",)),
        ("NHL",        lambda a: "icehockey_nhl" in a,
                       lambda s: s in ("nhl", "icehockey_nhl"),           ("nhl",)),
        ("WNBA",       lambda a: "basketball_wnba" in a,
                       lambda s: s in ("wnba", "basketball_wnba"),        ("wnba",)),
        ("Soccer/WC",  lambda a: "soccer_fifa_world_cup" in a,
                       lambda s: s == "soccer_fifa_world_cup",            ("wc",)),
        ("Tennis",     lambda a: any(k.startswith("tennis_") for k in a),
                       lambda s: s.startswith("tennis_"),                 ("tennis",)),
        ("Golf",       lambda a: any(k.startswith("golf_") for k in a),
                       lambda s: s.startswith("golf_"),                   ("pga",)),
        ("MMA/UFC",    lambda a: any(k.startswith("mma_") for k in a),
                       lambda s: s.startswith("mma_"),                    ("ufc",)),
        ("Motorsport", lambda a: any("auto_racing" in k for k in a),
                       lambda s: "auto_racing" in s,
                       ("f1", "nascar", "indycar")),
    ]
    specs = [(label, at, st, _expected(reg, st))
             for label, at, st, reg in _specs_raw]

    # 3b. "Active" in the Odds API does NOT mean "playing". It means the sport key
    #     is live in their system, which includes a board posted months ahead for
    #     next season. On 2026-07-29 that flagged icehockey_nhl as active while its
    #     earliest event was 2026-09-29 — so the monitor screamed that NHL
    #     moneyline/total/puck_line had gone DARK, in July, about a league on its
    #     summer break. Three false alarms every single day, in the same report as
    #     the real ones. That is how a daily red run becomes background noise and
    #     stops being read at all, so a precise season test is load-bearing for
    #     the alarm's credibility, not a nicety.
    #
    #     Ground truth instead: does this sport have an event starting inside the
    #     next SEASON_WINDOW days? The /events endpoint is free (0 quota credits),
    #     and we only probe the handful of keys our specs actually care about.
    #
    #     EXCEPTION — outright/futures lanes. Golf is modelled as tournament
    #     outrights, and its only active keys are season-long winner markets whose
    #     single "event" is dated a year out (golf_masters_tournament_winner →
    #     2027-04-08). Judging those by an imminent-event window would quietly
    #     drop golf from monitoring altogether — trading three noisy false alarms
    #     for a silent blind spot, which is the worse trade. Futures lanes keep
    #     the API's own active flag as their season test.
    SEASON_WINDOW = 7
    FUTURES_LANES = {"Golf", "Motorsport"}
    if active:
        from datetime import datetime as _dt, timezone as _tz
        horizon = (_dt.now(_tz.utc) + timedelta(days=SEASON_WINDOW)).isoformat()
        futures_keys = {k for k in active
                        if any(test({k}) for lbl, test, _, _ in specs
                               if lbl in FUTURES_LANES)}
        candidates = {k for k in active
                      if any(test({k}) for _, test, _, _ in specs)} - futures_keys
        playing: set = set(futures_keys)
        for k in sorted(candidates):
            try:
                ev = requests.get(
                    f"https://api.the-odds-api.com/v4/sports/{k}/events",
                    params={"apiKey": os.environ.get("ODDS_API_KEY")}, timeout=15)
                if not ev.ok:
                    unknown.append(f"could not list {k} events (HTTP {ev.status_code}) "
                                   f"— cannot tell if it is in season")
                    continue
                if any((e.get("commence_time") or "") <= horizon for e in ev.json()):
                    playing.add(k)
            except Exception as e:
                unknown.append(f"could not list {k} events ({type(e).__name__}) "
                               f"— cannot tell if it is in season")
        active = playing

    issues = 0
    emit("  In-season market coverage:")
    any_active = False
    for label, active_test, sport_test, markets in specs:
        if not active or not active_test(active):
            continue  # off-season → not expected
        any_active = True
        for mk in markets:
            d = _last_for(sport_test, mk)
            if d and d >= cutoff:
                emit(f"    ✓ {label:11} {mk:18} last {d}")
            else:
                shown = f"DARK (last {d})" if d else "NEVER logged"
                emit(f"    ✗ {label:11} {mk:18} {shown}  ← in season, not producing")
                issues += 1
    if not any_active and not unknown:
        # Reached the API fine and it named sports, but none of them are ones we
        # model. Genuinely possible, but rare enough to be worth surfacing rather
        # than passing over in silence.
        unknown.append("no sport we model is in season right now — nothing was "
                       "verified (real off-day, or the season tests are stale)")

    # 4. Closing capture freshness (the irreplaceable data CLV joins against)
    close_files = glob.glob("data/clv/closing/*.json")
    nonempty = 0
    for f in close_files:
        if Path(f).stem[-10:] < cutoff:
            continue
        try:
            b = json.loads(Path(f).read_text().replace("NaN", "null"))
            if isinstance(b, list) and b:
                nonempty += 1
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    if nonempty:
        emit(f"  ✓ Closing capture   {nonempty} non-empty archive(s) in last 2 days")
    else:
        emit(f"  ✗ Closing capture   NONE in last 2 days  ← CLV can't score (capture-closing.yml)")
        issues += 1

    # 5. CLV scoring fresh
    try:
        snaps = json.loads(Path("data/clv/snapshots.json").read_text())
        snaps = snaps.get("snapshots", snaps) if isinstance(snaps, dict) else snaps
        scored = [s for s in snaps if isinstance(s, dict)
                  and (s.get("clv") is not None or s.get("line_clv") is not None)]
        sd = sorted({s.get("date") for s in scored if s.get("date")})
        if sd and sd[-1] >= cutoff:
            emit(f"  ✓ CLV scoring       latest scored {sd[-1]}")
        else:
            emit(f"  ✗ CLV scoring       stale (latest {sd[-1] if sd else 'never'})  ← join not happening")
            issues += 1
    except (json.JSONDecodeError, ValueError, OSError):
        emit(f"  ✗ CLV scoring       snapshots.json unreadable")
        issues += 1

    # 6. Per-market CLV COVERAGE guard — the silent-regression catcher.
    #    Steps 1–5 verify things are PRODUCING; this verifies the join is still
    #    WORKING. A broken join (the UTC date-boundary that dropped every night
    #    game, or the unsigned-spread-line that stopped run-line scoring) keeps
    #    picks flowing and closings capturing while CLV coverage quietly craters —
    #    exactly the failure that went unnoticed for weeks. Measure the scored
    #    fraction over a settled window [today-9 .. today-3] (old enough to have
    #    closed) and go RED if an in-season market falls below the floor.
    COV_FLOOR, COV_MIN_N = 0.40, 10
    win_lo = (today - timedelta(days=9)).isoformat()
    win_hi = (today - timedelta(days=3)).isoformat()
    cov: dict = defaultdict(lambda: [0, 0])
    try:
        _snaps = json.loads(Path("data/clv/snapshots.json").read_text().replace("NaN", "null"))
        _snaps = _snaps.get("snapshots", _snaps) if isinstance(_snaps, dict) else _snaps
    except (json.JSONDecodeError, ValueError, OSError):
        _snaps = []
    for s in _snaps:
        if not isinstance(s, dict):
            continue
        d = str(s.get("date") or "")[:10]
        if not (win_lo <= d <= win_hi):
            continue
        cell = cov[(str(s.get("sport", "")), str(s.get("market", "")))]
        cell[0] += 1
        if (s.get("clv_pct") is not None or s.get("line_clv") is not None
                or s.get("clv") is not None):
            cell[1] += 1
    emit("  CLV coverage (settled window, in-season markets):")
    for label, active_test, sport_test, markets in specs:
        if not active or not active_test(active):
            continue
        for mk in markets:
            tot = scr = 0
            for (sp, m), (t, sc) in cov.items():
                if m == mk and sport_test(sp):
                    tot += t; scr += sc
            if tot < COV_MIN_N:
                continue  # too few settled to judge — no alarm
            frac = scr / tot
            if frac < COV_FLOOR:
                emit(f"    ✗ {label:11} {mk:18} {scr}/{tot} scored "
                      f"({frac*100:.0f}%)  ← CLV join REGRESSED (floor {COV_FLOOR*100:.0f}%)")
                issues += 1
            else:
                emit(f"    ✓ {label:11} {mk:18} {scr}/{tot} scored ({frac*100:.0f}%)")

    # 7. CAPTURE-RATE GATE — is this lane even CAPABLE of being validated?
    #    Sections 1–6 ask whether picks flow and whether the join works on what
    #    was captured. This asks a prior question they both miss: are we archiving
    #    the closing lines at all? A lane at 19% capture (tennis) or 0% (brazil,
    #    korea) can log picks forever and accrue a CLV sample that will never
    #    reach any promotion floor — it looks like patient progress and is
    #    actually a lane quietly disqualifying itself. Delegates to the shared
    #    src.analytics.coverage helpers rather than recomputing the rate here.
    from src.analytics.coverage import (capture_rate as _cap_rate,
                                        canon_sport as _canon,
                                        MIN_CAPTURE_RATE as _CAP_FLOOR)
    #    Measured over a SETTLED window ending CAP_LAG days ago, never one ending
    #    today. Closing lines are captured minutes before first pitch, so today's
    #    and tomorrow's picks legitimately have no close yet — counting them as
    #    misses made healthy lanes look broken (WNBA read 42% purely because 56 of
    #    its 68 "missing" closes were tonight's unplayed games). An alarm that
    #    fires on games that haven't happened yet teaches you to ignore it.
    CAP_DAYS, CAP_MIN_N, CAP_LAG = 14, 10, 3
    cap_end = today - timedelta(days=CAP_LAG)
    cap_lo = (cap_end - timedelta(days=CAP_DAYS)).isoformat()
    cap_hi = cap_end.isoformat()
    sports_seen = sorted({_canon(s.get("sport")) for s in _snaps
                          if isinstance(s, dict) and s.get("sport")
                          and cap_lo <= str(s.get("date") or "")[:10] <= cap_hi})
    emit(f"  Closing-line capture ({CAP_DAYS}d ending {cap_hi}) — "
         f"can these lanes ever be validated?")
    def _all_retired(sport: str) -> bool:
        """True if the registry knows this sport and has retired every lane.

        The gate asks "can this lane ever be validated?", which is only a
        question worth asking about lanes we are still trying to prove. The
        World Cup finished, its lanes were retired 2026-07-30, and it kept
        flagging at 38% capture — an alarm demanding better data collection for
        a tournament that no longer exists. A sport ABSENT from the registry
        still gets gated: those are scanner-discovered leagues (brazil, korea)
        quietly accruing picks, which is exactly what this check is for.
        """
        if not _rstatus:
            return False
        lanes = [(s, m) for (s, m) in _REG if s == sport]
        return bool(lanes) and all(_rstatus(s, m) == "retired" for s, m in lanes)

    for sp in sports_seen:
        if _all_retired(sp):
            continue  # not trying to validate it — nothing to alarm about
        n, closed, rate = _cap_rate(sp, CAP_DAYS, cap_end)
        if n < CAP_MIN_N:
            continue  # too thin to judge — not evidence of a problem
        if rate < _CAP_FLOOR:
            emit(f"    ✗ {sp:<22} {closed:>5}/{n:<5} {rate:>5.0%}  "
                  f"← UN-VALIDATABLE (floor {_CAP_FLOOR:.0%}): picks accruing "
                  f"that CLV can never score")
            issues += 1
        else:
            emit(f"    ✓ {sp:<22} {closed:>5}/{n:<5} {rate:>5.0%}")

    emit(f"  {'─' * 58}")
    if unknown:
        emit(f"  ✗ {len(unknown)} CHECK(S) COULD NOT BE RUN — this is NOT a pass:")
        for u in unknown:
            emit(f"      · {u}")
        emit("    Any ✓ above is unverified. Treat today as UNMONITORED until fixed.")
    if issues:
        emit(f"  ⚠ {issues} INTEGRITY GAP(S) — see ✗ above. Action exits RED on purpose.")
    if not issues and not unknown:
        emit(f"  ✓ ALL GREEN — every in-season market producing, closings + CLV fresh")
    return issues, unknown


def cmd_monitor(args: argparse.Namespace) -> int:
    """Loud data-integrity monitor — exits NON-ZERO on any gap OR blind spot.

    Wraps _monitor_run and turns its findings into an exit code. Non-zero here
    is what turns the GitHub Action red, which is what fires the alert issue.
    """
    issues, unknown = _monitor_run(print)
    return 1 if ((issues or unknown) and not getattr(args, "soft", False)) else 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    """One digest, EVERY day, green or red — so silence becomes the alarm.

    Alarms alone can't be trusted: an alarm that stops firing is indistinguishable
    from a system that's fine, which is precisely how twelve consecutive red days
    read as twelve quiet days. A heartbeat inverts the burden of proof. It arrives
    daily whatever the state, so a missing digest — cron dead, runner broken,
    repo unreachable, credentials expired — is itself the signal, and no positive
    alarm has to survive for you to notice.

    Deliberately dependency-free: it reads the committed record and never calls
    an external API, so it can still report on the day the Odds API is the thing
    that's down. Always exits 0 — the heartbeat reports state, it doesn't judge
    it; `chef.py monitor` is what goes red.
    """
    import json as _json
    from datetime import date as _date, timedelta as _td
    import glob as _glob

    today = _date.today()
    t_iso = today.isoformat()

    # Same checks the alarm runs, so the digest and the alarm can never disagree.
    sink: list[str] = []
    try:
        issues, unknown = _monitor_run(sink.append)
    except Exception as e:                       # a broken check must not
        issues, unknown = 0, [f"monitor itself raised {type(e).__name__}: {e}"]

    try:
        raw = _json.loads(_PNL_FILE.read_text())
        picks = raw if isinstance(raw, list) else raw.get("picks", [])
    except (OSError, ValueError):
        picks = []

    today_all  = [p for p in picks if p.get("date") == t_iso]
    card       = [p for p in picks if p.get("card_pick")]
    today_card = [p for p in card if p.get("date") == t_iso]
    sports_today = sorted({str(p.get("sport", "?")) for p in today_all})

    settled = [p for p in card if p.get("result") in ("win", "loss", "push")]
    w  = sum(1 for p in settled if p.get("result") == "win")
    l  = sum(1 for p in settled if p.get("result") == "loss")
    pu = sum(1 for p in settled if p.get("result") == "push")
    profit = sum((p.get("profit") or 0) for p in settled)
    roi = (profit / len(settled) * 100) if settled else 0.0

    # Ungraded settled picks: the backlog that silently rots the record.
    stale_cut = (today - _td(days=3)).isoformat()
    ungraded = sum(1 for p in picks
                   if not p.get("result") and str(p.get("date") or "") <= stale_cut)

    # Closing capture + CLV freshness, straight off disk.
    todays_files = [f for f in _glob.glob("data/clv/closing/*.json")
                    if Path(f).stem[-10:] == t_iso]
    events = 0
    for f in todays_files:
        try:
            d = _json.loads(Path(f).read_text().replace("NaN", "null"))
            events += len(d) if isinstance(d, list) else 0
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    try:
        snaps = _json.loads(Path("data/clv/snapshots.json").read_text().replace("NaN", "null"))
        snaps = snaps.get("snapshots", snaps) if isinstance(snaps, dict) else snaps
        scored = [s for s in snaps if isinstance(s, dict)
                  and (s.get("clv_pct") is not None or s.get("line_clv") is not None
                       or s.get("clv") is not None)]
        sd = sorted({s.get("date") for s in scored if s.get("date")})
        clv_line = f"latest {sd[-1] if sd else 'never'} · {len(scored)} scored all-time"
    except (json.JSONDecodeError, ValueError, OSError):
        clv_line = "snapshots.json UNREADABLE"

    try:
        from src.config.models import MODELS, is_live
        n_live = sum(1 for (s, m) in MODELS if is_live(s, m))
        lanes_line = f"{n_live} live · {len(MODELS) - n_live} not live"
    except Exception:
        lanes_line = "registry unreadable"

    # The un-validatable lanes the capture gate found, pulled from the same run.
    unval = [ln.strip().split()[1] for ln in sink if "UN-VALIDATABLE" in ln]

    if unknown:
        state = f"🟡 UNVERIFIED — {len(unknown)} check(s) could not run"
    elif issues:
        state = f"🔴 RED — {issues} integrity gap(s)"
    else:
        state = "🟢 GREEN — all checks passed"

    line = "═" * 64
    print(f"\n  {line}")
    print(f"  📟 OVERLAY HEARTBEAT — {today:%A %b %d, %Y}")
    print(f"  {line}")
    print(f"  STATE      {state}")
    print(f"  PIPELINE   {len(today_all)} pick(s) today across {len(sports_today)} sport(s)")
    print(f"  CARD       {len(today_card)} today · record {w}-{l}-{pu}  "
          f"{profit:+.1f}u ({roi:+.1f}% ROI)")
    print(f"  CAPTURE    {events} event(s) archived today in {len(todays_files)} file(s)")
    print(f"  CLV        {clv_line}")
    print(f"  GRADING    {ungraded} pick(s) unsettled and older than 3d")
    print(f"  LANES      {lanes_line}")
    if unval:
        print(f"  BLOCKED    un-validatable (capture < 60%): {' · '.join(unval)}")
    for u in unknown:
        print(f"  ⚠ UNKNOWN  {u}")
    if issues:
        # Only the findings themselves ("← reason" marks a real gap), never the
        # monitor's own tallies — echoing those back would pad the digest with
        # counts of the very list being printed.
        detail = [ln.strip() for ln in sink
                  if "←" in ln and "UN-VALIDATABLE" not in ln]
        if detail:
            print("  " + "─" * 62)
            for ln in detail:
                print(f"  {ln}")
    print("  " + "─" * 62)
    print("  This digest is sent EVERY day, green or red. If a day passes with")
    print("  no digest, the pipeline itself is down — that silence IS the alarm.")
    print(f"  {line}\n")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Trigger core workflows in the cloud on-demand and report pass/fail.

    The whole point: confirm a change actually works in the cloud in ~2-5 min,
    instead of waiting for the overnight cron to find out tomorrow. Dispatches
    each workflow, waits for it to finish, and prints ✓/✗ per workflow.
    """
    import subprocess, time

    wfs = (args.workflows.split(",") if getattr(args, "workflows", None)
           else ["monitor.yml", "night.yml", "clv.yml"])

    def gh(*a):
        return subprocess.run(["gh", *a], capture_output=True, text=True)

    if gh("auth", "status").returncode != 0:
        print("  ✗ gh not authenticated — run `gh auth login` first.")
        return 1

    print(f"\n  ─ Verify (cloud) — dispatching {len(wfs)} workflow(s) ─────────────")
    started: dict = {}
    for wf in wfs:
        before = gh("run", "list", "--workflow", wf, "--limit", "1",
                    "--json", "databaseId", "-q", ".[0].databaseId").stdout.strip()
        if gh("workflow", "run", wf).returncode != 0:
            print(f"    ✗ {wf}: dispatch failed (does it have workflow_dispatch?)")
            started[wf] = None
            continue
        rid = None
        for _ in range(15):
            time.sleep(4)
            cur = gh("run", "list", "--workflow", wf, "--limit", "1",
                     "--json", "databaseId", "-q", ".[0].databaseId").stdout.strip()
            if cur and cur != before:
                rid = cur
                break
        started[wf] = rid
        print(f"    → {wf:22} dispatched (run {rid or '?'})")

    print(f"  ─ waiting for completion ──────────────────────────────────")
    issues = 0
    for wf, rid in started.items():
        if not rid:
            print(f"    ✗ {wf:22} never started")
            issues += 1
            continue
        concl = None
        for _ in range(72):  # ~6 min cap per workflow
            if gh("run", "view", rid, "--json", "status",
                  "-q", ".status").stdout.strip() == "completed":
                concl = gh("run", "view", rid, "--json", "conclusion",
                           "-q", ".conclusion").stdout.strip()
                break
            time.sleep(5)
        ok = concl == "success"
        if not ok:
            issues += 1
        print(f"    {'✓' if ok else '✗'} {wf:22} {concl or 'TIMEOUT (still running)'}")

    print(f"  {'─' * 58}")
    print(f"  {'✓ all core workflows GREEN in the cloud' if not issues else f'✗ {issues} workflow(s) failed — gh run view <id> --log'}")
    return 1 if issues else 0


def _clv_gate(min_n: int = 200):
    """Delegates to src.analytics.clv_gate.clv_gate (extracted for reuse)."""
    from src.analytics.clv_gate import clv_gate
    return clv_gate(min_n)


def cmd_edge(args: argparse.Namespace) -> int:
    """Statistical promotion gate — is a market's CLV a real edge or just noise?

    For each market: a t-test of mean CLV vs 0, a minimum-sample floor, and a
    multiple-comparisons (Bonferroni) correction — because testing ~12 markets,
    one WILL look good by chance. A market is an EDGE CANDIDATE only if it clears
    all three AND still holds up on the last 30 days. Candidates must then persist
    out-of-sample before betting real money — this flags them, it doesn't bless them.

    CLV here is measured against a late-pre-game line (the wide capture band), so
    it's conservative: a positive result understates the true edge.
    """
    from src.config.models import model_status

    min_n = getattr(args, "min_n", None) or 200
    res = _clv_gate(min_n)
    if res is None:
        print("  ✗ snapshots.json unreadable")
        return 1
    rows, meta = res

    print(f"\n  ─ CLV Promotion Gate ─ min n={meta['min_n']}, α={meta['alpha']:.4f} "
          f"(Bonferroni ÷{meta['m_tests']}) ─")
    print(f"  best = CLV vs best price (flatters us) · sharp = CLV vs Pinnacle close (the truth)")
    print(f"  {'sport · market':24}{'n':>5}{'best':>9}{'beat%':>7}"
          f"{'sharp':>9}{'beat%':>7}{'p(>0)':>8}  verdict")
    print(f"  {'─'*84}")
    candidates = []
    mirages = []
    for r in rows:
        if r["is_candidate"]:
            candidates.append(r)
        pstr = f"{r['p_pos']:.4f}" if r["p_pos"] is not None else "—"
        bstr = f"{r['beat_pct']:.0f}%" if r["beat_pct"] is not None else "—"
        if r.get("sharp_n"):
            sm = f"{r['sharp_mean']:+.2f}{r['unit']}"
            sb = f"{r['sharp_beat_pct']:.0f}%"
        else:
            sm, sb = "—", "—"
        # Mirage = positive vs best price but negative vs the sharp close: the
        # "edge" is just us shopping the loosest book, not beating the market.
        if (r.get("sharp_n") and r["mean"] > 0 and r["sharp_mean"] is not None
                and r["sharp_mean"] < 0):
            mirages.append(r)
        print(f"  {r['label'][:24]:24}{r['n']:>5}{r['mean']:>+8.2f}{r['unit']:<1}"
              f"{bstr:>7}{sm:>9}{sb:>7}{pstr:>8}  {r['verdict']}")

    print(f"  {'─'*84}")
    if mirages:
        print(f"  ⚠ best-price mirage (positive vs best, NEGATIVE vs Pinnacle close): "
              f"{', '.join(m['label'] for m in mirages)}")
        print(f"     These don't beat the sharp market — the 'edge' is book-shopping, not skill.")
    if candidates:
        print(f"  ✅ {len(candidates)} edge candidate(s): "
              f"{', '.join(c['label'] for c in candidates)}")
        # Flag what's eligible for promotion vs already live (manual-approval model).
        for c in candidates:
            if model_status(c["sport"], c["market"]) == "live":
                print(f"     • {c['label']}: already LIVE (posting card picks)")
            else:
                print(f"     • {c['label']}: ELIGIBLE → run "
                      f"`python3 chef.py promote {c['sport']} {c['market']}` to post it")
        print(f"     Promotion is your call — each must also hold positive CLV on NEW")
        print(f"     picks logged AFTER today. This flags; it doesn't bless.")
    else:
        print(f"  No market clears the bar yet — keep collecting. (More data, not more bets.)")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Promote a market to live card picks — REFUSES unless it clears the CLV gate.

    Manual, deliberate, auditable: the same gate `chef.py edge` uses decides
    eligibility; this records the flip in data/models/promotions.json (git-tracked).
    """
    from datetime import datetime, timezone
    from src.config.models import _key, model_status, model_label, set_promotion

    s_label, mkt = _key(args.sport, args.market)
    res = _clv_gate(getattr(args, "min_n", None) or 200)
    if res is None:
        print("  ✗ snapshots.json unreadable")
        return 1
    rows, meta = res
    match = next((r for r in rows if r["sport"] == s_label and r["market"] == mkt), None)

    print(f"\n  ─ Promote {s_label} · {mkt} ─ ({model_label(args.sport, args.market)}) ─")
    if model_status(args.sport, args.market) == "live":
        print(f"  ℹ  Already LIVE — nothing to do.")
        return 0
    if match is None:
        print(f"  ✗ REFUSED — no CLV-scored picks for {s_label} · {mkt} yet. Can't confirm an edge.")
        return 1
    if not match["is_candidate"]:
        need = meta["min_n"]
        extra = f" (have {match['n']}, need {need})" if match["n"] < need else \
                f" (n={match['n']}, mean {match['mean']:+.3f}{match['unit']}, p={match['p_pos']:.4f} ≥ α={meta['alpha']:.4f})"
        print(f"  ✗ REFUSED — {match['verdict']}{extra}.")
        print(f"     The CLV gate is not satisfied. Keep collecting; do not bet.")
        return 1

    tier = getattr(args, "tier", None) or "t2"
    set_promotion(args.sport, args.market, "live", tier, evidence={
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "clv_n": match["n"], "clv_mean": round(match["mean"], 4),
        "clv_unit": match["unit"],
        "clv_p": round(match["p_pos"], 4) if match["p_pos"] is not None else None,
        "clv_30d": round(match["rmean"], 4) if match["rmean"] is not None else None,
    })
    r30 = f"{match['rmean']:+.3f}" if match["rmean"] is not None else "—"
    print(f"  ✅ PROMOTED → live (tier {tier}). New {s_label} {mkt} picks meeting the")
    print(f"     edge threshold will now post as card picks (card_pick=True).")
    print(f"     Evidence: n={match['n']}, mean CLV {match['mean']:+.3f}{match['unit']}, "
          f"p(>0)={match['p_pos']:.4f}, 30d {r30}")
    print(f"     Revert anytime: `python3 chef.py demote {s_label} {mkt}`")
    return 0


def cmd_demote(args: argparse.Namespace) -> int:
    """Demote a market back to shadow (incubating) — undo a promotion."""
    from src.config.models import _key, set_promotion
    s_label, mkt = _key(args.sport, args.market)
    set_promotion(args.sport, args.market, "incubating", "shadow")
    print(f"\n  ↩  Demoted {s_label} · {mkt} → incubating (shadow). New picks log as shadow.")
    return 0


def cmd_retire(args: argparse.Namespace) -> int:
    """Retire a lane: stop running it at all, and record WHY.

    Distinct from demote, which returns a lane to shadow so it keeps logging and
    can still earn promotion. Retirement is the verdict that there is nothing to
    earn — is_retired() drops the lane from the factory sweep entirely, so it
    stops consuming API credits and stops adding rows nobody will ever bet.

    The reason is mandatory. A retirement with no evidence is indistinguishable
    from someone quietly deleting an inconvenient model, and in six months the
    only question anyone asks is "why did we kill this?".
    """
    from src.config.models import _key, set_promotion, model_status

    reason = (getattr(args, "reason", None) or "").strip()
    if not reason:
        print("  Refusing to retire without --reason. Record the evidence.")
        return 1

    s_label, mkt = _key(args.sport, args.market)
    before = model_status(args.sport, args.market)
    set_promotion(args.sport, args.market, "retired", "shadow",
                  evidence={"reason": reason,
                            "retired_on": datetime.now().strftime("%Y-%m-%d"),
                            "previous_status": before})
    print(f"\n  ⛔  Retired {s_label} · {mkt}  (was {before})")
    print(f"      {reason}")
    print(f"      Reversible: chef.py demote {s_label} {mkt}\n")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Bet-tracking completeness audit — guarantees we never silently lose a bet's
    closing line / CLV / EV / odds / ROI.

    Odds, model prob/EV, result and profit we compute ourselves (should be 100%).
    The closing line (→ CLV) must be CAPTURED at game time, so it's the only field
    that can leak. This reports per-field coverage + the headline metrics, then
    lists any recently-settled card bet MISSING its closing line and exits non-zero
    (RED) so the gap can never slip by silently. Wire into a daily workflow.
    """
    from datetime import date as _date, timedelta
    days = getattr(args, "days", None) or 21
    cutoff = (_date.today() - timedelta(days=days)).isoformat()
    try:
        picks = json.loads(Path("data/pnl/picks.json").read_text())
        picks = picks if isinstance(picks, list) else picks.get("picks", [])
    except (json.JSONDecodeError, ValueError, OSError):
        print("  ✗ picks.json unreadable"); return 1
    try:
        snaps = json.loads(Path("data/clv/snapshots.json").read_text())
        snaps = snaps.get("snapshots", snaps) if isinstance(snaps, dict) else snaps
    except (json.JSONDecodeError, ValueError, OSError):
        snaps = []

    clv = {}
    for s in snaps:
        if isinstance(s, dict):
            clv[(str(s.get("date", ""))[:10], str(s.get("team", "")).lower(), s.get("market"))] = s

    def _snap(p):
        return clv.get((str(p.get("date", ""))[:10], str(p.get("team", "")).lower(), p.get("market")))

    def scored(p):
        """Closing line captured + CLV computed — prob markets use clv_pct, line
        markets (totals/spreads) use line_clv. Either counts as tracked."""
        s = _snap(p)
        return bool(s and (s.get("clv_pct") is not None or s.get("line_clv") is not None))

    def pct_clv(p):
        """Probability CLV only (moneyline-type) — safe to average (line CLV is in
        points, can't be pooled with %)."""
        s = _snap(p)
        return s.get("clv_pct") if s else None

    def ev(p):
        mp, o = p.get("model_prob"), p.get("odds")
        if mp is None or o is None:
            return None
        o = float(o); dec = (o / 100) if o > 0 else (100 / abs(o))
        return float(mp) * dec - (1 - float(mp))

    card    = [p for p in picks if p.get("card_pick")]
    settled = [p for p in card if p.get("result") in ("win", "loss", "push")]
    staked  = [p for p in settled if p["result"] in ("win", "loss")]
    if not card:
        print("  No card picks to audit."); return 0

    def cov(cond, pool):
        n = sum(1 for p in pool if cond(p))
        return f"{n}/{len(pool)} ({100*n/len(pool):.0f}%)" if pool else "0/0"

    print(f"\n  ─ Bet-Tracking Audit ─ {len(card)} card picks, {len(settled)} settled ─")
    print(f"    odds entered      {cov(lambda p: p.get('odds') is not None, card)}")
    print(f"    model prob / EV   {cov(lambda p: p.get('model_prob') is not None, card)}")
    print(f"    result + profit   {cov(lambda p: p.get('profit') is not None, settled)}")
    print(f"    closing line+CLV  {cov(scored, settled)}   ← capture-dependent")

    # Average odds the RIGHT way: American odds are non-linear (+150 and −150
    # aren't symmetric), so a raw arithmetic mean is meaningless. Average in
    # implied-probability space, then convert the mean back to American.
    def _am_imp(o):
        o = float(o); return 100/(o+100) if o > 0 else abs(o)/(abs(o)+100)
    def _imp_am(p):
        return -round(p/(1-p)*100) if p >= 0.5 else round((1-p)/p*100)
    imps = [_am_imp(p["odds"]) for p in card if p.get("odds") is not None]
    evs  = [ev(p) for p in card]; evs = [e for e in evs if e is not None]
    clvs = [pct_clv(p) for p in settled if pct_clv(p) is not None]
    prof = sum(float(p.get("profit") or 0) for p in staked)
    w    = sum(1 for p in staked if p["result"] == "win")
    if imps:
        ai = sum(imps)/len(imps)
        print(f"\n    avg odds entered  {_imp_am(ai):+d}  ({ai*100:.1f}% implied)")
    else:
        print("\n    avg odds entered  —")
    print(f"    avg model EV/bet  {100*sum(evs)/len(evs):+.1f}%" if evs else "    avg model EV/bet  —")
    print(f"    avg CLV (ML-type) {sum(clvs)/len(clvs):+.2f}%  (n={len(clvs)})" if clvs else "    avg CLV (ML-type) none")
    if staked:
        print(f"    record / ROI      {w}-{len(staked)-w}  {prof:+.2f}u  ({100*prof/len(staked):+.1f}%)")

    gaps = [p for p in settled if not scored(p) and str(p.get("date", ""))[:10] >= cutoff]
    print(f"\n    {'⚠' if gaps else '✓'} recent settled card bets (≤{days}d) missing closing/CLV: {len(gaps)}")
    for p in gaps[:20]:
        print(f"       {str(p.get('date',''))[:10]} {str(p.get('sport',''))[:5]:5s} "
              f"{str(p.get('market',''))[:10]:10s} {str(p.get('team',''))[:22]}")
    if gaps:
        print(f"    → closing-line capture missed these. Action exits RED on purpose.")
        return 1
    print(f"    → every recent settled bet has its closing line + CLV. Tracking intact.")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Refit every sport×market calibrator from settled results.

    The models already de-bias their probabilities through apply_calibration()
    (per-market .pkl calibrators), but those were stale — never refit as new
    results arrived — which is why `validate` still flagged props as
    overconfident. This re-fits them all (Platt for props/small samples, isotonic
    for large game-line datasets) from the current pnl. Every model that calls
    apply_calibration() picks up the fresh calibrators automatically.
    """
    from src.analytics.calibration import recalibrate_all
    min_picks = getattr(args, "min_n", None) or 30
    results = recalibrate_all(min_picks=min_picks, verbose=True)
    if not results:
        print("  No market had enough settled picks to (re)calibrate.")
        return 0
    print(f"\n  ─ Recalibrated {len(results)} market(s) ─ run `chef.py validate` to confirm")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Model validation harness — outcome calibration per (sport, market).

    Complements `edge` (which measures CLV vs the close) with a settled-results
    check: does the model's stated probability match how often picks actually hit?
    For each market with graded picks it reports n, the model's mean stated prob,
    the actual hit rate, the Brier score, and a calibration verdict. A model whose
    hit rate is far below its stated prob is OVERCONFIDENT (its edges are inflated)
    — exactly the failure that makes raw EV untrustworthy.
    """
    import statistics
    from collections import defaultdict

    try:
        raw = json.loads(Path("data/pnl/picks.json").read_text())
        picks = raw["picks"] if isinstance(raw, dict) and "picks" in raw else raw
    except (json.JSONDecodeError, ValueError, OSError):
        print("  ✗ picks.json unreadable")
        return 1

    # group graded picks (win/loss; skip push/void) by (sport, market)
    by: dict = defaultdict(list)
    for p in picks:
        if not isinstance(p, dict):
            continue
        res = str(p.get("result") or "").lower()
        mp = p.get("model_prob")
        if res not in ("win", "loss") or mp is None:
            continue
        try:
            mp = float(mp)
        except (ValueError, TypeError):
            continue
        if not 0.0 < mp < 1.0:
            continue
        by[(p.get("sport", "?"), p.get("market", "?"))].append((mp, 1 if res == "win" else 0))

    from src.config.models import is_live as _is_live
    min_n = getattr(args, "min_n", None) or 20
    print(f"\n  ─ Model Validation — outcome calibration (min n={min_n}) ─────────")
    print(f"  {'sport · market':26}{'n':>5}{'stated':>8}{'actual':>8}{'Brier':>8}  verdict")
    print(f"  {'─'*74}")
    flagged = 0
    live_overconfident = []  # LIVE markets that are overconfident — the real alarm
    rows = sorted(by.items(), key=lambda kv: -len(kv[1]))
    for (sport, market), obs in rows:
        n = len(obs)
        if n < min_n:
            continue
        stated = statistics.fmean(p for p, _ in obs)
        actual = statistics.fmean(o for _, o in obs)
        brier = statistics.fmean((p - o) ** 2 for p, o in obs)
        gap = actual - stated
        # Standard error of a proportion → is the gap beyond noise?
        se = (actual * (1 - actual) / n) ** 0.5 if 0 < actual < 1 else 0.0
        if gap < -2 * se and abs(gap) > 0.03:
            live = _is_live(sport, market)
            verdict = f"⚠ OVERCONFIDENT ({gap*100:+.0f}pt)" + ("  [LIVE!]" if live else "")
            flagged += 1
            if live:
                live_overconfident.append(f"{sport}·{market} ({gap*100:+.0f}pt)")
        elif gap > 2 * se and abs(gap) > 0.03:
            verdict = f"underconfident ({gap*100:+.0f}pt)"
        else:
            verdict = "✓ calibrated"
        print(f"  {f'{sport} · {market}'[:26]:26}{n:>5}{stated*100:>7.1f}%{actual*100:>7.1f}%{brier:>8.3f}  {verdict}")

    print(f"  {'─'*74}")
    tested = sum(1 for _, o in rows if len(o) >= min_n)
    if flagged:
        print(f"  ⚠ {flagged} market(s) OVERCONFIDENT — stated edge inflated, trust CLV not EV.")
    print(f"  {tested} market(s) had >= {min_n} graded picks. Markets below the floor are")
    print(f"  awaiting results (props/spreads just started — check back as they settle).")
    # --gate: fail (exit red) only if a LIVE market is overconfident. Incubating
    # markets being overconfident is expected (they're shadow) — not an alarm.
    if getattr(args, "gate", False) and live_overconfident:
        print(f"\n  🔴 GATE FAILED — LIVE market(s) overconfident: {', '.join(live_overconfident)}")
        print("     A market you're BETTING is miscalibrated. Demote or fix it.")
        return 1
    return 0


def cmd_strategies(args: argparse.Namespace) -> int:
    """Shadow strategies — research-rule picks logged (never bet) and measured by
    CLV against the close. Proves which edges beat the market before risking money.
    """
    from src.analytics.clv_tracker import print_clv_by_strategy

    if not getattr(args, "report", False):
        from src.strategies.shadow_strategies import log_shadow_strategies, STRATEGIES
        date_str = None
        if getattr(args, "date", None):
            d = args.date
            date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d
        n = log_shadow_strategies(date_str=date_str)
        print(f"  Logged {n} shadow strategy pick(s) across {len(STRATEGIES)} strategy(ies).")

    print_clv_by_strategy()
    return 0


def cmd_polydash(args: argparse.Namespace) -> int:
    """One screen for the Polymarket pilot: today's board, open exposure,
    fills, CLV, paper P&L, and entry timing."""
    import importlib
    dash = importlib.import_module("scripts.polymarket_dashboard")
    dash.run(eff_date=getattr(args, "date", None),
             as_json=getattr(args, "as_json", False))
    return 0


def cmd_polyready(args: argparse.Namespace) -> int:
    """Is the Polymarket experiment finished, and what did it conclude?

    Grades the run against gates fixed in advance (polymarket_protocol.py):
    sample size, anchor calibration, fill count, CLV, drawdown. Returns
    WAIT / RETIRE / PROMOTE. A RETIRE is a success — it closes the idea off
    at zero cost.
    """
    import importlib
    r = importlib.import_module("scripts.polymarket_readiness")
    r.run(as_json=getattr(args, "as_json", False))
    return 0


def cmd_polytiming(args: argparse.Namespace) -> int:
    """When is Polymarket actually mispriced? Replays played games to show how
    much price discovery is left at each lead time before kickoff."""
    import importlib
    t = importlib.import_module("scripts.polymarket_timing")
    t.run(since=getattr(args, "since", None),
          as_json=getattr(args, "as_json", False))
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    """Paper-trading ledger for the Polymarket pilot — the $112 without the $112.

    Replays every logged polymarket_ev pick at its recorded fill price and
    settles it against the real result. Taker rows simulate faithfully; maker
    rows only count when polymarket_fills judged the resting order hit.
    """
    import importlib
    paper = importlib.import_module("scripts.paper_trader")
    paper.run(bankroll=getattr(args, "bankroll", 112.0),
              mode=getattr(args, "mode", None),
              as_json=getattr(args, "as_json", False))
    return 0


def cmd_polyfills(args: argparse.Namespace) -> int:
    """Maker fill + adverse-selection report for logged polymarket_ev picks.

    The scanner's maker prices are only achievable if the resting orders fill,
    and fills that arrive because the counterparty knew something are worse
    than no fill at all. This replays the price history to measure both.
    """
    import importlib
    fills = importlib.import_module("scripts.polymarket_fills")
    fills.run(since=getattr(args, "since", None),
              as_json=getattr(args, "as_json", False))
    return 0


def cmd_polymarket(args: argparse.Namespace) -> int:
    """Polymarket-vs-Pinnacle price scanner — shadow strategy polymarket_ev.
    Finds Polymarket win contracts priced under Pinnacle's devigged fair and
    logs them as shadow picks. Prices a RESTING order inside the bid by
    default (no fee — sports_fees_v2 is takerOnly); crossing the spread is
    negative on nearly every board. See chef.py polyfills for whether those
    resting orders would actually have filled."""
    import importlib
    scanner = importlib.import_module("scripts.polymarket_scanner")
    date_str = None
    if getattr(args, "date", None):
        d = args.date
        date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d
    scanner.run(
        date_str=date_str,
        min_ev=getattr(args, "min_ev", 2.0),
        bankroll=getattr(args, "bankroll", 112.0),
        dry_run=getattr(args, "dry_run", False),
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Refresh public_stats.json from current picks.json."""
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
        return 0
    except Exception as e:
        print(f"  Error: {e}")
        return 1


# ─────────────────────────── monthly ─────────────────────────────────────────

def cmd_monthly(args: argparse.Namespace) -> int:
    """Generate monthly performance report."""
    month_arg = getattr(args, "month", None)
    cmd = [sys.executable, "scripts/gen_monthly_brief.py"]
    if month_arg:
        cmd.append(month_arg)
    return _run(cmd)


# ─────────────────────────── morning ───────────────────────────────────────

def cmd_morning(args: argparse.Namespace) -> int:
    """Run full morning pipeline: MLB + NBA + Tennis + Soccer + PGA + NHL picks."""
    import platform

    today = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    banner_date = datetime.strptime(today, "%Y%m%d").strftime("%B %d, %Y")
    sep = "═" * 60
    print(f"\n  {sep}")
    print(f"  Overlay — MORNING PIPELINE — {banner_date}  (folder {today})")
    print(f"  {sep}\n")

    # 1) MLB picks + cards
    print("  ▸ Generating MLB picks + cards...")
    mlb_cmd = [sys.executable, "predict.py", "--daily", "--sport", "mlb"]
    if getattr(args, "date", None):
        mlb_cmd += ["--date", args.date]
    rc = _run(mlb_cmd)
    if rc != 0:
        print("  ✗ MLB picks failed")
        return rc
    print("  ✓ MLB picks done\n")

    # 2) NBA picks + cards
    print("  ▸ Generating NBA picks + cards...")
    nba_cmd = [sys.executable, "run_nba.py"]
    if getattr(args, "date", None):
        nba_cmd += ["--date", args.date]
    rc = _run(nba_cmd)
    if rc != 0:
        print(f"  ✗ NBA picks failed (may be off-season)")
    else:
        print("  ✓ NBA picks done\n")

    # 3) WNBA picks (season May–Oct; silently skip if off-season)
    print("  ▸ Generating WNBA picks...")
    wnba_cmd = [sys.executable, "run_wnba.py"]
    if getattr(args, "date", None):
        wnba_cmd += ["--date", args.date]
    rc_wnba = _run(wnba_cmd)
    if rc_wnba != 0:
        print("  ✗ WNBA picks failed (may be off-season or no games today)")
    else:
        print("  ✓ WNBA picks done\n")

    # 4) Tennis picks (runs year-round; silently skip if no active tournament)
    print("  ▸ Generating Tennis picks...")
    tennis_cmd = [sys.executable, "run_tennis.py"]
    if getattr(args, "date", None):
        tennis_cmd += ["--date", args.date]
    rc_tennis = _run(tennis_cmd)
    if rc_tennis != 0:
        print("  ✗ Tennis picks failed (no active tournament or API miss)")
    else:
        print("  ✓ Tennis picks done\n")

    # 4b) June Challenge — auto-select bet of day and generate morning card
    print("  ▸ June Challenge — generating Bet of the Day card...")
    try:
        from src.output.june_challenge_card import (
            load_state, save_state, register_bet,
            generate_morning_card, get_todays_bet,
        )
        import json as _jc_json
        from pathlib import Path as _P
        _jc_state  = load_state()
        _jc_today  = datetime.strptime(today, "%Y%m%d").strftime("%Y-%m-%d")
        _jc_day    = len([b for b in _jc_state.get("bets", [])
                          if b.get("date", "") <= _jc_today]) + 1
        if not get_todays_bet(_jc_state, _jc_today):
            # Auto-select: highest-edge card pick from VALIDATED sports only.
            # WNBA, soccer, NASCAR, PGA are shadow/incubating — excluded.
            _VALIDATED_SPORTS = {
                "baseball_mlb",
                "basketball_nba",
                "icehockey_nhl",
                "tennis_atp_french_open",
                "tennis_wta_french_open",
                "tennis_atp_roland_garros",
            }
            # Priority: profitable markets only (avoid F5/NRFI which are losing)
            _SKIP_MARKETS = {"f5_total", "nrfi"}
            _jc_best = None
            _jc_best_sport = None
            _picks_root = _P("output/picks")
            for _sport_dir in sorted(_picks_root.iterdir()):
                if not _sport_dir.is_dir():
                    continue
                # Only consider validated sports
                if _sport_dir.name not in _VALIDATED_SPORTS:
                    continue
                _pf = _sport_dir / today / "picks.json"
                if not _pf.exists():
                    continue
                try:
                    _tp = _jc_json.loads(_pf.read_text())
                    _tp = _tp if isinstance(_tp, list) else _tp.get("picks", [])
                    for _p in _tp:
                        # Skip bad markets
                        if (_p.get("market") or _p.get("Market") or "").lower() in _SKIP_MARKETS:
                            continue
                        # Skip shadow picks (CardPick explicitly False)
                        if _p.get("CardPick") is False or _p.get("card_pick") is False:
                            continue
                        _e = float(_p.get("edge_pct") or _p.get("Edge") or _p.get("edge") or 0)
                        if _e < 8:  # minimum edge threshold
                            continue
                        if _jc_best is None or _e > float(
                                _jc_best.get("edge_pct") or _jc_best.get("Edge") or 0):
                            _jc_best = dict(_p)
                            _jc_best_sport = _sport_dir.name
                except Exception:
                    pass

            if _jc_best:
                _sp = _jc_best_sport or ""
                # Normalise field names across different pick formats
                _team  = (_jc_best.get("team") or _jc_best.get("Team") or
                          _jc_best.get("player") or "")
                _opp   = (_jc_best.get("opponent") or _jc_best.get("Opponent") or
                          _jc_best.get("matchup") or _jc_best.get("Matchup") or "")
                _odds  = int(float(_jc_best.get("odds") or _jc_best.get("BestOdds") or -110))
                _edge  = float(_jc_best.get("edge_pct") or _jc_best.get("Edge") or 0)
                _mprob = float(_jc_best.get("model_prob") or _jc_best.get("ModelProb") or 0)
                _iprob = float(_jc_best.get("market_prob") or _jc_best.get("implied_prob") or
                               _jc_best.get("ImpliedProb") or 0)
                _book  = (_jc_best.get("sportsbook") or _jc_best.get("Sportsbook") or "")
                _mkt   = (_jc_best.get("market") or _jc_best.get("Market") or "moneyline").lower()
                # Sport display labels
                _tour  = (_jc_best.get("tournament") or
                          {"tennis_atp_french_open": "Roland-Garros",
                           "baseball_mlb": "MLB", "basketball_nba": "NBA",
                           "icehockey_nhl": "NHL", "basketball_wnba": "WNBA"
                           }.get(_sp, _sp.replace("_", " ").title()))
                _surf  = _jc_best.get("surface") or ""

                _jc_bet = {
                    "date":            _jc_today,
                    "day":             _jc_day,
                    "player":          _team,
                    "opponent":        _opp,
                    "tournament":      _tour,
                    "surface":         _surf,
                    "sport":           _sp,
                    "market":          _mkt,
                    "odds":            _odds,
                    "edge":            _edge,
                    "model_prob":      _mprob,
                    "market_prob":     _iprob,
                    "book":            _book,
                    "unit":            _jc_state.get("unit", 20.0),
                    "bankroll_before": _jc_state.get("bankroll", 200.0),
                    "result":          None,
                }
                _jc_state  = register_bet(_jc_state, _jc_bet)
                save_state(_jc_state)
                _card_path = generate_morning_card(_jc_bet)
                if _card_path:
                    print(f"  ✓ June Challenge card → {_card_path}")
                    print(f"     Bet: {_team} ({_tour}) {_odds:+d} @ {_book}  edge={_edge:.1f}%")
                else:
                    print("  ✗ June Challenge card render failed")
            else:
                print("  ✗ No qualifying picks found for June Challenge card (need edge > 8%)")
        else:
            print(f"  ✓ June Challenge bet already registered for {_jc_today}")
    except Exception as _jc_err:
        print(f"  ✗ June Challenge card skipped: {_jc_err}")

    # 5) Soccer picks (EPL/La Liga/Bundesliga/Serie A/Ligue 1 club leagues + tournaments)
    print("  ▸ Generating Soccer picks...")
    soccer_cmd = [sys.executable, "run_soccer.py"]
    if getattr(args, "date", None):
        soccer_cmd += ["--date", args.date]
    rc_soccer = _run(soccer_cmd)
    if rc_soccer != 0:
        print("  ✗ Soccer picks failed (no games today or off-season)")
    else:
        print("  ✓ Soccer picks done\n")

    # 6) PGA picks (silently skips when no active major; runs Thu–Sun during events)
    print("  ▸ Generating PGA picks...")
    pga_cmd = [sys.executable, "run_pga.py"]
    rc_pga = _run(pga_cmd)
    if rc_pga != 0:
        print("  ✗ PGA picks skipped (no active major or no odds available)")
    else:
        print("  ✓ PGA picks done\n")

    # 7) NHL picks (live during playoffs/season; skips in off-season)
    print("  ▸ Generating NHL picks...")
    nhl_cmd = [sys.executable, "run_nhl.py"]
    if getattr(args, "date", None):
        nhl_cmd += ["--date", args.date]
    rc_nhl = _run(nhl_cmd)
    if rc_nhl != 0:
        print("  ✗ NHL picks skipped (off-season or no games today)")
    else:
        print("  ✓ NHL picks done\n")

    # 7b) NHL player props (shadow — building sample)
    print("  ▸ Generating NHL player props...")
    nhl_props_cmd = [sys.executable, "run_nhl_props.py"]
    if getattr(args, "date", None):
        nhl_props_cmd += ["--date", args.date]
    rc_nhl_props = _run(nhl_props_cmd)
    if rc_nhl_props != 0:
        print("  ✗ NHL props skipped (no games or API unavailable)")
    else:
        print("  ✓ NHL props done\n")

    # 8) MLB player props (pitcher Ks + batter HR/RBI/Total Bases/Hits)
    print("  ▸ Generating MLB player props + cards...")
    mlb_props_cmd = [sys.executable, "run_mlb_props.py"]
    if getattr(args, "date", None):
        mlb_props_cmd += ["--date", args.date]
    rc_mlb_props = _run(mlb_props_cmd)
    if rc_mlb_props != 0:
        print("  ✗ MLB props skipped (API unavailable or no games today)")
    else:
        print("  ✓ MLB props + batter cards done\n")

    # 9) Generate Reddit posts
    print("  ▸ Generating Reddit posts...")
    try:
        reddit_args = argparse.Namespace(date=today)
        cmd_reddit(reddit_args)
        print("  ✓ Reddit posts ready\n")
    except Exception as e:
        print(f"  ✗ Reddit generation failed: {e}\n")

    # 10) Show where cards are
    mlb_dir = Path(f"output/picks/baseball_mlb/{today}")
    nba_dir = Path(f"output/picks/basketball_nba/{today}")

    print(f"\n  {sep}")
    print(f"  CARDS READY — post to IG / X / TikTok:")
    print(f"  {'─'*58}")
    if mlb_dir.exists():
        for f in sorted(mlb_dir.glob("*.png")):
            print(f"    MLB  {f.name}")
    if nba_dir.exists():
        for f in sorted(nba_dir.glob("*.png")):
            print(f"    NBA  {f.name}")
    print(f"  {'─'*58}")
    print(f"  Captions in same folders (caption_*.txt)")
    print(f"  {sep}\n")

    # 11) Open cards folder on macOS
    if platform.system() == "Darwin" and mlb_dir.exists():
        subprocess.run(["open", str(mlb_dir)], check=False)

    # 12) Show Reddit posts location
    reddit_dir = Path(f"output/reddit")
    reddit_posts = sorted(reddit_dir.glob(f"{today}_*.md")) if reddit_dir.exists() else []
    if reddit_posts:
        print(f"  REDDIT POSTS — copy-paste to r/sportsbook megathread:")
        print(f"  {'─'*58}")
        for f in reddit_posts:
            print(f"    {f.name}")
        print(f"  {'─'*58}\n")

    # 13) Generate today's talking-head scripts (PICKS + EDUCATION)
    print("  ▸ Generating talking-head scripts for today...")
    try:
        from src.output.talking_head import write_all as write_talking_head
        write_talking_head(today, verbose=True)
    except Exception as e:
        print(f"  ✗ Talking-head failed: {e}")

    # 14) Generate the unified daily brief (one page, everything you need)
    print("\n  ▸ Building daily brief...")
    _run([sys.executable, "scripts/gen_morning_brief.py", today])

    # 14b) Voice brief — short scaffold in Anthony's voice
    print("  ▸ Building voice brief...")
    try:
        from scripts.gen_voice_brief import build_voice_brief
        from datetime import date as _date
        _vd = datetime.strptime(today, "%Y%m%d").date()
        _vpath = build_voice_brief(_vd)
        print(f"  ✓ Voice brief → {_vpath}")
    except Exception as _ve:
        print(f"  ✗ Voice brief skipped: {_ve}")

    # 14c) Franchise shadow bets — log today's franchise team games
    print("  ▸ Logging franchise shadow bets...")
    try:
        from scripts.run_franchise_bets import log_franchise_bets
        _fvd = datetime.strptime(today, "%Y%m%d").date()
        log_franchise_bets(_fvd)
    except Exception as _fe:
        print(f"  ✗ Franchise bets skipped: {_fe}")

    # 15) Rebuild overlay slate data (for /slate page on overlay-gray.vercel.app)
    print("  ▸ Rebuilding slate_data.json for overlay...")
    _run([sys.executable, "scripts/build_slate_data.py"])

    brief_path = Path(f"output/briefs/{today}.md")
    if brief_path.exists():
        print(f"\n  {sep}")
        print(f"  📋 DAILY BRIEF: {brief_path}")
        print(f"     open {brief_path}")
        print(f"  {sep}\n")
        if platform.system() == "Darwin":
            subprocess.run(["open", str(brief_path)], check=False)

    return 0


# ─────────────────────────── night ────────────────────────────────────────

def cmd_night(args: argparse.Namespace) -> int:
    """
    Night pipeline (run at 9:30 PM ET):
    - Generates picks for tomorrow's MLB, NBA, NHL, WNBA slate
    - Snapshots opening odds as 'open lines' in data/timing/open_lines/
    - Prints BET NOW vs HOLD status for each pick based on timing config
    """
    from scripts.night_pipeline import run as run_night, tomorrow_str, NIGHT_SPORTS
    date_str = getattr(args, "date", None) or tomorrow_str()
    sport    = getattr(args, "sport", None)
    sports   = [sport] if sport else NIGHT_SPORTS
    run_night(date_str, sports)

    # Factory sweep: run every registered adapter lane (all 7 soccer leagues +
    # MLB F5/totals) so the shadow lanes accumulate the CLV they need to earn
    # promotion. MLB dedups against the legacy path; the soccer leagues are
    # covered here and nowhere else. All shadow (card_pick=False) — no real money.
    if not sport:  # only on the full nightly sweep, not a single-sport run
        try:
            from src.pipeline.grid_runner import run_all
            print("\n  ▸ Factory sweep (shadow lanes)...")
            for r in run_all(date_str):
                if r.picks:
                    print(f"    {r.summary()}")
        except Exception as e:
            print(f"  ✗ factory sweep failed: {e}")

    # Auto-promoter: surface promote/demote recommendations nightly (report only;
    # promotions to real money stay a deliberate `--apply` decision).
    try:
        from src.pipeline.promoter import main as _promoter_main
        _promoter_main([])
    except Exception as e:
        print(f"  ✗ auto-promoter report failed: {e}")
    return 0


def cmd_gates(args: argparse.Namespace) -> int:
    """
    Bet gates check — run before placing bets.
    Checks live triggers (inactives, goalies, lineups) and prints
    BET NOW or HOLD for each pending card pick.
    """
    from scripts.bet_gates import run_gates
    sport = getattr(args, "sport", None)
    run_gates(sport)
    return 0


def cmd_timing(args: argparse.Namespace) -> int:
    """Print the sport-by-sport bet timing cheat sheet."""
    from scripts.timing_config import print_timing_guide
    print_timing_guide()
    return 0


# ─────────────────────────── evening ───────────────────────────────────────

def cmd_evening(args: argparse.Namespace) -> int:
    """Grade yesterday's picks, show record, refresh stats."""
    grade_date = getattr(args, "date", None)
    if not grade_date:
        yesterday = datetime.now() - timedelta(days=1)
        grade_date = yesterday.strftime("%Y%m%d")

    sep = "═" * 60
    print(f"\n  {sep}")
    print(f"  Overlay — EVENING GRADING — {datetime.now().strftime('%B %d, %Y')}")
    print(f"  Grading picks from: {grade_date}")
    print(f"  {sep}\n")

    # 1) Grade
    print("  ▸ Grading picks...")
    rc = _run([sys.executable, "grade.py", "--date", grade_date, "--sport", "all"])
    if rc != 0:
        print("  ✗ Grading failed")
        return rc
    print("  ✓ Grading done\n")

    # 2) Record
    print("  ▸ Full record:\n")
    cmd_record(argparse.Namespace(market="all", sport="all", shadow=False))

    # 3) Refresh public stats
    print("  ▸ Refreshing public_stats.json...")
    cmd_stats(argparse.Namespace())

    # 4) Generate graded results card PNG (for IG/X)
    print("\n  ▸ Generating graded results card PNG...")
    rc4 = _run([sys.executable, "scripts/gen_results_card.py", "--date", grade_date])
    if rc4 != 0:
        print("  ✗ Results card generation failed (continuing)")
    else:
        print("  ✓ Results card ready")

    # 5) Generate per-platform results captions (IG / X / Reddit)
    print("\n  ▸ Generating results captions (IG / X / Reddit)...")
    try:
        from src.output.results_captions import write_all as write_result_captions
        write_result_captions(grade_date, verbose=True)
    except Exception as e:
        print(f"  ✗ Results captions failed: {e}")

    # 6) Generate talking-head RECAP script (TikTok / YouTube Shorts)
    print("\n  ▸ Generating talking-head recap script...")
    try:
        from src.output.talking_head import write_all as write_talking_head
        write_talking_head(grade_date, verbose=True)
    except Exception as e:
        print(f"  ✗ Talking-head failed: {e}")

    print(f"\n  {sep}")
    print(f"  EVENING DONE — content ready in output/picks/.../{grade_date}/")
    print(f"  {sep}\n")

    return 0


# ─────────────────────────── deploy ─────────────────────────────────────────

def cmd_deploy(args: argparse.Namespace) -> int:
    """Rebuild customer_feed + stats, then push live to overlay-gray.vercel.app."""
    import shutil as _shutil

    sep = "═" * 60
    print(f"\n  {sep}")
    print(f"  Overlay — DEPLOY  →  overlay-gray.vercel.app")
    print(f"  {sep}\n")

    # 1) Refresh public_stats.json (data/) — overlay consumes customer_feed/slate
    print("  ▸ Refreshing stats (public_stats.json)...")
    rc = cmd_stats(argparse.Namespace())
    if rc != 0:
        print("  ✗ Stats refresh failed — aborting deploy")
        return rc
    print("  ✓ Stats refreshed\n")

    # 2a) Rebuild overlay/src/data/customer_feed.json
    print("  ▸ Building customer_feed.json...")
    rc = _run([sys.executable, "scripts/build_customer_feed.py"])
    if rc != 0:
        print("  ✗ customer_feed build failed — aborting deploy")
        return rc
    print("  ✓ customer_feed.json built\n")

    # 2b) Rebuild overlay/src/data/slate_data.json (powers /slate page)
    print("  ▸ Building slate_data.json...")
    rc = _run([sys.executable, "scripts/build_slate_data.py"])
    if rc != 0:
        print("  ✗ slate_data build failed — continuing anyway")
    else:
        print("  ✓ slate_data.json built\n")

    # 2c) Regenerate World Cup 2026 data (powers /world-cup pages)
    print("  ▸ Building World Cup data (fixtures, futures, scorers, groups)...")
    rc = _run([sys.executable, "scripts/wc_data.py", "--sims", "20000"])
    if rc != 0:
        print("  ✗ World Cup data build failed — continuing anyway")
    else:
        print("  ✓ World Cup data built\n")

    # 3) Locate vercel CLI (installed globally or in ~/.local/bin)
    vercel_bin: str | None = _shutil.which("vercel")
    if not vercel_bin:
        for candidate in [
            Path.home() / ".local" / "bin" / "vercel",
            Path("/usr/local/bin/vercel"),
            Path("/opt/homebrew/bin/vercel"),
        ]:
            if candidate.exists():
                vercel_bin = str(candidate)
                break

    if not vercel_bin:
        print("  ✗ vercel CLI not found.")
        print("    Fix: npm install -g vercel --prefix ~/.local")
        print("    Then re-run: python3 chef.py deploy")
        return 1

    # 4) Push to Vercel production
    # Vercel project rootDirectory is set to "overlay/" in the dashboard,
    # so we run from the march-madness/ root. The .vercelignore at the root
    # excludes output/, data/, logs/ etc. to stay under the 250MB limit.
    print(f"  ▸ Deploying via vercel --prod ...")
    rc = _run([
        vercel_bin, "--prod",
        "--scope",   "anthonymccrovitzs-projects",
        "--project", "overlay",
        "--archive=tgz",
    ])
    if rc != 0:
        print("  ✗ Vercel deploy failed")
        return rc

    print(f"\n  {sep}")
    print(f"  ✓  LIVE  →  https://overlay-gray.vercel.app")
    print(f"  {sep}\n")
    return 0


# ─────────────────────────── Entry point ─────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="chef",
        description="Overlay unified picks + grading CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # The one daily driver — listed first because it's the only one you run daily.
    sub.add_parser("today", help="★ THE daily driver: one screen — did it run, the record, what to bet")

    # grid — the whole model board: every sport×market lane + state + health
    p_grid = sub.add_parser("grid", help="The model grid: every sport×market lane, its state (live/shadow/planned) + live stats")
    p_grid.add_argument("sport", nargs="?", help="Optional: show only one sport (e.g. mlb)")
    p_grid.add_argument("--core", action="store_true", help="Core game markets only — hide prop lanes")

    p_scb = sub.add_parser("scoreboard", help="Promotion scoreboard: how close each shadow lane is to earning a live slot (CLV + ROI vs the gate)")
    p_scb.add_argument("sport", nargs="?", help="Optional: show only one sport (e.g. wnba)")

    # experiment — the model-tuning ledger (triage / snapshot / history)
    p_exp = sub.add_parser("experiment", help="Model-tuning ledger: triage every algo for real signal, snapshot a baseline, show history")
    p_exp.add_argument("action", nargs="?", default="triage",
                       choices=["triage", "optimize", "snapshot", "history"],
                       help="triage: map every algo; optimize: best confidence floor per lane; snapshot/history: one algo")
    p_exp.add_argument("sport", nargs="?", help="Sport (for snapshot/history)")
    p_exp.add_argument("market", nargs="?", help="Market (for snapshot/history)")
    p_exp.add_argument("--tag", help="Version tag for a snapshot (e.g. baseline, v2)")
    p_exp.add_argument("--note", help="Note describing the change/state")
    p_exp.add_argument("--min-n", type=int, default=30, dest="min_n", help="Min graded picks to triage a lane")

    # picks mlb / picks nba
    p_picks = sub.add_parser("picks", help="Generate picks for a sport")
    p_picks.add_argument("sport", choices=["mlb", "mlb-props", "mlb_props", "props", "nba", "nba-props", "nba_props", "nhl", "nhl-props", "nhl_props", "wnba", "soccer", "wc", "worldcup", "pga", "tennis", "rg", "roland-garros", "wimbledon", "ufc", "mma", "grid", "all"], help="Sport to generate picks for ('grid'/'all' = factory sweep of every adapter lane)")
    p_picks.add_argument("--date",    help="Date YYYYMMDD (MLB + NBA slate / output folder)")
    p_picks.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    p_picks.add_argument("--late",    action="store_true",
                         help="Late-line mode: refresh odds 1-2h before first pitch for best CLV")
    p_picks.add_argument("--dry-run", action="store_true",
                         help="grid sweep only: compute picks without logging to the ledger")
    p_picks.add_argument("--market",  type=str, default=None,
                         help="Single prop market to run (e.g. pitcher-strikeouts, player-points)")

    # grade
    p_grade = sub.add_parser("grade", help="Grade picks against actual results")
    p_grade.add_argument("--sport", default="all",
                         choices=["all", "mlb", "nba", "nhl", "wnba", "soccer", "tennis", "ufc", "pga"])
    p_grade.add_argument("--date",   help="Date YYYYMMDD (default: yesterday)")
    p_grade.add_argument("--winner", help="Outright winner name (for pga)")

    # record
    p_record = sub.add_parser("record", help="Show P&L record and breakdown")
    p_record.add_argument("--market", default="all",
                          choices=["all", "moneyline", "spread", "total", "nrfi", "prop"])
    p_record.add_argument("--sport",  default="all", choices=["all", "mlb", "nba", "nhl", "wnba"])  # nhl kept for historical record
    p_record.add_argument("--shadow", action="store_true",
                          help="Show all model picks (not just card picks) — validation mode")
    p_record.add_argument("--exclude-version", dest="exclude_version", action="append",
                          metavar="VERSION",
                          help="Exclude picks with this model_version (repeatable). "
                               "E.g. --exclude-version v0_heuristic")

    # shop — pure Monahan-style +EV line shopping
    p_shop = sub.add_parser("shop", help="Monahan-style: find every bet beating Pinnacle fair line")
    p_shop.add_argument("--sport", default="all", choices=["all", "mlb", "nba"])
    p_shop.add_argument("--min-ev", type=float, default=2.0,
                        help="Minimum EV%% vs Pinnacle fair line (default 2.0)")

    # draft — fantasy football draft assistant
    p_draft = sub.add_parser("draft",
        help="★ Fantasy draft board + live assistant (Sleeper)")
    p_draft.add_argument("--user", default="amccrovitz", help="Your Sleeper username")
    p_draft.add_argument("--top", type=int, default=15, help="Rows to show")
    p_draft.add_argument("--pos", default=None, help="Filter to a position (RB/WR/QB/TE)")
    p_draft.add_argument("--live", action="store_true",
                         help="Poll the live draft and recommend for your current pick")
    p_draft.add_argument("--watch", action="store_true",
                         help="With --live: refresh continuously until the draft ends")
    p_draft.add_argument("--sim", action="store_true",
                         help="Monte-Carlo which opening pair works best from your slot")
    p_draft.add_argument("--trials", type=int, default=250, help="Simulation trials")
    p_draft.add_argument("--slot", type=int, default=None,
                         help="Simulate a different draft slot (e.g. after a pick swap)")
    p_draft.add_argument("--handcuffs", action="store_true",
                         help="Show the RB2 behind each starter")

    # filters — prove a subgroup finding forward
    sub.add_parser("filters",
        help="Subgroup filters under prospective test (in-sample vs out-of-sample)")

    # coverage — is the pipeline still running?
    p_cov = sub.add_parser("coverage",
        help="★ Pipeline health: which lanes stopped emitting, and are closing lines being captured")
    p_cov.add_argument("--days", type=int, default=None, help="Window in days (default 30)")
    p_cov.add_argument("--sport", default=None, help="Only this sport")
    p_cov.add_argument("--min-picks", type=int, default=None, dest="min_picks",
                       help="Hide lanes below this activity floor")
    p_cov.add_argument("--gate", action="store_true",
                       help="CI mode: exit non-zero if any LIVE lane stopped emitting "
                            "or its closing lines stopped being captured")

    # audit-models — the build standard, as a report
    p_am = sub.add_parser("audit-models",
        help="★ Audit every lane against the build standard (what tests/test_model_standard.py enforces)")
    p_am.add_argument("--sport", default=None, help="Only this sport (e.g. mlb)")
    p_am.add_argument("--live", action="store_true", help="Only lanes that are LIVE")

    # scan — MARKET track (+EV line shop across every cached board)
    p_scan = sub.add_parser("scan",
        help="★ MARKET track: every book priced off the sharp fair, all sports (0 API credits)")
    p_scan.add_argument("--sport", default=None,
                        help="Substring filter on the board name (mlb, wnba, tennis, soccer…)")
    p_scan.add_argument("--min-ev", type=float, default=None,
                        help="Minimum true EV%% per unit staked (default 2.0)")
    p_scan.add_argument("--max-age", type=float, default=None,
                        help="Skip boards older than N minutes (default 90)")
    p_scan.add_argument("--bankroll", type=float, default=None,
                        help="Override bankroll for ¼-Kelly sizing (default: live balance)")
    p_scan.add_argument("--days", type=float, default=None,
                        help="Only show events starting within N days (default 3)")
    p_scan.add_argument("--refresh", action="store_true",
                        help="Re-fetch boards that are already too stale to scan "
                             "(costs API credits; only the stale ones)")
    p_scan.add_argument("--log", action="store_true",
                        help="Log hits as strategy=line_shop shadow picks for CLV scoring")

    # arb — arbitrage finder
    p_arb = sub.add_parser("arb", help="Scan for guaranteed-profit arbitrage opportunities")
    p_arb.add_argument("--sport",    default="all", choices=["all", "mlb", "nba", "nhl"])
    p_arb.add_argument("--bankroll", type=float, default=1000.0,
                       help="Bankroll for stake sizing (default $1000)")
    p_arb.add_argument("--tier1",   action="store_true",
                       help="Only use DK/FD/BetMGM/BetRivers (no offshore books)")

    # clv
    p_clv = sub.add_parser("clv", help="Closing Line Value dashboard — model edge signal")
    p_clv.add_argument("--refresh", action="store_true",
                       help="Recompute CLV from all date-specific archives")
    p_clv.add_argument("--matrix", action="store_true",
                       help="Show the full per-SPORT × per-market grid (every sport broken out)")

    p_clvw = sub.add_parser("clv-watch",
                            help="Weekly CLV edge watcher: accrual velocity, ETA to sample floor, crossing alerts")
    p_clvw.add_argument("--min-n", type=int, default=200, help="sample floor (default 200)")
    p_clvw.add_argument("--no-record", action="store_true",
                        help="print report but do NOT append to history")

    # dashboard — one-screen model status (record/ROI/EV/odds/CLV per sport×market)
    p_dash = sub.add_parser("dashboard", help="Model status check: ROI/EV/odds/CLV per sport×market")
    p_dash.add_argument("--sport", help="Filter to one sport (e.g. mlb, nba, wc)")
    p_dash.add_argument("--card", action="store_true", help="Card picks only (the real posted record)")
    p_dash.add_argument("--min-n", type=int, default=1, dest="min_n",
                        help="Hide markets with fewer than N picks (and no CLV)")

    # slate — list a day's actual picks (bet, book, odds) grouped by sport×market
    p_slate = sub.add_parser("slate", help="List a day's picks: bet, book, odds entered, edge (per sport×market)")
    p_slate.add_argument("--date", help="Slate date (YYYYMMDD or YYYY-MM-DD); default today")
    p_slate.add_argument("--sport", help="Filter to one sport (e.g. mlb, nba, wc)")
    p_slate.add_argument("--card", action="store_true", help="Card picks only (officially posted)")

    # wc-breakdown — full per-game WC market board (ml/total/spread/scorer)
    p_wcb = sub.add_parser("wc-breakdown", help="Full World Cup market breakdown per game (ml/total/spread/scorer)")
    p_wcb.add_argument("--date", help="Slate date (YYYYMMDD or YYYY-MM-DD); default today")

    # migrate
    sub.add_parser("migrate", help="Normalize picks.json to canonical schema")

    # test
    p_test = sub.add_parser("test", help="Run the full test suite (--grading for just grading)")
    p_test.add_argument("--grading", action="store_true",
                        help="Run only the fast grading tests")

    # stats
    sub.add_parser("stats", help="Refresh public_stats.json")

    # morning — full morning pipeline
    p_morning = sub.add_parser("morning", help="Morning pipeline: MLB + NBA picks, generate all cards")
    p_morning.add_argument(
        "--date",
        metavar="YYYYMMDD",
        help="Slate date for picks, cards, Reddit, talking-head, brief (default: today)",
    )

    # evening — grade + record + stats
    p_evening = sub.add_parser("evening", help="Evening: grade yesterday, show record, refresh stats")
    p_evening.add_argument("--date", help="Date YYYYMMDD to grade (default: yesterday)")

    # reddit — generate daily Reddit posts
    p_reddit = sub.add_parser("reddit", help="Generate ready-to-paste Reddit posts for today's picks")
    p_reddit.add_argument("--date", help="Date YYYYMMDD (default: today)")

    # bet — log a personal bet
    p_bet = sub.add_parser("bet", help="Record a personal bet (separate from algo record)")
    p_bet.add_argument("team",    help="Team or pick description")
    p_bet.add_argument("odds",    type=int, help="American odds (e.g. -110 or +140)")
    p_bet.add_argument("stake",   type=float, help="Dollars to stake")
    p_bet.add_argument("--sport",     default="mlb", choices=["mlb", "nba"], help="Sport")
    p_bet.add_argument("--market",    default="moneyline",
                       choices=["moneyline", "spread", "total", "nrfi", "prop", "f5_total"],
                       help="Market type")
    p_bet.add_argument("--direction", default="WIN", help="WIN | OVER | UNDER | COVER")
    p_bet.add_argument("--sportsbook", help="Which book you placed it at")
    p_bet.add_argument("--matchup",   help="Away @ Home game string")
    p_bet.add_argument("--line",      type=float, help="Spread/total line")
    p_bet.add_argument("--date",      help="Game date YYYY-MM-DD (default: today)")

    # result — grade a personal bet
    p_result = sub.add_parser("result", help="Mark a personal bet win/loss/push")
    p_result.add_argument("pick_id", help="Team name (partial match) or exact pick_id")
    p_result.add_argument("result",  choices=["win", "loss", "push"])

    # status — daily sanity check across all sport pipelines
    p_status = sub.add_parser("status", help="Show which sport pipelines produced picks today")
    p_status.add_argument("--date", help="Date YYYYMMDD (default: today)")

    sub.add_parser("health", help="Daily 30s health check: picks/closings/CLV/grading fresh?")
    p_monitor = sub.add_parser("monitor", help="Loud integrity check: flag any IN-SEASON market gone dark (exits RED on gaps)")
    p_monitor.add_argument("--soft", action="store_true", help="Always exit 0 (report only, don't fail the run)")
    sub.add_parser("heartbeat", help="★ Daily digest, sent green OR red — a missing digest is the alarm")
    p_verify = sub.add_parser("verify", help="Trigger core cloud workflows NOW and report pass/fail (~2-5 min, no waiting for cron)")
    p_verify.add_argument("--workflows", type=str, help="Comma-separated workflow files (default: monitor.yml,night.yml,clv.yml)")
    p_cal = sub.add_parser("calibrate", help="Refit all sport×market calibrators from settled results (fixes overconfident edges)")
    p_cal.add_argument("--min-n", type=int, dest="min_n", help="Minimum settled picks to calibrate a market (default 30)")
    p_validate = sub.add_parser("validate", help="Model validation: outcome calibration (stated prob vs actual hit rate, Brier) per sport·market")
    p_validate.add_argument("--min-n", type=int, dest="min_n", help="Minimum graded picks to validate a market (default 20)")
    p_validate.add_argument("--gate", action="store_true", help="Exit non-zero if a LIVE market is overconfident (for CI alerting)")
    p_edge = sub.add_parser("edge", help="Statistical promotion gate: which markets have a REAL CLV edge vs noise (t-test + sample floor + multiple-comparison correction)")
    p_edge.add_argument("--min-n", type=int, dest="min_n", help="Minimum scored picks to test a market (default 200)")

    p_promote = sub.add_parser("promote", help="Promote a market to live card picks (REFUSED unless it clears the CLV gate). e.g. promote wc moneyline")
    p_promote.add_argument("sport", help="Sport/league key (e.g. wc, mlb, nba, tennis)")
    p_promote.add_argument("market", help="Market (e.g. moneyline, total, spread, anytime_scorer)")
    p_promote.add_argument("--min-n", type=int, dest="min_n", help="Minimum scored picks to test (default 200)")
    p_promote.add_argument("--tier", choices=["t1", "t2"], help="Tier to assign on promotion (default t2)")

    p_demote = sub.add_parser("demote", help="Demote a market back to shadow/incubating (undo a promotion). e.g. demote wc moneyline")
    p_demote.add_argument("sport", help="Sport/league key")
    p_demote.add_argument("market", help="Market")

    p_retire = sub.add_parser("retire",
        help="Retire a lane so it stops running at all (requires --reason). Undo with demote.")
    p_retire.add_argument("sport", help="Sport/league key")
    p_retire.add_argument("market", help="Market")
    p_retire.add_argument("--reason", required=True,
                          help="Evidence for the decision — recorded in promotions.json")

    p_audit = sub.add_parser("audit", help="Bet-tracking completeness: odds/EV/CLV/ROI coverage + flags settled bets missing their closing line (exits RED on gaps)")
    p_audit.add_argument("--days", type=int, help="Window for the missing-closing alarm (default 21)")

    p_strat = sub.add_parser("strategies", help="Log + measure shadow strategies (research-rule picks, CLV-tracked, never bet)")
    p_strat.add_argument("--report", action="store_true", help="Report CLV by strategy only; don't log new picks")
    p_strat.add_argument("--date", help="Slate date YYYYMMDD (default: today)")

    p_poly = sub.add_parser("polymarket", help="Polymarket-vs-Pinnacle scanner (shadow polymarket_ev picks)")
    p_poly.add_argument("--date", help="Slate date YYYYMMDD (default: today)")
    p_poly.add_argument("--min-ev", type=float, default=2.0, dest="min_ev")
    p_poly.add_argument("--bankroll", type=float, default=112.0, help="Pilot bankroll for stake guidance")
    p_poly.add_argument("--dry-run", action="store_true", dest="dry_run")

    p_fills = sub.add_parser("polyfills",
                             help="Did the Polymarket maker orders fill? (adverse-selection report)")
    p_fills.add_argument("--since", help="Only picks on/after this date (YYYY-MM-DD)")
    p_fills.add_argument("--json", action="store_true", dest="as_json")

    p_paper = sub.add_parser("paper",
                             help="Paper-trade ledger for the Polymarket pilot (no money)")
    p_paper.add_argument("--bankroll", type=float, default=112.0)
    p_paper.add_argument("--mode", choices=["make", "take"],
                         help="Only simulate this execution style")
    p_paper.add_argument("--json", action="store_true", dest="as_json")

    p_dash = sub.add_parser("polydash", help="Polymarket pilot dashboard (one screen)")
    p_dash.add_argument("--date", help="Slate date YYYY-MM-DD (default: today)")
    p_dash.add_argument("--json", action="store_true", dest="as_json")

    p_ptime = sub.add_parser("polytiming",
                             help="When is Polymarket mispriced? (price discovery by lead time)")
    p_ptime.add_argument("--since", help="Games on/after this date (YYYY-MM-DD)")
    p_ptime.add_argument("--json", action="store_true", dest="as_json")

    p_ready = sub.add_parser("polyready",
                             help="Experiment verdict: WAIT / RETIRE / PROMOTE vs pre-set gates")
    p_ready.add_argument("--json", action="store_true", dest="as_json")

    # bankroll — personal P&L
    p_bankroll = sub.add_parser("bankroll", help="Show personal bankroll P&L")
    p_bankroll.add_argument("--sport",  default="all", choices=["all", "mlb", "nba"])
    p_bankroll.add_argument("--market", default="all",
                            choices=["all", "moneyline", "spread", "total", "nrfi", "prop"])

    # monthly — generate monthly performance report
    p_monthly = sub.add_parser("monthly", help="Generate monthly performance report (output/briefs/monthly_YYYYMM.md)")
    p_monthly.add_argument(
        "month", nargs="?", metavar="YYYYMM",
        help="Month to report (default: current month)",
    )

    # night — night pipeline (9:30 PM ET, runs night before to catch opening lines)
    p_night = sub.add_parser("night", help="Night pipeline: generate tomorrow's picks at line open (9:30 PM ET)")
    p_night.add_argument("--date",  metavar="YYYYMMDD", help="Target date (default: tomorrow)")
    p_night.add_argument("--sport", help="Single sport (mlb/nba/nhl/wnba)")

    # gates — bet trigger checker (run before placing bets)
    p_gates = sub.add_parser("gates", help="Check bet triggers: inactives / goalies / lineups — BET NOW or HOLD")
    p_gates.add_argument("--sport", default=None,
                         help="Filter to one sport (nba/nhl/mlb/wnba)")

    # timing — print sport-by-sport timing cheat sheet
    sub.add_parser("timing", help="Print bet timing cheat sheet for all sports")

    # deploy — rebuild feed + push to Vercel
    sub.add_parser("deploy", help="Rebuild customer_feed + stats, then push to overlay-gray.vercel.app")

    # wc — World Cup 2026 data generator (web app source of truth)
    p_wc = sub.add_parser("wc", help="Generate World Cup 2026 web data (fixtures, futures, groups)")
    p_wc.add_argument("--sims", type=int, default=20000, help="Monte Carlo sims (default 20000)")
    p_wc.add_argument("--blend", type=float, default=0.40, help="Model weight in blended numbers")
    p_voice = sub.add_parser("voice", help="Daily voice brief — what to post + outreach scaffold")
    p_voice.add_argument("--date", default=None, help="YYYYMMDD (default: today)")

    # daily — personal-bet content ritual (tweet + video script)
    p_daily = sub.add_parser("daily",
                             help="Daily personal-bet ritual: pick → tweet + video script → log")
    p_daily.add_argument("subcmd", nargs="?", default="pre",
                         choices=["pre", "result", "post", "post-game", "status"],
                         help="pre (default) = morning pick & content; result = post-game; status = record")
    p_daily.add_argument("--date",  help="YYYYMMDD slate date (default: today)")
    p_daily.add_argument("--stake", type=float, default=30.0, help="Dollar stake (default 30)")
    p_daily.add_argument("--book",  help="Sportsbook (default: best-odds book)")
    p_daily.add_argument("--auto",  help="Auto-select pick #N (skip prompt)")
    p_daily.add_argument("--all-books", dest="all_books", action="store_true",
                         help="Don't filter to RAF partner books (FD/DK/MGM)")
    p_daily.add_argument("--pick-id", dest="pick_id",
                         help="Specific pick_id or team substring to grade (result subcmd)")

    # wc-post — World Cup daily content generator
    p_wcp = sub.add_parser("wc-post",
                           help="World Cup content: tweet + video script for today's marquee match")
    p_wcp.add_argument("--date", help="YYYYMMDD or YYYY-MM-DD (default: today)")
    p_wcp.add_argument("--product-link", dest="product_link",
                       help=f"Override CTA link (default {None})")
    p_wcp.add_argument("--price", help="Override price string (default $9)")

    # franchise — shadow franchise team bet tracker
    p_fran = sub.add_parser("franchise", help="Franchise shadow bet tracker — all 30 MLB teams")
    p_fran.add_argument("--date",        default=None, help="YYYYMMDD to log bets for (default: today)")
    p_fran.add_argument("--grade",       action="store_true", help="Grade yesterday's bets")
    p_fran.add_argument("--report",      action="store_true", help="Per-team report")
    p_fran.add_argument("--leaderboard", action="store_true", help="ROI-ranked leaderboard (default view)")
    p_fran.add_argument("--min-picks",   type=int, default=5, help="Min picks to show in leaderboard (default 5)")

    # challenge — June 2026 bankroll challenge
    p_chal = sub.add_parser("challenge", help="June 2026 bankroll challenge: add/grade/card/recap/status")
    p_chal.add_argument("subcmd", choices=["add","grade","card","recap","status"],
                        help="Subcommand: add <pick_id> | grade | card | recap | status")
    p_chal.add_argument("pick_id", nargs="?", help="Pick ID (only for 'add')")
    p_chal.add_argument("--stake-units", type=float, default=1.0,
                        help="Stake in units when adding a bet (default 1.0)")

    # shadow — Phase 2.5 A/B filter analysis (hot/cold form gates)
    p_shadow = sub.add_parser("shadow", help="Shadow A/B filter analysis (hot/cold form gates)")
    p_shadow.add_argument("--include-shadow", action="store_true",
                          help="Include card_pick=False picks (shows full thesis)")
    p_shadow.add_argument("--backfill", action="store_true",
                          help="Re-run shadow_filter classification on all picks first")

    args = parser.parse_args()

    dispatch = {
        "picks":    cmd_picks,
        "grade":    cmd_grade,
        "record":   cmd_record,
        "shop":     cmd_shop,
        "scan":     cmd_scan,
        "audit-models": cmd_audit_models,
        "coverage": cmd_coverage,
        "filters":  cmd_filters,
        "draft":    cmd_draft,
        "retire":   cmd_retire,
        "arb":      cmd_arb,
        "clv":      cmd_clv,
        "clv-watch": cmd_clv_watch,
        "dashboard": cmd_dashboard,
        "slate":    cmd_slate,
        "wc-breakdown": cmd_wc_breakdown,
        "migrate":  cmd_migrate,
        "test":     cmd_test,
        "stats":    cmd_stats,
        "status":   cmd_status,
        "health":   cmd_health,
        "monitor":  cmd_monitor,
        "heartbeat": cmd_heartbeat,
        "verify":   cmd_verify,
        "edge":     cmd_edge,
        "promote":  cmd_promote,
        "demote":   cmd_demote,
        "audit":    cmd_audit,
        "validate": cmd_validate,
        "calibrate": cmd_calibrate,
        "strategies": cmd_strategies,
        "polymarket": cmd_polymarket,
        "polyfills": cmd_polyfills,
        "paper":     cmd_paper,
        "polydash":  cmd_polydash,
        "polytiming": cmd_polytiming,
        "polyready": cmd_polyready,
        "morning":  cmd_morning,
        "evening":  cmd_evening,
        "night":    cmd_night,
        "gates":    cmd_gates,
        "timing":   cmd_timing,
        "reddit":   cmd_reddit,
        "bet":      cmd_bet,
        "result":   cmd_result,
        "bankroll": cmd_record_personal,
        "monthly":  cmd_monthly,
        "deploy":   cmd_deploy,
        "challenge": cmd_challenge,
        "shadow":   cmd_shadow,
        "voice":    cmd_voice,
        "franchise": cmd_franchise,
        "wc":       cmd_wc,
        "daily":    cmd_daily,
        "wc-post":  cmd_wc_post,
        "today":    cmd_today,
        "grid":     cmd_grid,
        "scoreboard": cmd_scoreboard,
        "experiment": cmd_experiment,
    }
    return dispatch[args.command](args)


def cmd_wc(args: argparse.Namespace) -> int:
    """Generate World Cup 2026 web data (fixtures, futures, group standings)."""
    from scripts.wc_data import main as wc_main
    sys.argv = ["wc_data", "--sims", str(args.sims), "--blend", str(args.blend)]
    return wc_main()


def cmd_shadow(args: argparse.Namespace) -> int:
    """Run shadow A/B filter analysis (hot/cold form gates)."""
    import subprocess
    scripts = Path(__file__).parent / "scripts"
    if args.backfill:
        subprocess.run([sys.executable, str(scripts / "backfill_shadow_filter.py"), "--force"], check=False)
    cmd = [sys.executable, str(scripts / "analyze_shadow_filters.py")]
    if args.include_shadow:
        cmd.append("--include-shadow")
    return subprocess.run(cmd, check=False).returncode


def cmd_voice(args: argparse.Namespace) -> int:
    """Generate daily voice brief — scaffold for tweets, Instagram, outreach, challenge."""
    from scripts.gen_voice_brief import build_voice_brief
    ts = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    d  = datetime.strptime(ts, "%Y%m%d").date()
    path = build_voice_brief(d)
    print(path.read_text())
    print(f"\n→ {path}")
    return 0


def cmd_franchise(args: argparse.Namespace) -> int:
    """Franchise shadow bet tracker — all 30 MLB teams."""
    from scripts.run_franchise_bets import log_franchise_bets, grade_yesterday
    from src.analytics.franchise_tracker import print_report, print_leaderboard

    min_picks = getattr(args, "min_picks", 5)

    if getattr(args, "grade", False):
        n = grade_yesterday()
        print(f"  Graded {n} franchise bet(s).")
        print_leaderboard(min_picks=min_picks)
        return 0

    if getattr(args, "report", False):
        print_report()
        return 0

    # Default view: log today + show leaderboard
    ts = getattr(args, "date", None) or datetime.now().strftime("%Y%m%d")
    d  = datetime.strptime(ts, "%Y%m%d").date()

    if not getattr(args, "leaderboard", False):
        log_franchise_bets(d)

    print_leaderboard(min_picks=min_picks)
    return 0


def cmd_challenge(args: argparse.Namespace) -> int:
    """Dispatch to scripts/june_challenge.py subcommands."""
    import subprocess
    sub_args = [sys.executable, str(Path(__file__).parent / "scripts" / "june_challenge.py"), args.subcmd]
    if args.subcmd == "add":
        if not args.pick_id:
            print("Usage: chef.py challenge add <pick_id> [--stake-units N]")
            return 1
        sub_args += [args.pick_id, "--stake-units", str(args.stake_units)]
    return subprocess.call(sub_args)


if __name__ == "__main__":
    sys.exit(main())
