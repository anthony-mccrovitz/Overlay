"""
WNBA Game Prediction Model — spreads, totals, moneylines.

Methodology mirrors nba_model.py exactly (Four Factors efficiency regression),
with WNBA-specific calibration constants:
  - 40-min games, pace ~77 possessions (vs NBA 48 min, ~100 possessions)
  - Scoring baseline ~80 pts/game (vs NBA ~114)
  - Home court advantage ~2.0 pts (vs NBA ~3.0)
  - Spread std dev ~9 pts (vs NBA ~12) — tighter range, smaller scoring variance

Source: Basketball-Reference WNBA Advanced Stats (2021-2025 seasons)
"""
from __future__ import annotations

import math

from src.data.wnba_stats import (
    LG_AVG_DRTG,
    LG_AVG_ORTG,
    LG_AVG_PACE,
    HOME_COURT,
    fetch_team_ratings,
    get_team_ratings,
)

MIN_EDGE_PCT = 6.0     # Slightly lower threshold than NBA — WNBA books are softer
OVER_BIAS_CORRECTION = 0.0    # disabled: it double-tilted an already-under-biased
                              # totals model. Book shading is a CLV question, not an
                              # EV thumb on the scale.
WNBA_TOTAL_RECENTER = 3.2     # measured proj-minus-line offset (proj ran 3.2 pts low)
MIN_IMPLIED_PROB = 0.30       # skip picks at odds better than +233
WNBA_EDGE_CAP_PCT = 10.0      # WNBA has NO trained calibrator yet (needs 30+ clean
                              # graded picks/market — currently 8/9/22 usable). Until
                              # it does, the raw net-rating model is overconfident and
                              # emits phantom double-digit "edges" (a +33% spread is the
                              # model being wrong, not the book). Cap the SURFACED edge
                              # so the shadow board can't tempt a manual bet on an
                              # un-earned number. model_prob_raw is stamped BEFORE the
                              # cap, so calibration fuel is unaffected.

POSSESSIONS_PER_PACE = 100.0
GAME_MINUTES = 40.0    # WNBA games are 40 min, not 48


def _devig_two_way(odds_a: float, odds_b: float) -> tuple[float, float]:
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
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _is_unrated(ratings: dict) -> bool:
    """True when a ratings dict is the league-average default — the signature
    of a team the data source doesn't know (failed fetch, missing expansion
    team). Real teams never sit at EXACTLY net 0.0 / league-avg ORtg / .500."""
    return (
        float(ratings.get("NET_RATING") or 0.0) == 0.0
        and float(ratings.get("OFF_RATING") or LG_AVG_ORTG) == LG_AVG_ORTG
        and float(ratings.get("W_PCT") or 0.5) == 0.5
    )


def _calibrated_symmetric(p: float, market: str) -> float:
    """WNBA probs through the trained calibrator (symmetric, so the two sides
    of a market always sum to 1). Identity until a wnba_{market}.pkl exists —
    but the edge GATE still shrinks these markets via normalize_pick."""
    try:
        from src.analytics.calibration import apply_calibration_symmetric
        return apply_calibration_symmetric(p, "wnba", market)
    except Exception:
        return p


def _cap_edge(model_p: float, imp_p: float) -> tuple[float, float]:
    """Clamp the surfaced edge to ±WNBA_EDGE_CAP_PCT, pulling model_prob toward
    the implied prob so model_prob and edge_pct stay mutually consistent. This is
    a display-honesty guard, not a calibrator: with no trained WNBA calibrator the
    raw net-rating model is overconfident, so a >10% "edge" is noise, not signal.
    Symmetric, so phantom NEGATIVE edges are capped too."""
    edge = (model_p - imp_p) * 100.0
    cap = WNBA_EDGE_CAP_PCT
    if edge > cap:
        return imp_p + cap / 100.0, cap
    if edge < -cap:
        return imp_p - cap / 100.0, -cap
    return model_p, edge


def project_game(
    away_team: str,
    home_team: str,
    all_teams: list[dict] | None = None,
    away_rest_days: int = 2,
    home_rest_days: int = 2,
) -> dict:
    """
    Project a WNBA game: spread, total, win probability.

    Returns same structure as nba_model.project_game so the rest of the
    pipeline (edge-finding, pick logging) works without modification.
    """
    if all_teams is None:
        all_teams = fetch_team_ratings()

    away = get_team_ratings(away_team, all_teams)
    home = get_team_ratings(home_team, all_teams)

    away_ortg = float(away.get("OFF_RATING") or LG_AVG_ORTG)
    away_drtg = float(away.get("DEF_RATING") or LG_AVG_DRTG)
    home_ortg = float(home.get("OFF_RATING") or LG_AVG_ORTG)
    home_drtg = float(home.get("DEF_RATING") or LG_AVG_DRTG)
    # nba_api reports WNBA pace per 48-min (NBA convention); convert to 40-min actual
    PACE_SCALE = GAME_MINUTES / 48.0   # = 40/48 ≈ 0.833
    away_pace = float(away.get("PACE") or LG_AVG_PACE) * PACE_SCALE
    home_pace = float(home.get("PACE") or LG_AVG_PACE) * PACE_SCALE

    game_pace = (away_pace + home_pace) / 2.0

    # Net-rating spread model — same scale factor as NBA (0.45)
    # WNBA spread distribution is tighter but the rating→points conversion
    # is similar in per-100-possession space.
    SPREAD_SCALE = 0.45
    home_net = home_ortg - home_drtg
    away_net = away_ortg - away_drtg
    net_diff = home_net - away_net

    rest_diff = home_rest_days - away_rest_days
    projected_spread = net_diff * SPREAD_SCALE + HOME_COURT + rest_diff * 0.5

    # Score projection: convert per-100-possession ratings to actual points
    # per 40-min game at the expected pace.
    # NBA uses pace/100 as scalar; WNBA pace is per 40 min, same math.
    away_pts_per_100 = LG_AVG_ORTG + (away_ortg - LG_AVG_ORTG) * 0.6 + (LG_AVG_DRTG - home_drtg) * 0.4
    home_pts_per_100 = LG_AVG_ORTG + (home_ortg - LG_AVG_ORTG) * 0.6 + (LG_AVG_DRTG - away_drtg) * 0.4

    away_score_proj = away_pts_per_100 * (game_pace / POSSESSIONS_PER_PACE)
    home_score_proj = home_pts_per_100 * (game_pace / POSSESSIONS_PER_PACE) + HOME_COURT + rest_diff * 0.5

    projected_total = away_score_proj + home_score_proj

    # WNBA spread std dev: historically ~9 pts (NBA is ~12)
    spread_std = 9.0
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
        "projected_spread": round(-projected_spread, 1),
        "home_win_prob": round(home_win_prob, 4),
        "away_win_prob": round(away_win_prob, 4),
        "game_pace": round(game_pace, 1),
        "notes": notes,
    }


def find_wnba_edges(
    events: list[dict],
    min_edge_pct: float = MIN_EDGE_PCT,
) -> list[dict]:
    """
    Find edges across all WNBA games in `events`.

    `events` format identical to NBA (from Odds API basketball_wnba endpoint):
        [{"home_team": ..., "away_team": ..., "bookmakers": [...]}]

    Returns list of edge dicts, same schema as nba_model.find_nba_edges.
    """
    all_teams = fetch_team_ratings()
    edges = []
    skipped_unrated = 0

    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if not home or not away:
            continue

        # Degenerate-slate guard: a team that resolved to the league-average
        # default (NET 0 / W% .500 signature) is UNRATED — the model knows
        # nothing about it. Pricing such a game emits the constant coin-flip
        # pair (home 0.5879 / away 0.4121) regardless of opponent; that ran
        # for a month in June-July 2026 before anyone noticed. No pick beats
        # a team-blind pick.
        if _is_unrated(get_team_ratings(home, all_teams)) or \
           _is_unrated(get_team_ratings(away, all_teams)):
            skipped_unrated += 1
            continue

        proj = project_game(away, home, all_teams)
        proj_total = proj["projected_total"]
        proj_spread = proj["projected_spread"]   # away spread (market convention)
        home_win_p = proj["home_win_prob"]
        away_win_p = proj["away_win_prob"]

        for bookmaker in event.get("bookmakers", []):
            book = bookmaker.get("title", "")
            for market in bookmaker.get("markets", []):
                mkey = market.get("key", "")
                outcomes = market.get("outcomes", [])

                # ── Totals ──────────────────────────────────────────────────
                if mkey == "totals":
                    over = next((o for o in outcomes if o.get("name") == "Over"), None)
                    under = next((o for o in outcomes if o.get("name") == "Under"), None)
                    if not over or not under:
                        continue
                    line = float(over.get("point", 0))
                    over_odds = float(over.get("price", -110))
                    under_odds = float(under.get("price", -110))
                    imp_over, imp_under = _devig_two_way(over_odds, under_odds)

                    # P(total > line) from Normal(proj_total, std=18).
                    # The projection ran ~3.2 pts BELOW the market line on average
                    # (95-pick full board) — a systematic underprojection that made
                    # the model lean UNDER ~84% of the time (phantom under "edges").
                    # Recentre onto the sharp line; per-game deviations (the edge)
                    # survive. OVER_BIAS_CORRECTION is disabled below (was double-
                    # tilting an already-under-biased model).
                    total_std = 18.0
                    proj_total_adj = proj_total + WNBA_TOTAL_RECENTER
                    model_over_p = 1.0 - _normal_cdf((line - proj_total_adj) / total_std)
                    model_over_p = max(0.01, model_over_p - OVER_BIAS_CORRECTION)
                    model_over_p_raw = model_over_p   # pre-calibration, for refits
                    model_over_p = _calibrated_symmetric(model_over_p, "total")
                    model_under_p = 1.0 - model_over_p

                    for direction, model_p, model_p_raw, imp_p, odds in [
                        ("OVER",  model_over_p,  model_over_p_raw,       imp_over,  over_odds),
                        ("UNDER", model_under_p, 1.0 - model_over_p_raw, imp_under, under_odds),
                    ]:
                        if imp_p < MIN_IMPLIED_PROB:
                            continue
                        model_p, edge = _cap_edge(model_p, imp_p)
                        if edge >= min_edge_pct:
                            edges.append({
                                "sport":       "basketball_wnba",
                                "market":      "total",
                                "direction":   direction,
                                "team":        f"{direction} {line}",
                                "matchup":     f"{away} @ {home}",
                                "away_team":   away,
                                "home_team":   home,
                                "odds":        int(odds),
                                "best_odds":   int(odds),
                                "line":        line,
                                "model_prob":  round(model_p, 4),
                                "model_prob_raw": round(model_p_raw, 4),
                                "implied_prob": round(imp_p, 4),
                                "edge_pct":    round(edge, 2),
                                "sportsbook":  book,
                                "projected_total": proj_total,
                                "notes":       proj["notes"],
                            })

                # ── Spreads ─────────────────────────────────────────────────
                elif mkey == "spreads":
                    home_s = next((o for o in outcomes if o.get("name") == home), None)
                    away_s = next((o for o in outcomes if o.get("name") == away), None)
                    if not home_s or not away_s:
                        continue
                    home_line = float(home_s.get("point", 0))
                    home_odds = float(home_s.get("price", -110))
                    away_odds = float(away_s.get("price", -110))
                    imp_home, imp_away = _devig_two_way(home_odds, away_odds)

                    spread_std = 9.0
                    # P(home covers) = P(home_margin > home_line)
                    # home_margin ~ N(projected_spread_from_home_perspective, spread_std)
                    home_margin_proj = -proj_spread  # proj_spread is away perspective
                    model_home_p = 1.0 - _normal_cdf((home_line - home_margin_proj) / spread_std)
                    model_home_p_raw = model_home_p   # pre-calibration, for refits
                    model_home_p = _calibrated_symmetric(model_home_p, "spread")
                    model_away_p = 1.0 - model_home_p

                    for team, model_p, model_p_raw, imp_p, odds, line in [
                        (home, model_home_p, model_home_p_raw,       imp_home, home_odds, home_line),
                        (away, model_away_p, 1.0 - model_home_p_raw, imp_away, away_odds, -home_line),
                    ]:
                        model_p, edge = _cap_edge(model_p, imp_p)
                        if edge >= min_edge_pct:
                            edges.append({
                                "sport":       "basketball_wnba",
                                "market":      "spread",
                                "direction":   f"{'+' if line >= 0 else ''}{line}",
                                "team":        team,
                                "matchup":     f"{away} @ {home}",
                                "away_team":   away,
                                "home_team":   home,
                                "odds":        int(odds),
                                "best_odds":   int(odds),
                                "line":        line,
                                "model_prob":  round(model_p, 4),
                                "model_prob_raw": round(model_p_raw, 4),
                                "implied_prob": round(imp_p, 4),
                                "edge_pct":    round(edge, 2),
                                "sportsbook":  book,
                                "projected_spread": proj_spread,
                                "notes":       proj["notes"],
                            })

                # ── Moneyline ───────────────────────────────────────────────
                elif mkey == "h2h":
                    home_ml = next((o for o in outcomes if o.get("name") == home), None)
                    away_ml = next((o for o in outcomes if o.get("name") == away), None)
                    if not home_ml or not away_ml:
                        continue
                    home_odds = float(home_ml.get("price", -110))
                    away_odds = float(away_ml.get("price", -110))
                    imp_home, imp_away = _devig_two_way(home_odds, away_odds)

                    ml_home_p = _calibrated_symmetric(home_win_p, "moneyline")
                    ml_away_p = 1.0 - ml_home_p
                    for team, model_p, model_p_raw, imp_p, odds in [
                        (home, ml_home_p, home_win_p,       imp_home, home_odds),
                        (away, ml_away_p, 1.0 - home_win_p, imp_away, away_odds),
                    ]:
                        model_p, edge = _cap_edge(model_p, imp_p)
                        if edge >= min_edge_pct:
                            edges.append({
                                "sport":       "basketball_wnba",
                                "market":      "moneyline",
                                "direction":   "ML",
                                "team":        team,
                                "matchup":     f"{away} @ {home}",
                                "away_team":   away,
                                "home_team":   home,
                                "odds":        int(odds),
                                "best_odds":   int(odds),
                                "line":        None,
                                "model_prob":  round(model_p, 4),
                                "model_prob_raw": round(model_p_raw, 4),
                                "implied_prob": round(imp_p, 4),
                                "edge_pct":    round(edge, 2),
                                "sportsbook":  book,
                                "notes":       proj["notes"],
                            })

    if skipped_unrated:
        print(f"  [wnba_model] skipped {skipped_unrated} game(s) with unrated "
              "team(s) — ratings source returned league-average defaults")

    # Sort by edge descending, dedup by (team, market, direction)
    edges.sort(key=lambda x: x["edge_pct"], reverse=True)
    seen: set[tuple] = set()
    deduped = []
    for e in edges:
        key = (e["team"], e["market"], e["direction"], e["matchup"])
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return deduped
