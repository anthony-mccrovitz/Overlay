"""
NBA Game Prediction Model — spreads, totals, moneylines.

Approach:
  1. Fetch team efficiency ratings (ORtg, DRtg, Pace) from NBA Stats API
  2. Project game total using Four Factors adjusted pace formula
  3. Project spread using net rating differential + home court + rest
  4. De-vig market odds to get implied probability
  5. Return picks where model edge >= threshold

No ML training needed — uses pure efficiency-stat regression which has
documented predictive validity in the literature (Kubatko et al. 2007).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from src.data.nba_stats import (
    LG_AVG_DRTG,
    LG_AVG_ORTG,
    LG_AVG_PACE,
    HOME_COURT,
    fetch_team_ratings,
    get_team_ratings,
)

# Minimum edge to surface as a pick
MIN_EDGE_PCT = 4.0

# Points per possession constants
POSSESSIONS_PER_PACE = 100.0   # ORtg/DRtg are per-100-possessions


def _devig_two_way(odds_a: float, odds_b: float) -> tuple[float, float]:
    """De-vig American odds pair. Returns (prob_a, prob_b)."""
    def imp(o: float) -> float:
        return 100 / (o + 100) if o >= 0 else abs(o) / (abs(o) + 100)
    pa, pb = imp(odds_a), imp(odds_b)
    total = pa + pb
    return pa / total, pb / total


def _american_to_decimal(o: float) -> float:
    return o / 100 + 1 if o >= 0 else 100 / abs(o) + 1


def _prob_to_american(p: float) -> int:
    if p <= 0 or p >= 1:
        return 0
    if p >= 0.5:
        return -int(round(p / (1 - p) * 100))
    return int(round((1 - p) / p * 100))


def _normal_cdf(x: float) -> float:
    """Cumulative normal distribution."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def project_game(
    away_team: str,
    home_team: str,
    all_teams: list[dict] | None = None,
    away_rest_days: int = 2,
    home_rest_days: int = 2,
) -> dict:
    """
    Project a game: spread, total, win probability.

    Returns dict with:
        projected_total     - expected combined score
        projected_spread    - home team spread (negative = home favored)
        home_win_prob       - probability home team wins
        away_win_prob       - probability away team wins
        pace_factor         - estimated pace of game
        notes               - human-readable model reasoning
    """
    if all_teams is None:
        all_teams = fetch_team_ratings()

    away = get_team_ratings(away_team, all_teams)
    home = get_team_ratings(home_team, all_teams)

    away_ortg = float(away.get("OFF_RATING") or LG_AVG_ORTG)
    away_drtg = float(away.get("DEF_RATING") or LG_AVG_DRTG)
    home_ortg = float(home.get("OFF_RATING") or LG_AVG_ORTG)
    home_drtg = float(home.get("DEF_RATING") or LG_AVG_DRTG)
    away_pace = float(away.get("PACE") or LG_AVG_PACE)
    home_pace = float(home.get("PACE") or LG_AVG_PACE)

    # Game pace = average of both teams' paces (they share possessions)
    game_pace = (away_pace + home_pace) / 2.0

    # Net-rating spread model (replaces multiplicative formula which over-amplified edges)
    # Historical NBA: 1 pt net rating differential ≈ 0.45 pts on the spread
    # (not 1:1 — regression to mean from unequal schedule strength)
    SPREAD_SCALE = 0.45
    home_net = home_ortg - home_drtg
    away_net = away_ortg - away_drtg
    net_diff = home_net - away_net  # positive = home team is better

    # Projected spread: net rating diff * scale + home court + rest
    rest_diff = (home_rest_days - away_rest_days)
    projected_spread = net_diff * SPREAD_SCALE + HOME_COURT + rest_diff * 0.5

    # Projected scores: use league avg as base, apply team-specific adjustments
    # Additive adjustment avoids compounding that inflates gap in multiplicative approach
    away_pts_per_100 = LG_AVG_ORTG + (away_ortg - LG_AVG_ORTG) * 0.6 + (LG_AVG_DRTG - home_drtg) * 0.4
    home_pts_per_100 = LG_AVG_ORTG + (home_ortg - LG_AVG_ORTG) * 0.6 + (LG_AVG_DRTG - away_drtg) * 0.4

    away_score_proj = away_pts_per_100 * (game_pace / POSSESSIONS_PER_PACE)
    home_score_proj = home_pts_per_100 * (game_pace / POSSESSIONS_PER_PACE) + HOME_COURT + rest_diff * 0.5

    # Playoff / play-in intensity adjustment: defense sharpens, pace slows ~4%.
    # Regular season avg ~228 pts/game, playoff avg ~215 — about 5.7% lower.
    PLAYOFF_FACTOR = 0.944
    away_score_proj *= PLAYOFF_FACTOR
    home_score_proj *= PLAYOFF_FACTOR

    projected_total = away_score_proj + home_score_proj

    # Win probability via normal distribution
    # Historical NBA single-game std dev ≈ 12 pts
    spread_std = 12.0
    home_win_prob = _normal_cdf(projected_spread / spread_std)
    away_win_prob = 1.0 - home_win_prob

    notes = (
        f"Home net {home_net:+.1f} vs Away net {away_net:+.1f} → "
        f"spread {projected_spread:+.1f} | "
        f"Away proj {away_score_proj:.1f} | Home proj {home_score_proj:.1f} | "
        f"Pace {game_pace:.1f}"
    )

    return {
        "away_team": away_team,
        "home_team": home_team,
        "away_proj": round(away_score_proj, 1),
        "home_proj": round(home_score_proj, 1),
        "projected_total": round(projected_total, 1),
        "projected_spread": round(-projected_spread, 1),  # away team spread (market convention)
        "home_win_prob": round(home_win_prob, 4),
        "away_win_prob": round(away_win_prob, 4),
        "game_pace": round(game_pace, 1),
        "notes": notes,
    }


def find_nba_edges(
    events: list[dict],
    min_edge_pct: float = MIN_EDGE_PCT,
) -> list[dict]:
    """
    Find edges across all NBA games in `events`.

    `events` format (from Odds API):
        [{
            'id', 'home_team', 'away_team', 'commence_time',
            'bookmakers': [{
                'title', 'markets': [{
                    'key': 'h2h'|'spreads'|'totals',
                    'outcomes': [{'name', 'price', 'point?'}]
                }]
            }]
        }]

    Returns list of edge dicts sorted by edge_pct descending.
    """
    all_teams = fetch_team_ratings()
    now_utc = datetime.now(timezone.utc)
    edges = []

    for event in events:
        home = event["home_team"]
        away = event["away_team"]
        commence = event.get("commence_time", "")
        game_id = event.get("id", "")

        # Skip started games
        if commence:
            try:
                ct = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                if ct <= now_utc:
                    continue
            except ValueError:
                pass

        proj = project_game(away, home, all_teams)

        # Build best odds per side per market across all books
        best_h2h:    dict[str, dict] = {}  # team_name -> {odds, book}
        best_spread: dict[str, dict] = {}  # team_name -> {odds, point, book}
        best_total:  dict[str, dict] = {}  # "Over"/"Under" -> {odds, point, book}

        for bk in event.get("bookmakers", []):
            book = bk.get("title", "")
            for mkt in bk.get("markets", []):
                mkey = mkt.get("key")
                for o in mkt.get("outcomes", []):
                    name  = o.get("name", "")
                    price = float(o.get("price", 0))
                    point = o.get("point")

                    if mkey == "h2h":
                        if name not in best_h2h or price > best_h2h[name]["odds"]:
                            best_h2h[name] = {"odds": price, "book": book}
                    elif mkey == "spreads":
                        if name not in best_spread or price > best_spread[name]["odds"]:
                            best_spread[name] = {"odds": price, "point": point, "book": book}
                    elif mkey == "totals":
                        if name not in best_total or price > best_total[name]["odds"]:
                            best_total[name] = {"odds": price, "point": point, "book": book}

        matchup = f"{away} @ {home}"

        # ── Moneyline edge ─────────────────────────────────────────────────
        if home in best_h2h and away in best_h2h:
            h_odds = best_h2h[home]["odds"]
            a_odds = best_h2h[away]["odds"]
            h_implied, a_implied = _devig_two_way(h_odds, a_odds)

            for team, model_prob, implied, odds, book in [
                (home, proj["home_win_prob"], h_implied, h_odds, best_h2h[home]["book"]),
                (away, proj["away_win_prob"], a_implied, a_odds, best_h2h[away]["book"]),
            ]:
                edge = (model_prob - implied) * 100
                if abs(edge) >= min_edge_pct and model_prob > 0.52:
                    edges.append({
                        "matchup": matchup,
                        "game_id": game_id,
                        "commence_time": commence,
                        "market": "moneyline",
                        "team": team,
                        "direction": "WIN",
                        "bet_line": None,
                        "best_odds": int(odds),
                        "sportsbook": book,
                        "model_prob": round(model_prob, 4),
                        "implied_prob": round(implied, 4),
                        "edge_pct": round(edge, 2),
                        "proj_spread": proj["projected_spread"],
                        "proj_total": proj["projected_total"],
                        "notes": proj["notes"],
                    })

        # ── Spread edge ────────────────────────────────────────────────────
        if home in best_spread and away in best_spread:
            h_sp = best_spread[home]
            a_sp = best_spread[away]
            h_implied, a_implied = _devig_two_way(h_sp["odds"], a_sp["odds"])

            # proj["projected_spread"] = -home_advantage (negative when home is favored)
            # home_advantage = -model_spread
            home_adv = -proj["projected_spread"]  # positive = home is projected to win by this many

            for team, mkt_line, model_covers_prob, implied, odds, book in [
                # Away covers +L when home wins by < L: P(X < L) where X ~ N(home_adv, 12²)
                (away, a_sp["point"],
                 _normal_cdf((float(a_sp["point"] or 0) - home_adv) / 12.0),
                 a_implied, a_sp["odds"], a_sp["book"]),
                # Home covers -L when home wins by > L: P(X > L) = 1 - P(X < L)
                (home, h_sp["point"],
                 1.0 - _normal_cdf((-float(h_sp["point"] or 0) - home_adv) / 12.0),
                 h_implied, h_sp["odds"], h_sp["book"]),
            ]:
                edge = (model_covers_prob - implied) * 100
                if abs(edge) >= min_edge_pct:
                    line_str = f"{mkt_line:+.1f}" if mkt_line is not None else ""
                    edges.append({
                        "matchup": matchup,
                        "game_id": game_id,
                        "commence_time": commence,
                        "market": "spread",
                        "team": f"{team} {line_str}",
                        "direction": "COVER",
                        "bet_line": mkt_line,
                        "best_odds": int(odds),
                        "sportsbook": book,
                        "model_prob": round(model_covers_prob, 4),
                        "implied_prob": round(implied, 4),
                        "edge_pct": round(edge, 2),
                        "proj_spread": proj["projected_spread"],
                        "proj_total": proj["projected_total"],
                        "notes": proj["notes"],
                    })

        # ── Totals edge ────────────────────────────────────────────────────
        if "Over" in best_total and "Under" in best_total:
            ov = best_total["Over"]
            un = best_total["Under"]
            ov_implied, un_implied = _devig_two_way(ov["odds"], un["odds"])
            market_line = float(ov.get("point") or 0)

            # Model probability of going over using normal distribution
            # Std dev of NBA totals historically ~13 pts
            total_std = 13.0
            model_over_prob = 1.0 - _normal_cdf(
                (market_line - proj["projected_total"]) / total_std
            )
            model_under_prob = 1.0 - model_over_prob

            for direction, model_prob, implied, odds, book in [
                ("OVER",  model_over_prob,  ov_implied, ov["odds"], ov["book"]),
                ("UNDER", model_under_prob, un_implied, un["odds"], un["book"]),
            ]:
                edge = (model_prob - implied) * 100
                if abs(edge) >= min_edge_pct and model_prob > 0.50:
                    edges.append({
                        "matchup": matchup,
                        "game_id": game_id,
                        "commence_time": commence,
                        "market": "total",
                        "team": f"{direction} {market_line}",
                        "direction": direction,
                        "bet_line": market_line,
                        "best_odds": int(odds),
                        "sportsbook": book,
                        "model_prob": round(model_prob, 4),
                        "implied_prob": round(implied, 4),
                        "edge_pct": round(edge, 2),
                        "proj_spread": proj["projected_spread"],
                        "proj_total": proj["projected_total"],
                        "notes": proj["notes"],
                    })

    edges.sort(key=lambda x: x["edge_pct"], reverse=True)
    return edges
