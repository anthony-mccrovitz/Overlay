"""
Daily franchise bet logger — all 30 MLB teams.

Logs 3 shadow bets per team per game:
  - Moneyline              (win straight up)
  - run_line     (-1.5)   (team is the FAVORITE)
  - run_line_dog (+1.5)   (team is the UNDERDOG)

After 30+ picks per team/market, see who validates:
  python3 chef.py franchise --leaderboard

Also callable standalone:
  python3 scripts/run_franchise_bets.py
  python3 scripts/run_franchise_bets.py --date 20260607
  python3 scripts/run_franchise_bets.py --grade
  python3 scripts/run_franchise_bets.py --leaderboard
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.analytics.franchise_tracker import (
    load_config, load_bets, save_bets, build_records, print_report, print_leaderboard
)


# ── Math helpers ──────────────────────────────────────────────────────────────

def _american_to_prob(odds: float) -> float:
    if odds >= 100:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def _make_bet(
    bet_id: str, date_iso: str, team: str, slug: str, matchup: str,
    market: str, direction: str, line: float | None,
    odds: int, implied_pct: float, book: str,
) -> dict:
    return {
        "bet_id":      bet_id,
        "date":        date_iso,
        "team":        team,
        "team_slug":   slug,
        "matchup":     matchup,
        "market":      market,
        "direction":   direction,
        "line":        line,
        "odds":        odds,
        "implied_pct": round(implied_pct, 2),
        "sportsbook":  book,
        "stake":       1.0,
        "result":      None,
        "profit":      None,
        "logged_at":   datetime.now().isoformat(),
    }


# ── Team lookup ───────────────────────────────────────────────────────────────

def _build_team_lookup(teams_cfg: list[dict]) -> dict[str, dict]:
    """Build name → team-config lookup indexed by full name, last word, and aliases."""
    lookup: dict[str, dict] = {}
    for tc in teams_cfg:
        name_low = tc["name"].lower()
        lookup[name_low] = tc
        # Last word shortcut: "astros", "yankees", "dodgers" …
        last = name_low.split()[-1]
        lookup.setdefault(last, tc)
        # Explicit aliases (e.g., "red sox", "blue jays")
        for alias in tc.get("aliases", []):
            lookup[alias.lower()] = tc
    return lookup


def _resolve_team(raw_name: str, lookup: dict[str, dict]) -> tuple[str, str]:
    """Return (slug, canonical_name). Falls back to last-word slug if unknown."""
    tn = raw_name.lower().strip()
    if tn in lookup:
        tc = lookup[tn]
        return tc["slug"], tc["name"]
    last = tn.split()[-1]
    if last in lookup:
        tc = lookup[last]
        return tc["slug"], tc["name"]
    # Unknown team — use last word as slug, raw name as display name
    return last, raw_name


# ── Core logger ───────────────────────────────────────────────────────────────

def log_franchise_bets(target_date: date | None = None) -> list[dict]:
    """
    Fetch today's MLB odds and log 3 shadow bets (ML, RL-fav, RL-dog)
    for every team playing today.  Returns list of newly logged bets.
    """
    if target_date is None:
        target_date = date.today()

    cfg        = load_config()
    team_lookup = _build_team_lookup(cfg.get("teams", []))
    date_str   = target_date.strftime("%Y%m%d")
    date_iso   = target_date.strftime("%Y-%m-%d")

    # ── Fetch odds ────────────────────────────────────────────────────────────
    try:
        from src.data.odds_api import fetch_odds, get_best_odds
        df_ml = get_best_odds(fetch_odds("h2h",     sport="baseball_mlb", refresh=True), market="h2h")
        df_rl = get_best_odds(fetch_odds("spreads",  sport="baseball_mlb", refresh=True), market="spreads")
    except Exception as e:
        print(f"  [franchise] Odds fetch failed: {e}")
        return []

    if df_ml.empty:
        print(f"  [franchise] No MLB games found for {date_iso}")
        return []

    # ── Build RL lookup by home team name ─────────────────────────────────────
    rl_by_home: dict[str, object] = {}
    for _, row in df_rl.iterrows():
        key = str(row.get("HomeTeam", "")).lower()
        rl_by_home[key] = row

    # ── Already-logged bet IDs (dedup) ────────────────────────────────────────
    logged_ids = {b["bet_id"] for b in load_bets() if "bet_id" in b}

    new_bets: list[dict] = []

    for _, ml_row in df_ml.iterrows():
        home_raw = str(ml_row.get("HomeTeam", "")).strip()
        away_raw = str(ml_row.get("AwayTeam", "")).strip()
        if not home_raw or not away_raw:
            continue

        matchup  = f"{away_raw} @ {home_raw}"
        rl_row   = rl_by_home.get(home_raw.lower())

        # Home spread (sign tells us who's the fav)
        home_spread = None
        away_spread = None
        if rl_row is not None:
            hs = rl_row.get("HomeSpread")
            as_ = rl_row.get("AwaySpread")
            if hs is not None:
                home_spread = float(hs)
            if as_ is not None:
                away_spread = float(as_)
            elif home_spread is not None:
                away_spread = -home_spread

        for position in ("home", "away"):
            team_raw  = home_raw if position == "home" else away_raw
            slug, canonical = _resolve_team(team_raw, team_lookup)

            # ── Moneyline ────────────────────────────────────────────────────
            ml_col    = "BestHomeML"      if position == "home" else "BestAwayML"
            book_col  = "BestHomeSportsbook" if position == "home" else "BestAwaySportsbook"
            impl_col  = "HomeImpliedProb" if position == "home" else "AwayImpliedProb"

            ml_odds   = ml_row.get(ml_col)
            ml_book   = str(ml_row.get(book_col, ""))
            ml_impl   = float(ml_row.get(impl_col) or 0)

            if ml_odds and float(ml_odds) != 0:
                bet_id = f"franchise_{date_str}_{slug}_moneyline_{position}"
                if bet_id not in logged_ids:
                    new_bets.append(_make_bet(
                        bet_id, date_iso, canonical, slug, matchup,
                        "moneyline", position, None,
                        int(float(ml_odds)), ml_impl * 100, ml_book,
                    ))

            # ── Run line ─────────────────────────────────────────────────────
            if rl_row is not None:
                rl_line = home_spread if position == "home" else away_spread
                if rl_line is None:
                    continue

                if position == "home":
                    rl_odds = rl_row.get("BestHomeSpreadOdds")
                    rl_book = str(rl_row.get("BestHomeSpreadBook", ""))
                else:
                    rl_odds = rl_row.get("BestAwaySpreadOdds")
                    rl_book = str(rl_row.get("BestAwaySpreadBook", ""))

                if not rl_odds or float(rl_odds) == 0:
                    continue

                # Market name encodes which side: fav (-1.5) or dog (+1.5)
                rl_market = "run_line" if rl_line < 0 else "run_line_dog"
                bet_id    = f"franchise_{date_str}_{slug}_{rl_market}_{position}"
                if bet_id not in logged_ids:
                    implied = _american_to_prob(float(rl_odds)) * 100
                    new_bets.append(_make_bet(
                        bet_id, date_iso, canonical, slug, matchup,
                        rl_market, position, round(rl_line, 1),
                        int(float(rl_odds)), round(implied, 2), rl_book,
                    ))

    # ── Persist ───────────────────────────────────────────────────────────────
    if new_bets:
        save_bets(new_bets)
        n_games = len(df_ml)
        print(f"  [franchise] Logged {len(new_bets)} shadow bets for {date_iso} ({n_games} games)")
        # Summary line per team
        teams_seen = {}
        for b in new_bets:
            k = b["team_slug"]
            teams_seen.setdefault(k, {"team": b["team"], "markets": []})
            line_s = f"{b['line']:+.1f}" if b.get("line") is not None else "—"
            teams_seen[k]["markets"].append(f"{b['market']}({line_s} @ {b['odds']:+d})")
        for k, v in sorted(teams_seen.items()):
            print(f"    {v['team']:28}  {', '.join(v['markets'])}")
    else:
        print(f"  [franchise] No new bets for {date_iso} (all logged or no games)")

    return new_bets


# ── Grader ────────────────────────────────────────────────────────────────────

def grade_yesterday(verbose: bool = True) -> int:
    """
    Grade all unresolved franchise bets from yesterday using final MLB scores.
    Returns number of bets graded.
    """
    yesterday = date.today() - timedelta(days=1)
    date_iso  = yesterday.strftime("%Y-%m-%d")

    try:
        from src.data.mlb_stats import get_final_scores
        scores_raw = get_final_scores(yesterday)
    except Exception as e:
        if verbose:
            print(f"  [franchise] Score fetch failed: {e}")
        return 0

    # Build matchup → scores dict  ("Away @ Home" → {home_score, away_score})
    scores: dict[str, dict] = {}
    for g in (scores_raw or []):
        home = g.get("home_team", "")
        away = g.get("away_team", "")
        key  = f"{away} @ {home}"
        scores[key] = {
            "home_score": g.get("home_score", 0),
            "away_score": g.get("away_score", 0),
        }

    from src.analytics.franchise_tracker import grade_bets
    n = grade_bets(scores)
    if verbose and n:
        print(f"  [franchise] Graded {n} bet(s) from {date_iso}")
    return n


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Franchise bet logger / grader / leaderboard")
    parser.add_argument("--date",        default=None, help="YYYYMMDD (default: today)")
    parser.add_argument("--grade",       action="store_true", help="Grade yesterday's bets")
    parser.add_argument("--report",      action="store_true", help="Full per-team report")
    parser.add_argument("--leaderboard", action="store_true", help="ROI-ranked leaderboard")
    parser.add_argument("--min-picks",   type=int, default=5, help="Min picks for leaderboard (default 5)")
    args = parser.parse_args()

    if args.grade:
        n = grade_yesterday()
        print(f"  Graded {n} bets.")
        print_leaderboard(min_picks=args.min_picks)
    elif args.leaderboard:
        print_leaderboard(min_picks=args.min_picks)
    elif args.report:
        print_report()
    else:
        if args.date:
            d = date(int(args.date[:4]), int(args.date[4:6]), int(args.date[6:]))
        else:
            d = date.today()
        log_franchise_bets(d)
        print_leaderboard(min_picks=args.min_picks)
