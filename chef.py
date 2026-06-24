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
    else:
        print(f"Unknown sport: {sport}. Use: mlb, mlb-props, nba, nba-props, nhl, nhl-props, wnba, soccer, pga, tennis, ufc.")
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

_SPORT_LABEL = {"mlb": "MLB", "nba": "NBA", "nhl": "NHL"}


def _cmd_record_shadow(picks: list[dict], filter_market: str, filter_sport: str) -> int:
    """Show model-only (shadow) record — all picks the algo generated, not just card picks."""
    shadow = [p for p in picks if not p.get("card_pick")]
    if filter_market != "all":
        shadow = [p for p in shadow if p.get("market") == filter_market]
    if filter_sport != "all":
        shadow = [p for p in shadow if p.get("sport") == filter_sport]

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
            sp  = [p for p in shadow if p.get("sport") == sport_key]
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

    print(f"\n  {sep}\n")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    picks = _load_picks()
    if not picks:
        print("  No picks found. Run: python3 chef.py picks mlb")
        return 0

    filter_market    = getattr(args, "market", "all")
    filter_sport     = getattr(args, "sport",  "all")
    shadow_mode      = getattr(args, "shadow", False)
    exclude_versions = set(getattr(args, "exclude_version", None) or [])

    if exclude_versions:
        picks = [p for p in picks if p.get("model_version") not in exclude_versions]

    if shadow_mode:
        return _cmd_record_shadow(picks, filter_market, filter_sport)

    card_picks = list(picks)
    if filter_market != "all":
        card_picks = [p for p in card_picks if p.get("market") == filter_market]
    if filter_sport != "all":
        card_picks = [p for p in card_picks if p.get("sport") == filter_sport]

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
            sp = [p for p in card_picks if p.get("sport") == sport_key]
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

_PERSONAL_BANKROLL_START = 100.0   # dollars


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
    picks = _load_personal()
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

    settled  = [p for p in picks if p.get("result") in ("win", "loss", "push")]
    non_push = [p for p in settled if p.get("result") != "push"]
    wins     = [p for p in non_push if p.get("result") == "win"]
    losses   = [p for p in non_push if p.get("result") == "loss"]
    pending  = [p for p in picks if not p.get("result")]
    staked   = sum(float(p.get("stake_dollars") or p.get("stake") or 0) for p in non_push)
    profit   = sum(float(p.get("profit_dollars") or 0) for p in non_push)
    wr       = len(wins) / len(non_push) if non_push else 0.0
    roi      = profit / staked * 100 if staked > 0 else 0.0
    bankroll = _PERSONAL_BANKROLL_START + profit

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
            tm_   = str(p.get("team") or "?")[:21]
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
    picks = data.get("picks", [])
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
    picks = json.loads(_PNL_FILE.read_text()).get("picks", [])
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
    return _run([sys.executable, "-m", "pytest", "tests/test_grading.py", "-v"])


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
            print_clv_report, print_clv_by_market, compute_clv,
            backfill_snapshots_from_pnl, upgrade_snapshots,
            backfill_snapshot_markets,
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
            # 3. Recompute CLV for every date that has a closing archive — scores
            #    moneyline, spread, total, F5, NRFI, and props in one pass.
            archive_dir = Path("data/clv/closing")
            dates = {f.stem[-10:] for f in archive_dir.glob("*.json") if len(f.stem) >= 10}
            if dates:
                print(f"  Recomputing CLV for {len(dates)} archive dates...")
                for d in sorted(dates):
                    compute_clv(date_str=d)

        print_clv_report()
        print_clv_by_market()   # per-market: which market actually beats the close
        return 0
    except Exception as e:
        print(f"  CLV error: {e}")
        import traceback; traceback.print_exc()
        return 1


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


def cmd_monitor(args: argparse.Namespace) -> int:
    """Loud data-integrity monitor — flags any IN-SEASON market that's gone dark.

    The silent-failure trap that bit us repeatedly: workflows exit green even
    when a component stops producing (props, MLB spreads, motorsport all died
    when the laptop was retired and nothing noticed for weeks). This asks the
    Odds API what's *actually* in season, then verifies every market we model
    for those sports produced a pick in the last 2 days, closings are being
    captured, and CLV is scoring. Exits NON-ZERO on any gap so the GitHub
    Action turns RED — a visible alarm instead of a silently-green check.
    """
    from datetime import date as _date, timedelta
    from collections import defaultdict
    import os, glob

    today  = _date.today()
    cutoff = (today - timedelta(days=2)).isoformat()
    print(f"\n  ─ Integrity Monitor — {today.strftime('%A %b %d, %Y')} ────────────────")

    # 1. Ground truth: what's actually in season (Odds API active-sports list)
    active: set = set()
    try:
        import requests
        key = os.environ.get("ODDS_API_KEY")
        if key:
            r = requests.get("https://api.the-odds-api.com/v4/sports",
                             params={"apiKey": key}, timeout=15)
            if r.ok:
                active = {s["key"] for s in r.json() if s.get("active")}
    except Exception as e:
        print(f"  ⚠ could not fetch active sports ({e}) — season check skipped")

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
    specs = [
        ("MLB",        lambda a: "baseball_mlb" in a,
                       lambda s: s in ("mlb", "baseball_mlb"),
                       ["moneyline", "total", "spread", "f5_total", "nrfi", "pitcher_strikeouts"]),
        ("NBA",        lambda a: "basketball_nba" in a,
                       lambda s: s in ("nba", "basketball_nba"),
                       ["moneyline", "spread", "total"]),
        ("NHL",        lambda a: "icehockey_nhl" in a,
                       lambda s: s in ("nhl", "icehockey_nhl"),
                       ["moneyline", "puck_line", "total"]),
        ("WNBA",       lambda a: "basketball_wnba" in a,
                       lambda s: s in ("wnba", "basketball_wnba"),
                       ["moneyline", "spread", "total"]),
        ("Soccer/WC",  lambda a: "soccer_fifa_world_cup" in a,
                       lambda s: s == "soccer_fifa_world_cup",
                       ["moneyline"]),
        ("Tennis",     lambda a: any(k.startswith("tennis_") for k in a),
                       lambda s: s.startswith("tennis_"),
                       ["moneyline"]),
        ("Golf",       lambda a: any(k.startswith("golf_") for k in a),
                       lambda s: s.startswith("golf_"),
                       ["outright"]),
        ("MMA/UFC",    lambda a: any(k.startswith("mma_") for k in a),
                       lambda s: s.startswith("mma_"),
                       ["moneyline"]),
        ("Motorsport", lambda a: any("auto_racing" in k for k in a),
                       lambda s: "auto_racing" in s,
                       ["win"]),
    ]

    issues = 0
    print("  In-season market coverage:")
    any_active = False
    for label, active_test, sport_test, markets in specs:
        if not active or not active_test(active):
            continue  # off-season → not expected
        any_active = True
        for mk in markets:
            d = _last_for(sport_test, mk)
            if d and d >= cutoff:
                print(f"    ✓ {label:11} {mk:18} last {d}")
            else:
                shown = f"DARK (last {d})" if d else "NEVER logged"
                print(f"    ✗ {label:11} {mk:18} {shown}  ← in season, not producing")
                issues += 1
    if not any_active:
        print("    (no active sports detected — Odds API key issue or true off-day)")

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
        print(f"  ✓ Closing capture   {nonempty} non-empty archive(s) in last 2 days")
    else:
        print(f"  ✗ Closing capture   NONE in last 2 days  ← CLV can't score (capture-closing.yml)")
        issues += 1

    # 5. CLV scoring fresh
    try:
        snaps = json.loads(Path("data/clv/snapshots.json").read_text())
        snaps = snaps.get("snapshots", snaps) if isinstance(snaps, dict) else snaps
        scored = [s for s in snaps if isinstance(s, dict)
                  and (s.get("clv") is not None or s.get("line_clv") is not None)]
        sd = sorted({s.get("date") for s in scored if s.get("date")})
        if sd and sd[-1] >= cutoff:
            print(f"  ✓ CLV scoring       latest scored {sd[-1]}")
        else:
            print(f"  ✗ CLV scoring       stale (latest {sd[-1] if sd else 'never'})  ← join not happening")
            issues += 1
    except (json.JSONDecodeError, ValueError, OSError):
        print(f"  ✗ CLV scoring       snapshots.json unreadable")
        issues += 1

    print(f"  {'─' * 58}")
    if issues:
        print(f"  ⚠ {issues} INTEGRITY GAP(S) — see ✗ above. Action exits RED on purpose.")
    else:
        print(f"  ✓ ALL GREEN — every in-season market producing, closings + CLV fresh")
    # Loud by default: non-zero exit turns the GitHub Action RED on any gap.
    return 1 if (issues and not getattr(args, "soft", False)) else 0


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
    """Compute the CLV promotion gate for every (sport, market).

    Shared by `chef.py edge` (display) and `chef.py promote` (enforcement) so the
    two can never diverge. Returns (rows, meta) or None if snapshots unreadable.

    Each row: {sport, market, label, n, mean, unit, rmean, p_pos, verdict,
               is_candidate}. `sport` is the short label (mlb/nba/wc/...), which
               matches src.config.models._key so promotion targets line up.
    meta: {min_n, alpha, m_tests}.
    """
    import math, statistics
    from datetime import date as _date, timedelta
    from collections import defaultdict

    try:
        snaps = json.loads(Path("data/clv/snapshots.json").read_text())
        snaps = snaps.get("snapshots", snaps) if isinstance(snaps, dict) else snaps
    except (json.JSONDecodeError, ValueError, OSError):
        return None

    def clv_val(s):
        # natural per-market metric: prob markets in %, line markets in points
        if s.get("clv_pct") is not None:
            return float(s["clv_pct"]), "%"
        if s.get("line_clv") is not None:
            return float(s["line_clv"]), "pt"
        return None, None

    try:
        from src.analytics.clv_tracker import _normalize_sport
    except Exception:
        def _normalize_sport(x): return x

    # Short, readable sport label — MUST match src.config.models._key so a row
    # here maps 1:1 to a promotable registry entry (e.g. 'wc', 'mlb', 'wnba').
    def _sport_label(sp: str) -> str:
        sp = _normalize_sport(str(sp or "?"))
        return {
            "baseball_mlb": "mlb", "basketball_nba": "nba", "basketball_wnba": "wnba",
            "icehockey_nhl": "nhl", "mma_mixed_martial_arts": "mma",
            "soccer_fifa_world_cup": "wc",
        }.get(sp, sp.replace("soccer_", "").replace("tennis_atp_", "atp-")
                  .replace("tennis_wta_", "wta-").replace("golf_", "golf-")[:14])

    recent_cut = (_date.today() - timedelta(days=30)).isoformat()
    # Key on (sport, market) — NOT market alone. Pooling sports is Simpson's
    # paradox: a real tennis-ML edge gets washed out by MLB ML, a soccer outlier
    # drags the blend. An edge is model+sport specific, so each gets its own row.
    by_mkt: dict = defaultdict(list)
    for s in snaps:
        if not isinstance(s, dict):
            continue
        v, unit = clv_val(s)
        if v is None:
            continue
        mkt = s.get("market") or "(unset)"
        key = (_sport_label(s.get("sport", "?")), mkt)
        by_mkt[key].append((v, unit, s.get("date", "")))

    testable = [k for k, vals in by_mkt.items() if len(vals) >= min_n]
    m_tests = max(1, len(testable))
    alpha = 0.05 / m_tests  # Bonferroni-corrected for the number of markets tested

    def p_gt0(mean, sd, n):
        """One-sided p-value that the true mean > 0."""
        if n < 2 or sd == 0:
            return 1.0
        t = mean / (sd / math.sqrt(n))
        try:
            from scipy import stats
            return float(stats.t.sf(t, n - 1))
        except Exception:
            return 0.5 * math.erfc(t / math.sqrt(2))  # normal approx

    rows = []
    for key in sorted(by_mkt, key=lambda k: -len(by_mkt[k])):
        sport, mkt = key
        vals = by_mkt[key]
        n = len(vals)
        unit = vals[0][1]
        xs = [v for v, _, _ in vals]
        mean = statistics.fmean(xs)
        recent = [v for v, _, d in vals if d and d >= recent_cut]
        rmean = statistics.fmean(recent) if recent else None
        p_pos = None
        is_candidate = False
        if n < min_n:
            verdict = f"insufficient (need {min_n})"
        else:
            sd = statistics.pstdev(xs)
            p_pos = p_gt0(mean, sd, n)
            p_neg = p_gt0(-mean, sd, n)
            if mean > 0 and p_pos < alpha and (rmean is None or rmean > 0):
                verdict = "✅ EDGE CANDIDATE → out-of-sample watch"
                is_candidate = True
            elif mean < 0 and p_neg < alpha:
                verdict = "❌ negative — fade or stop modeling"
            else:
                verdict = "noise (no edge)"
        rows.append({
            "sport": sport, "market": mkt, "label": f"{sport} · {mkt}",
            "n": n, "mean": mean, "unit": unit, "rmean": rmean,
            "p_pos": p_pos, "verdict": verdict, "is_candidate": is_candidate,
        })
    return rows, {"min_n": min_n, "alpha": alpha, "m_tests": m_tests}


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
    print(f"  {'sport · market':26}{'n':>6}{'mean':>10}{'30d':>9}{'p(>0)':>9}  verdict")
    print(f"  {'─'*72}")
    candidates = []
    for r in rows:
        if r["is_candidate"]:
            candidates.append(r)
        rstr = f"{r['rmean']:+.3f}" if r["rmean"] is not None else "—"
        pstr = f"{r['p_pos']:.4f}" if r["p_pos"] is not None else "—"
        print(f"  {r['label'][:26]:26}{r['n']:>6}{r['mean']:>+9.3f}{r['unit']:<1}"
              f"{rstr:>9}{pstr:>9}  {r['verdict']}")

    print(f"  {'─'*72}")
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

    def cv(p):
        s = clv.get((str(p.get("date", ""))[:10], str(p.get("team", "")).lower(), p.get("market")))
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
    print(f"    closing line+CLV  {cov(lambda p: cv(p) is not None, settled)}   ← capture-dependent")

    od   = [float(p["odds"]) for p in card if p.get("odds") is not None]
    evs  = [ev(p) for p in card]; evs = [e for e in evs if e is not None]
    clvs = [cv(p) for p in settled if cv(p) is not None]
    prof = sum(float(p.get("profit") or 0) for p in staked)
    w    = sum(1 for p in staked if p["result"] == "win")
    print(f"\n    avg odds entered  {(sum(od)/len(od)):+.0f}" if od else "    avg odds entered  —")
    print(f"    avg model EV/bet  {100*sum(evs)/len(evs):+.1f}%" if evs else "    avg model EV/bet  —")
    print(f"    avg CLV (scored)  {sum(clvs)/len(clvs):+.2f}%  (n={len(clvs)})" if clvs else "    avg CLV (scored)  none")
    if staked:
        print(f"    record / ROI      {w}-{len(staked)-w}  {prof:+.2f}u  ({100*prof/len(staked):+.1f}%)")

    gaps = [p for p in settled if cv(p) is None and str(p.get("date", ""))[:10] >= cutoff]
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

    min_n = getattr(args, "min_n", None) or 20
    print(f"\n  ─ Model Validation — outcome calibration (min n={min_n}) ─────────")
    print(f"  {'sport · market':26}{'n':>5}{'stated':>8}{'actual':>8}{'Brier':>8}  verdict")
    print(f"  {'─'*74}")
    flagged = 0
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
            verdict = f"⚠ OVERCONFIDENT ({gap*100:+.0f}pt)"
            flagged += 1
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

    # picks mlb / picks nba
    p_picks = sub.add_parser("picks", help="Generate picks for a sport")
    p_picks.add_argument("sport", choices=["mlb", "mlb-props", "mlb_props", "props", "nba", "nba-props", "nba_props", "nhl", "nhl-props", "nhl_props", "wnba", "soccer", "wc", "worldcup", "pga", "tennis", "rg", "roland-garros", "wimbledon", "ufc", "mma"], help="Sport to generate picks for")
    p_picks.add_argument("--date",    help="Date YYYYMMDD (MLB + NBA slate / output folder)")
    p_picks.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    p_picks.add_argument("--late",    action="store_true",
                         help="Late-line mode: refresh odds 1-2h before first pitch for best CLV")
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
    p_record.add_argument("--sport",  default="all", choices=["all", "mlb", "nba", "nhl"])  # nhl kept for historical record
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

    # migrate
    sub.add_parser("migrate", help="Normalize picks.json to canonical schema")

    # test
    sub.add_parser("test", help="Run grading unit tests")

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
    p_verify = sub.add_parser("verify", help="Trigger core cloud workflows NOW and report pass/fail (~2-5 min, no waiting for cron)")
    p_verify.add_argument("--workflows", type=str, help="Comma-separated workflow files (default: monitor.yml,night.yml,clv.yml)")
    p_cal = sub.add_parser("calibrate", help="Refit all sport×market calibrators from settled results (fixes overconfident edges)")
    p_cal.add_argument("--min-n", type=int, dest="min_n", help="Minimum settled picks to calibrate a market (default 30)")
    p_validate = sub.add_parser("validate", help="Model validation: outcome calibration (stated prob vs actual hit rate, Brier) per sport·market")
    p_validate.add_argument("--min-n", type=int, dest="min_n", help="Minimum graded picks to validate a market (default 20)")
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

    p_audit = sub.add_parser("audit", help="Bet-tracking completeness: odds/EV/CLV/ROI coverage + flags settled bets missing their closing line (exits RED on gaps)")
    p_audit.add_argument("--days", type=int, help="Window for the missing-closing alarm (default 21)")

    p_strat = sub.add_parser("strategies", help="Log + measure shadow strategies (research-rule picks, CLV-tracked, never bet)")
    p_strat.add_argument("--report", action="store_true", help="Report CLV by strategy only; don't log new picks")
    p_strat.add_argument("--date", help="Slate date YYYYMMDD (default: today)")

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
        "arb":      cmd_arb,
        "clv":      cmd_clv,
        "migrate":  cmd_migrate,
        "test":     cmd_test,
        "stats":    cmd_stats,
        "status":   cmd_status,
        "health":   cmd_health,
        "monitor":  cmd_monitor,
        "verify":   cmd_verify,
        "edge":     cmd_edge,
        "promote":  cmd_promote,
        "demote":   cmd_demote,
        "audit":    cmd_audit,
        "validate": cmd_validate,
        "calibrate": cmd_calibrate,
        "strategies": cmd_strategies,
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
