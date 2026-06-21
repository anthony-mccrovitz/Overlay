"""
WNBA player-props model — Overlay.

Projects points / rebounds / assists from season per-game averages and prices
the over/under against the book line:
  - Points:   stat ~ Normal(mean, 0.35·mean)  (continuous, higher variance)
  - Rebounds: stat ~ Normal(mean, 0.40·mean)
  - Assists:  stat ~ Poisson(mean)             (low-count)
P(over) = P(stat > line); edge = model P − de-vigged book implied P.

Mirrors the NBA props approach (src/data/nba_props.py): same coefficients of
variation, same OVER-shading correction (books set lines a touch low to attract
Over money), and the same confidence gate. WNBA-specific averages.

KNOWN LIMITATIONS (shadow-only, CLV-validated before any bet):
  - Season averages, NOT matchup/opponent-adjusted (no pace or defense vs
    position) and NOT minutes/injury-aware — a player in foul trouble or a
    blowout is overestimated.
  - Variance coefficients are borrowed from NBA; WNBA's true variance may differ
    (the validation harness will measure calibration and we'll retune).
  - No recent-form weighting (uses full-season GP average).
"""
from __future__ import annotations

import math

# CV coefficients (std as fraction of mean) — from NBA prop data, retune on WNBA.
_POINTS_CV = 0.35
_REBOUNDS_CV = 0.40
_MIN_POINTS_STD = 2.5
_MIN_REBOUNDS_STD = 1.5
# Books shade prop lines slightly low to attract Over money; subtract from the
# raw model Over prob before computing edge (same as NBA pipeline).
_OVER_SHADE = 0.05
# Don't model players below these minutes/lines — no real signal.
_MIN_MINUTES = 18.0

WNBA_PROPS = {
    "player_points":   ("PTS", "normal", _POINTS_CV, _MIN_POINTS_STD),
    "player_rebounds": ("REB", "normal", _REBOUNDS_CV, _MIN_REBOUNDS_STD),
    "player_assists":  ("AST", "poisson", None, None),
}


def _american_to_imp(odds: float) -> float:
    odds = float(odds)
    return (100.0 / (odds + 100.0)) if odds > 0 else (abs(odds) / (abs(odds) + 100.0))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _normal_over(mean: float, line: float, std: float) -> float:
    return 1.0 - _normal_cdf((line - mean) / std)


def _poisson_over(lam: float, line: float) -> float:
    """P(X > floor(line)) for X ~ Poisson(lam)."""
    k = int(math.floor(line))
    cdf = sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k + 1))
    return 1.0 - cdf


def project_prop(player_stats: dict, market: str) -> float | None:
    """Season per-game average for the player+market, or None if unavailable."""
    spec = WNBA_PROPS.get(market)
    if not spec:
        return None
    field = spec[0]
    if (player_stats.get("MIN") or 0) < _MIN_MINUTES:
        return None
    val = player_stats.get(field)
    return float(val) if val is not None else None


def over_prob(player_stats: dict, market: str, line: float) -> float | None:
    """Model P(stat > line) for this player+market."""
    spec = WNBA_PROPS.get(market)
    proj = project_prop(player_stats, market)
    if spec is None or proj is None:
        return None
    _field, dist, cv, min_std = spec
    if dist == "poisson":
        return _poisson_over(max(proj, 0.1), line)
    std = max(proj * cv, min_std)
    return _normal_over(proj, line, std)


def find_wnba_prop_edges(event: dict, players_by_name: dict,
                         min_edge_pct: float = 8.0) -> list[dict]:
    """Find WNBA prop edges for one per-event Odds API response.

    players_by_name: {player_name_lower: stat_dict} from fetch_player_stats.
    Returns pnl-schema edge dicts, market = the specific prop key.
    """
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    edges: list[dict] = []
    for bm in event.get("bookmakers", []):
        book = bm.get("title", "")
        for market in bm.get("markets", []):
            mkey = market.get("key", "")
            if mkey not in WNBA_PROPS:
                continue
            # group outcomes by player → has Over and Under at a line
            by_player: dict[str, dict] = {}
            for o in market.get("outcomes", []):
                name = str(o.get("description") or "").strip()
                side = str(o.get("name") or "").lower()
                if not name or side not in ("over", "under"):
                    continue
                by_player.setdefault(name, {})[side] = o
            for player, sides in by_player.items():
                over_o, under_o = sides.get("over"), sides.get("under")
                if not over_o or not under_o or over_o.get("point") is None:
                    continue
                stats = players_by_name.get(player.lower())
                if not stats:  # surname fallback
                    sn = player.lower().split()[-1] if player.split() else ""
                    stats = next((s for k, s in players_by_name.items()
                                  if len(sn) > 3 and k.split()[-1] == sn), None)
                if not stats:
                    continue
                line = float(over_o["point"])
                p_over = over_prob(stats, mkey, line)
                if p_over is None:
                    continue
                p_over = max(0.0, p_over - _OVER_SHADE)
                op = _american_to_imp(float(over_o["price"]))
                up = _american_to_imp(float(under_o["price"]))
                tot = op + up
                if tot <= 0:
                    continue
                for direction, mp, price, imp in [
                    ("OVER", p_over, float(over_o["price"]), op / tot),
                    ("UNDER", 1.0 - p_over, float(under_o["price"]), up / tot),
                ]:
                    edge = (mp - imp) * 100.0
                    if edge >= min_edge_pct:
                        edges.append({
                            "sport": "basketball_wnba", "market": mkey,
                            "direction": direction, "team": f"{player} {direction} {line}",
                            "player": player, "matchup": f"{away} @ {home}",
                            "odds": int(price), "best_odds": int(price), "line": line,
                            "model_prob": round(mp, 4), "implied_prob": round(imp, 4),
                            "edge_pct": round(edge, 2), "sportsbook": book,
                        })
    # best edge per (player, market, direction)
    best: dict[tuple, dict] = {}
    for e in edges:
        k = (e["player"], e["market"], e["direction"])
        if k not in best or e["edge_pct"] > best[k]["edge_pct"]:
            best[k] = e
    return sorted(best.values(), key=lambda x: x["edge_pct"], reverse=True)
