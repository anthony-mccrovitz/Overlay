"""
Automated pick grading — pulls results from MLB Stats API and grades picks.

Handles:
  1. Fetching final scores from the MLB API
  2. Fetching closing odds from the-odds-api
  3. Matching results to picks (both picks.json and CLV tracker records)
  4. Updating P&L and CLV trackers
  5. Generating a grading report
"""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from src.tracking.clv import CLVTracker
from src.tracking.ids import make_game_id
from src.tracking.pnl import PnLTracker
from src.tracking.schema import profit_from_odds as _profit_units


PICKS_DIR = Path("output/picks")
MLB_API = "https://statsapi.mlb.com/api/v1"


def _fmt_american(odds) -> str:
    """Format American odds for display (+150, -110)."""
    try:
        x = float(odds)
    except (TypeError, ValueError):
        return "?"
    if math.isnan(x):
        return "?"
    return f"{int(round(x)):+d}"


def _mlb_get(endpoint: str, params: dict | None = None) -> dict:
    """Direct MLB API call with short cache for live results."""
    resp = requests.get(f"{MLB_API}/{endpoint}", params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_final_scores(game_date: date | None = None) -> list[dict]:
    """Fetch all completed MLB games for a date with final scores."""
    d = game_date or date.today()

    data = _mlb_get("schedule", {
        "date": d.isoformat(),
        "sportId": 1,
        "hydrate": "team,linescore",
    })

    results = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            state = game.get("status", {}).get("abstractGameState", "")
            detailed_state = game.get("status", {}).get("detailedState", "")

            home_info = game.get("teams", {}).get("home", {})
            away_info = game.get("teams", {}).get("away", {})

            home_name = home_info.get("team", {}).get("name", "")
            away_name = away_info.get("team", {}).get("name", "")
            home_score = home_info.get("score")
            away_score = away_info.get("score")

            # Extract first-inning runs from linescore for NRFI grading
            innings = game.get("linescore", {}).get("innings", [])
            first_inn = next((i for i in innings if i.get("num") == 1), None)
            first_inn_home = None
            first_inn_away = None
            if first_inn:
                first_inn_home = first_inn.get("home", {}).get("runs")
                first_inn_away = first_inn.get("away", {}).get("runs")

            results.append({
                "game_pk": game.get("gamePk"),
                "home_team": home_name,
                "away_team": away_name,
                "home_score": int(home_score) if home_score is not None else None,
                "away_score": int(away_score) if away_score is not None else None,
                "state": state,
                "detailed_state": detailed_state,
                "first_inning_home_runs": int(first_inn_home) if first_inn_home is not None else None,
                "first_inning_away_runs": int(first_inn_away) if first_inn_away is not None else None,
            })

    return results


def load_picks(sport: str = "baseball_mlb", pick_date: date | None = None) -> list[dict]:
    """
    Load card picks for a given date.
    Prefers picks_card.json (exact 5 picks shown on the card) over picks.json.
    picks_card.json is written by _save_picks() in predict.py at card-gen time.
    """
    d = pick_date or date.today()
    date_str = d.strftime("%Y%m%d")
    base = PICKS_DIR / sport / date_str

    # Prefer picks_card.json — always matches the card exactly
    for fname in ("picks_card.json", "picks.json"):
        path = base / fname
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    return []


def _load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _spread_side_won(
    team: str,
    home_name: str,
    away_name: str,
    home_score: int,
    away_score: int,
    market_spread_home: float,
) -> bool | None:
    """
    Run-line cover: `market_spread_home` is the home team's line (e.g. -1.5).
    Returns True/False if final, None if scores missing.
    """
    if home_score is None or away_score is None:
        return None
    margin = home_score - away_score
    if _normalize(team) == _normalize(home_name):
        return margin + market_spread_home > 0
    if _normalize(team) == _normalize(away_name):
        return -margin + (-market_spread_home) > 0
    return None


def _total_outcome(direction: str, line: float, home_score: int, away_score: int) -> str | None:
    """Returns 'win', 'loss', or 'push' for O/U."""
    if home_score is None or away_score is None:
        return None
    total_runs = home_score + away_score
    d = direction.upper()
    if abs(total_runs - line) < 1e-6:
        return "push"
    if d == "OVER":
        return "win" if total_runs > line else "loss"
    if d == "UNDER":
        return "win" if total_runs < line else "loss"
    return None


def _normalize(name: str) -> str:
    """Normalize team name for fuzzy matching."""
    return name.strip().lower().replace(".", "").replace("'", "")


TEAM_ALIASES = {
    "athletics": ["athletics", "oakland athletics", "as"],
    "d-backs": ["arizona diamondbacks", "diamondbacks"],
}


def _match_team_to_result(team_name: str, results: list[dict]) -> dict | None:
    """Find the game result matching a team name via fuzzy matching."""
    tn = _normalize(team_name)

    for r in results:
        home_n = _normalize(r["home_team"])
        away_n = _normalize(r["away_team"])
        if tn == home_n or tn == away_n:
            return r

    for r in results:
        home_n = _normalize(r["home_team"])
        away_n = _normalize(r["away_team"])
        if tn in home_n or tn in away_n:
            return r
        if home_n in tn or away_n in tn:
            return r

    team_parts = tn.split()
    for r in results:
        home_parts = _normalize(r["home_team"]).split()
        away_parts = _normalize(r["away_team"]).split()
        if team_parts[-1] in home_parts or team_parts[-1] in away_parts:
            return r

    return None


def _team_won(team_name: str, result: dict) -> bool | None:
    """Did the named team win? Returns None if game not final."""
    if result["home_score"] is None or result["away_score"] is None:
        return None
    if result["state"] != "Final":
        return None

    tn = _normalize(team_name)
    home_n = _normalize(result["home_team"])
    away_n = _normalize(result["away_team"])

    is_home = (
        tn == home_n
        or tn in home_n
        or home_n in tn
        or tn.split()[-1] in home_n.split()
    )

    if is_home:
        return result["home_score"] > result["away_score"]
    return result["away_score"] > result["home_score"]


def _profit(stake: float, odds: float, won: bool) -> float:
    """Thin wrapper — delegates to canonical schema.profit_from_odds."""
    from src.tracking.schema import profit_from_odds
    if odds is None or odds == 0:
        # Missing price — assume -110 payout (preserves prior behavior for display path)
        return stake * (100 / 110) if won else -stake
    return profit_from_odds(odds, stake, won)


def fetch_closing_odds(sport: str = "baseball_mlb") -> dict[str, dict]:
    """
    Fetch current odds as closing-line proxy.
    Returns dict keyed by normalized team name.
    Best accuracy when called close to first pitch.
    """
    try:
        from src.data.odds_api import fetch_odds, _american_to_prob
    except ImportError:
        return {}

    raw = fetch_odds(sport=sport, refresh=True)
    if raw.empty:
        return {}

    closing: dict[str, dict] = {}
    for _, row in raw.iterrows():
        if "HomeMoneyline" not in raw.columns:
            continue
        home = str(row.get("HomeTeamCanonical") or row.get("HomeTeam", ""))
        away = str(row.get("AwayTeamCanonical") or row.get("AwayTeam", ""))

        for team, odds_col in [(home, "HomeMoneyline"), (away, "AwayMoneyline")]:
            odds = row.get(odds_col)
            tn = _normalize(team)
            if odds is None or tn in closing:
                continue
            closing[tn] = {
                "odds": int(odds),
                "sportsbook": row.get("Sportsbook", ""),
                "implied_prob": _american_to_prob(odds),
            }
    return closing


_PNL_FILE = Path("data/pnl/picks.json")


def _update_pnl_pick_result(
    pick_date: date,
    team: str,
    market: str,
    won: bool,
    profit: float,
) -> bool:
    """
    Update the result on an _auto_log_picks entry in data/pnl/picks.json.

    Matches by (date, team, market). Returns True if an entry was updated,
    False if no matching entry was found (caller should use PnLTracker instead).
    """
    if not _PNL_FILE.exists():
        return False
    try:
        data = json.loads(_PNL_FILE.read_text())
    except (json.JSONDecodeError, ValueError):
        return False

    date_str = pick_date.isoformat()
    team_lower = team.lower().strip()
    now_ts = datetime.now(tz=timezone.utc).isoformat()

    for p in data.get("picks", []):
        if (
            p.get("date") == date_str
            and p.get("team", "").lower().strip() == team_lower
            and p.get("market", "moneyline") == market
            and p.get("result") is None
        ):
            p["result"]      = "win" if won else "loss"
            p["profit"]      = round(profit, 4)
            p["resulted_at"] = now_ts
            from src.tracking.schema import rewrite_picks_safe
            rewrite_picks_safe(_PNL_FILE, data)
            return True
    return False


def _update_pnl_nrfi(nrfi_picks: list[dict], results: list[dict], pick_date: date) -> None:
    """
    Write NRFI pick results into pnl/picks.json so public_stats can show
    a real NRFI-specific record separate from moneyline picks.
    """
    if not nrfi_picks:
        return

    _PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(_PNL_FILE.read_text()) if _PNL_FILE.exists() else {"picks": []}
        if "picks" not in existing:
            existing = {"picks": []}
    except (json.JSONDecodeError, ValueError):
        existing = {"picks": []}

    date_str = pick_date.isoformat()
    now_ts = datetime.now(tz=timezone.utc).isoformat()

    # Build lookup key: (date, home_team, away_team, direction) to avoid dupes
    existing_keys = {
        (p.get("date", ""), p.get("home_team", "").lower(), p.get("away_team", "").lower(), p.get("direction", "").upper())
        for p in existing["picks"]
        if p.get("market") == "nrfi"
    }

    for np_ in nrfi_picks:
        home_t = np_.get("home_team", "")
        away_t = np_.get("away_team", "")
        direction = (np_.get("direction") or "NRFI").upper()
        key = (date_str, home_t.lower(), away_t.lower(), direction)

        if key in existing_keys:
            # Update result if it's now known
            for p in existing["picks"]:
                if (
                    p.get("market") == "nrfi"
                    and p.get("date") == date_str
                    and p.get("home_team", "").lower() == home_t.lower()
                    and p.get("away_team", "").lower() == away_t.lower()
                    and p.get("direction", "").upper() == direction
                    and p.get("result") is None
                ):
                    # Find result
                    result = None
                    for r in results:
                        if (
                            _normalize(r["home_team"]) == _normalize(home_t)
                            or _normalize(home_t) in _normalize(r["home_team"])
                        ):
                            if (
                                _normalize(r["away_team"]) == _normalize(away_t)
                                or _normalize(away_t) in _normalize(r["away_team"])
                            ):
                                result = r
                                break
                    if result and result["state"] == "Final":
                        h1 = result.get("first_inning_home_runs")
                        a1 = result.get("first_inning_away_runs")
                        if h1 is not None and a1 is not None:
                            runs_in_first = h1 + a1
                            won = (runs_in_first == 0) if direction == "NRFI" else (runs_in_first > 0)
                            p["result"] = "win" if won else "loss"
                            p["first_inning_runs"] = runs_in_first
                            p["resulted_at"] = now_ts
            continue

        # Only count toward public record if we have real odds to bet
        has_odds = np_.get("odds") is not None and not np_.get("no_odds")
        # Translate side-aware model probability so the calibrator can train on
        # NRFI history. Without this, model_prob was None on every NRFI pick
        # and recalibrate_all() had no data to fit a calibrator with — leaving
        # NRFI silently uncalibrated. (Bug found 2026-06-12.)
        projected_nrfi = np_.get("projected_nrfi")
        if projected_nrfi is not None:
            model_prob = float(projected_nrfi) if direction == "NRFI" else 1.0 - float(projected_nrfi)
        else:
            model_prob = None
        # Pre-calibration probability, side-matched — calibrator refits train
        # on THIS so they never re-learn their own previous output.
        projected_nrfi_raw = np_.get("projected_nrfi_raw")
        if projected_nrfi_raw is not None:
            model_prob_raw = (float(projected_nrfi_raw) if direction == "NRFI"
                              else 1.0 - float(projected_nrfi_raw))
        else:
            model_prob_raw = None
        implied = np_.get("implied_nrfi")
        edge_pct = np_.get("edge_pct")
        entry = {
            "date": date_str,
            "sport": "mlb",
            "market": "nrfi",
            "direction": direction,
            "home_team": home_t,
            "away_team": away_t,
            "team": f"{away_t} @ {home_t}",
            "matchup": f"{away_t} @ {home_t}",
            "opponent": f"{away_t} @ {home_t}",
            "odds": np_.get("odds") if has_odds else None,
            "stake": 1.0 if has_odds else 0.0,
            "card_pick": False,
            "projected_nrfi": projected_nrfi,
            "model_prob": model_prob,
            "model_prob_raw": model_prob_raw,
            "implied_prob": implied,
            "edge_pct": edge_pct,
            "result": None,
            "profit": None,
            "recorded_at": now_ts,
            "resulted_at": None,
        }

        # Try to grade immediately if results are available
        result = None
        for r in results:
            if (
                _normalize(r["home_team"]) == _normalize(home_t)
                or _normalize(home_t) in _normalize(r["home_team"])
            ):
                if (
                    _normalize(r["away_team"]) == _normalize(away_t)
                    or _normalize(away_t) in _normalize(r["away_team"])
                ):
                    result = r
                    break

        if result and result["state"] == "Final":
            h1 = result.get("first_inning_home_runs")
            a1 = result.get("first_inning_away_runs")
            if h1 is not None and a1 is not None:
                runs_in_first = h1 + a1
                won = (runs_in_first == 0) if direction == "NRFI" else (runs_in_first > 0)
                entry["result"] = "win" if won else "loss"
                entry["first_inning_runs"] = runs_in_first
                entry["resulted_at"] = now_ts

        existing["picks"].append(entry)
        existing_keys.add(key)

    from src.tracking.schema import rewrite_picks_safe
    rewrite_picks_safe(_PNL_FILE, existing)


def grade_picks(
    pick_date: date | None = None,
    sport: str = "baseball_mlb",
    flat_stake: float = 100.0,
    capture_closing: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Grade all picks for a date against actual MLB results.

    Returns a summary dict with W/L, profit, CLV, and per-pick details.
    """
    d = pick_date or date.today()
    date_str = d.strftime("%Y%m%d")
    report_dir = PICKS_DIR / sport / date_str

    picks = load_picks(sport, d)
    spread_picks = _load_json_list(report_dir / "picks_spreads.json")
    total_picks = _load_json_list(report_dir / "picks_totals.json")

    if not picks and not spread_picks and not total_picks:
        if verbose:
            print(f"  No picks found for {d.isoformat()}")
        return {"date": d.isoformat(), "picks": 0, "graded": 0}

    results = fetch_final_scores(d)
    final_games = [r for r in results if r["state"] == "Final"]
    live_games = [r for r in results if r["state"] == "Live"]

    n_all = len(picks) + len(spread_picks) + len(total_picks)
    if not final_games and not live_games:
        if verbose:
            total_scheduled = len(results)
            print(f"  No games finished yet for {d.isoformat()} ({total_scheduled} scheduled)")
        return {"date": d.isoformat(), "picks": n_all, "graded": 0, "pending": n_all}

    # Optionally capture closing odds for CLV
    closing_odds: dict = {}
    if capture_closing:
        try:
            closing_odds = fetch_closing_odds(sport)
        except Exception:
            pass

    clv_tracker = CLVTracker()
    pnl_tracker = PnLTracker()

    graded = []
    wins = 0
    losses = 0
    pending = 0
    total_profit = 0.0
    total_staked = 0.0

    if verbose:
        print(f"\n{'='*70}")
        print(f"  GRADING REPORT — {d.strftime('%A, %B %d, %Y')}")
        print(f"{'='*70}")
        print(
            f"  ML {len(picks)} | spreads {len(spread_picks)} | totals {len(total_picks)} "
            f"| {len(final_games)} final | {len(live_games)} live\n"
        )

    for pick in picks:
        team = pick.get("Team", "")
        opponent = pick.get("Opponent", "")
        market = str(pick.get("Market", "moneyline")).lower()

        # Totals from picks.json are model outputs — they don't appear on the card.
        # Only grade totals if they come from picks_totals.json (handled below).
        if market == "total":
            continue
        _bo = pick.get("BestOdds", 0)
        odds = float(_bo) if _bo is not None else 0.0
        model_prob = pick.get("ModelProb", 0)
        edge = pick.get("Edge", 0)
        book = pick.get("Sportsbook", "")
        game_id = make_game_id(d, team)

        # For spread/total picks, the team name may be "OVER 8.0" etc — use HomeTeam for lookup
        lookup_name = team
        if market == "total":
            lookup_name = pick.get("HomeTeam", "") or opponent

        result = _match_team_to_result(lookup_name, results)

        if result is None or result["state"] != "Final":
            pending += 1
            status_msg = "IN PROGRESS" if (result and result["state"] == "Live") else "NOT STARTED"
            if verbose:
                print(f"  {'LIVE' if result else 'PEND':4s}  {team} vs {opponent} — {status_msg}")
            graded.append({
                "team": team, "opponent": opponent, "odds": odds,
                "model_prob": model_prob, "status": "pending",
                "game_id": game_id,
            })
            continue

        hs = result["home_score"]
        aws = result["away_score"]

        # Grade based on market type
        if market == "spread":
            home_name = pick.get("HomeTeam", result["home_team"])
            market_spread = pick.get("MarketSpread")
            if market_spread is None:
                bet_line = pick.get("BetLine", "+1.5")
                try:
                    bet_line_val = float(bet_line)
                except (TypeError, ValueError):
                    bet_line_val = 1.5
                # BetLine is the picked team's line; MarketSpread is home team's line
                # If team is home: market_spread = bet_line_val
                # If team is away: market_spread = -bet_line_val
                team_is_home = _normalize(team) in _normalize(home_name) or _normalize(home_name) in _normalize(team)
                market_spread = bet_line_val if team_is_home else -bet_line_val
            won = _spread_side_won(team, home_name, result["away_team"], hs, aws, float(market_spread))
            bet_line_str = pick.get("BetLine", "?")
            label = f"{team} ({bet_line_str}) ({_fmt_american(odds)} @ {book})"
        elif market == "total":
            team_label = team  # e.g. "OVER 8.0" or "UNDER 9.0"
            parts = team_label.upper().split()
            direction = parts[0] if parts else "OVER"
            try:
                line = float(parts[1]) if len(parts) > 1 else float(pick.get("BetLine", 8.0))
            except (ValueError, IndexError):
                line = float(pick.get("BetLine", 8.0) or 8.0)
            out = _total_outcome(direction, line, hs, aws)
            if out is None:
                pending += 1
                continue
            won = out == "win"
            label = f"{team_label} ({_fmt_american(odds)} @ {book})"
        else:
            # moneyline
            won = _team_won(team, result)
            if won is None:
                pending += 1
                continue
            label = f"{team} ({_fmt_american(odds)} @ {book})"

        if won is None:
            pending += 1
            continue

        profit = _profit(flat_stake, odds, won)
        total_profit += profit
        total_staked += flat_stake

        if won:
            wins += 1
        else:
            losses += 1

        # -- Update CLV tracker (moneyline only) --
        if market == "moneyline":
            tn = _normalize(team)
            if tn in closing_odds:
                cl = closing_odds[tn]
                try:
                    clv_tracker.record_closing_line(game_id, team, cl["odds"])
                except Exception as e:
                    print(f"  ⚠ CLV record_closing_line failed for {team} ({game_id}): {e}")
            try:
                clv_tracker.record_result(game_id, team, won)
            except Exception as e:
                print(f"  ⚠ CLV record_result failed for {team} ({game_id}): {e}")

        # -- Update P&L: direct entry update first, PnLTracker fallback --
        if not _update_pnl_pick_result(d, team, market, won, _profit_units(int(odds), 1.0, won)):
            try:
                pnl_tracker.record_pick(
                    game_id=game_id, team=team, opponent=opponent,
                    odds=odds, model_prob=model_prob, bet_size=flat_stake,
                )
            except ValueError:
                pass
            try:
                pnl_tracker.record_result(game_id, team, won)
            except ValueError:
                pass

        score_str = (
            f"{result['away_team']} {result['away_score']}, "
            f"{result['home_team']} {result['home_score']}"
        )
        tag = "WIN " if won else "LOSS"

        if verbose:
            print(f"  {tag:4s}  {label} — ${profit:+.0f} | {score_str}")

        graded.append({
            "team": team, "opponent": opponent, "odds": odds,
            "model_prob": model_prob, "edge": edge,
            "won": won, "profit": profit, "score": score_str,
            "status": "win" if won else "loss", "game_id": game_id,
            "bet_type": market,
        })

    # --- Spreads (run line) ---
    for sp in spread_picks:
        home_n = sp.get("home_team", "")
        away_n = sp.get("away_team", "")
        team = sp.get("team", "")
        odds = float(sp.get("best_odds", -110))
        ms = float(sp.get("market_spread", 0))
        book = sp.get("sportsbook", "")
        gid = sp.get("game_id_paper") or (make_game_id(d, team) + "_spread")

        result = None
        for r in results:
            if _normalize(r["home_team"]) == _normalize(home_n) and _normalize(r["away_team"]) == _normalize(away_n):
                result = r
                break
        if result is None or result["state"] != "Final":
            pending += 1
            graded.append({"bet_type": "spread", "team": team, "status": "pending", "game_id": gid})
            continue

        hs, aws = result["home_score"], result["away_score"]
        if hs is None or aws is None:
            pending += 1
            continue

        cov = _spread_side_won(team, home_n, away_n, hs, aws, ms)
        if cov is None:
            pending += 1
            continue

        profit = _profit(flat_stake, odds, cov)
        total_profit += profit
        total_staked += flat_stake
        if cov:
            wins += 1
        else:
            losses += 1

        if not _update_pnl_pick_result(d, team, "spread", cov, _profit_units(int(odds), 1.0, cov)):
            try:
                pnl_tracker.record_pick(
                    game_id=gid, team=team, opponent=sp.get("opponent", ""),
                    bet_type="spread", odds=odds, model_prob=float(sp.get("model_prob", 0.5)),
                    bet_size=flat_stake,
                )
                pnl_tracker.record_result(gid, team, cov, bet_type="spread")
            except ValueError:
                try:
                    pnl_tracker.record_result(gid, team, cov, bet_type="spread")
                except ValueError:
                    pass

        score_str = f"{away_n} {aws} @ {home_n} {hs}"
        tag = "WIN " if cov else "LOSS"
        if verbose:
            print(f"  {tag:4s}  SPREAD {team} ({ms:+.1f}) ({odds:+.0f} @ {book}) — ${profit:+.0f} | {score_str}")

        graded.append({
            "bet_type": "spread", "team": team, "opponent": sp.get("opponent", ""),
            "odds": odds, "won": cov, "profit": profit, "score": score_str,
            "status": "win" if cov else "loss", "game_id": gid,
            "market_spread": ms,
            "edge_runs": float(sp.get("edge_runs", 0) or 0),
        })

    # --- Totals (O/U) ---
    for tp in total_picks:
        home_n = tp.get("home_team", "")
        away_n = tp.get("away_team", "")
        direction = tp.get("direction", "OVER")
        line = float(tp.get("market_line", 0))
        odds = float(tp.get("best_odds", -110))
        book = tp.get("sportsbook", "")
        gid = tp.get("game_id_paper") or (make_game_id(d, home_n) + "_total")

        result = None
        for r in results:
            if _normalize(r["home_team"]) == _normalize(home_n) and _normalize(r["away_team"]) == _normalize(away_n):
                result = r
                break
        if result is None or result["state"] != "Final":
            pending += 1
            graded.append({"bet_type": "total", "status": "pending", "game_id": gid})
            continue

        hs, aws = result["home_score"], result["away_score"]
        if hs is None or aws is None:
            pending += 1
            continue

        out = _total_outcome(direction, line, hs, aws)
        if out is None:
            pending += 1
            continue

        if out == "push":
            profit = 0.0
            if verbose:
                print(f"  PUSH  TOTAL {direction} {line} — $0 | {home_n} vs {away_n} ({hs + aws} runs)")
            graded.append({
                "bet_type": "total", "direction": direction, "line": line,
                "profit": 0, "status": "push", "game_id": gid,
            })
            continue

        won = out == "win"
        profit = _profit(flat_stake, odds, won)
        total_profit += profit
        total_staked += flat_stake
        if won:
            wins += 1
        else:
            losses += 1

        label = f"{direction} {line}"
        if not _update_pnl_pick_result(d, label, "total", won, _profit_units(int(odds), 1.0, won)):
            try:
                pnl_tracker.record_pick(
                    game_id=gid, team=label, opponent=f"{away_n} @ {home_n}",
                    bet_type="total", odds=odds, model_prob=0.5, bet_size=flat_stake,
                )
                pnl_tracker.record_result(gid, label, won, bet_type="total")
            except ValueError:
                try:
                    pnl_tracker.record_result(gid, label, won, bet_type="total")
                except ValueError:
                    pass

        tr = hs + aws
        tag = "WIN " if won else "LOSS"
        if verbose:
            print(f"  {tag:4s}  TOTAL {direction} {line} ({odds:+.0f} @ {book}) — ${profit:+.0f} | {tr} runs")

        graded.append({
            "bet_type": "total", "direction": direction, "line": line,
            "won": won, "profit": profit, "total_runs": tr,
            "status": "win" if won else "loss", "game_id": gid,
            "edge_runs": float(tp.get("edge_runs", 0) or 0),
        })

    # --- NRFI / YRFI ---
    nrfi_picks = _load_json_list(report_dir / "nrfi.json")
    nrfi_wins = 0
    nrfi_losses = 0
    nrfi_pending = 0

    for np_ in nrfi_picks:
        home_t = np_.get("home_team", "")
        away_t = np_.get("away_team", "")
        direction = (np_.get("direction") or "NRFI").upper()

        result = None
        for r in results:
            if (
                _normalize(r["home_team"]) == _normalize(home_t)
                or _normalize(home_t) in _normalize(r["home_team"])
                or _normalize(r["home_team"]) in _normalize(home_t)
            ):
                if (
                    _normalize(r["away_team"]) == _normalize(away_t)
                    or _normalize(away_t) in _normalize(r["away_team"])
                    or _normalize(r["away_team"]) in _normalize(away_t)
                ):
                    result = r
                    break

        if result is None or result["state"] != "Final":
            nrfi_pending += 1
            continue

        h1 = result.get("first_inning_home_runs")
        a1 = result.get("first_inning_away_runs")

        if h1 is None or a1 is None:
            # linescore not available — can't grade
            nrfi_pending += 1
            continue

        runs_in_first = h1 + a1
        if direction == "NRFI":
            won = runs_in_first == 0
        else:  # YRFI
            won = runs_in_first > 0

        if won:
            nrfi_wins += 1
        else:
            nrfi_losses += 1

        label = f"{away_t} @ {home_t} {direction}"
        score_str = f"1st inning: {away_t} {a1}, {home_t} {h1}"
        tag = "WIN " if won else "LOSS"
        if verbose:
            print(f"  {tag:4s}  NRFI {label} — {score_str}")

    # Persist NRFI results to pnl so public_stats can show NRFI-specific record
    _update_pnl_nrfi(nrfi_picks, results, d)

    settled = wins + losses
    roi = (total_profit / total_staked * 100) if total_staked > 0 else 0
    nrfi_settled = nrfi_wins + nrfi_losses

    if verbose:
        print(f"\n  {'─'*50}")
        if nrfi_settled > 0:
            print(f"  NRFI:    {nrfi_wins}-{nrfi_losses} ({nrfi_wins/nrfi_settled:.1%}) today")
        if settled > 0:
            print(f"  RECORD:  {wins}-{losses} ({wins/settled:.1%} win rate)")
            print(f"  PROFIT:  ${total_profit:+,.0f} on ${total_staked:,.0f} wagered")
            print(f"  ROI:     {roi:+.1f}%")

            clv_summary = clv_tracker.get_clv_summary(sport="mlb")
            if clv_summary.get("with_closing_line", 0) > 0:
                print(f"\n  CLV:     {clv_summary['clv_mean_cents']:+.1f} cents avg")
                pct = clv_summary['clv_positive_pct']
                if isinstance(pct, float):
                    print(f"  CLV+:    {pct:.0%} of picks beat closing line")

        if pending > 0:
            print(f"\n  {pending} game(s) still pending — run again later to complete grading")

        print(f"  {'='*50}\n")

    # Per-category breakdown
    def _cat(bet_type: str) -> dict:
        items = [g for g in graded if g.get("bet_type") == bet_type and g.get("status") in ("win", "loss")]
        w = sum(1 for g in items if g.get("status") == "win")
        l = sum(1 for g in items if g.get("status") == "loss")
        profit = sum(float(g.get("profit") or 0) for g in items)
        staked = len(items) * flat_stake
        return {
            "wins": w, "losses": l,
            "win_rate": round(w / (w + l), 4) if (w + l) > 0 else None,
            "profit": round(profit, 2),
            "roi": round((profit / staked) * 100, 2) if staked > 0 else None,
        }

    def _agreement_breakdown(graded_list: list) -> dict:
        """Break down win rate by model agreement signal (AGREE vs SPLIT)."""
        result = {}
        for signal in (True, False):
            label = "agree" if signal else "split"
            items = [
                g for g in graded_list
                if g.get("model_agreement") is signal and g.get("status") in ("win", "loss")
            ]
            w = sum(1 for g in items if g.get("status") == "win")
            l = len(items) - w
            profit = sum(float(g.get("profit") or 0) for g in items)
            staked = len(items) * flat_stake
            result[label] = {
                "wins": w, "losses": l,
                "win_rate": round(w / (w + l), 4) if (w + l) > 0 else None,
                "profit": round(profit, 2),
                "roi": round((profit / staked) * 100, 2) if staked > 0 else None,
            }
        return result

    def _clv_summary(graded_list: list) -> dict:
        """Summarize CLV (closing line value) across graded picks."""
        clv_picks = [g for g in graded_list if g.get("clv_pct") is not None]
        if not clv_picks:
            return {"picks_with_clv": 0}
        avg_clv = sum(float(g["clv_pct"]) for g in clv_picks) / len(clv_picks)
        beating_close = sum(1 for g in clv_picks if float(g.get("clv_pct", 0)) > 0)
        return {
            "picks_with_clv": len(clv_picks),
            "avg_clv_pct": round(avg_clv * 100, 2),
            "beating_close": beating_close,
            "pct_beating_close": round(beating_close / len(clv_picks), 4) if clv_picks else None,
        }

    # Persist grading report
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "date": d.isoformat(),
        "total_picks": n_all,
        "moneyline_picks": len(picks),
        "spread_picks": len(spread_picks),
        "total_picks_ou": len(total_picks),
        "graded": settled,
        "pending": pending,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / settled if settled > 0 else None,
        "total_staked": total_staked,
        "total_profit": total_profit,
        "roi": roi,
        "nrfi_picks": len(nrfi_picks),
        "nrfi_wins": nrfi_wins,
        "nrfi_losses": nrfi_losses,
        "nrfi_pending": nrfi_pending,
        "nrfi_win_rate": nrfi_wins / nrfi_settled if nrfi_settled > 0 else None,
        "by_type": {
            "moneyline": _cat("moneyline"),
            "spread":    _cat("spread"),
            "total":     _cat("total"),
        },
        "by_agreement": _agreement_breakdown(graded),
        "clv_summary":  _clv_summary(graded),
        "details": graded,
        "graded_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(report_dir / "grades.json", "w") as f:
        json.dump(report, f, indent=2)

    return report


def grade_date_range(
    start: date,
    end: date | None = None,
    sport: str = "baseball_mlb",
    flat_stake: float = 100.0,
) -> dict:
    """Grade all picks across a date range and print a cumulative summary."""
    end = end or date.today()

    all_wins = 0
    all_losses = 0
    all_profit = 0.0
    all_staked = 0.0
    days_graded = 0

    current = start
    while current <= end:
        picks = load_picks(sport, current)
        if picks:
            report = grade_picks(current, sport, flat_stake, verbose=False)
            all_wins += report.get("wins", 0)
            all_losses += report.get("losses", 0)
            all_profit += report.get("total_profit", 0)
            all_staked += report.get("total_staked", 0)
            if report.get("graded", 0) > 0:
                days_graded += 1
        current += timedelta(days=1)

    settled = all_wins + all_losses
    roi = (all_profit / all_staked * 100) if all_staked > 0 else 0

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days_graded": days_graded,
        "total_picks": settled,
        "wins": all_wins,
        "losses": all_losses,
        "win_rate": all_wins / settled if settled > 0 else None,
        "total_staked": all_staked,
        "total_profit": all_profit,
        "roi": roi,
    }


def poll_and_grade(
    pick_date: date | None = None,
    sport: str = "baseball_mlb",
    interval_min: int = 30,
    max_hours: float = 8.0,
    flat_stake: float = 100.0,
) -> dict:
    """
    Poll MLB API at intervals and grade games as they finish.
    Designed to run in the background during game hours.
    """
    d = pick_date or date.today()
    picks = load_picks(sport, d)
    if not picks:
        print(f"No picks for {d.isoformat()}")
        return {}

    start_time = time.time()
    max_seconds = max_hours * 3600
    last_graded = 0

    print(f"Polling every {interval_min}min for up to {max_hours}h...")
    print(f"Tracking {len(picks)} picks for {d.isoformat()}\n")

    while True:
        report = grade_picks(d, sport, flat_stake, verbose=True)
        graded_now = report.get("graded", 0)

        if graded_now > last_graded:
            last_graded = graded_now

        if report.get("pending", 0) == 0 and graded_now > 0:
            print("\nAll games graded. Final report above.")
            return report

        elapsed = time.time() - start_time
        if elapsed > max_seconds:
            print(f"\nMax polling time ({max_hours}h) reached. {report.get('pending', 0)} games ungraded.")
            return report

        remaining = report.get("pending", 0)
        print(f"  Waiting {interval_min}min... ({remaining} games remaining, {elapsed/60:.0f}min elapsed)")
        time.sleep(interval_min * 60)


def capture_closing_lines(
    pick_date: date | None = None,
    sport: str = "baseball_mlb",
    verbose: bool = True,
) -> int:
    """
    Fetch current odds and record as closing lines for today's CLV picks.

    Best run ~30 min before first pitch for most accurate closing lines.
    Returns number of closing lines recorded.
    """
    d = pick_date or date.today()
    picks = load_picks(sport, d)
    if not picks:
        if verbose:
            print(f"  No picks for {d.isoformat()}")
        return 0

    closing_odds = fetch_closing_odds(sport)
    if not closing_odds:
        if verbose:
            print("  Could not fetch closing odds (check ODDS_API_KEY)")
        return 0

    clv_tracker = CLVTracker()
    recorded = 0

    for pick in picks:
        team = pick.get("Team", "")
        game_id = make_game_id(d, team)
        tn = _normalize(team)

        if tn not in closing_odds:
            if verbose:
                print(f"  No closing odds for {team}")
            continue

        cl = closing_odds[tn]
        result = clv_tracker.record_closing_line(game_id, team, cl["odds"])
        if result:
            recorded += 1
            if verbose:
                print(f"  {team}: closing line {_fmt_american(cl['odds'])} ({cl['sportsbook']})")

    if verbose:
        print(f"\n  Recorded {recorded}/{len(picks)} closing lines")

    return recorded


def grade_slate(
    pick_date: date | None = None,
    sport: str = "baseball_mlb",
    verbose: bool = True,
) -> dict:
    """
    Grade every line on the full slate card — ML pick, run line pick, and
    over/under pick for every game shown on the card, not just edge picks.

    Reads from output/picks/{sport}/{date}/slate.json (written by morning.py).
    Writes results to output/picks/{sport}/{date}/slate_grades.json.

    Returns an accuracy summary broken down by market and by whether the
    game had a model edge flagged.
    """
    d = pick_date or date.today()
    date_str = d.strftime("%Y%m%d")
    slate_path = PICKS_DIR / sport / date_str / "slate.json"

    if not slate_path.exists():
        if verbose:
            print(f"  No slate.json found for {d.isoformat()} — run morning.py first.")
        return {}

    with open(slate_path) as f:
        slate = json.load(f)

    games = slate.get("games", [])
    if not games:
        if verbose:
            print("  slate.json is empty.")
        return {}

    results = fetch_final_scores(d)
    final_games = [r for r in results if r["state"] == "Final"]

    if verbose:
        print(f"\n{'='*70}")
        print(f"  FULL SLATE ACCURACY — {d.strftime('%A, %B %d, %Y')}")
        print(f"{'='*70}")
        print(f"  {len(games)} games on slate | {len(final_games)} final\n")

    graded = []
    ml_w = ml_l = rl_w = rl_l = ou_w = ou_l = pending = 0
    edge_ml_w = edge_ml_l = 0

    for game in games:
        away = game.get("away", "")
        home = game.get("home", "")
        ml_pick  = game.get("ml_pick", "")
        ml_odds  = int(game.get("ml_odds", 0) or 0)
        rl_pick  = game.get("rl_pick", "")
        rl_spread = float(game.get("rl_spread", -1.5) or -1.5)
        rl_odds  = int(game.get("rl_odds", -110) or -110)
        ou_pick  = game.get("ou_pick", "UNDER")
        total    = float(game.get("total", 8.0) or 8.0)
        ou_odds  = int(game.get("ou_odds", -110) or -110)
        edge     = float(game.get("model_edge", 0) or 0)
        is_edge  = edge >= 0.07

        # find matching result
        result = None
        for r in final_games:
            hn = _normalize(r["home_team"])
            an = _normalize(r["away_team"])
            if _normalize(home) in hn or hn in _normalize(home):
                if _normalize(away) in an or an in _normalize(away):
                    result = r
                    break
        if result is None:
            # looser match on home team alone
            for r in final_games:
                if _normalize(home) in _normalize(r["home_team"]) or \
                   _normalize(r["home_team"]) in _normalize(home):
                    result = r
                    break

        if result is None or result.get("home_score") is None:
            pending += 1
            graded.append({"away": away, "home": home, "status": "pending"})
            if verbose:
                print(f"  PEND  {away} @ {home}")
            continue

        hs = result["home_score"]
        aws = result["away_score"]
        score_str = f"{aws}-{hs}"
        game_total = hs + aws

        # ML
        ml_team_is_home = _normalize(ml_pick) in _normalize(home) or _normalize(home) in _normalize(ml_pick)
        ml_won = (hs > aws) if ml_team_is_home else (aws > hs)

        # RL — rl_spread stored as home team's spread (e.g. -1.5 means home favored)
        # Need to figure out which side rl_pick is and what spread applies
        rl_team_is_home = _normalize(rl_pick) in _normalize(home) or _normalize(home) in _normalize(rl_pick)
        if rl_team_is_home:
            # rl_spread is home team's spread — pass directly
            rl_won = _spread_side_won(home, home, away, hs, aws, rl_spread)
        else:
            # rl_spread is away team's spread; _spread_side_won expects home team's spread
            rl_won = _spread_side_won(away, home, away, hs, aws, -rl_spread)

        # O/U
        ou_result = _total_outcome(ou_pick, total, hs, aws)
        ou_won = ou_result == "win" if ou_result else None

        # tally
        if ml_won:
            ml_w += 1
            if is_edge: edge_ml_w += 1
        else:
            ml_l += 1
            if is_edge: edge_ml_l += 1

        if rl_won is True:   rl_w += 1
        elif rl_won is False: rl_l += 1

        if ou_won is True:   ou_w += 1
        elif ou_won is False: ou_l += 1

        edge_tag = " ⚡EDGE" if is_edge else ""
        ml_tag  = "WIN " if ml_won else "LOSS"
        rl_tag  = "WIN " if rl_won else ("LOSS" if rl_won is False else "----")
        ou_tag  = "WIN " if ou_won else ("LOSS" if ou_won is False else "PUSH")

        if verbose:
            print(
                f"  {away[:12]:12s} @ {home[:12]:12s}  {score_str:5s}{edge_tag}\n"
                f"    ML  {ml_tag}  {ml_pick[:14]:14s} {ml_odds:+5d}\n"
                f"    RL  {rl_tag}  {rl_pick[:14]:14s} {rl_spread:+.1f} ({rl_odds:+d})\n"
                f"    O/U {ou_tag}  {ou_pick} {total}         ({ou_odds:+d})\n"
            )

        graded.append({
            "away": away, "home": home, "score": score_str,
            "ml_pick": ml_pick, "ml_odds": ml_odds, "ml_won": ml_won,
            "rl_pick": rl_pick, "rl_spread": rl_spread, "rl_odds": rl_odds, "rl_won": rl_won,
            "ou_pick": ou_pick, "total": total, "ou_odds": ou_odds, "ou_won": ou_won,
            "model_edge": edge, "status": "graded",
        })

    ml_settled  = ml_w + ml_l
    rl_settled  = rl_w + rl_l
    ou_settled  = ou_w + ou_l
    edge_settled = edge_ml_w + edge_ml_l

    if verbose and ml_settled > 0:
        print(f"  {'─'*50}")
        print(f"  ML PICKS:   {ml_w}-{ml_l}  ({ml_w/ml_settled:.0%})")
        if edge_settled:
            print(f"  EDGE PICKS: {edge_ml_w}-{edge_ml_l}  ({edge_ml_w/edge_settled:.0%})  ← model edges only")
        if rl_settled:
            print(f"  RUN LINE:   {rl_w}-{rl_l}  ({rl_w/rl_settled:.0%})")
        if ou_settled:
            print(f"  O/U:        {ou_w}-{ou_l}  ({ou_w/ou_settled:.0%})")
        all_w = ml_w + rl_w + ou_w
        all_l = ml_l + rl_l + ou_l
        all_s = all_w + all_l
        if all_s:
            print(f"  OVERALL:    {all_w}-{all_l}  ({all_w/all_s:.0%})  across all lines")
        if pending:
            print(f"  {pending} game(s) still pending")
        print(f"  {'='*50}\n")

    report = {
        "date": d.isoformat(),
        "sport": sport,
        "games_on_slate": len(games),
        "games_graded": len([g for g in graded if g.get("status") == "graded"]),
        "games_pending": pending,
        "ml":  {"wins": ml_w,  "losses": ml_l,  "pct": ml_w/ml_settled  if ml_settled  else None},
        "rl":  {"wins": rl_w,  "losses": rl_l,  "pct": rl_w/rl_settled  if rl_settled  else None},
        "ou":  {"wins": ou_w,  "losses": ou_l,  "pct": ou_w/ou_settled  if ou_settled  else None},
        "edge_ml": {"wins": edge_ml_w, "losses": edge_ml_l,
                    "pct": edge_ml_w/edge_settled if edge_settled else None},
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "games": graded,
    }

    out_path = PICKS_DIR / sport / date_str / "slate_grades.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    return report
