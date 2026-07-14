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

Usage: python3 scripts/grade_backlog.py [--dry-run]
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta
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


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().replace("&", "and").strip()


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
    seen, out = set(), []
    for info in games.values():
        gid = (info["away"], info["home"])
        if gid in seen:
            continue
        seen.add(gid)
        if _pick_matches_game(pick, info):
            out.append(info)
    return out


def _find_game(pick: dict, boards: list[tuple[str, dict]]):
    """Locate the pick's game across (date, games_dict) boards.

    Prefer the pick's own date; fall back to adjacent days only when the
    matchup identifies exactly one game there — teams play daily in MLB, so
    a multi-day match must be unique to be trusted.
    """
    pick_date = pick["date"].replace("-", "")
    exact = [g for day, games in boards if day == pick_date for g in _hits_on(pick, games)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:  # doubleheader — same matchup twice on the day, ambiguous
        return None
    adjacent = [g for day, games in boards if day != pick_date for g in _hits_on(pick, games)]
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
    hits = [g for _day, games in boards for g in _hits_on(pick, games)]
    return hits[0] if len(hits) == 1 else None


def _settle(pick: dict, info: dict) -> str | None:
    """Settle any market this sweep supports. Returns result or None."""
    market = pick.get("market")
    if market in ("moneyline", "spread", "total", "puck_line", "run_line", "runline"):
        if market == "runline":
            pick = pick  # _settle_game_pick handles run_line; runline shares logic via spread branch
        return grade._settle_game_pick(pick, info)

    now = datetime.now(grade.timezone.utc).isoformat()
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
    """ESPN UFC scoreboard → {fighter_name_lower: 'win'|'loss'} for one date."""
    import requests
    try:
        r = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard",
            params={"dates": date_str}, headers={"User-Agent": "Mozilla/5.0"}, timeout=12,
        )
        if r.status_code != 200:
            return {}
        out: dict[str, str] = {}
        for ev in r.json().get("events", []):
            for comp in ev.get("competitions", []):
                if not comp.get("status", {}).get("type", {}).get("completed"):
                    continue
                for c in comp.get("competitors", []):
                    name = c.get("athlete", {}).get("displayName", "")
                    if name and c.get("winner") is not None:
                        out[_norm(name)] = "win" if c.get("winner") else "loss"
        return out
    except Exception:
        return {}


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

    def _board(source: str, day: str) -> dict:
        key = (source, day)
        if key not in board_cache:
            if source == "mlb":
                _w, games = grade._fetch_scores(day)
                board_cache[key] = games or {}
            else:
                board_cache[key] = grade._fetch_scores_espn(source, day) or {}
        return board_cache[key]

    for p in sorted(stale, key=lambda x: x.get("date") or ""):
        sport = _norm(p.get("sport"))
        market = p.get("market")
        d = datetime.strptime(p["date"].replace("-", ""), "%Y%m%d")
        days = [(d + timedelta(days=off)).strftime("%Y%m%d") for off in (-1, 0, 1)]
        days = [x for x in days if x < cutoff or x <= datetime.now().strftime("%Y%m%d")]
        tag = f"{sport}/{market}"

        if sport in ("mlb", "baseball_mlb"):
            if market in grade._MLB_PROP_MARKETS:
                mlb_prop_dates.add(p["date"].replace("-", ""))
                continue
            boards = [(day, _board("mlb", day)) for day in days]
        elif sport in _SPORT_TO_ESPN:
            espn_key = _SPORT_TO_ESPN[sport]
            boards = [(day, _board(espn_key, day)) for day in days]
        elif sport.startswith("soccer_") and sport in grade._ESPN_SCOREBOARD_PATHS:
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

        info = _find_game(p, boards)
        if info is None and sport not in ("mlb", "baseball_mlb"):
            # Scanner-logged picks (WC, playoff series) can be dated weeks off.
            # Widen to a 4-week window; only a globally unique matchup counts.
            source = _SPORT_TO_ESPN.get(sport, sport)
            wide_days = [
                (d + timedelta(days=off)).strftime("%Y%m%d")
                for off in range(-2, 26)
            ]
            wide_days = [x for x in wide_days if x < cutoff]
            wide = [(day, _board(source, day)) for day in wide_days]
            info = _find_game_wide(p, wide)
        if info is None:
            unresolved[tag] += 1
            continue
        if _settle(p, info) is None:
            unresolved[tag] += 1
            continue
        graded[tag] += 1

    print("── Graded ──")
    for tag, n in sorted(graded.items()):
        print(f"  {tag:44} {n}")
    print("── Unresolved (left pending) ──")
    for tag, n in sorted(unresolved.items()):
        print(f"  {tag:44} {n}")
    if mlb_prop_dates:
        print(f"── MLB prop dates to grade: {sorted(mlb_prop_dates)}")

    if dry_run:
        print("Dry run — nothing saved.")
        return

    grade._save(data)
    for day in sorted(mlb_prop_dates):
        grade._grade_mlb_props(day)
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
    except Exception as e:
        print(f"[stats] {e}")
    print("Saved.")


if __name__ == "__main__":
    main()
