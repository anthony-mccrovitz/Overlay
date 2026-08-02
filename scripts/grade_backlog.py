#!/usr/bin/env python3
"""
Sweep ALL stale pending picks across every sport and grade what's resolvable.

Why picks go stale: the nightly grader only looks at yesterday's date, so any
pick that misses its one-night window (pipeline failure, sport-field drift,
wrong slate date from the pre-PR-#62 UTC bug) stays pending forever with no
alert. This sweep re-grades the whole backlog:

  - MLB game lines (moneyline/spread/total/nrfi/f5_total) via MLB Stats API,
    matching the pick's matchup across date -1/+0/+1.
  - MLB player props via grade._grade_mlb_props per missing date.
  - ESPN-scoreboard sports (NBA, WNBA, NHL, soccer leagues) same ±1 window.
  - MMA moneylines via ESPN's UFC scoreboard winner map.

Left alone on purpose: futures/outrights (need --winner), tennis (has its own
all-dates backlog grader), and picks from the last 2 days (nightly handles).

Anything still pending after 30 days that is *provably* ungradeable — a
phantom matchup no board ever carried, a prop whose stat type was never
recorded, a tennis match outside the results source — is voided with a
void_reason rather than left to sit as a fake open position forever. Voids
settle at 0 profit; nothing is ever guessed into a win or a loss.

Usage: python3 scripts/grade_backlog.py [--dry-run]
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grade  # noqa: E402

# pick["sport"] value → ESPN scoreboard key in grade._ESPN_SCOREBOARD_PATHS
_SPORT_TO_ESPN = {
    "nba":  "basketball_nba",
    "basketball_nba": "basketball_nba",
    "wnba": "basketball_wnba",
    "basketball_wnba": "basketball_wnba",
    "nhl":  "icehockey_nhl",
    "icehockey_nhl": "icehockey_nhl",
}
_GAME_LINE_MARKETS = ("moneyline", "spread", "total", "runline", "puck_line", "run_line")

# A pick this old that the sweep still can't resolve is not waiting on a slow
# data source — every source this sweep reads is complete well inside a month.
# Past this age an unresolvable pick is voided with a reason so it stops
# masquerading as an open position. See _terminal_void.
_TERMINAL_AGE_DAYS = 30
# Sports the sweep never grades (need --winner / a human); leave them alone.
_MANUAL_ONLY_PREFIXES = ("golf", "auto_racing")


def _norm(s: str) -> str:
    # Delegates — grade._norm_name is the one name-normalization implementation.
    return grade._norm_name(s)


def _matchup_teams(pick: dict) -> tuple[str, str]:
    """(away, home) from the matchup field, or ('','') if it isn't a pair."""
    mu = pick.get("matchup") or ""
    if "@" in mu:
        away, home = mu.split("@", 1)
        return _norm(away), _norm(home)
    return "", ""


def _toks(s: str) -> set[str]:
    """Word set for name comparison — hyphens split, filler words dropped, so
    'Bosnia & Herzegovina' == ESPN 'Bosnia-Herzegovina', 'DR Congo' == 'Congo DR'."""
    import re
    return set(re.split(r"[\s\-]+", s)) - {"and", "the", ""}


def _side_match(name: str, info: dict, side: str) -> bool:
    """Does `name` refer to info's home/away team under any ESPN alias?"""
    aliases = [_norm(a) for a in info.get(f"{side}_names") or [info[side]]]
    return any(
        name == a
        or (len(name) > 3 and (name in a or a in name))
        or (len(a) > 3 and a in name)
        or _toks(name) == _toks(a)
        for a in aliases
    )


def _pick_matches_game(pick: dict, info: dict) -> bool:
    away, home = _matchup_teams(pick)
    if away and home:
        return _side_match(away, info, "away") and _side_match(home, info, "home")
    team = _norm(pick.get("team", ""))
    # Opponent-only matchup (old MLB ML picks store just the opponent name)
    opp = _norm(pick.get("matchup", ""))
    names = {n for n in (team, opp) if n and not n.startswith(("over", "under"))}
    if not names:
        return False
    return all(_side_match(n, info, "away") or _side_match(n, info, "home")
               for n in names)


def _hits_on(pick: dict, games: dict) -> list[dict]:
    # Dedup includes the scoreline so a doubleheader (same pairing twice in
    # one day) yields TWO hits -> ambiguous -> stays pending. Identical-score
    # twins would collapse, but they settle identically so it's harmless.
    seen, out = set(), []
    for info in games.values():
        gid = (info["away"], info["home"], info["away_score"], info["home_score"])
        if gid in seen:
            continue
        seen.add(gid)
        if _pick_matches_game(pick, info):
            out.append(info)
    return out


def _find_game(pick: dict, boards: list[tuple[str, dict | None]]):
    """Locate the pick's game across (date, games_dict) boards.

    Prefer the pick's own date; fall back to adjacent days only when the
    matchup identifies exactly one game there — teams play daily in MLB, so
    a multi-day match must be unique to be trusted.

    A board of None means the fetch FAILED (unknown), not "no games". If the
    pick's own date is unknown, no fallback is allowed: an outage on the exact
    date must not let a same-matchup game from an adjacent day settle the pick.
    """
    pick_date = pick["date"].replace("-", "")
    exact_board = next((games for day, games in boards if day == pick_date), None)
    if exact_board is None:
        return None
    exact = _hits_on(pick, exact_board)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:  # doubleheader — same matchup twice on the day, ambiguous
        return None
    adjacent = [g for day, games in boards
                if day != pick_date and games is not None
                for g in _hits_on(pick, games)]
    if len(adjacent) == 1:
        return adjacent[0]
    return None


def _find_game_wide(pick: dict, boards: list[tuple[str, dict]]):
    """Wide-window lookup for scanner-logged picks whose stored date can be
    weeks off (e.g. every World Cup pick stamped with the scan date). Only
    trusts a match that is UNIQUE across the whole window and requires a full
    away@home matchup — repeated pairings (playoff series, MLB series) come
    back ambiguous and stay pending."""
    away, home = _matchup_teams(pick)
    if not (away and home):
        return None  # single-team match is never safe over a wide window
    hits = [g for _day, games in boards if games is not None
            for g in _hits_on(pick, games)]
    return hits[0] if len(hits) == 1 else None


def _settle(pick: dict, info: dict) -> str | None:
    """Settle any market this sweep supports. Returns result or None."""
    market = pick.get("market")
    if market in _GAME_LINE_MARKETS:
        return grade._settle_game_pick(pick, info)

    now = datetime.now(timezone.utc).isoformat()
    if market == "nrfi":
        h1, a1 = info.get("first_inning_home_runs"), info.get("first_inning_away_runs")
        if h1 is None or a1 is None:
            return None
        runs1 = int(h1) + int(a1)
        direction = (pick.get("direction") or "NRFI").upper()
        won = (runs1 == 0) if direction == "NRFI" else (runs1 > 0)
        pick["result"] = "win" if won else "loss"
        pick["profit"] = round(grade._profit(pick.get("stake") or 1.0, float(pick.get("odds") or 0), won), 4)
        pick["resulted_at"] = now
        pick["first_inning_runs"] = runs1
        return pick["result"]

    if market == "f5_total":
        if info.get("f5_home_runs") is None:
            return None
        f5 = int(info["f5_home_runs"]) + int(info["f5_away_runs"])
        line = float(pick.get("line") or 0)
        direction = (pick.get("direction") or "OVER").upper()
        if f5 == line:
            pick["result"], pick["profit"] = "push", 0.0
        else:
            won = (f5 > line) if direction == "OVER" else (f5 < line)
            pick["result"] = "win" if won else "loss"
            pick["profit"] = round(grade._profit(pick.get("stake") or 1.0, float(pick.get("odds") or 0), won), 4)
        pick["resulted_at"] = now
        return pick["result"]
    return None


def _fetch_mma_winners(date_str: str) -> dict[str, str]:
    """Delegates — grade._fetch_mma_winners_espn is the one ESPN winner map."""
    return grade._fetch_mma_winners_espn(date_str)


def _void_reason(pick: dict) -> str | None:
    """Why this pick can never be graded, or None if it might still resolve.

    Only reasons that are *provable* from the pick itself or from an exhausted
    search count. "The sweep failed today" is not one of them.
    """
    sport = _norm(pick.get("sport"))
    if any(sport.startswith(pfx) for pfx in _MANUAL_ONLY_PREFIXES):
        return None
    if pick.get("market") == "prop" and not pick.get("prop_market"):
        # The emitter never recorded which stat the line was on, and the team
        # field ("Ron Holland OVER 4.5") doesn't say. Points? Rebounds? Guessing
        # would fabricate a result, so this is unrecoverable by construction.
        return "prop_market_missing"
    if sport.startswith("tennis_"):
        # _grade_tennis_backlog re-reads tennis-data.co.uk on every run. A match
        # still absent a month on is outside the source's coverage — it only
        # carries main-draw results, not qualifying.
        return "source_coverage_gap"
    if sport in ("mma_mixed_martial_arts", "ufc", "mma"):
        # Graded off ESPN's UFC scoreboard by fighter name, not by matchup.
        # A fighter still missing a month on was on a card ESPN never carried
        # (regional/prelim), so there is no winner to look up.
        if pick.get("backlog_attempts", 0) >= 3:
            return "source_coverage_gap"
        return None
    if _matchup_teams(pick) == ("", ""):
        # Every remaining sport locates its game by "Away @ Home". Without a
        # pair there is nothing to search boards for.
        return "matchup_incomplete"
    if pick.get("backlog_attempts", 0) >= 3:
        # Three separate sweeps searched successfully-fetched boards around this
        # date and never landed a unique match. Either the game never happened
        # (phantom slate date) or the pairing stays ambiguous (doubleheader).
        # Both are terminal — neither resolves by waiting longer.
        return "unresolvable_after_retries"
    return None


def _terminal_void(picks: list[dict], dry_run: bool) -> dict[str, int]:
    """Void long-stale picks that are provably ungradeable, with a reason.

    Without this, an unresolvable pick sits pending forever: it inflates the
    open-position count, trips the stale-pending watchdog every night, and
    makes the sweep refetch boards for a game that never existed.
    """
    cutoff = datetime.now() - timedelta(days=_TERMINAL_AGE_DAYS)
    voided: dict[str, int] = defaultdict(int)
    now_iso = datetime.now(timezone.utc).isoformat()

    for p in picks:
        if p.get("result") not in (None, "pending") or p.get("odds") is None:
            continue
        try:
            d = datetime.strptime((p.get("date") or "").replace("-", ""), "%Y%m%d")
        except ValueError:
            continue
        if d >= cutoff:
            continue
        reason = _void_reason(p)
        if reason is None:
            continue
        voided[f"{_norm(p.get('sport'))}/{p.get('market')} — {reason}"] += 1
        if not dry_run:
            p["result"], p["profit"] = "void", 0.0
            p["resulted_at"] = now_iso
            p["void_reason"] = reason
    return voided


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y%m%d")

    data = grade._load()
    stale = [
        p for p in data["picks"]
        if p.get("result") in (None, "pending")
        and p.get("odds") is not None
        and (p.get("date") or "").replace("-", "") < cutoff
    ]
    if not stale:
        print("No stale pending picks. ✨")
        return

    graded = defaultdict(int)
    unresolved = defaultdict(int)
    board_cache: dict[tuple[str, str], dict] = {}
    mma_cache: dict[str, dict[str, str]] = {}
    mlb_prop_dates: set[str] = set()
    scorer_dates: set[str] = set()

    def _board(source: str, day: str) -> dict | None:
        """Games for one source+day. None = fetch failed (unknown), {} = no games."""
        key = (source, day)
        if key not in board_cache:
            if source == "mlb":
                # MLB Stats API covers any historical date and carries the
                # inning data NRFI/F5 need. (grade._fetch_scores also hits the
                # paid, date-independent Odds API scores endpoint — pure waste
                # for backlog dates, so call the free per-date API directly.)
                day_dashed = f"{day[:4]}-{day[4:6]}-{day[6:]}"
                games = grade._fetch_scores_mlb_api(day_dashed)
                # Can't distinguish outage from off-day here; MLB plays daily
                # in-season, so treat an empty board as unknown (conservative).
                board_cache[key] = games or None
            else:
                board_cache[key] = grade._fetch_scores_espn(source, day)
        return board_cache[key]

    today_compact = datetime.now().strftime("%Y%m%d")
    for p in sorted(stale, key=lambda x: x.get("date") or ""):
        sport = _norm(p.get("sport"))
        market = p.get("market")
        tag = f"{sport}/{market}"
        try:
            d = datetime.strptime((p.get("date") or "").replace("-", ""), "%Y%m%d")
        except ValueError:
            print(f"  ⚠️ unparseable date on {p.get('pick_id') or p.get('team')} — skipping")
            unresolved[tag] += 1
            continue
        days = [(d + timedelta(days=off)).strftime("%Y%m%d") for off in (-1, 0, 1)]
        days = [x for x in days if x <= today_compact]

        if sport in ("mlb", "baseball_mlb"):
            if market in grade._MLB_PROP_MARKETS:
                mlb_prop_dates.add(p["date"].replace("-", ""))
                continue
            boards = [(day, _board("mlb", day)) for day in days]
        elif sport in _SPORT_TO_ESPN:
            espn_key = _SPORT_TO_ESPN[sport]
            boards = [(day, _board(espn_key, day)) for day in days]
        elif sport.startswith("soccer_") and sport in grade._ESPN_SCOREBOARD_PATHS:
            if market == "anytime_scorer":
                # Needs per-goal minutes from match summaries, not the board.
                scorer_dates.add(p["date"].replace("-", ""))
                continue
            boards = [(day, _board(sport, day)) for day in days]
        elif sport in ("mma_mixed_martial_arts", "ufc", "mma"):
            if market != "moneyline":
                unresolved[tag] += 1
                continue
            won = None
            for day in days:
                if day not in mma_cache:
                    mma_cache[day] = _fetch_mma_winners(day)
                res = mma_cache[day].get(_norm(p.get("team")))
                if res is None:  # last-name fallback
                    last = _norm(p.get("team")).split()[-1] if _norm(p.get("team")).split() else ""
                    matches = [v for k, v in mma_cache[day].items()
                               if last and len(last) > 3 and k.split()[-1] == last]
                    res = matches[0] if len(matches) == 1 else None
                if res is not None:
                    won = res == "win"
                    break
            if won is None:
                p["backlog_attempts"] = p.get("backlog_attempts", 0) + 1
                unresolved[tag] += 1
                continue
            p["result"] = "win" if won else "loss"
            p["profit"] = round(grade._profit(p.get("stake") or 1.0, float(p["odds"]), won), 4)
            p["resulted_at"] = datetime.now(grade.timezone.utc).isoformat()
            graded[tag] += 1
            continue
        else:
            # tennis (own backlog grader), golf/futures (need --winner), unknown
            unresolved[tag] += 1
            continue

        if market not in _GAME_LINE_MARKETS + ("nrfi", "f5_total"):
            unresolved[tag] += 1
            continue

        try:
            info = _find_game(p, boards)
            if (info is None
                    and sport not in ("mlb", "baseball_mlb")
                    and _matchup_teams(p) != ("", "")     # wide needs a full away@home
                    and p.get("backlog_attempts", 0) < 3):
                # Scanner-logged picks (WC, playoff series) can be dated weeks
                # off. Widen to a 4-week window; only a globally unique matchup
                # counts. Capped at 3 sweeps per pick — a pick still unmatched
                # after that is a phantom/ambiguous pairing, and refetching 28
                # scoreboards for it every night forever is pure waste.
                source = _SPORT_TO_ESPN.get(sport, sport)
                wide_days = [
                    (d + timedelta(days=off)).strftime("%Y%m%d")
                    for off in range(-2, 26)
                ]
                wide_days = [x for x in wide_days if x < cutoff]
                wide = [(day, _board(source, day)) for day in wide_days]
                info = _find_game_wide(p, wide)
        except Exception as e:
            # One malformed pick must not kill the whole nightly sweep.
            print(f"  ⚠️ sweep error on {p.get('pick_id') or p.get('team')}: {e}")
            unresolved[tag] += 1
            continue
        if info is None or _settle(p, info) is None:
            # Count every sweep that failed to settle this pick, not just the
            # wide-search path — _void_reason reads this to decide when the
            # search is exhausted, and it has to mean the same thing for every
            # sport (MLB never runs the wide search at all).
            p["backlog_attempts"] = p.get("backlog_attempts", 0) + 1
            unresolved[tag] += 1
            continue
        graded[tag] += 1

    print("── Graded ──")
    for tag, n in sorted(graded.items()):
        print(f"  {tag:44} {n}")
    print("── Unresolved (left pending) ──")
    for tag, n in sorted(unresolved.items()):
        print(f"  {tag:44} {n}")

    voided = _terminal_void(data["picks"], dry_run)
    if voided:
        print(f"── Voided (ungradeable, >{_TERMINAL_AGE_DAYS}d old) ──")
        for tag, n in sorted(voided.items()):
            print(f"  {tag:60} {n}")
    if mlb_prop_dates:
        print(f"── MLB prop dates to grade: {sorted(mlb_prop_dates)}")
    if scorer_dates:
        print(f"── Soccer scorer dates to grade: {sorted(scorer_dates)}")

    if dry_run:
        print("Dry run — nothing saved.")
        return

    grade._save(data)
    for day in sorted(mlb_prop_dates):
        grade._grade_mlb_props(day)
    for day in sorted(scorer_dates):
        grade._grade_soccer_scorers(day)
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
    except Exception as e:
        print(f"[stats] {e}")
    print("Saved.")


if __name__ == "__main__":
    main()
