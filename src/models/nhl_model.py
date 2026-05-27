"""
NHL Game Prediction Model — puck lines, totals, moneylines.

Approach:
  1. Project expected goals for each team using GF/game + GA/game (both teams)
  2. Adjust for home ice (+0.15 goals), PP/PK differential, goalie SV%
  3. Model goal differential with normal distribution (sigma ~1.8 for NHL)
  4. Compare projected probabilities to Pinnacle de-vigged market
  5. Return edges where model beats market by >= MIN_EDGE_PCT

Why Poisson/normal for NHL: Goals are well-modeled by independent Poisson processes.
The goal differential is approximately normal with sigma ~1.8 goals (empirical).
"""
from __future__ import annotations

import math
import pickle
from pathlib import Path
from typing import Optional

from src.data.nhl_stats import (
    LG_AVG_GF_PER_GAME,
    LG_AVG_GA_PER_GAME,
    LG_AVG_SV_PCT,
    HOME_GOALS_ADJ,
    fetch_team_stats,
    fetch_goalie_stats,
    get_team_stats,
    get_team_goalie,
)


_TRAINED_MODEL_PATH = Path("models/nhl_logreg.pkl")
_TRAINED_PAYLOAD: dict | None = None


def _load_trained_model() -> dict | None:
    """Lazy-load the trained NHL logreg model. Returns None if not present."""
    global _TRAINED_PAYLOAD
    if _TRAINED_PAYLOAD is not None:
        return _TRAINED_PAYLOAD
    if not _TRAINED_MODEL_PATH.exists():
        return None
    try:
        with open(_TRAINED_MODEL_PATH, "rb") as f:
            _TRAINED_PAYLOAD = pickle.load(f)
        return _TRAINED_PAYLOAD
    except Exception:
        return None


def _trained_features(home_stats: dict, away_stats: dict,
                      home_sv: float, away_sv: float) -> list[float]:
    """Build the feature vector matching train_nhl.py FEATURE_NAMES."""
    h_gf = home_stats.get("goalsForPerGame", LG_AVG_GF_PER_GAME)
    h_ga = home_stats.get("goalsAgainstPerGame", LG_AVG_GA_PER_GAME)
    a_gf = away_stats.get("goalsForPerGame", LG_AVG_GF_PER_GAME)
    a_ga = away_stats.get("goalsAgainstPerGame", LG_AVG_GA_PER_GAME)
    h_pp = home_stats.get("powerPlayPct", 0.200)
    h_pk = home_stats.get("penaltyKillPct", 0.800)
    a_pp = away_stats.get("powerPlayPct", 0.200)
    a_pk = away_stats.get("penaltyKillPct", 0.800)
    h_sf = home_stats.get("shotsForPerGame", 30.0)
    h_sa = home_stats.get("shotsAgainstPerGame", 30.0)
    a_sf = away_stats.get("shotsForPerGame", 30.0)
    a_sa = away_stats.get("shotsAgainstPerGame", 30.0)
    h_pt = home_stats.get("pointPct", 0.5)
    a_pt = away_stats.get("pointPct", 0.5)
    return [
        h_gf - a_ga, a_gf - h_ga, h_pt - a_pt, home_sv - away_sv,
        h_pp - a_pk, a_pp - h_pk, h_sf - a_sa, a_sf - h_sa, 1.0,
    ]

MIN_EDGE_PCT = 5.0     # lowered from 8% — goalie bug fix makes model more trustworthy
GOAL_SIGMA = 1.80      # std dev of goal differential (empirical NHL)
PUCK_LINE = 1.5        # standard NHL puck line
OVER_BIAS_CORRECTION = 0.04   # subtract from OVER prob: books shade totals high to attract squares
MIN_IMPLIED_PROB = 0.30       # no picks at odds better than +233 — model unreliable at extreme odds

# Canonical team name → 3-letter NHL Stats API abbreviation
_NHL_ABBREV: dict[str, str] = {
    "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF",
    "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL",
    "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM", "Florida Panthers": "FLA",
    "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN", "Montreal Canadiens": "MTL",
    "Nashville Predators": "NSH", "New Jersey Devils": "NJD", "New York Islanders": "NYI",
    "New York Rangers": "NYR", "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI",
    "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJS", "Seattle Kraken": "SEA",
    "St. Louis Blues": "STL", "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR",
    "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK", "Washington Capitals": "WSH",
    "Winnipeg Jets": "WPG", "Utah Hockey Club": "UTA",
}

def _team_to_abbrev(team_name: str) -> str:
    """Convert full team name to NHL 3-letter abbreviation for goalie lookup."""
    if team_name in _NHL_ABBREV:
        return _NHL_ABBREV[team_name]
    # Fuzzy: match on last word (team nickname)
    nickname = team_name.split()[-1]
    for full, abbrev in _NHL_ABBREV.items():
        if full.endswith(nickname):
            return abbrev
    # Last resort: first 3 chars of city (original broken behavior, logged)
    return team_name.split()[0][:3].upper()


def _devig(odds_a: float, odds_b: float) -> tuple[float, float]:
    def imp(o: float) -> float:
        return 100 / (o + 100) if o >= 0 else abs(o) / (abs(o) + 100)
    pa, pb = imp(odds_a), imp(odds_b)
    t = pa + pb
    return pa / t, pb / t


def _prob_to_american(p: float) -> int:
    if p <= 0 or p >= 1:
        return 0
    if p >= 0.5:
        return -int(round(p / (1 - p) * 100))
    return int(round((1 - p) / p * 100))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _poisson_prob(lam: float, k: int) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def project_game(
    away_team: str,
    home_team: str,
    all_teams: list[dict] | None = None,
    all_goalies: list[dict] | None = None,
    home_abbrev: str = "",
    away_abbrev: str = "",
) -> dict:
    """
    Project expected goals, goal differential, and win probability.

    Returns:
        home_exp_goals    - expected goals for home team
        away_exp_goals    - expected goals for away team
        total_exp_goals   - combined expected goals
        home_win_prob     - P(home wins in regulation)
        away_win_prob     - P(away wins in regulation)
        home_cover_1_5    - P(home covers -1.5 puck line)
        away_cover_1_5    - P(away covers +1.5 puck line)
        goalie_adj        - goals adjusted by starting goalie quality
        notes             - list of reasoning strings
    """
    if all_teams is None:
        # Prefer playoff stats if available
        all_teams = fetch_team_stats(game_type=3)
        if not all_teams:
            all_teams = fetch_team_stats(game_type=2)

    if all_goalies is None:
        all_goalies = fetch_goalie_stats(game_type=3)

    home_stats = get_team_stats(home_team, all_teams)
    away_stats = get_team_stats(away_team, all_teams)

    notes = []

    # ── Base expected goals ──────────────────────────────────────────────────
    # Blend team's offense vs opponent's defense, normalized by league average
    home_offense = home_stats.get("goalsForPerGame", LG_AVG_GF_PER_GAME)
    home_defense = home_stats.get("goalsAgainstPerGame", LG_AVG_GA_PER_GAME)
    away_offense = away_stats.get("goalsForPerGame", LG_AVG_GF_PER_GAME)
    away_defense = away_stats.get("goalsAgainstPerGame", LG_AVG_GA_PER_GAME)

    # Log5-style blending normalized to league average
    lg = LG_AVG_GF_PER_GAME
    home_exp = (home_offense / lg) * (away_defense / lg) * lg
    away_exp = (away_offense / lg) * (home_defense / lg) * lg

    # Home ice advantage
    home_exp += HOME_GOALS_ADJ
    away_exp -= HOME_GOALS_ADJ * 0.5   # home advantage suppresses visitor slightly

    notes.append(
        f"Base: {home_team} {home_exp:.2f} exp goals | {away_team} {away_exp:.2f} exp goals"
    )

    # ── Power play / penalty kill differential ────────────────────────────────
    home_pp = home_stats.get("powerPlayPct", 0.200)
    home_pk = home_stats.get("penaltyKillPct", 0.800)
    away_pp = away_stats.get("powerPlayPct", 0.200)
    away_pk = away_stats.get("penaltyKillPct", 0.800)

    # PP advantage: relative to league average (0.200 PP, 0.800 PK)
    # Each 1% PP advantage over a ~3-PP-opportunity game ≈ 0.03 goals
    home_pp_adj = (home_pp - 0.200) * 3.0 * 0.5 - (away_pk - 0.800) * 3.0 * 0.5
    away_pp_adj = (away_pp - 0.200) * 3.0 * 0.5 - (home_pk - 0.800) * 3.0 * 0.5
    home_exp = max(1.0, home_exp + home_pp_adj)
    away_exp = max(1.0, away_exp + away_pp_adj)

    # ── Goalie adjustment ────────────────────────────────────────────────────
    goalie_adj = 0.0
    home_goalie = get_team_goalie(home_abbrev, all_goalies) if home_abbrev else None
    away_goalie = get_team_goalie(away_abbrev, all_goalies) if away_abbrev else None

    # Home goalie faces away team shots → reduces away_exp
    if home_goalie:
        goalie_sv = home_goalie.get("savePct", LG_AVG_SV_PCT)
        sv_delta = goalie_sv - LG_AVG_SV_PCT
        # Each 0.01 SV% above avg ≈ 0.3 fewer goals allowed; cap at ±0.5
        adj = max(-0.5, min(0.5, sv_delta * 30.0))
        away_exp = max(1.0, away_exp - adj)
        goalie_adj -= adj
        notes.append(
            f"Home goalie SV%: {goalie_sv:.3f} ({sv_delta:+.3f}) → away -{adj:+.2f}g"
        )

    # Away goalie faces home team shots → reduces home_exp
    if away_goalie:
        goalie_sv = away_goalie.get("savePct", LG_AVG_SV_PCT)
        sv_delta = goalie_sv - LG_AVG_SV_PCT
        adj = max(-0.5, min(0.5, sv_delta * 30.0))
        home_exp = max(1.0, home_exp - adj)
        goalie_adj += adj
        notes.append(
            f"Away goalie SV%: {goalie_sv:.3f} ({sv_delta:+.3f}) → home -{adj:+.2f}g"
        )

    total_exp = home_exp + away_exp

    # ── Win probability (normal approximation of goal differential) ──────────
    diff_mean = home_exp - away_exp     # positive = home favored
    p_home_regulation = _normal_cdf(diff_mean / GOAL_SIGMA)

    # NHL has OT/SO — roughly 25% of games go to OT, 50/50 there
    # P(home wins) = P(home wins regulation) + P(OT) * 0.5
    p_ot = _normal_cdf(0.5 / GOAL_SIGMA) - _normal_cdf(-0.5 / GOAL_SIGMA)
    p_home_wins = (p_home_regulation - p_ot * 0.5) + p_ot * 0.5
    p_away_wins = 1 - p_home_wins

    # ── Puck line coverage probability ───────────────────────────────────────
    # P(home - away > 1.5) = P(diff > 1.5) = 1 - CDF(1.5)
    p_home_cover = 1 - _normal_cdf((PUCK_LINE - diff_mean) / GOAL_SIGMA)
    p_away_cover = _normal_cdf((PUCK_LINE - diff_mean) / GOAL_SIGMA)  # away +1.5 = 1 - p_home_cover

    # ── Trained model override (if available) ────────────────────────────────
    # If models/nhl_logreg.pkl exists, use its calibrated prediction for win
    # probability. Falls back to heuristic if model not trained yet.
    payload = _load_trained_model()
    if payload is not None:
        try:
            home_sv = (home_goalie or {}).get("savePct", LG_AVG_SV_PCT) if home_goalie else LG_AVG_SV_PCT
            away_sv = (away_goalie or {}).get("savePct", LG_AVG_SV_PCT) if away_goalie else LG_AVG_SV_PCT
            feats = _trained_features(home_stats, away_stats, home_sv, away_sv)
            import numpy as _np
            X = _np.array(feats).reshape(1, -1)
            p_home_trained = float(payload["model"].predict_proba(X)[0, 1])
            # Trained model is the authoritative win prob
            p_home_wins = p_home_trained
            p_away_wins = 1 - p_home_wins
            notes.append(f"Trained model win prob: {p_home_wins:.1%}")
        except Exception as exc:
            notes.append(f"Trained model failed ({exc}) — falling back to heuristic")

    notes.append(
        f"Projected total: {total_exp:.1f} | Home win: {p_home_wins:.1%} | "
        f"Home -1.5: {p_home_cover:.1%}"
    )

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_exp_goals": round(home_exp, 2),
        "away_exp_goals": round(away_exp, 2),
        "total_exp_goals": round(total_exp, 2),
        "home_win_prob": round(p_home_wins, 4),
        "away_win_prob": round(p_away_wins, 4),
        "home_cover_1_5": round(p_home_cover, 4),
        "away_cover_1_5": round(p_away_cover, 4),
        "goalie_adj": round(goalie_adj, 3),
        "notes": notes,
    }


def find_nhl_edges(
    odds_data: list[dict],
    game_date: str = "",
    min_edge_pct: float = MIN_EDGE_PCT,
) -> list[dict]:
    """
    Find NHL betting edges vs market implied probability.

    odds_data: list of game dicts from The Odds API (icehockey_nhl)
    Returns list of edge dicts sorted by edge_pct descending.
    """
    all_teams = fetch_team_stats(game_type=3)
    if not all_teams:
        all_teams = fetch_team_stats(game_type=2)
    all_goalies = fetch_goalie_stats(game_type=3)

    edges: list[dict] = []

    for game in odds_data:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        commence = game.get("commence_time", "")
        matchup = f"{away} @ {home}"

        # Find game abbreviations for goalie lookup (best-effort from schedule cache)
        # We use first 3 chars of city as fallback
        home_abbrev = _team_to_abbrev(home)
        away_abbrev = _team_to_abbrev(away)

        proj = project_game(
            away_team=away,
            home_team=home,
            all_teams=all_teams,
            all_goalies=all_goalies,
            home_abbrev=home_abbrev,
            away_abbrev=away_abbrev,
        )

        # ── Find Pinnacle lines for de-vig baseline ──────────────────────────
        pin_h2h: tuple[float, float] | None = None           # (home_fair, away_fair)
        pin_puck: dict[str, float] = {}                       # name -> fair prob
        pin_totals: dict[float, dict] = {}                    # line -> {over, under}

        for book in game.get("bookmakers", []):
            if book.get("key") != "pinnacle":
                continue
            for mkt in book.get("markets", []):
                key = mkt.get("key")
                outcomes = mkt.get("outcomes", [])
                if len(outcomes) < 2:
                    continue

                if key == "h2h":
                    o_home = next((o for o in outcomes if o["name"] == home), None)
                    o_away = next((o for o in outcomes if o["name"] == away), None)
                    if o_home and o_away:
                        ph, pa = _devig(o_home["price"], o_away["price"])
                        pin_h2h = (ph, pa)

                elif key == "spreads":
                    for o in outcomes:
                        name = o["name"]
                        pt = o.get("point", 0)
                        pair = next(
                            (x for x in outcomes if x["name"] != name), None
                        )
                        if pair:
                            p1, _ = _devig(o["price"], pair["price"])
                            pin_puck[f"{name}_{pt}"] = p1

                elif key == "totals":
                    over  = next((o for o in outcomes if o["name"] == "Over"),  None)
                    under = next((o for o in outcomes if o["name"] == "Under"), None)
                    if over and under:
                        pt = over.get("point", 5.5)
                        po, pu = _devig(over["price"], under["price"])
                        pin_totals[float(pt)] = {"Over": po, "Under": pu}

        # Fall back to best-price market consensus if no Pinnacle
        has_pinnacle = pin_h2h is not None or pin_puck or pin_totals

        def _best_odds(market_key: str, side_name: str, point: float | None = None) -> tuple[float, float] | None:
            """Find best market odds and implied prob for a side. Returns (odds, implied_prob)."""
            best_odds = None
            for book in game.get("bookmakers", []):
                if book.get("key") == "pinnacle":
                    continue
                for mkt in book.get("markets", []):
                    if mkt.get("key") != market_key:
                        continue
                    for o in mkt.get("outcomes", []):
                        if o["name"] != side_name:
                            continue
                        if point is not None and abs(float(o.get("point", 0)) - point) > 0.01:
                            continue
                        odds = float(o["price"])
                        if best_odds is None or odds > best_odds:
                            best_odds = odds
            if best_odds is None:
                return None
            imp = 100 / (best_odds + 100) if best_odds >= 0 else abs(best_odds) / (abs(best_odds) + 100)
            return best_odds, imp

        def _emit(
            market: str,
            team: str,
            direction: str,
            model_prob: float,
            market_prob: float,
            odds: float,
            fair_prob: float,
            line: float | None = None,
        ) -> None:
            edge = model_prob - market_prob
            if edge < min_edge_pct / 100:
                return
            edges.append({
                "sport":        "nhl",
                "matchup":      matchup,
                "team":         team,
                "market":       market,
                "direction":    direction,
                "line":         line,
                "odds":         int(odds),
                "fair_odds":    _prob_to_american(fair_prob) if fair_prob else None,
                "model_prob":   round(model_prob, 4),
                "market_prob":  round(market_prob, 4),
                "fair_prob":    round(fair_prob, 4) if fair_prob else None,
                "edge_pct":     round(edge * 100, 2),
                "commence":     commence,
                "proj_total":   proj["total_exp_goals"],
                "notes":        proj["notes"],
            })

        # ── Moneyline edges ──────────────────────────────────────────────────
        for team, model_prob, direction in [
            (home, proj["home_win_prob"], "HOME"),
            (away, proj["away_win_prob"], "AWAY"),
        ]:
            fair_prob = pin_h2h[0] if direction == "HOME" and pin_h2h else (
                pin_h2h[1] if pin_h2h else None
            )
            market_prob = fair_prob  # if Pinnacle, use their fair price as market
            best = _best_odds("h2h", team)
            if best is None:
                continue
            best_odds, book_prob = best
            # Use Pinnacle fair as market baseline; if no Pinnacle, use book implied
            effective_market = fair_prob if fair_prob is not None else book_prob
            edge = model_prob - effective_market
            if edge >= min_edge_pct / 100:
                _emit(
                    "moneyline", team, direction,
                    model_prob, effective_market, best_odds,
                    fair_prob or book_prob,
                )

        # ── Puck line edges ──────────────────────────────────────────────────
        for team, model_prob, pt, direction in [
            (home, proj["home_cover_1_5"], -PUCK_LINE, "HOME -1.5"),
            (away, proj["away_cover_1_5"],  PUCK_LINE, "AWAY +1.5"),
        ]:
            pin_key = f"{team}_{pt}"
            fair_prob = pin_puck.get(pin_key)
            best = _best_odds("spreads", team, pt)
            if best is None:
                continue
            best_odds, book_prob = best
            effective_market = fair_prob if fair_prob is not None else book_prob
            edge = model_prob - effective_market
            if edge >= min_edge_pct / 100:
                _emit(
                    "puck_line", f"{team} {'+' if pt > 0 else ''}{pt}", direction,
                    model_prob, effective_market, best_odds,
                    fair_prob or book_prob,
                    line=pt,
                )

        # ── Totals edges ─────────────────────────────────────────────────────
        for pt, fair_sides in pin_totals.items():
            for side in ("Over", "Under"):
                fair_prob = fair_sides.get(side)
                best = _best_odds("totals", side, pt)
                if best is None:
                    continue
                best_odds, book_prob = best

                # Model probability: use normal CDF around projected total
                mean = proj["total_exp_goals"]
                sigma = GOAL_SIGMA * math.sqrt(2)   # sum of two Poisson variances
                if side == "Over":
                    model_prob = max(0.01, (1 - _normal_cdf((pt - mean) / sigma)) - OVER_BIAS_CORRECTION)
                else:
                    model_prob = _normal_cdf((pt - mean) / sigma)

                effective_market = fair_prob if fair_prob is not None else book_prob
                if effective_market < MIN_IMPLIED_PROB:
                    continue
                edge = model_prob - effective_market
                if edge >= min_edge_pct / 100:
                    _emit(
                        "total", f"{side} {pt}", side.upper(),
                        model_prob, effective_market, best_odds,
                        fair_prob or book_prob,
                        line=pt,
                    )

        # ── If no Pinnacle totals, use our projection standalone ─────────────
        if not pin_totals:
            mean = proj["total_exp_goals"]
            sigma = GOAL_SIGMA * math.sqrt(2)
            for side in ("Over", "Under"):
                # Find common lines offered by any book
                lines_offered: set[float] = set()
                for book in game.get("bookmakers", []):
                    for mkt in book.get("markets", []):
                        if mkt.get("key") != "totals":
                            continue
                        for o in mkt.get("outcomes", []):
                            if o["name"] == side:
                                lines_offered.add(float(o.get("point", 5.5)))
                for pt in lines_offered:
                    if side == "Over":
                        model_prob = max(0.01, (1 - _normal_cdf((pt - mean) / sigma)) - OVER_BIAS_CORRECTION)
                    else:
                        model_prob = _normal_cdf((pt - mean) / sigma)
                    best = _best_odds("totals", side, pt)
                    if best is None:
                        continue
                    best_odds, book_prob = best
                    if book_prob < MIN_IMPLIED_PROB:
                        continue
                    edge = model_prob - book_prob
                    if edge >= min_edge_pct / 100:
                        _emit(
                            "total", f"{side} {pt}", side.upper(),
                            model_prob, book_prob, best_odds, book_prob,
                            line=pt,
                        )

    edges.sort(key=lambda x: x["edge_pct"], reverse=True)
    return edges
