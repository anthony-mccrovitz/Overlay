#!/usr/bin/env python3
"""
Overlay — Grading Script
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

sys.path.insert(0, str(Path(__file__).parent))
from src.tracking.schema import profit_from_odds as _profit_from_odds


def _profit(stake: float, odds: float, won: bool) -> float:
    """Thin wrapper — delegates to canonical schema.profit_from_odds."""
    return _profit_from_odds(odds, stake, won)

DATA_FILE = Path("data/pnl/picks.json")


def _load():
    if not DATA_FILE.exists():
        return {"picks": []}
    raw = json.loads(DATA_FILE.read_text())
    if isinstance(raw, list):
        return {"picks": raw}
    return raw


def _save(data):
    # Always persist as a plain list
    picks = data["picks"] if isinstance(data, dict) else data
    DATA_FILE.write_text(json.dumps(picks, indent=2))


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


# MLB player-prop market → MLB Stats API boxscore batting key.
_MLB_BATTER_STATS = {
    "batter_hits":        "hits",
    "batter_walks":       "baseOnBalls",
    "batter_total_bases": "totalBases",
    "batter_rbis":        "rbi",
    "batter_home_runs":   "homeRuns",
}

# Every MLB market graded by _grade_mlb_props (and excluded from auto_grade).
# "prop" is the legacy market name for pitcher strikeouts.
_MLB_PROP_MARKETS = ("prop", "pitcher_strikeouts", *_MLB_BATTER_STATS)


def auto_grade(date_str: str):
    """Auto-grade all pending card picks for date_str using Odds API scores."""
    date_compact = _norm_date(date_str)   # e.g. 20260414
    date_dashed  = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}"  # 2026-04-14

    data   = _load()
    # Only grade MLB game-line picks here — props handled by _grade_mlb_props
    picks  = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p["result"] is None
        and p.get("sport", "mlb") in ("mlb", "baseball_mlb", "")
        and p.get("market") not in _MLB_PROP_MARKETS
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
    print(f"  Overlay — Grade {len(picks)} pending pick(s)")
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
    draw.text((PAD, 20), "Overlay", fill=_WHITE, font=f_brand)
    bw = draw.textlength("Overlay", font=f_brand)
    draw.text((PAD + bw + 8, 26), "Bets", fill=_GOLD, font=_load_font(42, bold=True))
    hw = draw.textlength("@Overlay", font=f_handle)
    draw.text((W - PAD - hw, 40), "@Overlay", fill=_GOLD, font=f_handle)

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


def _grade_mlb_props(date_str: str) -> None:
    """Grade MLB player props (pitcher Ks + batter markets) from MLB Stats API boxscores."""
    import re
    try:
        import requests
    except ImportError:
        print("  [mlb props] requests not installed")
        return

    date_compact = _norm_date(date_str)
    date_iso = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}"

    data = _load()
    pending = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p.get("sport") in ("baseball_mlb", "mlb")
        and p.get("market") in _MLB_PROP_MARKETS
        and p.get("result") in (None, "pending")
    ]
    if not pending:
        return

    # Fetch schedule to get game PKs
    try:
        sched_resp = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"date": date_iso, "sportId": 1, "hydrate": "team"},
            timeout=15,
        )
        sched_data = sched_resp.json() if sched_resp.status_code == 200 else {}
    except Exception as e:
        print(f"  [mlb props] schedule fetch error: {e}")
        sched_data = {}

    # Build player_name -> {market: stat_value} from all boxscores
    player_stats: dict[str, dict[str, int]] = {}
    for date_entry in sched_data.get("dates", []):
        for game in date_entry.get("games", []):
            # Only grade final games
            state = game.get("status", {}).get("abstractGameState", "")
            if state != "Final":
                continue
            game_pk = game.get("gamePk")
            if not game_pk:
                continue
            try:
                bx_resp = requests.get(
                    f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore",
                    timeout=15,
                )
                bx_data = bx_resp.json() if bx_resp.status_code == 200 else {}
            except Exception:
                bx_data = {}

            teams = bx_data.get("teams", {})
            for side in ("home", "away"):
                side_data = teams.get(side, {})
                players = side_data.get("players", {})
                for _pid, pdata in players.items():
                    full_name = pdata.get("person", {}).get("fullName", "")
                    if not full_name:
                        continue
                    stats = pdata.get("stats", {})
                    pitching = stats.get("pitching", {})
                    batting  = stats.get("batting", {})
                    entry = player_stats.setdefault(full_name, {})
                    if pitching.get("strikeOuts") is not None:
                        ks = int(pitching["strikeOuts"])
                        entry["pitcher_strikeouts"] = ks
                        entry["prop"] = ks  # legacy market name for pitcher Ks
                    # Batters who appeared always have a batting dict; only
                    # record stats when they actually batted (doubleheader
                    # collisions keep the later game — props are per-game and
                    # ambiguous either way, matching prior pitcher behaviour).
                    if batting:
                        for market, key in _MLB_BATTER_STATS.items():
                            val = batting.get(key)
                            if val is not None:
                                entry[market] = int(val)

    # Payout helper: returns multiplier on stake (not profit, just the payout)
    def _payout(odds: float) -> float:
        return odds / 100 if odds > 0 else 100 / abs(odds)

    # Grade each pending pick
    graded = 0
    wins = 0
    losses = 0
    now_str = datetime.now(timezone.utc).isoformat()

    # Regex to strip " OVER X.X" or " UNDER X.X" suffix from team field
    _suffix_re = re.compile(r"\s+(OVER|UNDER)\s+[\d.]+\s*$", re.IGNORECASE)

    print(f"\n  ── MLB props ──")
    for pick in pending:
        team_field = pick.get("team", "")
        # Extract player name by stripping direction+line suffix
        match = _suffix_re.search(team_field)
        if match:
            pick_name = team_field[: match.start()].strip()
        else:
            # Fallback: strip last two tokens (e.g. "OVER 5.5")
            parts = team_field.split()
            name_tokens = []
            for tok in parts:
                if tok.upper() in ("OVER", "UNDER"):
                    break
                name_tokens.append(tok)
            pick_name = " ".join(name_tokens).strip()

        if not pick_name:
            continue

        market = pick.get("market", "prop")

        # Fuzzy match against boxscore player names
        actual: int | None = None
        for full_name, stats in player_stats.items():
            if market not in stats:
                continue
            if (
                pick_name.lower() == full_name.lower()
                or pick_name.lower() in full_name.lower()
                or full_name.lower() in pick_name.lower()
            ):
                actual = stats[market]
                break

        if actual is None:
            # Player did not appear in any completed game — void
            pick["result"] = "void"
            pick["profit"] = 0.0
            pick["resulted_at"] = now_str
            print(f"  ⚫ VOID  {pick_name} ({market} not found in boxscore)")
            graded += 1
            continue

        line = float(pick.get("line") or 0)
        direction = (pick.get("direction") or "OVER").upper()
        odds = float(pick.get("odds") or 0)
        stake = float(pick.get("stake") or 1.0)

        if actual == line:
            pick["result"] = "push"
            pick["profit"] = 0.0
        else:
            won = (actual > line) if direction == "OVER" else (actual < line)
            pick["result"] = "win" if won else "loss"
            pick["profit"] = round(_payout(odds) * stake if won else -stake, 4)
            if won:
                wins += 1
            else:
                losses += 1

        pick["resulted_at"] = now_str
        graded += 1

        icon = {"win": "🟢 WIN ", "loss": "🔴 LOSS", "push": "⬜ PUSH"}.get(pick["result"], "?")
        sign = "+" if odds > 0 else ""
        prof = f"{pick['profit']:+.2f}u"
        print(
            f"  {icon}  {pick_name:<25} {direction} {line:<5}  ({sign}{int(odds)})  →  {prof}"
            f"  ({market}: {actual})"
        )

    _save(data)
    print(f"  ── MLB props ── {graded} graded, {wins}W {losses}L")

    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
    except Exception as e:
        print(f"  [stats] {e}")


def _fetch_scores_generic(sport_key: str, date_str: str) -> dict[str, dict]:
    """
    Fetch completed game scores from Odds API for any sport.
    Returns {team_name: {home, away, home_score, away_score, total, winner}} keyed by both teams.

    Works for: basketball_wnba, mma_mixed_martial_arts, soccer_*, tennis_*, etc.
    """
    import requests
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ODDS_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
    if not api_key:
        return {}

    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/",
            params={"apiKey": api_key, "daysFrom": 3, "dateFormat": "iso"},
            timeout=12,
        )
        if resp.status_code != 200:
            return {}
    except Exception as e:
        print(f"  [grade/{sport_key}] scores fetch error: {e}")
        return {}

    games: dict[str, dict] = {}
    for game in resp.json():
        if not game.get("completed") or not game.get("scores"):
            continue
        commence = game.get("commence_time", "")
        try:
            from datetime import timezone as _tz, timedelta as _td
            dt_utc = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            # Convert to Eastern Time (UTC-4 DST / UTC-5 standard) so late US games
            # (e.g. 8pm ET = midnight UTC) map to the correct local date.
            dt_et = dt_utc.astimezone(_tz(offset=_td(hours=-4)))
            game_date = dt_et.strftime("%Y%m%d")
        except Exception:
            game_date = commence[:10].replace("-", "")

        if game_date != date_str:
            continue

        scores = {s["name"]: s["score"] for s in game["scores"] if s.get("score") is not None}
        teams  = list(scores.keys())
        if len(teams) < 2:
            continue

        away_team, home_team = teams[0], teams[1]
        try:
            away_score = float(scores[away_team])
            home_score = float(scores[home_team])
        except (ValueError, TypeError):
            continue

        if away_score > home_score:
            winner = away_team
        elif home_score > away_score:
            winner = home_team
        else:
            winner = "Draw"
        info = {
            "home": home_team, "away": away_team,
            "home_score": home_score, "away_score": away_score,
            "total": home_score + away_score,
            "winner": winner,
            "margin": abs(home_score - away_score),
        }
        games[home_team] = info
        games[away_team] = info

    return games


# Sports whose historical scores are available on ESPN's scoreboard API.
# Odds API only keeps 3 days of scores; ESPN goes back all season.
_ESPN_SCOREBOARD_PATHS = {
    "basketball_wnba":                  "basketball/wnba",
    "basketball_nba":                   "basketball/nba",
    "icehockey_nhl":                    "hockey/nhl",
    "soccer_fifa_world_cup":            "soccer/fifa.world",
    "soccer_france_ligue_one":          "soccer/fra.1",
    "soccer_usa_mls":                   "soccer/usa.1",
    "soccer_spain_la_liga":             "soccer/esp.1",
    "soccer_italy_serie_a":             "soccer/ita.1",
    "soccer_germany_bundesliga":        "soccer/ger.1",
    "soccer_conmebol_copa_libertadores": "soccer/conmebol.libertadores",
}


def _fetch_scores_espn(sport_key: str, date_str: str) -> dict[str, dict]:
    """
    Fetch completed game scores from ESPN's scoreboard API for a single date.
    Returns the same {team_name: game_info} structure as _fetch_scores_generic.
    Used as a fallback when the date is outside Odds API's 3-day score window.
    """
    path = _ESPN_SCOREBOARD_PATHS.get(sport_key)
    if not path:
        return {}

    import requests
    try:
        resp = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard",
            params={"dates": date_str},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        if resp.status_code != 200:
            return {}
        events = resp.json().get("events", [])
    except Exception as e:
        print(f"  [grade/{sport_key}] ESPN scores fetch error: {e}")
        return {}

    games: dict[str, dict] = {}
    for event in events:
        for comp in event.get("competitions", []):
            if not (comp.get("status", {}).get("type", {}).get("completed")):
                continue
            home = away = None
            for c in comp.get("competitors", []):
                t = c.get("team", {})
                # All the names ESPN knows the team by — picks store anything
                # from "USA" to "Montréal Canadiens", so match against each.
                names = [t.get(k) for k in ("displayName", "shortDisplayName",
                                            "name", "abbreviation", "location")]
                names = list(dict.fromkeys(n for n in names if n))
                entry = (t.get("displayName", ""), c.get("score"), names)
                if c.get("homeAway") == "home":
                    home = entry
                elif c.get("homeAway") == "away":
                    away = entry
            if not home or not away or home[1] is None or away[1] is None:
                continue
            try:
                home_score, away_score = float(home[1]), float(away[1])
            except (ValueError, TypeError):
                continue
            home_team, away_team = home[0], away[0]
            if home_score > away_score:
                winner = home_team
            elif away_score > home_score:
                winner = away_team
            else:
                winner = "Draw"
            info = {
                "home": home_team, "away": away_team,
                "home_score": home_score, "away_score": away_score,
                "total": home_score + away_score,
                "winner": winner,
                "margin": abs(home_score - away_score),
                "home_names": home[2], "away_names": away[2],
            }
            for name in home[2] + away[2]:
                games.setdefault(name, info)

    return games


def _fetch_tennis_results_espn(tour: str, date_str: str) -> dict[str, str]:
    """
    Fetch tennis match winners from ESPN Core API.
    Returns {player_name_lower: 'win'|'loss'}.

    tour: 'atp' or 'wta'
    date_str: YYYYMMDD or YYYY-MM-DD
    """
    try:
        import requests
        from concurrent.futures import ThreadPoolExecutor
    except ImportError:
        return {}

    date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}" if len(date_str) == 8 else date_str

    # ESPN uses a fixed event ID per Grand Slam — map sport key → ESPN event ID
    _ESPN_EVENTS = {
        "tennis_atp_french_open":  ("atp", "172-2026"),
        "tennis_wta_french_open":  ("wta", "262-2026"),
        "tennis_atp_australian_open": ("atp", "166-2026"),
        "tennis_wta_australian_open": ("wta", "256-2026"),
        "tennis_atp_us_open":      ("atp", "180-2026"),
        "tennis_wta_us_open":      ("wta", "270-2026"),
        "tennis_atp_wimbledon":    ("atp", "176-2026"),
        "tennis_wta_wimbledon":    ("wta", "266-2026"),
    }

    results: dict[str, str] = {}
    # Find matching ESPN event IDs for this tour
    espn_ids = [(league, eid) for key, (league, eid) in _ESPN_EVENTS.items()
                if league == tour]
    if not espn_ids:
        return {}

    for league, event_id in espn_ids:
        try:
            r = requests.get(
                f"https://sports.core.api.espn.com/v2/sports/tennis/leagues/{league}/events/{event_id}/competitions",
                params={"limit": 1000},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                continue
            items = r.json().get("items", [])

            def _fetch(item):
                ref = item.get("$ref", "")
                if not ref:
                    return None
                try:
                    rr = requests.get(ref, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                    return rr.json() if rr.status_code == 200 else None
                except Exception:
                    return None

            with ThreadPoolExecutor(max_workers=20) as pool:
                comps = list(pool.map(_fetch, items))

            for comp in comps:
                if not comp:
                    continue
                raw_date = comp.get("date", "")
                try:
                    dt_utc = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    comp_date = (dt_utc - timedelta(hours=4)).strftime("%Y-%m-%d")
                except Exception:
                    comp_date = raw_date[:10]
                if comp_date != date_iso:
                    continue
                for c in comp.get("competitors", []):
                    name = c.get("name", "")
                    if name:
                        results[name.lower()] = "win" if c.get("winner") else "loss"
        except Exception:
            continue

    return results


def _settle_game_pick(pick: dict, game_info: dict) -> str | None:
    """
    Settle one moneyline/spread/total pick against a final score and stamp
    result/profit/resulted_at on the pick. Returns the result
    ("win"/"loss"/"push") or None if the market is unknown.
    """
    team   = pick.get("team", "")
    market = pick.get("market", "moneyline")
    odds   = float(pick["odds"])

    if market == "moneyline":
        # MMA: winner is stored as fighter name
        winner = game_info["winner"]
        won = (winner.lower() == team.lower()) or (team.lower() in winner.lower())

    elif market in ("spread", "puck_line", "run_line"):
        line = float(pick.get("line") or 1.5)
        team_score = game_info["away_score"] if team == game_info["away"] else game_info["home_score"]
        opp_score  = game_info["home_score"] if team == game_info["away"] else game_info["away_score"]
        won = (team_score + line) > opp_score

    elif market == "total":
        line = float(pick.get("line") or 0)
        direction = (pick.get("direction") or team.split()[0]).upper()
        actual = game_info["total"]
        if actual == line:
            pick["result"] = "push"; pick["profit"] = 0.0
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
            return "push"
        won = (actual > line) if direction == "OVER" else (actual < line)

    else:
        return None

    pick["result"] = "win" if won else "loss"
    pick["profit"] = round(_profit(pick.get("stake", 1.0), odds, won), 4)
    pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
    return pick["result"]


def _grade_sport_generic(
    sport_key: str,
    sport_name: str,
    date_str: str,
    sport_field: str | tuple[str, ...] | None = None,
) -> None:
    """
    Generic grader for any sport that uses moneyline/spread/total markets.
    Fetches scores via Odds API and grades all pending picks matching sport_field.

    sport_key   — Odds API key, e.g. "basketball_wnba"
    sport_name  — Display name, e.g. "WNBA"
    sport_field — Value(s) of pick["sport"] to match (defaults to sport_key).
                  A tuple matches any of its values — pick writers have used
                  both short names ("wnba") and Odds API keys ("basketball_wnba").
    """
    if sport_field is None:
        sport_field = sport_key
    sport_fields = (sport_field,) if isinstance(sport_field, str) else tuple(sport_field)

    date_compact = _norm_date(date_str)
    data = _load()
    pending = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p.get("sport") in sport_fields
        and p.get("result") in (None, "pending")
        and p.get("odds") is not None
    ]

    if not pending:
        print(f"  No pending {sport_name} picks for {date_str}")
        return

    print(f"  Fetching {sport_name} scores from Odds API...")
    games = _fetch_scores_generic(sport_key, date_compact)

    # ESPN fallback: Odds API scores only go back 3 days — ESPN's scoreboard
    # covers the whole season for sports registered in _ESPN_SCOREBOARD_PATHS.
    if not games and sport_key in _ESPN_SCOREBOARD_PATHS:
        print(f"  Odds API has no scores for {date_str} — falling back to ESPN scoreboard...")
        games = _fetch_scores_espn(sport_key, date_compact)

    # Tennis fallback: Odds API has no tennis scores — use ESPN Core API
    espn_winners: dict[str, str] = {}
    if not games and sport_key.startswith("tennis_"):
        tour = "atp" if "atp" in sport_key else "wta"
        print(f"  Odds API has no tennis scores — falling back to ESPN Core API ({tour.upper()})...")
        espn_winners = _fetch_tennis_results_espn(tour, date_compact)
        if espn_winners:
            n_matches = sum(1 for v in espn_winners.values() if v == "win")
            print(f"  ESPN: {n_matches} completed match(es) found.")
        else:
            print(f"  No {sport_name} completed games found for {date_str}")
            return
    elif not games:
        print(f"  No {sport_name} completed games found for {date_str}")
        return

    if games:
        print(f"  Found {len(games)//2} {sport_name} game(s). Grading {len(pending)} pick(s)...")
    graded = 0

    for pick in pending:
        team   = pick.get("team", "")
        market = pick.get("market", "moneyline")
        odds   = float(pick["odds"])
        sign   = "+" if odds > 0 else ""

        # ── Tennis: use ESPN winner lookup (no game_info structure) ──────────
        if espn_winners:
            t_lower = team.lower().strip()
            result = espn_winners.get(t_lower)
            if result is None:
                # last-name fallback
                last = t_lower.split()[-1] if t_lower.split() else ""
                for wname, res in espn_winners.items():
                    if last and len(last) > 3 and wname.split()[-1] == last:
                        result = res
                        break
            if result is None:
                print(f"  ⚫ UNGRADED  {team} — not found in ESPN results")
                continue
            won = result == "win"
            profit = _profit(pick["stake"], odds, won)
            pick["result"]     = "win" if won else "loss"
            pick["profit"]     = round(profit, 4)
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
            icon = "🟢 WIN " if won else "🔴 LOSS"
            print(f"  {icon}  {team:<28} ({sign}{int(odds):+d})  →  {profit:+.2f}u")
            graded += 1
            continue

        # Fuzzy game lookup
        game_info = games.get(team)
        if not game_info:
            for gt, gi in games.items():
                if len(team) > 3 and (team.lower() in gt.lower() or gt.lower() in team.lower()):
                    game_info = gi
                    break

        if not game_info:
            # Try matching via matchup field
            matchup = pick.get("matchup", "")
            for gt, gi in games.items():
                if gi["home"] in matchup or gi["away"] in matchup:
                    game_info = gi
                    break

        if not game_info:
            print(f"  ⚠️  No score found for {team} ({sport_name}) — skipping")
            continue

        result = _settle_game_pick(pick, game_info)
        if result is None:
            print(f"  ⚠️  Unknown market {market} for {team} — skipping")
            continue

        graded += 1
        if result == "push":
            print(f"  ⬜ PUSH  {team:<28} ({int(odds):+d})")
            continue
        icon = "🟢 WIN " if result == "win" else "🔴 LOSS"
        prof = f"{pick['profit']:+.2f}u"
        final = f"{game_info['away']} {game_info['away_score']:.0f} @ {game_info['home']} {game_info['home_score']:.0f}"
        print(f"  {icon}  {team:<28} ({int(odds):+d})  {market:10}  →  {prof}  |  {final}")

    _save(data)
    print(f"  Graded {graded}/{len(pending)} {sport_name} picks.")


def _grade_tennis_backlog() -> None:
    """Grade every pending tennis pick (any date) from tennis-data.co.uk.

    Moneyline: winner match. Totals: sum of per-set games vs the line; a
    retirement voids the total (push) but still settles the moneyline.
    Picks whose match hasn't appeared in the data yet stay pending — the
    source updates ~daily during tournaments, so re-runs converge.
    """
    from datetime import date as _dt_date
    from src.data.tennis_results import build_results_index, find_result
    from src.data.tennis_data import norm_odds_name

    data = _load()
    pending = [
        p for p in data["picks"]
        if str(p.get("sport", "")).startswith("tennis_")
        and p.get("result") in (None, "pending")
        and p.get("odds") is not None
    ]
    if not pending:
        print("  No pending tennis picks.")
        return

    indexes = {
        "atp": build_results_index("atp"),
        "wta": build_results_index("wta"),
    }
    graded = voided = 0

    for pick in pending:
        tour = "wta" if "_wta_" in str(pick.get("sport", "")) else "atp"
        matchup = str(pick.get("matchup", ""))
        for sep in (" vs ", " @ "):
            if sep in matchup:
                a, b = [t.strip() for t in matchup.split(sep, 1)]
                break
        else:
            continue
        try:
            pick_date = _dt_date.fromisoformat(str(pick.get("date")))
        except (ValueError, TypeError):
            continue

        rec = find_result(indexes[tour], a, b, pick_date)
        if rec is None:
            continue

        market = str(pick.get("market", "moneyline"))
        odds = float(pick["odds"])
        stake = float(pick.get("stake") or 0) or 1.0   # shadow analysis at 1u flat
        now_iso = datetime.now(timezone.utc).isoformat()

        if market == "moneyline":
            team_key = norm_odds_name(str(pick.get("team", "")))
            won = (team_key == rec["winner_key"]
                   or team_key.rsplit(" ", 1)[0] == rec["winner_key"].rsplit(" ", 1)[0])
            pick["result"] = "win" if won else "loss"
            pick["profit"] = round(_profit(stake, odds, won), 4)
        elif market == "total":
            if not rec.get("completed") or rec.get("games") is None:
                pick["result"] = "push"    # retirement → total voided
                pick["profit"] = 0.0
                voided += 1
            else:
                line = float(pick.get("line") or
                             str(pick.get("team", "")).split()[-1])
                games = float(rec["games"])
                direction = str(pick.get("direction") or
                                str(pick.get("team", "")).split()[0]).upper()
                if games == line:
                    pick["result"] = "push"
                    pick["profit"] = 0.0
                else:
                    won = (games > line) if direction == "OVER" else (games < line)
                    pick["result"] = "win" if won else "loss"
                    pick["profit"] = round(_profit(stake, odds, won), 4)
        else:
            continue

        pick["resulted_at"] = now_iso
        graded += 1

    _save(data)
    still = len(pending) - graded
    print(f"  Graded {graded} tennis pick(s) ({voided} voided on retirement); "
          f"{still} still pending (match not in source yet).")


def _grade_outright(sport_field: str, sport_name: str, date_str: str, winner: str) -> None:
    """
    Grade outright winner picks (PGA, NASCAR, IndyCar, F1) by providing the winner's name.

    winner — the actual race/tournament winner (fuzzy matched against pick team field)
    """
    date_compact = _norm_date(date_str)
    data = _load()
    pending = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p.get("sport") == sport_field
        and p.get("result") in (None, "pending")
    ]

    if not pending:
        print(f"  No pending {sport_name} picks for {date_str}")
        return

    print(f"\n  Grading {len(pending)} {sport_name} outright pick(s). Winner: {winner}")
    graded = 0
    for pick in pending:
        team = pick.get("team", "")
        odds = float(pick.get("odds") or 0)
        won  = (winner.lower() == team.lower()) or (team.lower() in winner.lower()) or (winner.lower() in team.lower())
        pick["result"] = "win" if won else "loss"
        pick["profit"] = round(_profit(pick.get("stake", 1.0), odds, won), 4)
        pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
        graded += 1
        icon = "🟢 WIN " if won else "🔴 LOSS"
        prof = f"{pick['profit']:+.2f}u"
        sign = "+" if odds > 0 else ""
        print(f"  {icon}  {team:<30} ({sign}{int(odds)})  →  {prof}")

    _save(data)
    print(f"  Graded {graded}/{len(pending)} {sport_name} picks.")


def _grade_nba_props_v2(date_str: str) -> None:
    """
    Grade NBA player props logged under sport='basketball_nba' with per-market names
    (player_points, player_rebounds, etc.) — new schema from run_nba_props.py.
    """
    date_compact = _norm_date(date_str)
    data = _load()
    pending = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p.get("sport") in ("basketball_nba",)
        and p.get("market") in _PROP_MARKET_TO_STAT
        and p.get("result") in (None, "pending")
    ]
    if not pending:
        return

    stats = _fetch_nba_player_stats(date_compact)
    if not stats:
        print(f"  [nba props v2] No NBA stats for {date_str}")
        return

    print(f"\n  ── NBA props (new schema) ──")
    graded = 0
    for pick in pending:
        player = pick.get("player") or pick.get("team", "").split(" OVER")[0].split(" UNDER")[0].strip()
        market = pick.get("market", "player_points")
        stat_key = _PROP_MARKET_TO_STAT.get(market)
        if not stat_key:
            continue

        actual = None
        for name, s in stats.items():
            if name == player or player.lower() in name.lower() or name.lower() in player.lower():
                actual = s.get(stat_key)
                break

        if actual is None:
            pick["result"] = "void"; pick["profit"] = 0.0
            pick["resulted_at"] = datetime.now(timezone.utc).isoformat()
            print(f"  ⚫ VOID  {player} {market} (DNP)")
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
        icon = {"win": "🟢 WIN ", "loss": "🔴 LOSS", "push": "⬜ PUSH"}.get(pick["result"], "?")
        print(f"  {icon}  {player:<25} {direction} {line:<5}  ({int(odds):+d})  →  {pick['profit']:+.2f}u  ({stat_key}: {actual})")

    _save(data)
    if graded:
        print(f"  Graded {graded}/{len(pending)} NBA props (new schema).")


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


def _grade_nhl_props(date_str: str) -> None:
    """Grade NHL player props using api-web.nhle.com boxscore data."""
    import requests

    _NHL_PROP_STAT: dict[str, str] = {
        "player_points":         "points",
        "player_goals":          "goals",
        "player_assists":        "assists",
        "player_shots_on_goal":  "sog",
        "player_blocked_shots":  "blockedShots",
    }

    date_compact = _norm_date(date_str)
    date_iso = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}"

    data = _load()
    pending = [
        p for p in data["picks"]
        if _norm_date(p.get("date", "")) == date_compact
        and p.get("sport") in ("nhl", "icehockey_nhl")
        and p.get("market") in _NHL_PROP_STAT
        and p.get("result") in (None, "pending")
    ]
    if not pending:
        return

    # Fetch game IDs for the date
    try:
        resp = requests.get(
            f"https://api-web.nhle.com/v1/score/{date_iso}",
            timeout=12,
        )
        games_raw = resp.json().get("games", []) if resp.status_code == 200 else []
    except Exception as e:
        print(f"  [nhl props] schedule error: {e}")
        return

    # Build player_name_lower → stats dict from all game boxscores
    player_stats: dict[str, dict] = {}
    for game in games_raw:
        state = game.get("gameState", "")
        if state not in ("OFF", "FINAL"):
            continue
        gid = game.get("id")
        if not gid:
            continue
        try:
            bx = requests.get(
                f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore",
                timeout=12,
            )
            bd = bx.json() if bx.status_code == 200 else {}
        except Exception:
            continue

        for side in ("homeTeam", "awayTeam"):
            team_data = bd.get("playerByGameStats", {}).get(side, {})
            for group in ("forwards", "defense"):
                for p in team_data.get(group, []):
                    raw_name = p.get("name", {})
                    full = raw_name.get("default", "") if isinstance(raw_name, dict) else str(raw_name)
                    if full:
                        player_stats[full.lower()] = p

    if not player_stats:
        print(f"  [nhl props] No boxscore data for {date_str}")
        return

    print(f"\n  ── NHL player props ({len(pending)} picks) ──")
    graded = 0
    now_str = datetime.now(timezone.utc).isoformat()

    for pick in pending:
        player = (pick.get("player") or pick.get("team") or "").strip()
        # Strip line suffix e.g. "C. Caufield OVER 0.5"
        for tok in ("OVER", "UNDER"):
            if tok in player.upper():
                player = player[:player.upper().index(tok)].strip()
                break

        market = pick.get("market", "")
        stat_key = _NHL_PROP_STAT.get(market)
        if not stat_key:
            continue

        # Match pick full name (e.g. "Sebastian Aho") against boxscore abbreviated name
        # (e.g. "S. Aho"). Strategy: match on last name + first initial.
        pname_lower = player.lower()
        stats = player_stats.get(pname_lower)
        if not stats:
            pick_parts = pname_lower.split()
            pick_last = pick_parts[-1] if pick_parts else ""
            pick_init = pick_parts[0][0] if pick_parts else ""
            for name, s in player_stats.items():
                name_parts = name.split()
                name_last = name_parts[-1] if name_parts else ""
                name_first = name_parts[0].rstrip(".") if name_parts else ""
                if name_last == pick_last and name_first == pick_init:
                    stats = s
                    break
            # Fallback: substring match
            if not stats:
                for name, s in player_stats.items():
                    if pname_lower in name or name in pname_lower:
                        stats = s
                        break

        if stats is None:
            pick["result"] = "void"
            pick["profit"] = 0.0
            pick["resulted_at"] = now_str
            print(f"  ⚫ VOID  {player} {market} (DNP / not found)")
            graded += 1
            continue

        actual = stats.get(stat_key)
        if actual is None:
            continue

        line = float(pick.get("line") or 0)
        direction = (pick.get("direction") or "OVER").upper()
        odds = float(pick.get("odds") or 0)

        if actual == line:
            pick["result"] = "push"
            pick["profit"] = 0.0
        else:
            won = (actual > line) if direction == "OVER" else (actual < line)
            pick["result"] = "win" if won else "loss"
            pick["profit"] = round(_profit(pick.get("stake", 1.0), odds, won), 4)
        pick["resulted_at"] = now_str
        graded += 1

        icon = {"win": "🟢 WIN ", "loss": "🔴 LOSS", "push": "⬜ PUSH"}.get(pick["result"], "?")
        print(f"  {icon}  {player:<25} {direction} {line:<5}  ({int(odds):+d})  →  {pick['profit']:+.2f}u  ({stat_key}: {actual})")

    _save(data)
    if graded:
        print(f"  Graded {graded}/{len(pending)} NHL props.")


_ALL_SPORTS = [
    "all", "mlb", "nba", "nhl", "wnba", "soccer", "tennis", "ufc", "pga",
]

# Maps short sport name → (odds_api_key, sport_field_values_in_picks).
# Pick writers have stamped both short names and Odds API keys over time,
# so each entry matches every value that has appeared in picks.json.
_GENERIC_SPORT_MAP = {
    "wnba": ("basketball_wnba", ("wnba", "basketball_wnba")),
    "ufc":  ("mma_mixed_martial_arts", ("ufc", "mma_mixed_martial_arts")),
}

_OUTRIGHT_SPORT_MAP = {
    "pga": "golf_pga_championship",
}


def main():
    parser = argparse.ArgumentParser(
        prog="grade",
        description="Grade picks against actual results (all sports).",
    )
    parser.add_argument("cmd",    nargs="?", help="win | loss | (blank=auto)")
    parser.add_argument("team",   nargs="?", help="Team/player name for win/loss")
    parser.add_argument("--date",   help="Date to grade YYYYMMDD (default: yesterday)")
    parser.add_argument("--sport",  default="all", choices=_ALL_SPORTS,
                        help="Which sport to grade (default: all)")
    parser.add_argument("--winner", help="Outright winner name (for pga)")
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

        sport = args.sport

        # ── MLB ──────────────────────────────────────────────────────────
        if sport in ("all", "mlb"):
            auto_grade(grade_date)
            _grade_mlb_props(grade_date)
            if args.recap_card:
                generate_recap_card(grade_date)

        # ── NBA (game lines + both prop schemas) ─────────────────────────
        if sport in ("all", "nba"):
            print(f"\n  ── Grading NBA picks for {grade_date} ──")
            _grade_nba(grade_date)
            _grade_nba_props_v2(grade_date)

        # ── NHL (game lines + player props) ─────────────────────────────
        if sport in ("all", "nhl"):
            print(f"\n  ── Grading NHL picks for {grade_date} ──")
            _grade_nhl(grade_date)
            _grade_nhl_props(grade_date)

        # ── WNBA / UFC (generic Odds API scores) ─────────────────────────
        for short, (api_key, field) in _GENERIC_SPORT_MAP.items():
            if sport in ("all", short):
                label = short.upper()
                print(f"\n  ── Grading {label} picks for {grade_date} ──")
                _grade_sport_generic(api_key, label, grade_date, sport_field=field)

        # ── Soccer — grade each league that has pending picks ─────────────
        if sport in ("all", "soccer"):
            date_compact = _norm_date(grade_date)
            data_tmp = _load()
            soccer_keys = sorted({
                p.get("sport", "")
                for p in data_tmp["picks"]
                if _norm_date(p.get("date", "")) == date_compact
                and (p.get("sport", "").startswith("soccer_"))
                and p.get("result") in (None, "pending")
            })
            if soccer_keys:
                print(f"\n  ── Grading SOCCER picks for {grade_date} ──")
                for sk in soccer_keys:
                    label = sk.replace("soccer_", "").replace("_", " ").upper()
                    _grade_sport_generic(sk, f"SOCCER/{label}", grade_date, sport_field=sk)
            else:
                print(f"\n  ── Grading SOCCER picks for {grade_date} ──")
                print(f"  No pending SOCCER picks for {grade_date}")

        # ── Tennis — bulk-grade ALL pending picks from tennis-data.co.uk ──
        # (winner + set scores per match, both tours, ~daily updates). This
        # replaced the ESPN winners-only path, which covered only Grand Slam
        # moneylines and left every total pending forever.
        if sport in ("all", "tennis"):
            print(f"\n  ── Grading TENNIS picks (full backlog) ──")
            _grade_tennis_backlog()

        # ── Outright winner markets (PGA only) ────────────────────────────
        for short, field in _OUTRIGHT_SPORT_MAP.items():
            if sport in ("all", short):
                if args.winner:
                    label = short.upper()
                    print(f"\n  ── Grading {label} picks for {grade_date} ──")
                    _grade_outright(field, label, grade_date, winner=args.winner)
                elif sport == short:
                    print(f"\n  [{short.upper()}] Outright markets require --winner \"Player Name\"")
                    print(f"  Example: python3 grade.py --sport {short} --date {grade_date} --winner \"Scottie Scheffler\"")

        # ── Update public stats after all grading ─────────────────────────
        try:
            from src.analytics.public_stats import write_public_stats
            write_public_stats()
        except Exception as e:
            print(f"  [stats] {e}")


if __name__ == "__main__":
    main()
