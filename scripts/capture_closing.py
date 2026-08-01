#!/usr/bin/env python3
"""
Per-game closing-line capture daemon.

Designed to run every 2 minutes via cron. For each upcoming game starting
within the next [3, 10] minutes, fetches that event's current odds and
appends to data/clv/closing/{sport}_{date}.json.

Captures regardless of whether picks were posted — every game's closing
line is archived for later CLV analysis on any pick we ever take on it.

Idempotent: once an event has been captured (by event_id), subsequent runs
skip it. To force a re-capture (e.g., line moved late), pass --force.

Usage:
    python3 scripts/capture_closing.py                # MLB + NBA
    python3 scripts/capture_closing.py --sport mlb
    python3 scripts/capture_closing.py --window 5     # ±5 min around tipoff
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make project root importable when run as a script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data.odds_api import (  # noqa: E402
    fetch_events_list, fetch_event_odds, OddsAPIUnavailable,
)


CLOSING_DIR = ROOT / "data" / "clv" / "closing"
LOG_FILE = ROOT / "logs" / "capture_closing.log"

SPORTS = {
    "mlb":     "baseball_mlb",
    "nba":     "basketball_nba",
    "nhl":     "icehockey_nhl",
    "wnba":    "basketball_wnba",
    "soccer":  "soccer_fifa_world_cup",
    # League soccer — closings when these resume (EXTRA markets already configured
    # below). Off-season keys return an empty events list (one cheap call), so
    # leaving them in costs nothing until games appear. Keyed by their FULL Odds
    # API key so the archive file (soccer_spain_la_liga_DATE.json) matches what
    # compute_clv looks up per snapshot — the short "soccer_" prefix is reserved
    # for the World Cup and would otherwise collide.
    "soccer_epl":                "soccer_epl",
    "soccer_spain_la_liga":      "soccer_spain_la_liga",
    "soccer_italy_serie_a":      "soccer_italy_serie_a",
    "soccer_germany_bundesliga": "soccer_germany_bundesliga",
    "soccer_france_ligue_one":   "soccer_france_ligue_one",
    "soccer_usa_mls":            "soccer_usa_mls",
    "soccer_mexico_ligamx":      "soccer_mexico_ligamx",
    # Added 2026-07-29. The dynamic event scanner had been logging picks for both
    # of these for weeks while capture never fetched their closings, so they sat
    # at 0/13 scored — a lane accruing a CLV sample it could never score, which
    # looks like patient progress and is actually a lane disqualifying itself.
    # tests/test_capture_coverage.py now fails the build if any sport logging
    # snapshots is missing from this dict, so the next league can't repeat it.
    "soccer_brazil_campeonato":  "soccer_brazil_campeonato",
    "soccer_korea_kleague1":     "soccer_korea_kleague1",
    "ufc":     "mma_mixed_martial_arts",
    "mma":     "mma_mixed_martial_arts",
    # American football, added 2026-07-31 — five weeks BEFORE kickoff, because
    # the soccer leagues above document what happens in the other order: picks
    # accrue, closings don't, and the lane disqualifies itself at 0/13 scored
    # while looking like patient progress. Off-season these keys return an
    # empty events list for one cheap call each.
    "nfl":     "americanfootball_nfl",
    "ncaaf":   "americanfootball_ncaaf",
    # NOTE: tennis is handled dynamically (see _active_tennis_keys) because it runs
    # many concurrent tournament keys that a static dict can't enumerate — each
    # match IS a normal event with a commence_time, so it captures like any game.
    # Golf is an outright (futures) market with no game-line commence time, so it
    # uses a separate tee-off outright capture (see capture_golf_outrights).
    "nascar":  "auto_racing_nascar_cup_series",
    "indycar": "auto_racing_indycar_series",
    "f1":      "auto_racing_formula_one",
}


def _active_tennis_keys() -> list[str]:
    """Currently active tennis tournament Odds API keys (e.g. tennis_atp_wimbledon).

    Tennis runs many concurrent tournaments, so we discover the live ones from the
    Odds API sports catalog (cached 24h by list_sports) rather than hard-coding a
    dict. Each returned key is captured like any other sport — one match per event,
    h2h closing at match time. Returns [] when the catalog is unavailable so the
    rest of the capture run proceeds unaffected.
    """
    try:
        from src.data.odds_api import list_sports
        df = list_sports()
        if df.empty or "key" not in df:
            return []
        active = df[df.get("active", False)] if "active" in df else df
        return sorted(k for k in active["key"] if str(k).startswith("tennis_"))
    except Exception:
        return []

# Base full-game markets captured for every sport.
_BASE_MARKETS = "h2h,spreads,totals"


def _base_markets_for(odds_api_sport: str) -> str:
    """Base markets to request per sport. Tennis only offers h2h reliably (and the
    model is moneyline), so requesting spreads/totals there just risks a 422 that
    could lose the h2h capture — keep it to h2h. Everything else gets the full set."""
    if odds_api_sport.startswith("tennis_"):
        return "h2h"
    return _BASE_MARKETS

# Sport-specific alternate markets (period/derivative + props). Per-event endpoint only.
# MLB: F5 + NRFI for period totals; pitcher_strikeouts for props.
# NBA: player props (points, rebounds, assists) so prop CLV finally gets coverage.
# Soccer: anytime scorer + alternate spreads for full WC CLV.
# MMA: method-of-victory + total_rounds for fight prop CLV.
# Each market widens the per-event call payload but the event count stays the
# same — the cost is "extra markets per call", not extra API calls.
# Measurement-first (2026-06-16): capture the full standard catalog per sport so
# CLV can eventually be read on every market, not just the 5 we model today.
# Props are the documented soft market — books set lower limits / pay them less
# attention — so we archive every available prop closing now, even for markets we
# don't yet bet, to build the closing-line history a future model validates against.
# These ride a SEPARATE per-event call from h2h/spreads/totals, so an unsupported
# key for a given sport degrades to "no props that event", never losing the base.
_SOCCER_EXTRA = ("alternate_spreads,alternate_totals,btts,draw_no_bet,double_chance,"
                 "player_goal_scorer_anytime,player_shots_on_target,player_shots,"
                 "player_assists")
_EXTRA_MARKETS = {
    "baseball_mlb": ("totals_1st_5_innings,totals_1st_1_innings,"
                     "pitcher_strikeouts,pitcher_hits_allowed,pitcher_walks,"
                     "pitcher_earned_runs,pitcher_outs,"
                     "batter_hits,batter_total_bases,batter_home_runs,batter_rbis,"
                     "batter_runs_scored,batter_walks,batter_strikeouts,"
                     "batter_stolen_bases,batter_singles,batter_doubles"),
    "basketball_nba": ("player_points,player_rebounds,player_assists,player_threes,"
                       "player_blocks,player_steals,player_turnovers,"
                       "player_points_rebounds_assists,player_points_rebounds,"
                       "player_points_assists,player_rebounds_assists,"
                       "player_double_double"),
    "basketball_wnba": ("player_points,player_rebounds,player_assists,player_threes,"
                        "player_blocks,player_steals,player_points_rebounds_assists"),
    "icehockey_nhl": ("player_points,player_goals,player_assists,player_shots_on_goal,"
                      "player_blocked_shots,player_power_play_points,"
                      "player_total_saves,player_goal_scorer_anytime"),
    "soccer_fifa_world_cup":       _SOCCER_EXTRA,
    "soccer_epl":                  _SOCCER_EXTRA,
    "soccer_spain_la_liga":        _SOCCER_EXTRA,
    "soccer_italy_serie_a":        _SOCCER_EXTRA,
    "soccer_germany_bundesliga":   _SOCCER_EXTRA,
    "soccer_france_ligue_one":     _SOCCER_EXTRA,
    "soccer_usa_mls":              _SOCCER_EXTRA,
    "soccer_mexico_ligamx":        _SOCCER_EXTRA,
    "mma_mixed_martial_arts":      "fight_result_method,total_rounds",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load_archive(sport_key: str, date_str: str) -> list[dict]:
    path = CLOSING_DIR / f"{sport_key}_{date_str}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return []


def _save_archive(sport_key: str, date_str: str, records: list[dict]) -> None:
    CLOSING_DIR.mkdir(parents=True, exist_ok=True)
    path = CLOSING_DIR / f"{sport_key}_{date_str}.json"
    path.write_text(json.dumps(records, indent=2))


def _log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


# A capture taken within this many minutes of kickoff is treated as the true
# CLOSING line and locked (no further re-capture). Earlier captures are kept only
# as a safety net and get UPGRADED to a closing-window capture when a later cron
# tick lands inside it — this is what turns "a line 90 min out" into the real close.
FINAL_WINDOW_MIN = 25.0


def _minutes_to_commence(commence_iso: str) -> float | None:
    """Minutes until kickoff (>0 = future, <0 = already started), or None."""
    try:
        ct = datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (ct - _now_utc()).total_seconds() / 60.0


def _within_window(commence_iso: str, lo_min: float, hi_min: float) -> bool:
    """Return True if commence_iso is between [now+lo_min, now+hi_min]."""
    delta_min = _minutes_to_commence(commence_iso)
    return delta_min is not None and lo_min <= delta_min <= hi_min


def capture_sport(
    sport_key: str,
    odds_api_sport: str,
    lo_min: float,
    hi_min: float,
    force: bool,
) -> int:
    """Capture closing odds for any game in the [lo_min, hi_min] window."""
    # refresh=False — use 1h cache. We only need to know game times once per hour,
    # not every 2 minutes. This prevents burning credits on empty event-list polls.
    events = fetch_events_list(sport=odds_api_sport, refresh=False)
    if not events:
        return 0

    today_str = _now_utc().date().isoformat()
    archive = _load_archive(sport_key, today_str)
    existing = {r.get("event_id"): r for r in archive}

    captured_now = 0
    for ev in events:
        ev_id = ev.get("id")
        if not ev_id:
            continue
        if not _within_window(ev.get("commence_time", ""), lo_min, hi_min):
            continue

        mins = _minutes_to_commence(ev.get("commence_time", ""))
        in_final_window = mins is not None and mins <= FINAL_WINDOW_MIN
        prior = existing.get(ev_id)
        if prior and not force:
            # Already captured. Re-capture ONLY to upgrade an early (safety-net)
            # line to the true closing line: skip if it's already locked as final,
            # or if we're not yet inside the closing window (keep the early capture).
            if prior.get("closing_final") or not in_final_window:
                continue

        # Base markets (h2h/spreads/totals) in their own call — these must never
        # be lost to an unsupported prop key, so capture + save them regardless of
        # whether the props call below succeeds.
        try:
            base_df = fetch_event_odds(
                event_id=ev_id,
                sport=odds_api_sport,
                markets=_base_markets_for(odds_api_sport),
                refresh=True,
            )
        except OddsAPIUnavailable:
            # Quota/auth failure is not a per-event problem to skip past: every
            # remaining event in this window will fail the same way, and
            # continuing would end the run green having archived nothing. Let it
            # reach main(), which exits non-zero so the alert fires.
            raise
        except Exception as e:
            _log(f"  ERROR fetching {sport_key} base markets {ev_id}: {e}")
            continue

        if base_df is None or base_df.empty:
            continue

        all_rows = base_df.to_dict(orient="records")

        # Props / period markets — separate call so a 422 on any one key only
        # costs that event's props, not the base capture. API bills per
        # market×region regardless of how calls are grouped, so cost is unchanged.
        extra = _EXTRA_MARKETS.get(odds_api_sport)
        if extra is None and odds_api_sport.startswith("tennis_"):
            # Tennis totals (games) — the totals model bets these, but the BASE
            # tennis capture is h2h-only (see _base_markets_for). Requesting
            # totals as an EXTRA keeps the 422 risk isolated: a tournament that
            # doesn't price totals loses only this call, never the h2h close.
            extra = "totals"
        if extra:
            try:
                extra_df = fetch_event_odds(
                    event_id=ev_id,
                    sport=odds_api_sport,
                    markets=extra,
                    refresh=True,
                )
                if extra_df is not None and not extra_df.empty:
                    all_rows += extra_df.to_dict(orient="records")
            except OddsAPIUnavailable:
                raise           # same reasoning as the base-markets call above
            except Exception as e:
                _log(f"  WARN props fetch failed {sport_key} {ev_id}: {e}")

        # Pull the best (most favorable) ML for each side from the base markets
        ml_rows = base_df[base_df["Market"] == "h2h"]
        home_ml = away_ml = None
        home_book = away_book = None
        if not ml_rows.empty:
            for _, r in ml_rows.iterrows():
                sel = str(r.get("Selection", ""))
                price = r.get("Odds")
                book = str(r.get("Sportsbook", ""))
                if sel == ev.get("home_team"):
                    if home_ml is None or price > home_ml:
                        home_ml, home_book = price, book
                elif sel == ev.get("away_team"):
                    if away_ml is None or price > away_ml:
                        away_ml, away_book = price, book

        record = {
            "event_id":      ev_id,
            "sport":         odds_api_sport,
            "home_team":     ev.get("home_team"),
            "away_team":     ev.get("away_team"),
            "commence_time": ev.get("commence_time"),
            "captured_at":   _now_utc().isoformat(),
            "mins_to_commence": round(mins, 1) if mins is not None else None,
            "closing_final": bool(in_final_window),  # True = locked as the true close
            "BestHomeML":    int(home_ml) if home_ml is not None else None,
            "BestAwayML":    int(away_ml) if away_ml is not None else None,
            "HomeBook":      home_book,
            "AwayBook":      away_book,
            "all_odds":      all_rows,
        }
        # Replace any prior capture for this event (force or closing-window upgrade)
        if ev_id in existing:
            archive = [r for r in archive if r.get("event_id") != ev_id]

        archive.append(record)
        existing[ev_id] = record
        captured_now += 1
        tag = "CLOSING" if in_final_window else "pre-game"
        matchup = f"{ev.get('away_team')} @ {ev.get('home_team')}"
        _log(f"  ✓ {sport_key.upper()} {tag} captured: {matchup} "
             f"({'%+.0f' % mins if mins is not None else '?'}m to start, event {ev_id[:8]})")

    if captured_now > 0:
        _save_archive(sport_key, today_str, archive)

    return captured_now


# Golf is a futures (outright winner) market — one tournament, no per-game
# commence time the game loop iterates. A tournament has ONE close: the board at
# first-round tee-off. We capture the outright winner board per active tournament
# and keep upgrading the day's archive until a capture lands inside the tee-off
# window, then lock it. compute_clv reads it tournament-scoped (across entry dates).
_GOLF_FINAL_WINDOW_MIN = 720.0  # within 12h of tee-off counts as the close


def _active_golf_keys() -> list[str]:
    """Active golf outright-winner Odds API keys (e.g. golf_the_open_championship_winner)."""
    try:
        from src.data.odds_api import list_sports
        df = list_sports()
        if df.empty or "key" not in df:
            return []
        active = df[df.get("active", False)] if "active" in df else df
        return sorted(k for k in active["key"]
                      if str(k).startswith("golf_") and str(k).endswith("_winner"))
    except Exception:
        return []


def capture_golf_outrights(force: bool) -> int:
    """Capture each active golf tournament's outright winner board as the close."""
    import requests
    from src.data.odds_api import _get_api_key, API_BASE, BOOKMAKERS
    api_key = _get_api_key()
    if not api_key or api_key == "your_key_here":
        return 0

    today_str = _now_utc().date().isoformat()
    captured = 0
    for sport in _active_golf_keys():
        archive = _load_archive(sport, today_str)
        if archive and archive[0].get("closing_final") and not force:
            continue  # today's close already locked
        try:
            resp = requests.get(
                f"{API_BASE}/sports/{sport}/odds",
                params={"apiKey": api_key, "bookmakers": BOOKMAKERS,
                        "markets": "outrights", "oddsFormat": "american"},
                timeout=30)
            if resp.status_code != 200:
                continue
            events = resp.json()
        except Exception as e:
            _log(f"  WARN golf outrights fetch failed {sport}: {e}")
            continue

        # Best (longest) price per player across books — mirrors get_best_golf_odds.
        best: dict[str, float] = {}
        commence = None
        for ev in events:
            commence = ev.get("commence_time") or commence
            for bk in ev.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    if mk.get("key") != "outrights":
                        continue
                    for oc in mk.get("outcomes", []):
                        name = str(oc.get("name") or "").strip()
                        price = oc.get("price")
                        if not name or price is None:
                            continue
                        p = float(price)
                        if name not in best or p > best[name]:
                            best[name] = p
        if not best:
            continue

        mins = _minutes_to_commence(commence) if commence else None
        in_final = mins is not None and mins <= _GOLF_FINAL_WINDOW_MIN
        record = {
            "sport":            sport,
            "commence_time":    commence,
            "captured_at":      _now_utc().isoformat(),
            "mins_to_commence": round(mins, 1) if mins is not None else None,
            "closing_final":    bool(in_final),
            # player_lower -> best american odds (the close-so-far board)
            "outrights":        {k.lower(): v for k, v in best.items()},
        }
        _save_archive(sport, today_str, [record])
        captured += 1
        tag = "CLOSING" if in_final else "pre-tee"
        _log(f"  ✓ GOLF {tag}: {sport} ({len(best)} players, "
             f"{('%+.0f' % mins) if mins is not None else '?'}m to tee)")

    return captured


def _preflight_quota() -> None:
    """Refuse to run blind: exit RED when the Odds API has no credits left.

    Delegates to src.data.quota so capture, line-movement and any future
    credit-spending script report the SAME cause with the SAME message. This was
    duplicated here first; one exhausted key then produced seven red runs across
    three workflows on 2026-07-30, each with a different-looking symptom.

    Closing lines cannot be backfilled — miss tonight's close and that CLV is
    gone permanently — so a run that CANNOT capture must exit non-zero rather
    than archive nothing and report success.
    """
    from src.data.quota import preflight_quota
    ok, _why = preflight_quota(log=_log)
    if not ok:
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=list(SPORTS.keys()) + ["tennis", "golf", "all"], default="all")
    ap.add_argument("--window", type=float, default=90.0,
                    help="Pre-game capture LEAD in minutes (default 90): capture any "
                         "game starting within this many minutes. A WIDE lead is what "
                         "makes capture survive GitHub's sporadic/late cron — the old "
                         "narrow ±20 band only worked with the laptop's every-2-min "
                         "cron; once that was removed, lagged GitHub ticks landed "
                         "between games and captured nothing (CLV went to 0). Capture "
                         "is idempotent (first run inside the band locks the line), so "
                         "this yields a consistent late-pre-game reference for CLV.")
    ap.add_argument("--force", action="store_true",
                    help="Re-capture even if event already in archive")
    args = ap.parse_args()

    _preflight_quota()

    # Pre-game band: from GRACE minutes after first pitch (lag grace) out to
    # --window minutes before start. delta = minutes until commence (>0 = future).
    GRACE = 5.0
    lo, hi = -GRACE, float(args.window)

    # Build (archive_key, odds_api_sport) pairs. Static sports come from SPORTS;
    # tennis is discovered dynamically — each active tournament key is its own
    # "sport" and its own archive file (tennis_atp_wimbledon_DATE.json), which is
    # exactly what compute_clv looks up per snapshot's tennis key.
    pairs: list[tuple[str, str]] = []
    if args.sport in ("all", "tennis"):
        for tk in _active_tennis_keys():
            pairs.append((tk, tk))
    if args.sport == "all":
        pairs += [(sk, SPORTS[sk]) for sk in SPORTS]
    elif args.sport != "tennis":
        pairs.append((args.sport, SPORTS[args.sport]))

    total = 0
    try:
        for sk, odds_sport in pairs:
            n = capture_sport(sk, odds_sport, lo, hi, args.force)
            total += n
    except OddsAPIUnavailable as e:
        # The preflight checks quota once, at startup. A key that dies MID-RUN
        # used to be invisible: the 401 was swallowed, a stale board came back,
        # and it was archived as the close. Now the run dies here instead —
        # loudly, non-zero, so the workflow's alert step opens an issue.
        _log(f"  FATAL: {e}")
        _log(f"  Captured {total} event(s) before the API became unavailable; "
             f"the rest of this window is LOST and cannot be backfilled.")
        sys.exit(2)

    # Golf outrights — separate futures capture (no per-game commence loop).
    if args.sport in ("all", "golf"):
        total += capture_golf_outrights(args.force)

    if total == 0:
        # Quiet run when nothing in window — keeps logs clean
        sys.exit(0)
    _log(f"  Total events captured this run: {total}")


if __name__ == "__main__":
    main()
