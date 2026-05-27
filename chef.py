#!/usr/bin/env python3
"""
chef.py — ChefTonyBets unified CLI

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
    print(f"  ChefTonyBets — SHADOW RECORD (Model Only / Not Bet)")
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
    title = "ChefTonyBets — RECORD"
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
        from src.analytics.clv_tracker import get_clv_summary
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
    print(f"  ChefTonyBets — PERSONAL BANKROLL")
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

    posts["daily"] = f"""**ChefTonyBets AI Model — {day_str} {date_str}**

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

    posts["mlb"] = f"""**ChefTonyBets AI — MLB {day_str} {date_str}**

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

    posts["mlb_props"] = f"""**ChefTonyBets AI — MLB Props {day_str} {date_str}**

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

    posts["nba"] = f"""**ChefTonyBets AI — NBA Playoffs {day_str} {date_str}**

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
        from src.analytics.clv_tracker import print_clv_report, compute_clv

        refresh = getattr(args, "refresh", False)
        if refresh:
            from pathlib import Path
            archive_dir = Path("data/clv/closing")
            # Extract date portion (last 10 chars: YYYY-MM-DD) from all archive files
            dates = {f.stem[-10:] for f in archive_dir.glob("*.json") if len(f.stem) >= 10}
            if dates:
                print(f"  Recomputing CLV for {len(dates)} archive dates...")
                for d in sorted(dates):
                    compute_clv(date_str=d)

        print_clv_report()
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

    print(f"\n  ChefTonyBets Pipeline Status — {target_dt.strftime('%A %B %d, %Y')}")
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
    print(f"  ChefTonyBets — MORNING PIPELINE — {banner_date}  (folder {today})")
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
    print(f"  ChefTonyBets — EVENING GRADING — {datetime.now().strftime('%B %d, %Y')}")
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


# ─────────────────────────── Entry point ─────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="chef",
        description="ChefTonyBets unified picks + grading CLI",
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
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
