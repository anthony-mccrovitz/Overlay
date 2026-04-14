"""
NRFI / YRFI edge detection — No Run First Inning.

Model: P(NRFI) = P(home_no_score_1st | away_sp) × P(away_no_score_1st | home_sp)
Uses pitcher ERA + K/9 to estimate first-inning run suppression probability.
Compares to book's implied NRFI probability (from h2h_1st_1_innings market).

League baseline: ~42% of games have NRFI (each team ~65% chance not scoring in 1st).
Elite SP matchups push NRFI probability to 55-60%.
Weak SP matchups drop it to 28-35%.
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

load_dotenv()

CACHE_DIR = Path("data/cache/nrfi")
API_BASE = "https://api.the-odds-api.com/v4"

# League baseline: P(one team doesn't score in first inning) facing avg SP
_BASE_P_HOLD = 0.648   # calibrated so avg game NRFI ≈ 0.42 (0.648 × 0.648)
_LEAGUE_AVG_ERA = 4.20
_LEAGUE_AVG_K9  = 8.5
MIN_EDGE = 0.04   # 4 percentage points vs implied


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
    Fetch first-inning H2H odds for a game.
    Returns {yrfi_odds, nrfi_odds, implied_yrfi_prob, implied_nrfi_prob, book}
    or None if market not available.
    """
    data = _cached_get(
        f"nrfi_{event_id}",
        f"{API_BASE}/sports/baseball_mlb/events/{event_id}/odds",
        {
            "regions": "us",
            "markets": "h2h_1st_1_innings",
            "oddsFormat": "american",
            "bookmakers": "draftkings,fanduel,betmgm,caesars",
        },
        max_age_s=1800,
    )
    if not data or not isinstance(data, dict):
        return None

    best: dict | None = None
    for bookmaker in data.get("bookmakers", []):
        book_name = bookmaker.get("title", "")
        for mkt in bookmaker.get("markets", []):
            if mkt.get("key") != "h2h_1st_1_innings":
                continue
            outcomes = mkt.get("outcomes", [])
            # outcomes: [{name: "Yes", price: -130}, {name: "No", price: +110}]
            yes_odds = next((o["price"] for o in outcomes if "yes" in o.get("name","").lower()), None)
            no_odds  = next((o["price"] for o in outcomes if "no"  in o.get("name","").lower()), None)

            # some books label by team names instead of Yes/No — try home/away
            if yes_odds is None and len(outcomes) == 2:
                yes_odds = outcomes[0].get("price")
                no_odds  = outcomes[1].get("price")

            if yes_odds is None or no_odds is None:
                continue

            implied_yrfi = _devig(yes_odds, no_odds)
            # Keep the book with best NRFI odds (highest no_odds)
            if best is None or no_odds > best.get("nrfi_odds", -999):
                best = {
                    "yrfi_odds": int(yes_odds),
                    "nrfi_odds": int(no_odds),
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
        home_sp_era = m.get("home_sp_era", _LEAGUE_AVG_ERA)
        home_sp_k9  = m.get("home_sp_k9",  _LEAGUE_AVG_K9)
        away_sp_era = m.get("away_sp_era", _LEAGUE_AVG_ERA)
        away_sp_k9  = m.get("away_sp_k9",  _LEAGUE_AVG_K9)

        p_nrfi = project_nrfi(home_sp_era, home_sp_k9, away_sp_era, away_sp_k9)
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
                        "implied_nrfi": implied_nrfi,
                        "edge_pct": round(nrfi_edge * 100, 1),
                        "odds": book_data["nrfi_odds"],
                        "book": book_data["book"],
                        "label": f"{m['away_team']} @ {m['home_team']} NRFI",
                    })
                else:
                    edges.append({
                        "type": "nrfi",
                        "market": "yrfi",
                        "direction": "YRFI",
                        "home_team": m["home_team"],
                        "away_team": m["away_team"],
                        "home_sp": m.get("home_sp_name", "TBD"),
                        "away_sp": m.get("away_sp_name", "TBD"),
                        "projected_nrfi": p_nrfi,
                        "implied_nrfi": implied_nrfi,
                        "edge_pct": round(abs(yrfi_edge) * 100, 1),
                        "odds": book_data["yrfi_odds"],
                        "book": book_data["book"],
                        "label": f"{m['away_team']} @ {m['home_team']} YRFI",
                    })
        else:
            # No live odds — show model projection only (no edge calc)
            edges.append({
                "type": "nrfi",
                "market": "nrfi" if p_nrfi >= 0.50 else "yrfi",
                "direction": "NRFI" if p_nrfi >= 0.50 else "YRFI",
                "home_team": m["home_team"],
                "away_team": m["away_team"],
                "home_sp": m.get("home_sp_name", "TBD"),
                "away_sp": m.get("away_sp_name", "TBD"),
                "projected_nrfi": p_nrfi,
                "implied_nrfi": None,
                "edge_pct": None,
                "odds": None,
                "book": None,
                "label": f"{m['away_team']} @ {m['home_team']} {'NRFI' if p_nrfi >= 0.50 else 'YRFI'}",
            })

    # Sort: if we have edge data, sort by edge; otherwise by projected_nrfi descending
    edges.sort(key=lambda x: (x["edge_pct"] or 0) + x["projected_nrfi"], reverse=True)
    return edges
