#!/usr/bin/env python3
"""
ChefTonyBets — Grading Script
Run this each evening after games finish.

Usage:
    python3 grade.py              # auto-grade yesterday's pending picks via Odds API
    python3 grade.py --date 20260408   # auto-grade a specific date
    python3 grade.py --manual     # interactive W/L prompts (fallback)
    python3 grade.py win "Team"   # quick single result
    python3 grade.py loss "Team"  # quick single result
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_FILE = Path("data/pnl/picks.json")


def _load():
    if not DATA_FILE.exists():
        return {"picks": []}
    return json.loads(DATA_FILE.read_text())


def _save(data):
    DATA_FILE.write_text(json.dumps(data, indent=2))


def _profit(stake: float, odds: float, won: bool) -> float:
    if not won:
        return -stake
    if not odds or odds == 0:
        return 0.0
    if odds > 0:
        return stake * odds / 100
    return stake * 100 / abs(odds)


def _fetch_scores(date_str: str) -> tuple[dict[str, str], dict[str, dict]]:
    """
    Fetch completed MLB game results for a given date (YYYYMMDD).

    Returns:
        winners  — {team_name: winner_name}   (for moneyline grading)
        games    — {team_name: {home, away, home_score, away_score, total, winner}}
                   (for totals/spread grading — keyed by BOTH team names)
    """
    try:
        import requests
    except ImportError:
        print("  requests not installed — cannot auto-grade")
        return {}, {}

    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ODDS_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
    if not api_key:
        print("  ODDS_API_KEY not found — cannot auto-grade")
        return {}, {}

    # Try MLB Stats API first for dates older than 3 days (Odds API daysFrom max = 3)
    date_dashed = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    mlb_games = _fetch_scores_mlb_api(date_dashed)

    # Also try Odds API (covers last 3 days)
    odds_games = {}
    try:
        resp = requests.get(
            "https://api.the-odds-api.com/v4/sports/baseball_mlb/scores/",
            params={"apiKey": api_key, "daysFrom": 2, "dateFormat": "iso"},
            timeout=10,
        )
        if resp.status_code == 200:
            for game in resp.json():
                if not game.get("completed") or not game.get("scores"):
                    continue
                commence = game.get("commence_time", "")
                try:
                    dt_utc = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                    dt_et  = dt_utc - timedelta(hours=4)
                    game_date = dt_et.strftime("%Y%m%d")
                except Exception:
                    game_date = commence[:10].replace("-", "")
                if game_date != date_str:
                    continue
                scores = {s["name"]: int(s["score"]) for s in game["scores"]}
                teams  = list(scores.keys())
                if len(teams) < 2:
                    continue
                away_team, home_team = teams[0], teams[1]
                away_score = scores[away_team]
                home_score = scores[home_team]
                winner = away_team if away_score > home_score else home_team
                game_info = {
                    "home": home_team, "away": away_team,
                    "home_score": home_score, "away_score": away_score,
                    "total": home_score + away_score,
                    "winner": winner,
                    "margin": abs(home_score - away_score),
                }
                odds_games[home_team] = game_info
                odds_games[away_team] = game_info
    except Exception as e:
        print(f"  [grade] Odds API scores: {e}")

    # Merge: Odds API wins on team name format, but preserve MLB API inning/F5 fields
    # that Odds API doesn't provide (first_inning_*, f5_*).
    games = {}
    all_teams = set(mlb_games) | set(odds_games)
    for team in all_teams:
        if team in odds_games and team in mlb_games:
            merged = dict(odds_games[team])
            for k, v in mlb_games[team].items():
                if merged.get(k) is None and v is not None:
                    merged[k] = v
            games[team] = merged
        else:
            games[team] = odds_games.get(team) or mlb_games[team]
    winners = {team: info["winner"] for team, info in games.items()}
    return winners, games


def _fetch_scores_mlb_api(date_dashed: str) -> dict[str, dict]:
    """Fetch scores from MLB Stats API (covers any historical date).

    Includes per-inning runs from linescore so we can grade NRFI / F5 markets
    in addition to game-line markets.
    """
    try:
        import requests
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_dashed,
                    "hydrate": "linescore", "gameType": "R,F,D,L,W,S"},
            timeout=15,
        )
        if resp.status_code != 200:
            return {}
        games = {}
        for date_entry in resp.json().get("dates", []):
            for g in date_entry.get("games", []):
                state = g.get("status", {}).get("abstractGameState", "")
                if state != "Final":
                    continue
                away_team  = g["teams"]["away"]["team"]["name"]
                home_team  = g["teams"]["home"]["team"]["name"]
                away_score = int(g["teams"]["away"].get("score", 0) or 0)
                home_score = int(g["teams"]["home"].get("score", 0) or 0)
                winner = away_team if away_score > home_score else home_team

                # Per-inning runs for NRFI / F5 grading
                innings = g.get("linescore", {}).get("innings", [])
                first_home = first_away = None
                f5_home = f5_away = None
                if innings:
                    inn1 = innings[0] if len(innings) >= 1 else {}
                    first_home = (inn1.get("home") or {}).get("runs")
                    first_away = (inn1.get("away") or {}).get("runs")
                    if len(innings) >= 5:
                        f5_home = sum(int((inn.get("home") or {}).get("runs", 0) or 0) for inn in innings[:5])
                        f5_away = sum(int((inn.get("away") or {}).get("runs", 0) or 0) for inn in innings[:5])

                info = {
                    "home": home_team, "away": away_team,
                    "home_score": home_score, "away_score": away_score,
                    "total": home_score + away_score,
                    "winner": winner,
                    "margin": abs(home_score - away_score),
                    "first_inning_home_runs": int(first_home) if first_home is not None else None,
                    "first_inning_away_runs": int(first_away) if first_away is not None else None,
                    "f5_home_runs": f5_home,
                    "f5_away_runs": f5_away,
                }
                games[home_team] = info
                games[away_team] = info
        return games
    except Exception:
        return {}


def _norm_date(d: str) -> str:
    """Normalize a date string to YYYYMMDD regardless of input format."""
    return d.replace("-", "")


_PITCHER_KS_CACHE: dict[tuple[str, str], int | None] = {}
_NBA_PROP_CACHE: dict[str, dict] = {}  # date_compact -> {player_name: stats_dict}


def _fetch_nba_player_stats(date_compact: str) -> dict:
    """Return {player_full_name: {'pts','reb','ast','pra'}} for the date.

    Uses NBA Stats API leaguegamelog endpoint via nba_api.
    """
    if date_compact in _NBA_PROP_CACHE:
        return _NBA_PROP_CACHE[date_compact]

    date_dashed = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}"
    try:
        from nba_api.stats.endpoints import leaguegamelog
        season_year = int(date_compact[:4])
        # NBA season "2024-25" → starts in October 2024
        if int(date_compact[4:6]) >= 10:
            season = f"{season_year}-{str(season_year+1)[-2:]}"
        else:
            season = f"{season_year-1}-{str(season_year)[-2:]}"
        season_type = "Playoffs" if int(date_compact[4:6]) in (4, 5, 6) else "Regular Season"
        # Pull the day's player game logs
        resp = leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star=season_type,
            player_or_team_abbreviation="P",
            date_from_nullable=date_dashed,
            date_to_nullable=date_dashed,
            timeout=30,
        )
        df = resp.get_data_frames()[0]
    except Exception as e:
        print(f"  [nba props] fetch error: {e}")
        return {}

    stats = {}
    for _, r in df.iterrows():
        name = r.get("PLAYER_NAME", "")
        if not name:
            continue
        pts = int(r.get("PTS", 0) or 0)
        reb = int(r.get("REB", 0) or 0)
        ast = int(r.get("AST", 0) or 0)
        stl = int(r.get("STL", 0) or 0)
        blk = int(r.get("BLK", 0) or 0)
        fg3m = int(r.get("FG3M", 0) or 0)
        stats[name] = {
            "pts": pts, "reb": reb, "ast": ast, "stl": stl, "blk": blk, "fg3m": fg3m,
            "pra": pts + reb + ast,
            "pr":  pts + reb,
            "pa":  pts + ast,
            "ra":  reb + ast,
        }
    _NBA_PROP_CACHE[date_compact] = stats
    return stats


_PROP_MARKET_TO_STAT = {
    "player_points":   "pts",
    "player_rebounds": "reb",
    "player_assists":  "ast",
    "player_pra":      "pra",
    "player_pr":       "pr",
    "player_pa":       "pa",
    "player_ra":       "ra",
    "player_threes":   "fg3m",
    "player_steals":   "stl",
    "player_blocks":   "blk",
}


def _fetch_pitcher_ks(team_field: str, date_compact: str) -> int | None:
    """Look up a pitcher's strikeout count from MLB Stats API box scores.

    `team_field` looks like "Framber Valdez UNDER 5.5" or "Andrew Painter OVER 3.5".
    Strips the line/direction to get the pitcher name, finds their start in any
    final game on the given date, returns Ks or None if the pitcher did not pitch.
    """
    # Extract pitcher name: everything before the first OVER/UNDER token
    parts = team_field.split()
    name_tokens = []
    for p in parts:
        if p.upper() in ("OVER", "UNDER"):
            break
        name_tokens.append(p)
    pitcher_name = " ".join(name_tokens).strip()
    if not pitcher_name:
        return None

    cache_key = (pitcher_name, date_compact)
    if cache_key in _PITCHER_KS_CACHE:
        return _PITCHER_KS_CACHE[cache_key]

    try:
        import requests
        date_dashed = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}"
        sched = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_dashed},
            timeout=15,
        ).json()
        for d in sched.get("dates", []):
            for g in d.get("games", []):
                pk = g.get("gamePk")
                if not pk:
                    continue
                bx = requests.get(
                    f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live",
                    timeout=15,
                ).json()
                box = bx.get("liveData", {}).get("boxscore", {}).get("teams", {})
                for side in ("home", "away"):
                    for _pid, pdata in box.get(side, {}).get("players", {}).items():
                        if pdata.get("person", {}).get("fullName", "") == pitcher_name:
                            stats = pdata.get("stats", {}).get("pitching", {})
                            ip = stats.get("inningsPitched", "0.0")
                            try:
                                ip_f = float(ip)
                            except (ValueError, TypeError):
                                ip_f = 0.0
                            if ip_f <= 0:
                                _PITCHER_KS_CACHE[cache_key] = None
                                return None
                            ks = int(stats.get("strikeOuts", 0) or 0)
                            _PITCHER_KS_CACHE[cache_key] = ks
                            return ks
    except Exception:
        pass

    _PITCHER_KS_CACHE[cache_key] = None
    return None


def auto_grade(date_str: str):
    """Auto-grade all pending card picks for date_str using Odds API scores."""
    date_compact = _norm_date(date_str)   # e.g. 20260414
    date_dashed  = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}"  # 2026-04-14

    data   = _load()
    # Only grade MLB picks here — NBA/NHL handled by their own graders
    picks  = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p["result"] is None
        and p.get("sport", "mlb") in ("mlb", "baseball_mlb", "")
    ]

    if not picks:
        print(f"\n  No pending picks for {date_str}.")
        return

    print(f"\n  Fetching scores for {date_str}...")
    winners, games = _fetch_scores(date_str)

    if not winners:
        print("  Could not fetch scores. Run with --manual instead.")
        return

    print(f"  Found {len(set(winners.values()))} completed games.\n")
    print(f"  {'='*52}")
    print(f"  Auto-grading {len(picks)} pick(s) for {date_str}")
    print(f"  {'='*52}\n")

    graded = 0
    for pick in picks:
        team     = pick["team"]
        market   = pick.get("market", "moneyline")
        opponent = pick.get("opponent", "") or pick.get("matchup", "")
        # NRFI and F5 are graded on outcome only — odds may be None if not tracked
        needs_odds = market not in ("nrfi", "f5_total")
        if needs_odds and not pick.get("odds"):
            print(f"  ⚠️  No odds for {team} — skipping")
            continue
        odds = float(pick["odds"]) if pick.get("odds") else 0.0
        if needs_odds and odds == 0:
            print(f"  ⚠️  Invalid odds (0) for {team} — skipping")
            continue
        sign     = "+" if odds > 0 else ""

        # ── Totals grading ───────────────────────────────────────────────
        if market == "total":
            # Parse direction + line from team field: "UNDER 8.5" or "OVER 9.0"
            parts = team.upper().split()
            direction = parts[0] if parts else "UNDER"
            try:
                line = float(parts[1]) if len(parts) > 1 else 0.0
            except ValueError:
                line = 0.0

            # Find the game via opponent field ("Away @ Home")
            game_info = None
            opp_teams = [t.strip() for t in opponent.replace(" @ ", "@").split("@")]
            for opp_name in opp_teams:
                if opp_name in games:
                    game_info = games[opp_name]
                    break
            # Fuzzy fallback: partial team name match
            if not game_info:
                for gt, gi in games.items():
                    for opp_name in opp_teams:
                        if len(opp_name) > 4 and (
                            opp_name.lower() in gt.lower() or gt.lower() in opp_name.lower()
                        ):
                            game_info = gi
                            break
                    if game_info:
                        break

            if not game_info:
                print(f"  ⚠️  No score found for {team} ({opponent}) — skipping")
                continue

            actual_total = game_info["total"]
            won = (actual_total < line) if direction == "UNDER" else (actual_total > line)
            # Push (exactly on the line)
            if actual_total == line:
                print(f"  ⬜ PUSH  {team:<30} ({sign}{int(odds)})  →  0.00u")
                print(f"         Final: {game_info['away']} {game_info['away_score']} @ "
                      f"{game_info['home']} {game_info['home_score']}  (total {actual_total})")
                print()
                pick["result"] = "push"
                pick["profit"] = 0.0
                pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
                graded += 1
                continue

            pick["result"]      = "win" if won else "loss"
            pick["profit"]      = round(_profit(pick["stake"], odds, won), 4)
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()

            icon = "🟢 WIN " if won else "🔴 LOSS"
            prof = f"+{pick['profit']:.2f}u" if won else f"{pick['profit']:.2f}u"
            print(f"  {icon}  {team:<30} ({sign}{int(odds)})  →  {prof}")
            print(f"         Final: {game_info['away']} {game_info['away_score']} @ "
                  f"{game_info['home']} {game_info['home_score']}"
                  f"  (total {actual_total} vs line {line})")
            print()
            graded += 1

        # ── Moneyline grading ────────────────────────────────────────────
        # ── NRFI / YRFI grading ──────────────────────────────────────────
        elif market == "nrfi":
            # team field for NRFI looks like "Away @ Home NRFI" or matchup field has it
            mu = pick.get("matchup") or team
            game_info = None
            for gt, gi in games.items():
                if gi["away"] in mu or gi["home"] in mu:
                    game_info = gi; break
            if not game_info:
                print(f"  ⚠️  No score found for NRFI {mu} — skipping")
                continue
            h1 = game_info.get("first_inning_home_runs")
            a1 = game_info.get("first_inning_away_runs")
            if h1 is None or a1 is None:
                print(f"  ⚠️  No 1st-inning data for {mu} — skipping")
                continue
            runs1 = int(h1) + int(a1)
            direction = (pick.get("direction") or "NRFI").upper()
            won = (runs1 == 0) if direction == "NRFI" else (runs1 > 0)
            pick["result"]      = "win" if won else "loss"
            pick["profit"]      = round(_profit(pick["stake"], odds, won), 4)
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
            pick["first_inning_runs"] = runs1
            icon = "🟢 WIN " if won else "🔴 LOSS"
            prof = f"+{pick['profit']:.2f}u" if won else f"{pick['profit']:.2f}u"
            print(f"  {icon}  {direction:<5} {mu[:25]:<25} ({sign}{int(odds)})  →  {prof}  (1st: {runs1} runs)")
            graded += 1

        # ── F5 (first 5 innings) grading ─────────────────────────────────
        elif market == "f5_total":
            mu = pick.get("matchup") or opponent or team
            game_info = None
            for gt, gi in games.items():
                if gi["away"] in mu or gi["home"] in mu:
                    game_info = gi; break
            if not game_info or game_info.get("f5_home_runs") is None:
                print(f"  ⚠️  No F5 data for {mu} — skipping")
                continue
            f5_total = int(game_info["f5_home_runs"]) + int(game_info["f5_away_runs"])
            line = float(pick.get("line") or 0)
            direction = (pick.get("direction") or "OVER").upper()
            if f5_total == line:
                pick["result"] = "push"
                pick["profit"] = 0.0
            else:
                won = (f5_total > line) if direction == "OVER" else (f5_total < line)
                pick["result"] = "win" if won else "loss"
                pick["profit"] = round(_profit(pick["stake"], odds, won), 4)
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
            print(f"  F5 {direction} {line}  {mu[:25]:<25} ({sign}{int(odds)})  result={pick['result']}  (F5 total: {f5_total})")
            graded += 1

        # ── Run-line / spread grading ────────────────────────────────────
        elif market in ("spread", "runline"):
            # team is the side taken (e.g., "Milwaukee Brewers"); line is +/- runs
            game_info = games.get(team, {})
            if not game_info:
                for gt, gi in games.items():
                    if len(team) > 4 and (team.lower() in gt.lower() or gt.lower() in team.lower()):
                        game_info = gi; break
            if not game_info:
                print(f"  ⚠️  No score found for {team} runline — skipping")
                continue
            line = float(pick.get("line") or 1.5)
            # +1.5 means team gets 1.5 runs; -1.5 means lays 1.5 runs.
            # Convention: positive line stored = receiving runs.
            team_score = game_info["away_score"] if team == game_info["away"] else game_info["home_score"]
            opp_score  = game_info["home_score"] if team == game_info["away"] else game_info["away_score"]
            adjusted   = team_score + line
            won = adjusted > opp_score
            pick["result"]      = "win" if won else "loss"
            pick["profit"]      = round(_profit(pick["stake"], odds, won), 4)
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
            icon = "🟢 WIN " if won else "🔴 LOSS"
            prof = f"+{pick['profit']:.2f}u" if won else f"{pick['profit']:.2f}u"
            print(f"  {icon}  {team:<30} {line:+.1f}  ({sign}{int(odds)})  →  {prof}")
            graded += 1

        # ── Prop grading (pitcher Ks) ────────────────────────────────────
        elif market == "prop":
            # team field: e.g. "Framber Valdez UNDER 5.5". We need the actual
            # K count from the game's box score. Fetch on-demand.
            try:
                k_count = _fetch_pitcher_ks(team, date_compact)
            except Exception as e:
                print(f"  ⚠️  Prop fetch failed for {team}: {e}")
                continue
            if k_count is None:
                pick["result"] = "void"
                pick["profit"] = 0.0
                pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
                print(f"  ⚫ VOID  {team:<30} (pitcher did not appear)")
                graded += 1
                continue
            line = float(pick.get("line") or 0)
            direction = (pick.get("direction") or "OVER").upper()
            if k_count == line:
                pick["result"] = "push"
                pick["profit"] = 0.0
            else:
                won = (k_count > line) if direction == "OVER" else (k_count < line)
                pick["result"] = "win" if won else "loss"
                pick["profit"] = round(_profit(pick["stake"], odds, won), 4)
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
            icon = "🟢 WIN " if pick["result"] == "win" else ("⬜ PUSH" if pick["result"] == "push" else "🔴 LOSS")
            prof = f"{pick['profit']:+.2f}u"
            print(f"  {icon}  {team:<30} ({sign}{int(odds)})  →  {prof}  (Ks: {k_count})")
            graded += 1

        # ── Moneyline grading (default) ──────────────────────────────────
        else:
            winner = winners.get(team)
            if winner is None:
                # Fuzzy match
                for gt, w in winners.items():
                    if len(team) > 4 and (team.lower() in gt.lower() or gt.lower() in team.lower()):
                        winner = w
                        break
            if winner is None:
                print(f"  ⚠️  No score found for {team} — skipping")
                continue

            game_info = games.get(team, {})
            won = (winner == team)
            pick["result"]      = "win" if won else "loss"
            pick["profit"]      = round(_profit(pick["stake"], odds, won), 4)
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()

            icon = "🟢 WIN " if won else "🔴 LOSS"
            prof = f"+{pick['profit']:.2f}u" if won else f"{pick['profit']:.2f}u"
            print(f"  {icon}  {team:<30} ({sign}{int(odds)})  →  {prof}")
            if game_info:
                print(f"         Final: {game_info.get('away','')} {game_info.get('away_score','')} @ "
                      f"{game_info.get('home','')} {game_info.get('home_score','')}")
            else:
                print(f"         Winner: {winner}")
            print()
            graded += 1

    _save(data)
    print(f"  Graded {graded}/{len(picks)} picks.")

    # Final record
    settled = [p for p in data["picks"] if p["result"] in ("win", "loss")]
    wins   = sum(1 for p in settled if p["result"] == "win")
    losses = len(settled) - wins
    profit = sum(p.get("profit") or 0 for p in settled)
    staked = sum(float(p.get("stake") or 1) for p in settled)
    roi    = (profit / staked * 100) if staked else 0
    ps = "+" if profit >= 0 else ""
    rs = "+" if roi    >= 0 else ""
    print(f"\n  ─────────────────────────────────────────")
    print(f"  SEASON RECORD   {wins}W – {losses}L")
    print(f"  PROFIT          {ps}{profit:.2f}u  |  ROI {rs}{roi:.1f}%")
    print(f"  ─────────────────────────────────────────\n")


def quick_result(team: str, won: bool, date: str | None = None):
    """Grade a single pick by team name (and optionally date) directly in the JSON."""
    data = _load()
    now  = datetime.now(timezone.utc).isoformat()

    for pick in data["picks"]:
        if pick["team"].lower().strip() != team.lower().strip():
            continue
        if pick["result"] is not None:
            continue
        if date and pick.get("date") != date:
            continue

        pick["result"]     = "win" if won else "loss"
        pick["profit"]     = round(_profit(pick["stake"], pick["odds"], won), 4)
        pick["resulted_at"] = now
        _save(data)

        icon = "🟢 WIN" if won else "🔴 LOSS"
        sign = "+" if pick["profit"] >= 0 else ""
        print(f"\n  {icon}  {team}  →  {sign}{pick['profit']:.2f}u\n")
        return

    print(f"\n  ⚠️  No pending card pick found for '{team}'{' on ' + date if date else ''}.\n")


def interactive():
    data  = _load()
    picks = [p for p in data["picks"] if p["result"] is None]

    if not picks:
        print("\n  No pending card picks to grade.\n")
        _print_record(data)
        return

    print(f"\n  {'='*50}")
    print(f"  ChefTonyBets — Grade {len(picks)} pending pick(s)")
    print(f"  {'='*50}\n")

    for pick in picks:
        team = pick["team"]
        odds = int(pick["odds"])
        sign = "+" if odds > 0 else ""
        opp  = pick.get("opponent","?")
        d    = pick.get("date","?")

        print(f"  {team}  ({sign}{odds})  vs  {opp}  [{d}]")
        while True:
            ans = input("  Result? [W/L/skip]: ").strip().upper()
            if ans == "W":
                quick_result(team, won=True, date=d)
                break
            elif ans == "L":
                quick_result(team, won=False, date=d)
                break
            elif ans in ("S", "SKIP", ""):
                print(f"  Skipping {team}.\n")
                break
            else:
                print("  Type W, L, or skip.")

    data = _load()
    _print_record(data)


def _print_record(data):
    settled = [p for p in data["picks"] if p["result"] in ("win", "loss")]
    wins   = sum(1 for p in settled if p["result"] == "win")
    losses = len(settled) - wins
    profit = sum(p.get("profit") or 0 for p in settled)
    staked = sum(float(p.get("stake") or 1) for p in settled)
    roi    = (profit / staked * 100) if staked else 0
    ps = "+" if profit >= 0 else ""
    rs = "+" if roi    >= 0 else ""
    print(f"  ─────────────────────────────────────────")
    print(f"  SEASON RECORD   {wins}W – {losses}L")
    print(f"  PROFIT          {ps}{profit:.2f}u  |  ROI {rs}{roi:.1f}%")
    print(f"  ─────────────────────────────────────────\n")


def generate_recap_card(grade_date: str) -> Path | None:
    """
    Generate a nightly recap card image for Instagram Stories.
    Shows last night's results + running season record.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  Pillow not installed — skipping recap card.")
        return None

    data    = _load()
    settled = [p for p in data["picks"]
               if p.get("result") in ("win", "loss")]

    last_night = [p for p in settled if p.get("date") == grade_date]
    if not last_night:
        print(f"  No settled picks for {grade_date} — skipping recap card.")
        return None

    # Season totals
    wins   = sum(1 for p in settled if p["result"] == "win")
    losses = len(settled) - wins
    profit = sum(p.get("profit") or 0 for p in settled)
    staked = sum(p.get("stake", 1.0) for p in settled)
    roi    = (profit / staked * 100) if staked else 0

    # Last night totals
    ln_wins   = sum(1 for p in last_night if p["result"] == "win")
    ln_losses = len(last_night) - ln_wins
    ln_profit = sum(p.get("profit") or 0 for p in last_night)

    # Layout
    W, H   = 1080, 1080
    PAD    = 50
    _BG    = (8, 10, 18)
    _GOLD  = (255, 184, 0)
    _GREEN = (70, 210, 90)
    _RED   = (220, 60, 60)
    _WHITE = (248, 248, 252)
    _GRAY  = (155, 158, 180)
    _DARK  = (14, 17, 28)
    _HDR   = (10, 12, 22)

    def _load_font(size, bold=False):
        paths = [("/System/Library/Fonts/HelveticaNeue.ttc", 1 if bold else 0),
                 ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
                  else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)]
        from PIL import ImageFont
        for path, idx in paths:
            try:
                return ImageFont.truetype(path, size, index=idx)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    f_brand  = _load_font(52, bold=True)
    f_handle = _load_font(28, bold=False)
    f_big    = _load_font(88, bold=True)
    f_mid    = _load_font(42, bold=True)
    f_pick   = _load_font(34, bold=True)
    f_sub    = _load_font(26, bold=False)
    f_label  = _load_font(22, bold=False)

    img  = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    # Gold top bar
    draw.rectangle([0, 0, W, 6], fill=_GOLD)

    # Header
    draw.rectangle([0, 0, W, 110], fill=_HDR)
    draw.text((PAD, 20), "ChefTony", fill=_WHITE, font=f_brand)
    bw = draw.textlength("ChefTony", font=f_brand)
    draw.text((PAD + bw + 8, 26), "Bets", fill=_GOLD, font=_load_font(42, bold=True))
    hw = draw.textlength("@ChefTonyBets", font=f_handle)
    draw.text((W - PAD - hw, 40), "@ChefTonyBets", fill=_GOLD, font=f_handle)

    draw.rectangle([0, 110, W, 114], fill=_GOLD)

    # Date label
    from datetime import datetime as _dt
    try:
        d_obj = _dt.strptime(grade_date, "%Y%m%d")
        date_label = d_obj.strftime("%B %d, %Y").upper()
    except Exception:
        date_label = grade_date
    draw.text((W // 2 - draw.textlength(f"LAST NIGHT · {date_label}", font=f_sub) // 2,
               130), f"LAST NIGHT · {date_label}", fill=_GRAY, font=f_sub)

    # Big W-L
    wl_str   = f"{ln_wins}W - {ln_losses}L"
    wl_color = _GREEN if ln_wins >= ln_losses else _RED
    wl_w     = draw.textlength(wl_str, font=f_big)
    draw.text(((W - wl_w) // 2, 175), wl_str, fill=wl_color, font=f_big)

    # Profit line
    ln_p = f"+{ln_profit:.2f}u" if ln_profit >= 0 else f"{ln_profit:.2f}u"
    ln_pc = _GREEN if ln_profit >= 0 else _RED
    lnpw = draw.textlength(ln_p, font=f_mid)
    draw.text(((W - lnpw) // 2, 290), ln_p, fill=ln_pc, font=f_mid)

    # Divider
    draw.rectangle([PAD, 360, W - PAD, 362], fill=_GOLD)

    # Individual picks
    y = 380
    for pick in last_night:
        won  = pick["result"] == "win"
        icon = "✅" if won else "❌"
        team = pick["team"]
        odds = int(pick["odds"])
        sign = "+" if odds > 0 else ""
        prof = pick.get("profit") or 0
        pstr = f"+{prof:.2f}u" if prof >= 0 else f"{prof:.2f}u"
        pc   = _GREEN if prof >= 0 else _RED

        draw.text((PAD, y), icon, fill=_WHITE, font=f_pick)
        draw.text((PAD + 48, y), f"{team}", fill=_WHITE, font=f_pick)
        tw = draw.textlength(f"{team}", font=f_pick)
        draw.text((PAD + 52 + tw, y + 4), f"({sign}{odds})", fill=_GRAY, font=f_sub)
        pw = draw.textlength(pstr, font=f_pick)
        draw.text((W - PAD - pw, y), pstr, fill=pc, font=f_pick)
        y += 52
        if y > 780:
            break

    # Season record box
    draw.rectangle([PAD, 820, W - PAD, 960], fill=_DARK, outline=_GOLD, width=2)
    draw.text((W // 2 - draw.textlength("SEASON RECORD", font=f_label) // 2, 835),
              "SEASON RECORD", fill=_GRAY, font=f_label)

    season_str = f"{wins}W - {losses}L"
    ssw = draw.textlength(season_str, font=f_mid)
    draw.text(((W - ssw) // 2, 865), season_str, fill=_WHITE, font=f_mid)

    roi_str  = f"+{roi:.1f}% ROI" if roi >= 0 else f"{roi:.1f}% ROI"
    prof_str = f"+{profit:.2f}u" if profit >= 0 else f"{profit:.2f}u"
    detail   = f"{prof_str}  ·  {roi_str}"
    dw = draw.textlength(detail, font=f_sub)
    rc = _GREEN if roi >= 0 else _RED
    draw.text(((W - dw) // 2, 920), detail, fill=rc, font=f_sub)

    # Footer
    draw.rectangle([0, H - 74, W, H], fill=_HDR)
    draw.rectangle([0, H - 74, W, H - 70], fill=_GOLD)
    cta = "Free picks every day  ·  All picks AI-model backed"
    draw.text((W // 2 - draw.textlength(cta, font=f_label) // 2, H - 58),
              cta, fill=_GOLD, font=f_label)

    # Save
    save_dir = Path("output/picks/recaps")
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"{grade_date}.png"
    img.save(path, quality=95)
    print(f"  Recap card saved: {path}")
    return path


def _grade_nba(date_str: str) -> None:
    """Grade NBA picks for date_str. Game lines via run_nba.py, props via NBA Stats API."""
    try:
        from run_nba import grade_nba_picks
        grade_nba_picks(target_date=date_str, verbose=True)
    except ImportError as e:
        print(f"  [grade] NBA game grading unavailable: {e}")
    except Exception as e:
        print(f"  [grade] NBA game grading error: {e}")

    # Now grade NBA props from data/pnl/picks.json
    _grade_nba_props(date_str)


def _grade_nba_props(date_str: str) -> None:
    """Grade NBA player props for date_str using nba_api game logs."""
    date_compact = _norm_date(date_str)
    data = _load()
    pending_props = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p.get("sport") == "nba"
        and p.get("market") == "prop"
        and p.get("result") in (None, "pending")
    ]
    if not pending_props:
        return

    stats = _fetch_nba_player_stats(date_compact)
    if not stats:
        print(f"  [nba props] No NBA stats fetched for {date_str}")
        return

    print(f"\n  ── NBA props ──")
    graded = 0
    for pick in pending_props:
        player = pick.get("player") or pick.get("team", "").split(" OVER")[0].split(" UNDER")[0].strip()
        prop_market = pick.get("prop_market", "player_points")
        stat_key = _PROP_MARKET_TO_STAT.get(prop_market)
        if not stat_key:
            print(f"  ⚠️  Unknown prop_market {prop_market} for {player}")
            continue

        # Fuzzy player lookup
        actual = None
        for name, s in stats.items():
            if name == player or (player.lower() in name.lower()) or (name.lower() in player.lower()):
                actual = s.get(stat_key)
                break

        if actual is None:
            pick["result"] = "void"
            pick["profit"] = 0.0
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
            print(f"  ⚫ VOID  {player} {prop_market} (DNP)")
            graded += 1
            continue

        line = float(pick.get("line") or 0)
        direction = (pick.get("direction") or "OVER").upper()
        odds = float(pick.get("odds") or 0)
        if actual == line:
            pick["result"] = "push"; pick["profit"] = 0.0
        else:
            won = (actual > line) if direction == "OVER" else (actual < line)
            pick["result"] = "win" if won else "loss"
            pick["profit"] = round(_profit(pick.get("stake", 1.0), odds, won), 4)
        pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
        graded += 1
        icon = "🟢 WIN " if pick["result"] == "win" else ("⬜ PUSH" if pick["result"] == "push" else "🔴 LOSS")
        prof = f"{pick['profit']:+.2f}u"
        sign = "+" if odds > 0 else ""
        print(f"  {icon}  {player:<25} {direction} {line:<5}  ({sign}{int(odds)})  →  {prof}  ({stat_key.upper()}: {actual})")

    _save(data)
    print(f"  Graded {graded}/{len(pending_props)} NBA props.")


def _grade_nhl(date_str: str) -> None:
    """Grade NHL picks for date_str using api-web.nhle.com final scores."""
    try:
        from datetime import date as _date
        from src.data.nhl_stats import fetch_final_scores
    except ImportError as e:
        print(f"  [grade] NHL grading unavailable: {e}")
        return

    date_compact = _norm_date(date_str)
    try:
        d = _date(int(date_compact[:4]), int(date_compact[4:6]), int(date_compact[6:]))
    except ValueError:
        print(f"  [grade] Invalid date {date_str}")
        return

    finals = fetch_final_scores(d)
    if not finals:
        print(f"  No NHL final scores for {date_str}")
        return

    games_by_team: dict[str, dict] = {}
    for g in finals:
        games_by_team[g["away_team"]] = g
        games_by_team[g["home_team"]] = g

    data = _load()
    picks = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p.get("sport") == "nhl"
        and p.get("result") in (None, "pending")
        and p.get("odds") is not None
    ]
    if not picks:
        print(f"  No pending NHL picks for {date_str}")
        return

    graded = 0
    for pick in picks:
        team = pick.get("team", "")
        market = pick.get("market", "moneyline")
        odds = float(pick["odds"])

        # Find the game this pick belongs to (fuzzy match)
        game_info = games_by_team.get(team)
        if not game_info:
            for gt, gi in games_by_team.items():
                if len(team) > 4 and (team.lower() in gt.lower() or gt.lower() in team.lower()):
                    game_info = gi; break
        # Strip suffix like "Buffalo Sabres +1.5" → "Buffalo Sabres"
        if not game_info:
            stripped = team.rsplit(" ", 1)[0]
            game_info = games_by_team.get(stripped)
            if not game_info:
                for gt, gi in games_by_team.items():
                    if len(stripped) > 4 and (stripped.lower() in gt.lower() or gt.lower() in stripped.lower()):
                        game_info = gi; break

        if not game_info:
            print(f"  ⚠️  No NHL score found for {team} — skipping")
            continue

        if market == "moneyline":
            won = game_info["winner"] == team
        elif market in ("spread", "puck_line"):
            line = float(pick.get("line") or 1.5)
            team_score = game_info["away_score"] if team.startswith(game_info["away_team"]) else game_info["home_score"]
            opp_score  = game_info["home_score"] if team.startswith(game_info["away_team"]) else game_info["away_score"]
            won = (team_score + line) > opp_score
        elif market == "total":
            line = float(pick.get("line") or 0)
            direction = (pick.get("direction") or "OVER").upper()
            actual = game_info["total"]
            if actual == line:
                pick["result"] = "push"; pick["profit"] = 0.0
                pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
                _save(data); graded += 1
                print(f"  ⬜ PUSH  {team:<25} ({pick.get('odds'):+d})")
                continue
            won = (actual > line) if direction == "OVER" else (actual < line)
        else:
            continue

        pick["result"] = "win" if won else "loss"
        pick["profit"] = round(_profit(pick.get("stake", 1.0), odds, won), 4)
        pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
        graded += 1
        icon = "🟢 WIN " if won else "🔴 LOSS"
        prof = f"{pick['profit']:+.2f}u"
        print(f"  {icon}  {team:<28} ({int(odds):+d})  {market:10}  →  {prof}")

    _save(data)
    print(f"  Graded {graded}/{len(picks)} NHL picks.")


def main():
    parser = argparse.ArgumentParser(
        prog="grade",
        description="Grade picks against actual results (MLB + NBA).",
    )
    parser.add_argument("cmd",    nargs="?", help="win | loss | (blank=auto)")
    parser.add_argument("team",   nargs="?", help="Team name for win/loss")
    parser.add_argument("--date",   help="Date to grade YYYYMMDD (default: yesterday)")
    parser.add_argument("--sport",  default="all", choices=["all", "mlb", "nba", "nhl"],
                        help="Which sport to grade (default: all)")
    parser.add_argument("--manual",      action="store_true", help="Interactive W/L mode")
    parser.add_argument("--recap-card",  action="store_true", help="Generate recap card image")

    args = parser.parse_args()

    if args.cmd == "win" and args.team:
        quick_result(args.team, won=True, date=args.date)
    elif args.cmd == "loss" and args.team:
        quick_result(args.team, won=False, date=args.date)
    elif args.manual:
        interactive()
    else:
        if args.date:
            grade_date = args.date
        else:
            yesterday  = datetime.now() - timedelta(days=1)
            grade_date = yesterday.strftime("%Y%m%d")

        if args.sport in ("all", "mlb"):
            auto_grade(grade_date)
            if args.recap_card:
                generate_recap_card(grade_date)

        if args.sport in ("all", "nba"):
            print(f"\n  ── Grading NBA picks for {grade_date} ──")
            _grade_nba(grade_date)

        if args.sport in ("all", "nhl"):
            print(f"\n  ── Grading NHL picks for {grade_date} ──")
            _grade_nhl(grade_date)

        # Update public stats after all grading is done
        try:
            from src.analytics.public_stats import write_public_stats
            write_public_stats()
        except Exception as e:
            print(f"  [stats] {e}")


if __name__ == "__main__":
    main()
