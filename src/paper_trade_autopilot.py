#!/usr/bin/env python3
"""
Paper trading autopilot — runs the right step for the time of day and logs health.

Designed for cron (3–4x daily) or manual `python -m src.paper_trade_autopilot`.

Time windows (America/New_York by default, override with TZ env):

  Early morning (4:00–9:59):  grade yesterday's picks (games from last night are final)
  Late morning (10:00–12:59): generate today's picks if missing
  Evening (17:00–20:59):      capture closing lines for today
  Night (21:00–23:59):        optional second close pass (soft books)

Health log: data/ops/paper_trade_health.jsonl (one JSON object per line)
Summary:    data/ops/last_run_summary.json (latest snapshot for dashboards)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SPORT = "baseball_mlb"
SPORT_SHORT = "mlb"
FLAT_STAKE = 100.0

OPS_DIR = Path("data/ops")
HEALTH_LOG = OPS_DIR / "paper_trade_health.jsonl"
SUMMARY_JSON = OPS_DIR / "last_run_summary.json"


def _tz() -> ZoneInfo:
    name = __import__("os").environ.get("PAPER_TRADE_TZ", "America/New_York")
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/New_York")


def _now_local() -> datetime:
    return datetime.now(_tz())


def _picks_path(d: date) -> Path:
    return Path("output/picks") / SPORT / d.strftime("%Y%m%d") / "picks.json"


def log_health(event: dict[str, Any]) -> None:
    """Append one structured event to the health log."""
    OPS_DIR.mkdir(parents=True, exist_ok=True)
    event.setdefault("ts_utc", datetime.now(__import__("datetime").timezone.utc).isoformat())
    line = json.dumps(event, default=str) + "\n"
    with open(HEALTH_LOG, "a", encoding="utf-8") as f:
        f.write(line)

    snap = collect_snapshot()
    snap["last_event"] = event
    with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, default=str)


def collect_snapshot() -> dict[str, Any]:
    """Current P&L / CLV / today picks for dashboards."""
    out: dict[str, Any] = {"tz": str(_tz())}

    today = _now_local().date()
    picks_today = _picks_path(today)
    out["today"] = today.isoformat()
    out["picks_file_exists"] = picks_today.exists()
    out["picks_count_today"] = 0
    if picks_today.exists():
        try:
            with open(picks_today) as f:
                data = json.load(f)
            out["picks_count_today"] = len(data) if isinstance(data, list) else 0
        except Exception:
            pass

    try:
        from src.tracking.pnl import PnLTracker

        pnl = PnLTracker()
        s = pnl.get_summary()
        out["pnl"] = {
            "total_picks": s.get("total_picks", 0),
            "settled": s.get("settled_picks", 0),
            "wins": s.get("wins", 0),
            "losses": s.get("losses", 0),
            "win_rate": s.get("win_rate", 0),
            "roi": s.get("roi", 0),
            "units_profit": s.get("units_profit", 0),
        }
    except Exception as e:
        out["pnl_error"] = str(e)

    try:
        from src.tracking.clv import CLVTracker

        clv = CLVTracker()
        cs = clv.get_clv_summary(sport=SPORT_SHORT)
        out["clv"] = {
            "total_picks": cs.get("total_picks", 0),
            "with_closing_line": cs.get("with_closing_line", 0),
            "clv_mean_cents": cs.get("clv_mean_cents", 0),
        }
    except Exception as e:
        out["clv_error"] = str(e)

    # Days with picks
    root = Path("output/picks") / SPORT
    days = 0
    if root.exists():
        days = sum(1 for d in root.iterdir() if d.is_dir() and (d / "picks.json").exists())
    out["days_with_picks"] = days

    return out


def _run_morning(min_edge: float) -> dict[str, Any]:
    from src import paper_trade as pt

    class A:
        min_edge = min_edge

    pt.cmd_morning(A())
    return {"action": "morning", "ok": True}


def _run_close(for_date: date) -> dict[str, Any]:
    from src import paper_trade as pt

    class A:
        date = for_date.isoformat()

    pt.cmd_close(A())
    return {"action": "close", "date": for_date.isoformat(), "ok": True}


def _run_grade(for_date: date, no_closing: bool) -> dict[str, Any]:
    from src import paper_trade as pt

    class A:
        date = for_date.isoformat()
        no_closing = no_closing

    pt.cmd_grade(A())
    return {"action": "grade", "date": for_date.isoformat(), "ok": True}


def _run_report() -> dict[str, Any]:
    from src import paper_trade as pt

    class A:
        pass

    pt.cmd_report(A())
    return {"action": "report", "ok": True}


def decide_action(now: datetime | None = None) -> str | None:
    """
    Return one of: grade_yesterday | morning_if_missing | close_today | none

    Order matters: 10:00–12:59 = morning first; 00:00–09:59 = grade yesterday;
    17:00–23:59 = closing lines. (1am cron grades prior slate; 10:30am generates picks.)
    """
    now = now or _now_local()
    h = now.hour

    if 10 <= h <= 12:
        return "morning_if_missing"

    if 0 <= h <= 9:
        return "grade_yesterday"

    if 17 <= h <= 23:
        return "close_today"

    return None


def run_tick(
    min_edge: float = 0.03,
    force: str | None = None,
    no_closing: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Run at most one action based on clock + force flag.
    force: morning | close | grade-yesterday | report
    """
    now = _now_local()
    result: dict[str, Any] = {
        "local_time": now.isoformat(),
        "tz": str(now.tzinfo),
        "action_taken": None,
        "skipped": None,
        "error": None,
    }

    try:
        if force == "morning":
            action = "morning_force"
        elif force == "close":
            action = "close_today"
        elif force == "grade-yesterday":
            action = "grade_yesterday"
        elif force == "report":
            action = "report"
        elif force:
            raise ValueError(f"Unknown --force {force!r}")
        else:
            action = decide_action(now)

        if dry_run:
            result["would_run"] = action
            log_health({**result, "dry_run": True})
            return result

        if action is None:
            result["skipped"] = "outside_autopilot_windows"
            log_health(result)
            return result

        if action == "report":
            _run_report()
            result["action_taken"] = "report"
            log_health({**result, **collect_snapshot()})
            return result

        if action == "grade_yesterday":
            y = (now.date() - timedelta(days=1))
            if not _picks_path(y).exists() and force != "grade-yesterday":
                result["skipped"] = f"no picks file for {y.isoformat()}"
                log_health(result)
                return result
            _run_grade(y, no_closing=no_closing)
            result["action_taken"] = "grade"
            result["pick_date"] = y.isoformat()

        elif action == "morning_force":
            _run_morning(min_edge)
            result["action_taken"] = "morning"

        elif action == "morning_if_missing":
            today = now.date()
            if _picks_path(today).exists():
                result["skipped"] = "picks_already_exist"
                log_health(result)
                return result
            _run_morning(min_edge)
            result["action_taken"] = "morning"

        elif action == "close_today":
            today = now.date()
            if not _picks_path(today).exists() and force != "close":
                result["skipped"] = "no_picks_today_skip_close"
                log_health(result)
                return result
            _run_close(today)
            result["action_taken"] = "close"
            result["pick_date"] = today.isoformat()

        log_health({**result, **collect_snapshot()})
        return result

    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        log_health(result)
        raise


def cmd_health_tail(n: int = 30) -> None:
    if not HEALTH_LOG.exists():
        print("No health log yet. Run the autopilot once.")
        return
    lines = HEALTH_LOG.read_text(encoding="utf-8").strip().splitlines()
    for line in lines[-n:]:
        try:
            obj = json.loads(line)
            print(json.dumps(obj, indent=2)[:800])
            print("---")
        except json.JSONDecodeError:
            print(line)


def cmd_status() -> None:
    snap = collect_snapshot()
    print(json.dumps(snap, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="Paper trade autopilot + health logging")
    p.add_argument(
        "command",
        nargs="?",
        default="tick",
        choices=["tick", "health", "status", "summary", "morning", "close", "grade-yesterday", "report"],
        help="tick=auto by time; health=tail log; summary=validation; manual steps",
    )
    p.add_argument("--min-edge", type=float, default=0.03)
    p.add_argument(
        "--force",
        type=str,
        default=None,
        choices=["morning", "close", "grade-yesterday", "report"],
        help="With tick: run this step regardless of clock",
    )
    p.add_argument("--no-closing", action="store_true", help="Pass to grade step")
    p.add_argument("--dry-run", action="store_true", help="Log what would run, do nothing")
    p.add_argument("--tail", type=int, default=20, help="Lines for health command")
    args = p.parse_args()

    if args.command == "tick":
        try:
            r = run_tick(
                min_edge=args.min_edge,
                force=args.force,
                no_closing=args.no_closing,
                dry_run=args.dry_run,
            )
            print(json.dumps(r, indent=2, default=str))
        except Exception:
            sys.exit(1)
        return

    if args.command == "health":
        cmd_health_tail(args.tail)
        return

    if args.command == "status":
        cmd_status()
        return

    if args.command == "summary":
        from src.validation.stats import validate, print_validation

        v = validate(flat_stake=FLAT_STAKE)
        print(print_validation(v))
        return

    if args.command == "morning":
        ev = {"manual": "morning"}
        try:
            _run_morning(args.min_edge)
            ev["ok"] = True
        except Exception as e:
            ev["error"] = str(e)
            log_health(ev)
            raise
        log_health({**ev, **collect_snapshot()})
        return

    if args.command == "close":
        today = _now_local().date()
        ev = {"manual": "close", "date": today.isoformat()}
        try:
            _run_close(today)
            ev["ok"] = True
        except Exception as e:
            ev["error"] = str(e)
            log_health(ev)
            raise
        log_health({**ev, **collect_snapshot()})
        return

    if args.command == "grade-yesterday":
        y = _now_local().date() - timedelta(days=1)
        ev = {"manual": "grade-yesterday", "date": y.isoformat()}
        try:
            _run_grade(y, args.no_closing)
            ev["ok"] = True
        except Exception as e:
            ev["error"] = str(e)
            log_health(ev)
            raise
        log_health({**ev, **collect_snapshot()})
        return

    if args.command == "report":
        try:
            _run_report()
        finally:
            log_health({"manual": "report", **collect_snapshot()})


if __name__ == "__main__":
    main()
