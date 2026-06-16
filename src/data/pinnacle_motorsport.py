"""
Pinnacle Motorsport Odds Fetcher — Overlay

Fetches live outright odds for IndyCar, F1, and NASCAR from Pinnacle's
guest API (no auth required for read-only outrights on special events).

Pinnacle is the sharpest book in the world — their lines are the closest
proxy to true market probability. Use these as the gold standard for
edge detection instead of the manual-odds paste flow.

Sport IDs:
  44 = Formula 1
  63 = Motorsport (IndyCar, NASCAR)

Returns events in Odds-API-compatible format so run_nascar.py / run_indycar.py
/ run_f1.py can consume them without changes.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

CACHE_DIR = Path("data/cache/pinnacle")
BASE_URL  = "https://guest.api.arcadia.pinnacle.com/0.1"

_HEADERS = {
    "Accept":       "application/json",
    "User-Agent":   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "X-Device-UUID": "edgefinder-motorsport-00000001",
}

# Pinnacle sport IDs → series labels
SPORT_MAP = {
    44: "Formula 1",
    63: "Motorsport",
}

# Map Pinnacle sport IDs to our internal sport keys
SPORT_KEY_MAP = {
    44: "auto_racing_formula_one",
    63: "auto_racing_indycar_series",  # IndyCar + NASCAR share sportId=63 on Pinnacle
}

# Pinnacle league IDs for specific series — use /leagues/{id}/matchups
# because /sports/63/matchups requires auth while /leagues/{id}/matchups is public.
# Find new IDs via: fetch_motorsport_events(discover=True)
KNOWN_LEAGUE_IDS: dict[str, dict] = {
    "Indianapolis 500":    {"id": 209639, "sport_id": 63, "sport_key": "auto_racing_indycar_series"},
    "IndyCar Series":      {"id": 209638, "sport_id": 63, "sport_key": "auto_racing_indycar_series"},
    "NASCAR Cup Series":   {"id": 209640, "sport_id": 63, "sport_key": "auto_racing_nascar_cup_series"},
    "Formula 1":           {"id": None,   "sport_id": 44, "sport_key": "auto_racing_formula_one"},
}

# Participant ID → driver name maps for known events.
# These are seeded from a one-time fetch; prices update live via the markets endpoint.
# Add new events here when Pinnacle lists them.
KNOWN_PARTICIPANTS: dict[int, dict] = {
    # Indianapolis 500 2026 (matchupId=1630590614, league=209639, sport=63)
    1630590614: {
        "league":     "Indianapolis 500",
        "sport_key":  "auto_racing_indycar_series",
        "start_time": "2026-05-24T14:00:00Z",
        "drivers": {
            1630610368: "Alex Palou",
            1630610369: "Josef Newgarden",
            1630610370: "Pato O'Ward",
            1630610371: "David Malukas",
            1630610372: "Kyle Kirkwood",
            1630610373: "Scott McLaughlin",
            1630610374: "Scott Dixon",
            1630610375: "Marcus Ericsson",
            1630610376: "Christian Rasmussen",
            1630610377: "Will Power",
            1630610378: "Conor Daly",
            1630610379: "Takuma Sato",
            1630610380: "Christian Lundgaard",
            1630610381: "Alexander Rossi",
            1630610382: "Santino Ferrucci",
            1630610383: "Graham Rahal",
            1630610384: "Ryan Hunter-Reay",
            1630610385: "Helio Castroneves",
            1630610386: "Felix Rosenqvist",
            1630610387: "Mick Schumacher",
            1630610388: "Ed Carpenter",
            1630610389: "Dennis Hauger",
            1630610390: "Rinus Veekay",
            1630610391: "Romain Grosjean",
            1630610392: "Marcus Armstrong",
            1630610393: "Louis Foster",
            1630610394: "Caio Collet",
            1630610395: "Nolan Siegel",
            1630610396: "Kyffin Simpson",
            1630610397: "Jack Harvey",
            1630610398: "Jacob Abel",
            1630610399: "Sting Ray Robb",
            1630610400: "Katherine Legge",
        },
    },
}


def _get(path: str, params: dict | None = None, timeout: int = 12) -> list | dict | None:
    try:
        r = requests.get(
            f"{BASE_URL}/{path}",
            params=params,
            headers=_HEADERS,
            timeout=timeout,
        )
        if r.status_code == 204 or not r.content:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [pinnacle] {path}: {e}")
        return None


def fetch_known_events(refresh: bool = False, cache_ttl: int = 900) -> list[dict]:
    """
    Fetch live prices for all events in KNOWN_PARTICIPANTS using the markets endpoint
    (no auth required). Returns Odds-API-compatible event list.

    Use this when /sports/63/matchups is auth-gated — participant names are seeded
    from a one-time discovery fetch; prices update in real time.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "known_events.json"

    if not refresh and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < cache_ttl:
            print(f"  [pinnacle] Using cached known-event odds ({age/60:.0f}m old)")
            return json.loads(cache_file.read_text())

    events: list[dict] = []

    for mid, meta in KNOWN_PARTICIPANTS.items():
        markets_data = _get(f"matchups/{mid}/markets/related/straight")
        if not markets_data:
            print(f"  [pinnacle] matchup {mid} ({meta['league']}): no markets")
            continue

        pid_to_name = meta["drivers"]
        outcomes: list[dict] = []
        for market in markets_data:
            if market.get("type") != "moneyline":
                continue
            for price_entry in market.get("prices", []):
                pid   = price_entry.get("participantId")
                price = price_entry.get("price")
                name  = pid_to_name.get(pid, "")
                if name and price is not None:
                    outcomes.append({"name": name, "price": int(price)})

        if not outcomes:
            continue

        event = {
            "id":            str(mid),
            "sport_key":     meta["sport_key"],
            "sport_title":   meta["league"],
            "commence_time": meta["start_time"],
            "home_team":     outcomes[0]["name"],
            "away_team":     outcomes[-1]["name"],
            "league":        meta["league"],
            "bookmakers": [{
                "key":   "pinnacle",
                "title": "Pinnacle",
                "markets": [{
                    "key":      "outrights",
                    "outcomes": outcomes,
                }],
            }],
        }
        events.append(event)
        print(f"  [pinnacle] {meta['league']}: {len(outcomes)} drivers  (live Pinnacle prices)")

    cache_file.write_text(json.dumps(events, indent=2))
    return events


def _fetch_matchups_for_sport(sport_id: int) -> list[dict]:
    """
    Fetch outrights matchups for a sport.
    Sport 44 (F1): /sports/44/matchups works on guest API.
    Sport 63 (Motorsport): /sports/63/matchups requires auth — use known league IDs instead.
    """
    if sport_id == 44:
        result = _get(f"sports/{sport_id}/matchups")
        return result if isinstance(result, list) else []

    # Sport 63: /sports/63/matchups is auth-gated. Fetch via known league IDs.
    matchups = []
    league_ids = [v["id"] for v in KNOWN_LEAGUE_IDS.values()
                  if v.get("sport_id") == 63 and v.get("id")]
    for lid in league_ids:
        result = _get(f"leagues/{lid}/matchups")
        if isinstance(result, list):
            matchups.extend(result)
    return matchups


def fetch_motorsport_events(
    sport_ids: list[int] | None = None,
    refresh: bool = False,
    cache_ttl: int = 1800,
) -> list[dict]:
    """
    Fetch all live motorsport outright events from Pinnacle.

    Returns a list of Odds-API-compatible event dicts, each with:
      id, sport_key, sport_title, commence_time, bookmakers[{key, title, markets}]
    Driver names come from the participants list; prices from the markets endpoint.
    """
    if sport_ids is None:
        sport_ids = [44, 63]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "motorsport_events.json"

    if not refresh and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < cache_ttl:
            print(f"  [pinnacle] Using cached motorsport odds ({age/60:.0f}m old)")
            return json.loads(cache_file.read_text())

    all_events: list[dict] = []

    for sport_id in sport_ids:
        matchups = _fetch_matchups_for_sport(sport_id)

        for matchup in matchups:
            mtype = matchup.get("type", "")
            if mtype != "special":
                continue  # skip H2H matchups; we only want outrights

            mid          = matchup["id"]
            league       = matchup.get("league", {})
            league_name  = league.get("name", "")
            league_id    = league.get("id")
            start_time   = matchup.get("startTime", "")
            participants = matchup.get("participants", [])

            # Resolve sport key from league name or sport ID
            sport_key = SPORT_KEY_MAP.get(sport_id, f"motorsport_{sport_id}")
            for lname, ldata in KNOWN_LEAGUE_IDS.items():
                if ldata.get("id") == league_id or lname.lower() in league_name.lower():
                    sport_key = ldata["sport_key"]
                    break

            sport_title = SPORT_MAP.get(sport_id, "Motorsport")

            if not participants:
                continue

            pid_to_name = {p["id"]: p["name"] for p in participants}

            markets_data = _get(f"matchups/{mid}/markets/related/straight")
            if not markets_data:
                continue

            outcomes: list[dict] = []
            for market in markets_data:
                if market.get("type") != "moneyline":
                    continue
                for price_entry in market.get("prices", []):
                    pid   = price_entry.get("participantId")
                    price = price_entry.get("price")
                    name  = pid_to_name.get(pid, "")
                    if name and price is not None and name != "The Field":
                        outcomes.append({"name": name, "price": int(price)})

            if not outcomes:
                continue

            event = {
                "id":            str(mid),
                "sport_key":     sport_key,
                "sport_title":   sport_title,
                "commence_time": start_time,
                "home_team":     outcomes[0]["name"],
                "away_team":     outcomes[-1]["name"],
                "league":        league_name,
                "bookmakers": [{
                    "key":   "pinnacle",
                    "title": "Pinnacle",
                    "markets": [{
                        "key":      "outrights",
                        "outcomes": outcomes,
                    }],
                }],
            }
            all_events.append(event)
            print(
                f"  [pinnacle] {league_name}: {len(outcomes)} drivers  "
                f"start={start_time[:10]}  sport={sport_title}"
            )

    # Always include known-participant events (Indy 500, etc.) with live prices
    known = fetch_known_events(refresh=refresh)
    known_ids = {e["id"] for e in all_events}
    for ev in known:
        if ev["id"] not in known_ids:
            all_events.append(ev)

    cache_file.write_text(json.dumps(all_events, indent=2))
    return all_events


def print_indy_odds(events: list[dict]) -> None:
    """Pretty-print the Indy 500 (or any motorsport) outright odds."""
    for ev in events:
        print(f"\n{'='*60}")
        print(f"  {ev.get('league', ev['sport_title'])}  —  {ev['commence_time'][:10]}")
        print(f"  Source: Pinnacle  |  {ev['sport_key']}")
        print(f"{'='*60}")
        outcomes = ev["bookmakers"][0]["markets"][0]["outcomes"]
        for o in sorted(outcomes, key=lambda x: x["price"]):
            name  = o["name"]
            price = o["price"]
            # Convert American to implied prob
            imp = 100 / (price + 100) if price >= 0 else abs(price) / (abs(price) + 100)
            print(f"  {name:30s}  +{price:<6d}  ({imp:.1%})")


if __name__ == "__main__":
    print("Fetching live motorsport odds from Pinnacle...")
    events = fetch_motorsport_events(refresh=True)
    if events:
        print_indy_odds(events)
    else:
        print("No motorsport events found.")
