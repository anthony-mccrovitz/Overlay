"""
NRFI / YRFI edge detection — No Run First Inning.

Model: P(NRFI) = P(home_no_score_1st | away_sp) × P(away_no_score_1st | home_sp)
Uses pitcher ERA + K/9 to estimate first-inning run suppression probability.
Compares to book's implied NRFI probability (from h2h_1st_1_innings market).

League baseline: ~67% of MLB games have NRFI (each team ~82% chance not scoring in 1st).
Elite SP matchups push NRFI probability to 75-80%.
Weak SP matchups drop it to 55-60%.
"""
from __future__ import annotations

import math
import os
import time
import json
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

from src.data.odds_api import MY_BOOKS_PARAM

load_dotenv()

CACHE_DIR = Path("data/cache/nrfi")
API_BASE = "https://api.the-odds-api.com/v4"

# League baseline: P(one team doesn't score in first inning) facing avg SP
# Actual MLB NRFI rate ~67% → each team ~81.9% to not score → sqrt(0.67) = 0.819
_BASE_P_HOLD = 0.819
_LEAGUE_AVG_ERA = 4.20
_LEAGUE_AVG_K9  = 8.5
MIN_EDGE = 0.04   # 4 percentage points vs implied
MIN_IMPLIED_PROB = 0.30   # no picks at odds better than +233


def _api_key() -> str | None:
    return os.environ.get("ODDS_API_KEY")


def _cached_get(key: str, url: str, params: dict, max_age_s: int = 3600):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{key}.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < max_age_s:
        with open(cache) as f:
            return json.load(f)
    api_key = _api_key()
    if not api_key:
        return None
    try:
        resp = requests.get(url, params={**params, "apiKey": api_key}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        print(f"  [nrfi] API error: {e}")
        return None


def _devig(yes_odds: float, no_odds: float) -> float:
    """De-vig American odds pair → fair probability for YES (YRFI)."""
    def to_prob(a: float) -> float:
        if a > 0:
            return 100 / (a + 100)
        return abs(a) / (abs(a) + 100)
    p_yes = to_prob(yes_odds)
    p_no  = to_prob(no_odds)
    total = p_yes + p_no
    return p_yes / total if total > 0 else 0.5


def _p_sp_holds_first(era: float, k9: float) -> float:
    """
    P(this SP's team doesn't score off them in the first inning).
    Calibrated so avg ERA/K9 returns _BASE_P_HOLD.
    """
    era_adj = (_LEAGUE_AVG_ERA - era) * 0.025   # lower ERA → higher hold prob
    k9_adj  = (k9 - _LEAGUE_AVG_K9) * 0.008    # more Ks → higher hold prob
    p = _BASE_P_HOLD + era_adj + k9_adj
    return max(0.50, min(0.82, p))


def project_nrfi(
    home_sp_era: float,
    home_sp_k9: float,
    away_sp_era: float,
    away_sp_k9: float,
) -> float:
    """
    Project P(NRFI) for a game.
    home SP faces away batters; away SP faces home batters.
    """
    p_away_no_score = _p_sp_holds_first(home_sp_era, home_sp_k9)  # home SP holds away lineup
    p_home_no_score = _p_sp_holds_first(away_sp_era, away_sp_k9)  # away SP holds home lineup
    return round(p_away_no_score * p_home_no_score, 4)


def fetch_nrfi_odds(event_id: str) -> dict | None:
    """
    Fetch first-inning NRFI/YRFI odds for a game.
    Returns {yrfi_odds, nrfi_odds, implied_yrfi_prob, implied_nrfi_prob, book}
    or None if market not available.

    Primary: totals_1st_1_innings from FanDuel/BetMGM/DraftKings.
      UNDER 0.5 = NRFI, OVER 0.5 = YRFI.
    Fallback: h2h_1st_1_innings from any region (Yes/No format).
    """
    data = _cached_get(
        f"nrfi_{event_id}",
        f"{API_BASE}/sports/baseball_mlb/events/{event_id}/odds",
        {
            "regions": "us",
            "markets": "totals_1st_1_innings,h2h_1st_1_innings",
            "oddsFormat": "american",
        },
        max_age_s=1800,
    )
    if not data or not isinstance(data, dict):
        return None

    best: dict | None = None
    for bookmaker in data.get("bookmakers", []):
        book_name = bookmaker.get("title", "")
        book_key  = bookmaker.get("key", "")
        for mkt in bookmaker.get("markets", []):
            mkt_key = mkt.get("key", "")
            outcomes = mkt.get("outcomes", [])

            if mkt_key == "totals_1st_1_innings":
                # UNDER 0.5 = NRFI, OVER 0.5 = YRFI
                over_o  = next((o for o in outcomes if o.get("name","").lower() == "over"),  None)
                under_o = next((o for o in outcomes if o.get("name","").lower() == "under"), None)
                if not over_o or not under_o:
                    continue
                yes_odds = int(over_o["price"])   # YRFI
                no_odds  = int(under_o["price"])   # NRFI
            elif mkt_key == "h2h_1st_1_innings":
                # Yes/No format: Yes = YRFI, No = NRFI
                yes_odds = next((o["price"] for o in outcomes if "yes" in o.get("name","").lower()), None)
                no_odds  = next((o["price"] for o in outcomes if "no"  in o.get("name","").lower()), None)
                if yes_odds is None or no_odds is None:
                    continue
                yes_odds = int(yes_odds)
                no_odds  = int(no_odds)
            else:
                continue

            implied_yrfi = _devig(yes_odds, no_odds)
            # Prefer our tier-1 books; among those prefer best NRFI odds
            tier1 = book_key in ("fanduel", "draftkings", "betmgm", "caesars", "betrivers")
            if best is None or (tier1 and not best.get("tier1")) or no_odds > best.get("nrfi_odds", -999):
                best = {
                    "yrfi_odds": yes_odds,
                    "nrfi_odds": no_odds,
                    "tier1": tier1,
                    "implied_yrfi_prob": round(implied_yrfi, 4),
                    "implied_nrfi_prob": round(1 - implied_yrfi, 4),
                    "book": book_name,
                }
    return best


def find_nrfi_edges(
    matchups_with_stats: list[dict],
    game_date: date | None = None,
    min_edge: float = MIN_EDGE,
) -> list[dict]:
    """
    Find NRFI/YRFI edges for today's slate.

    matchups_with_stats: same format as find_prop_edges —
        home_team, away_team, home_sp_name, home_sp_era, home_sp_k9,
        away_sp_name, away_sp_era, away_sp_k9, event_id (optional)

    Returns list of edge dicts sorted by edge descending.
    """
    d = game_date or date.today()
    edges = []

    # Fetch event IDs if not provided
    from src.data.player_props import fetch_mlb_event_ids
    events = fetch_mlb_event_ids(d)
    event_lookup: dict[tuple[str, str], str] = {
        (ev["home_team"], ev["away_team"]): ev["event_id"] for ev in events
    }

    for m in matchups_with_stats:
        # Skip games with no confirmed starters — model has zero signal on TBD pitchers.
        # Defaulting to league-average ERA/K9 produces phantom ~12% edges at -120 lines.
        home_sp_name = m.get("home_sp_name", "").strip()
        away_sp_name = m.get("away_sp_name", "").strip()
        if not home_sp_name or home_sp_name.upper() == "TBD":
            continue
        if not away_sp_name or away_sp_name.upper() == "TBD":
            continue

        home_sp_era = m.get("home_sp_era", _LEAGUE_AVG_ERA)
        home_sp_k9  = m.get("home_sp_k9",  _LEAGUE_AVG_K9)
        away_sp_era = m.get("away_sp_era", _LEAGUE_AVG_ERA)
        away_sp_k9  = m.get("away_sp_k9",  _LEAGUE_AVG_K9)

        p_nrfi = project_nrfi(home_sp_era, home_sp_k9, away_sp_era, away_sp_k9)
        # Apply trained NRFI calibrator (Platt/isotonic from settled history)
        # before edge math so picks.json prob matches the edge.
        # SYMMETRIC: a one-sided calibrator here once pinned P(NRFI)≈0.44 below
        # every market price and emitted YRFI on all 64 July games. Symmetric
        # application keeps NRFI/YRFI complementary with no structural side.
        p_nrfi_raw = p_nrfi   # pre-calibration, for refits
        try:
            from src.analytics.calibration import apply_calibration_symmetric
            p_nrfi = apply_calibration_symmetric(p_nrfi, "mlb", "nrfi")
        except Exception:
            pass
        p_yrfi = 1.0 - p_nrfi

        # Try to get event ID
        event_id = m.get("event_id")
        if not event_id:
            for (ht, at), eid in event_lookup.items():
                if m["home_team"].lower() in ht.lower() or ht.lower() in m["home_team"].lower():
                    if m["away_team"].lower() in at.lower() or at.lower() in m["away_team"].lower():
                        event_id = eid
                        break

        # Try to fetch live odds
        book_data = fetch_nrfi_odds(event_id) if event_id and _api_key() else None

        if book_data:
            implied_nrfi = book_data["implied_nrfi_prob"]
            implied_yrfi = book_data["implied_yrfi_prob"]
            # Skip when either side is a longshot — model unreliable at extreme odds
            if implied_nrfi < MIN_IMPLIED_PROB or implied_yrfi < MIN_IMPLIED_PROB:
                continue
            nrfi_edge = p_nrfi - implied_nrfi
            yrfi_edge = p_yrfi - implied_yrfi

            # Pick whichever side has edge
            if abs(nrfi_edge) >= min_edge:
                if nrfi_edge > 0:
                    edges.append({
                        "type": "nrfi",
                        "market": "nrfi",
                        "direction": "NRFI",
                        "home_team": m["home_team"],
                        "away_team": m["away_team"],
                        "home_sp": m.get("home_sp_name", "TBD"),
                        "away_sp": m.get("away_sp_name", "TBD"),
                        "projected_nrfi": p_nrfi,
                "projected_nrfi_raw": p_nrfi_raw,
                        "projected_nrfi_raw": p_nrfi_raw,
                        "implied_nrfi": implied_nrfi,
                        "edge_pct": round(nrfi_edge * 100, 1),
                        "odds": book_data["nrfi_odds"],
                        "book": book_data["book"],
                        "label": f"{m['away_team']} @ {m['home_team']} NRFI",
                    })
                else:
                    edges.append({
                        "type": "nrfi",
                        "market": "nrfi",
                        "direction": "YRFI",
                        "home_team": m["home_team"],
                        "away_team": m["away_team"],
                        "home_sp": m.get("home_sp_name", "TBD"),
                        "away_sp": m.get("away_sp_name", "TBD"),
                        "projected_nrfi": p_nrfi,
                        "projected_nrfi_raw": p_nrfi_raw,
                        "implied_nrfi": implied_nrfi,
                        "edge_pct": round(abs(yrfi_edge) * 100, 1),
                        "odds": book_data["yrfi_odds"],
                        "book": book_data["book"],
                        "label": f"{m['away_team']} @ {m['home_team']} YRFI",
                    })
        else:
            # No live odds available from books for this event. Still log
            # with a default -120 (typical NRFI line) so the pick is gradeable
            # and feeds into model performance tracking. Don't market this as
            # +EV — flag with no_odds=True.
            direction = "NRFI" if p_nrfi >= 0.50 else "YRFI"
            edges.append({
                "type": "nrfi",
                "market": "nrfi",
                "direction": direction,
                "home_team": m["home_team"],
                "away_team": m["away_team"],
                "home_sp": m.get("home_sp_name", "TBD"),
                "away_sp": m.get("away_sp_name", "TBD"),
                "projected_nrfi": p_nrfi,
                "implied_nrfi": None,
                "edge_pct": None,
                "odds": -120,    # default for grading; verify book line before betting
                "book": None,
                "no_odds": True,
                "label": f"{m['away_team']} @ {m['home_team']} {direction}",
            })

    # Sort: if we have edge data, sort by edge; otherwise by projected_nrfi descending
    edges.sort(key=lambda x: (x["edge_pct"] or 0) + x["projected_nrfi"], reverse=True)
    return edges
