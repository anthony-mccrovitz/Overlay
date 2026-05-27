#!/usr/bin/env python3
"""
scripts/bet_gates.py — Bet trigger checker

Checks whether time-sensitive triggers have fired for today's pending picks:
  - NBA / WNBA : inactives posted (via ESPN API, ~T-90min before tip)
  - NHL        : starting goalies confirmed (via ESPN, ~T-120min)
  - MLB        : confirmed batting lineups (via MLB Stats API, ~T-60min)

Prints a clear "🟢 BET NOW" or "⏳ HOLD" for each pending pick.

Usage:
    python3 scripts/bet_gates.py              # check all sports today
    python3 scripts/bet_gates.py --sport nba  # NBA only
    python3 scripts/bet_gates.py --sport nhl
    python3 scripts/bet_gates.py --sport mlb

Cron (run multiple times in the evening as triggers fire):
    0 17,18,19,20 * * * cd /path && python3 scripts/bet_gates.py >> logs/gates.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────── NBA / WNBA Inactives ────────────────────────────

def check_nba_inactives(sport: str = "nba") -> dict[str, list[str]]:
    """
    Check ESPN scoreboard for games where inactives have been posted.
    Returns {matchup_key: [inactive_player_names]} for games with confirmed inactives.
    """
    league = "nba" if sport == "nba" else "wnba"
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{league}/scoreboard"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ⚠  ESPN {sport.upper()} scoreboard fetch failed: {e}")
        return {}

    inactives_by_game: dict[str, list[str]] = {}
    now = datetime.now(timezone.utc)

    for event in data.get("events", []):
        name = event.get("name", "")
        commence_str = event.get("date", "")
        status_desc  = event.get("status", {}).get("type", {}).get("description", "")

        # Parse game time
        try:
            commence = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
        except Exception:
            continue

        mins_until = (commence - now).total_seconds() / 60

        # Check game injuries/inactives via competitions
        comp = event.get("competitions", [{}])[0]
        injuries_present = []

        for team in comp.get("competitors", []):
            team_name = team.get("team", {}).get("displayName", "")
            roster    = team.get("roster", []) or []
            for player in roster:
                status = player.get("status", {}).get("type", {}).get("name", "")
                if status in ("Out", "Questionable", "Doubtful"):
                    pname = player.get("athlete", {}).get("displayName", "?")
                    injuries_present.append(f"{pname} ({team_name}) — {status}")

        # If game is within 3 hours and has injury data, inactives are likely posted
        if mins_until <= 180:
            key = name
            inactives_by_game[key] = injuries_present
            if injuries_present:
                print(f"  📋 {name} — inactives posted ({len(injuries_present)} players)")
            else:
                if mins_until <= 90:
                    print(f"  📋 {name} — T-{int(mins_until)}min, no inactives yet (healthy roster or not posted)")
                else:
                    print(f"  ⏳ {name} — T-{int(mins_until)}min, too early for inactives")

    return inactives_by_game


# ─────────────────────────── NHL Starting Goalies ────────────────────────────

def check_nhl_goalies() -> dict[str, dict]:
    """
    Check ESPN for NHL games where starting goalies are confirmed.
    Returns {matchup: {home_goalie, away_goalie, confirmed}} for each game.
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ⚠  ESPN NHL scoreboard fetch failed: {e}")
        return {}

    goalies: dict[str, dict] = {}
    now = datetime.now(timezone.utc)

    for event in data.get("events", []):
        name = event.get("name", "")
        commence_str = event.get("date", "")
        status_desc  = event.get("status", {}).get("type", {}).get("description", "")

        try:
            commence = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
        except Exception:
            continue

        mins_until = (commence - now).total_seconds() / 60

        # Look for probable goalies in competition notes / headlines
        comp       = event.get("competitions", [{}])[0]
        notes      = comp.get("notes", [])
        headlines  = event.get("headlines", []) or []

        home_goalie, away_goalie, confirmed = None, None, False

        # Parse competitor roster for goalies
        for team in comp.get("competitors", []):
            is_home  = team.get("homeAway") == "home"
            roster   = team.get("roster", []) or []
            for player in roster:
                pos = player.get("position", {}).get("abbreviation", "")
                if pos == "G":
                    starter = player.get("starter", False)
                    if starter:
                        pname = player.get("athlete", {}).get("displayName", "?")
                        if is_home:
                            home_goalie = pname
                        else:
                            away_goalie = pname
                        confirmed = True

        result = {
            "home_goalie": home_goalie,
            "away_goalie": away_goalie,
            "confirmed":   confirmed,
            "mins_until":  int(mins_until),
        }
        goalies[name] = result

        if confirmed:
            print(f"  🥅 {name} — goalies confirmed: {home_goalie} vs {away_goalie}  ✅ BET TOTALS")
        elif mins_until <= 120:
            print(f"  ⏳ {name} — T-{int(mins_until)}min, goalies NOT confirmed yet — HOLD totals")
        else:
            print(f"  ⏳ {name} — T-{int(mins_until)}min, too early for goalie confirmation")

    return goalies


# ─────────────────────────── MLB Lineups ─────────────────────────────────────

def check_mlb_lineups() -> dict[str, bool]:
    """
    Check MLB Stats API for confirmed batting lineups.
    Returns {matchup: lineup_confirmed} for each scheduled game today.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    url   = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}&hydrate=lineups"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ⚠  MLB Stats API fetch failed: {e}")
        return {}

    lineup_status: dict[str, bool] = {}
    now = datetime.now(timezone.utc)

    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            home = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
            away = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "")
            matchup = f"{away} @ {home}"

            game_time_str = game.get("gameDate", "")
            try:
                game_time = datetime.fromisoformat(game_time_str.replace("Z", "+00:00"))
            except Exception:
                game_time = None

            mins_until = int((game_time - now).total_seconds() / 60) if game_time else 999

            lineups = game.get("lineups", {})
            home_lineup = lineups.get("homePlayers", [])
            away_lineup = lineups.get("awayPlayers", [])
            confirmed   = len(home_lineup) >= 8 and len(away_lineup) >= 8

            lineup_status[matchup] = confirmed

            if confirmed:
                home_sp = home_lineup[0].get("fullName", "?") if home_lineup else "?"
                print(f"  ✅ {matchup} — lineups confirmed  ✅ BET TOTALS/PROPS")
            elif mins_until <= 90:
                print(f"  ⏳ {matchup} — T-{mins_until}min, lineups NOT posted yet")
            else:
                print(f"  ⏳ {matchup} — T-{mins_until}min, too early for lineups")

    return lineup_status


# ─────────────────────────── Main gate check ─────────────────────────────────

def load_pending_card_picks(sport_filter: str | None = None) -> list[dict]:
    """Load today's unresulted card picks, optionally filtered by sport."""
    pnl = ROOT / "data" / "pnl" / "picks.json"
    if not pnl.exists():
        return []
    try:
        raw = json.loads(pnl.read_text())
        picks = raw if isinstance(raw, list) else raw.get("picks", [])
    except Exception:
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    for p in picks:
        if not p.get("card_pick"):
            continue
        if not str(p.get("date", "")).startswith(today):
            continue
        if p.get("result"):
            continue
        sport = p.get("sport", "")
        if sport_filter and sport_filter.lower() not in sport.lower():
            continue
        out.append(p)
    return out


def run_gates(sport_filter: str | None = None) -> None:
    """Run all applicable gates and print BET NOW / HOLD for each pick."""
    from scripts.timing_config import get_timing

    sep = "═" * 64
    now = datetime.now().strftime("%Y-%m-%d %H:%M ET")
    print(f"\n  {sep}")
    print(f"  BET GATES CHECK — {now}")
    print(f"  {sep}\n")

    pending = load_pending_card_picks(sport_filter)
    if not pending:
        print(f"  ℹ  No pending card picks found for today.\n")
        return

    # Group by sport
    by_sport: dict[str, list[dict]] = {}
    for p in pending:
        s = p.get("sport", "unknown")
        by_sport.setdefault(s, []).append(p)

    # Fetch triggers once per relevant sport
    nba_inactives  = {}
    wnba_inactives = {}
    nhl_goalies    = {}
    mlb_lineups    = {}

    sports_present = set(by_sport.keys())

    if any("nba" in s for s in sports_present):
        print("  ── NBA Inactives Check ──────────────────────────────────")
        nba_inactives = check_nba_inactives("nba")
        print()

    if any("wnba" in s for s in sports_present):
        print("  ── WNBA Inactives Check ─────────────────────────────────")
        wnba_inactives = check_nba_inactives("wnba")
        print()

    if any("nhl" in s for s in sports_present):
        print("  ── NHL Goalie Check ─────────────────────────────────────")
        nhl_goalies = check_nhl_goalies()
        print()

    if any("mlb" in s for s in sports_present):
        print("  ── MLB Lineup Check ─────────────────────────────────────")
        mlb_lineups = check_mlb_lineups()
        print()

    # Now print per-pick verdict
    print(f"  {'═'*64}")
    print(f"  PICK-BY-PICK BET STATUS")
    print(f"  {'─'*64}")

    for sport, picks in sorted(by_sport.items()):
        cfg        = get_timing(sport)
        bet_ready  = cfg.get("bet_ready", "open")
        trig_mkts  = cfg.get("trigger_markets", [])
        trig_type  = cfg.get("trigger_type")

        print(f"\n  {sport.upper()}")

        for p in picks:
            market   = p.get("market", "")
            team     = p.get("team", "")[:28]
            matchup  = p.get("matchup", "")
            odds     = p.get("odds", 0)
            edge     = p.get("edge_pct", 0)
            odds_str = f"+{odds}" if odds > 0 else str(odds)

            # Determine if this pick needs a trigger
            needs_trigger = (
                bet_ready == "trigger" or
                (bet_ready == "split" and market in trig_mkts) or
                ("all" in trig_mkts and trig_type is not None)
            )

            if not needs_trigger:
                verdict = "✅ BET NOW"
            else:
                # Check actual trigger status
                trigger_fired = False

                if trig_type == "inactives":
                    # Check if the relevant game has inactives posted
                    inact = nba_inactives if "nba" in sport else wnba_inactives
                    for game_name, inactive_list in inact.items():
                        # Fuzzy match on team names in matchup
                        if any(t in game_name for t in matchup.split(" @ ")):
                            trigger_fired = True
                            break
                    # Fallback: time-based (T-90min)
                    if not trigger_fired:
                        # Check game time from picks
                        # We don't always have game time in picks, so use time-of-day heuristic
                        now_hour = datetime.now().hour
                        if now_hour >= 17:  # after 5 PM, inactives usually posted
                            trigger_fired = True

                elif trig_type == "goalie":
                    for game_name, info in nhl_goalies.items():
                        if any(t in game_name for t in matchup.split(" @ ")):
                            trigger_fired = info.get("confirmed", False)
                            break

                elif trig_type == "lineup":
                    for game_matchup, confirmed in mlb_lineups.items():
                        if any(t in game_matchup for t in matchup.split(" @ ")):
                            trigger_fired = confirmed
                            break

                if trigger_fired:
                    verdict = f"✅ BET NOW  (trigger: {trig_type} ✓)"
                else:
                    verdict = f"⏳ HOLD     (waiting: {trig_type})"

            print(f"    {verdict:<42}  {team:<28}  {odds_str:<7} edge {edge:.1f}%")

    print(f"\n  {'═'*64}")
    print(f"  Re-run 'python3 chef.py gates' to refresh trigger status.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check bet timing triggers")
    parser.add_argument("--sport", default=None,
                        help="Filter to a specific sport (nba, nhl, mlb, wnba)")
    args = parser.parse_args()
    run_gates(args.sport)


if __name__ == "__main__":
    main()
