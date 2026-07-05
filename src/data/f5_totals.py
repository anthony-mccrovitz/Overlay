"""
First 5 innings (F5) totals — projection model + Odds API fetch + edge finder.

Why F5:
  - Bypasses bullpen variance (the main source of full-game noise).
  - Books post less-sharp lines on F5 because volume is lower.
  - Cleaner signal: "what will the two starters give up?" — that's a more
    tractable model than full-game runs.

Markets we use:
  - totals_1st_5_innings (Odds API key)

Run via predict.py during the daily pipeline; results graded by
grade.py auto_grade where market == "f5_total".
"""
from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path

from src.data.mlb_stats import _cached_get
from src.data.odds_api import MY_BOOKS_PARAM
ODDS_API_BASE = "https://api.the-odds-api.com/v4"


# League-average baseline: ~4.4 runs total through 5 innings
# (League ERA ~4.0 → 4.0 * 5/9 = 2.22 runs per starter side per 5 IP × 2 sides)
LG_AVG_ERA = 4.00
INNINGS = 5.0


def _api_key() -> str | None:
    key = os.getenv("ODDS_API_KEY")
    if key:
        return key
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ODDS_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


_LG_AVG_K9 = 8.5


def project_f5_total(
    home_sp_era: float,
    away_sp_era: float,
    home_sp_k9: float = 8.5,
    away_sp_k9: float = 8.5,
    park_factor: float = 1.00,
    home_lineup_ops: float = 0.720,
    away_lineup_ops: float = 0.720,
) -> float:
    """
    Project total runs through 5 innings.

    Each starter faces the opposing lineup for ~5 innings. ERA-based baseline,
    adjusted for K/9 (strikeout rate suppresses balls in play → fewer runs),
    opposing lineup quality (OPS delta), and park factor.
    """
    # Base runs allowed per 5 IP from each starter
    home_runs = (home_sp_era / 9.0) * INNINGS
    away_runs = (away_sp_era / 9.0) * INNINGS

    # K/9 adjustment: each 1.0 K/9 above league avg (~8.5) → ~3% fewer runs
    # Higher Ks mean fewer balls in play and fewer baserunners in early innings
    home_k9_adj = (home_sp_k9 - _LG_AVG_K9) * 0.03
    away_k9_adj = (away_sp_k9 - _LG_AVG_K9) * 0.03
    home_runs *= (1.0 - home_k9_adj)
    away_runs *= (1.0 - away_k9_adj)

    # Lineup quality adjustment: higher OPS → more runs allowed
    # Each .020 OPS deviation from league avg → ~5% runs swing
    home_lineup_adj = (away_lineup_ops - 0.720) / 0.020 * 0.05
    away_lineup_adj = (home_lineup_ops - 0.720) / 0.020 * 0.05
    home_runs *= (1 + home_lineup_adj)
    away_runs *= (1 + away_lineup_adj)

    total = (home_runs + away_runs) * park_factor
    return round(total, 2)


# Book-shading correction is now handled by the isotonic/Platt calibration
# (apply_calibration below). The old extra 0.04 subtraction double-corrected on
# top of it and, with a slightly low projection, tilted the model ~83% UNDER.
# Left at 0 so the calibrated probability stands on its own.
OVER_BIAS_CORRECTION = 0.0
# Measured projection recentring: the projected F5 total ran ~0.11 runs below the
# market line on average (373 picks), which alone biases the lean UNDER. Add it
# back so the model is centred on the sharp line; per-game deviations (the edge)
# are preserved.
F5_PROJ_RECENTER = 0.11
MIN_IMPLIED_PROB = 0.30        # skip picks at odds better than +233

def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _devig(over_odds: float, under_odds: float) -> float:
    """Return de-vigged implied probability of OVER."""
    def imp(o):
        return 100.0 / (o + 100.0) if o > 0 else abs(o) / (abs(o) + 100.0)
    p_o, p_u = imp(over_odds), imp(under_odds)
    return p_o / (p_o + p_u) if (p_o + p_u) > 0 else 0.5


def fetch_f5_odds(event_id: str) -> dict | None:
    """
    Fetch totals_1st_5_innings from the Odds API for one event.
    Returns: {line, over_odds, under_odds, implied_over_prob, book} or None.
    """
    api_key = _api_key()
    if not api_key:
        return None
    data = _cached_get(
        f"f5_total_{event_id}",
        f"{ODDS_API_BASE}/sports/baseball_mlb/events/{event_id}/odds",
        {
            "apiKey":    api_key,
            "regions":   "us",
            "markets":   "totals_1st_5_innings",
            "oddsFormat": "american",
            "bookmakers": MY_BOOKS_PARAM,
        },
        max_age_s=1800,
    )
    if not data or not isinstance(data, dict):
        return None

    best: dict | None = None
    for bm in data.get("bookmakers", []):
        book_name = bm.get("title", "")
        for mkt in bm.get("markets", []):
            if mkt.get("key") != "totals_1st_5_innings":
                continue
            over = next((o for o in mkt.get("outcomes", []) if o.get("name", "").lower() == "over"), None)
            under = next((o for o in mkt.get("outcomes", []) if o.get("name", "").lower() == "under"), None)
            if not over or not under:
                continue
            line = over.get("point")
            implied_over = _devig(over["price"], under["price"])
            # Prefer the book offering best OVER odds (highest plus, smallest minus)
            score = over["price"] if over["price"] > 0 else 1000 / abs(over["price"])
            if best is None or score > best.get("_score", -1e9):
                best = {
                    "line":              line,
                    "over_odds":         int(over["price"]),
                    "under_odds":        int(under["price"]),
                    "implied_over_prob": round(implied_over, 4),
                    "book":              book_name,
                    "_score":            score,
                }
    if best:
        best.pop("_score", None)
    return best


def find_f5_edges(
    matchups_with_stats: list[dict],
    game_date: date | None = None,
    min_edge: float = 0.05,
) -> list[dict]:
    """
    Find F5 totals edges across today's slate.

    Each matchup dict must contain home_team, away_team, home_sp_era,
    away_sp_era. Optionally: home_sp_k9, away_sp_k9, home_lineup_ops,
    away_lineup_ops, park_factor, event_id.

    If event_id is missing, this function will look it up from the Odds API
    events list using fuzzy team-name matching.

    Returns list of edge dicts sorted by absolute edge desc.
    """
    if not _api_key():
        return []

    # Build event lookup if any matchup is missing event_id
    event_lookup: dict[tuple[str, str], str] = {}
    if any(not m.get("event_id") for m in matchups_with_stats):
        try:
            from src.data.player_props import fetch_mlb_event_ids
            for ev in fetch_mlb_event_ids(game_date or date.today()):
                event_lookup[(ev["home_team"], ev["away_team"])] = ev["event_id"]
        except Exception:
            pass

    edges = []
    for m in matchups_with_stats:
        event_id = m.get("event_id")
        if not event_id:
            for (ht, at), eid in event_lookup.items():
                ht_match = m["home_team"].lower() in ht.lower() or ht.lower() in m["home_team"].lower()
                at_match = m["away_team"].lower() in at.lower() or at.lower() in m["away_team"].lower()
                if ht_match and at_match:
                    event_id = eid; break
        if not event_id:
            continue

        # Project total
        proj = project_f5_total(
            home_sp_era=m.get("home_sp_era", LG_AVG_ERA),
            away_sp_era=m.get("away_sp_era", LG_AVG_ERA),
            home_sp_k9=m.get("home_sp_k9", 8.5),
            away_sp_k9=m.get("away_sp_k9", 8.5),
            park_factor=m.get("park_factor", 1.00),
            home_lineup_ops=m.get("home_lineup_ops", 0.720),
            away_lineup_ops=m.get("away_lineup_ops", 0.720),
        )

        odds = fetch_f5_odds(event_id)
        if not odds or odds.get("line") is None:
            continue

        line = float(odds["line"])

        # ── Sanity guard: F5 totals are always 3.5–6.5 runs. ──────────────────
        # If we get a line > 7.0 it means the API returned a full-game total
        # (9.5, 8.5, etc.) under the wrong market key — discard it.
        if line > 7.0:
            continue
        # Also reject implausibly low lines (model data error)
        if line < 2.5:
            continue
        # ──────────────────────────────────────────────────────────────────────
        # Estimate prob of going over using normal approx (std dev ~2.5 runs for 5-inning totals)
        F5_STD = 2.5
        z = ((proj + F5_PROJ_RECENTER) - line) / F5_STD
        model_p_over = _normal_cdf(z)
        # Calibrate against the trained mlb_f5_total isotonic/Platt fit so the
        # edge_pct we compute downstream reflects post-calibration probability.
        try:
            from src.analytics.calibration import apply_calibration
            model_p_over = apply_calibration(model_p_over, "mlb", "f5_total")
        except Exception:
            pass
        # Correct for systematic OVER shading by books
        model_p_over = max(0.01, model_p_over - OVER_BIAS_CORRECTION)
        implied_over = odds["implied_over_prob"]

        if implied_over < MIN_IMPLIED_PROB or (1 - implied_over) < MIN_IMPLIED_PROB:
            continue

        edge_over  = model_p_over - implied_over
        edge_under = (1 - model_p_over) - (1 - implied_over)

        if abs(edge_over) >= min_edge or abs(edge_under) >= min_edge:
            if edge_over >= edge_under:
                direction = "OVER"
                model_prob = model_p_over
                pick_odds = odds["over_odds"]
                edge = edge_over
            else:
                direction = "UNDER"
                model_prob = 1 - model_p_over
                pick_odds = odds["under_odds"]
                edge = edge_under

            matchup_str = f"{m['away_team']} @ {m['home_team']}"
            edges.append({
                "type":            "f5_total",
                "market":          "f5_total",
                "direction":       direction,
                "home_team":       m["home_team"],
                "away_team":       m["away_team"],
                "matchup":         matchup_str,
                # team field = human-readable "F5 UNDER 4.5 (SEA @ OAK)" so the
                # card and picks record clearly identifies the game, not just "UNDER 4.5"
                "team":            f"F5 {direction} {line} ({matchup_str})",
                "projected_total": proj,
                "line":            line,
                "model_prob":      round(model_prob, 4),
                "implied_prob":    round(implied_over if direction == "OVER" else 1 - implied_over, 4),
                "edge_pct":        round(edge * 100, 1),
                "odds":            pick_odds,
                "book":            odds["book"],
                "label":           f"F5 {direction} {line} ({matchup_str})",
            })

    edges.sort(key=lambda x: abs(x.get("edge_pct", 0)), reverse=True)
    return edges
