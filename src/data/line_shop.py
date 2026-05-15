"""
src/data/line_shop.py — Pure positive-EV line shopping (Monahan-style).

Finds every bet on your 12 soft books that beats Pinnacle's no-vig
fair probability. No outcome prediction — pure pricing arbitrage.

This is the Alex Monahan approach: Pinnacle sets the true market price.
Any soft book offering better than fair price = +EV bet it.

Usage:
    python3 -c "from src.data.line_shop import find_ev_bets; find_ev_bets()"
    or via chef.py: chef.py shop
"""
from __future__ import annotations

import json
from pathlib import Path

PREFERRED_BOOKS = {
    "fanduel", "draftkings", "hardrockbet", "fliff", "bet365",
    "ballybet", "betrivers", "thescore", "betmgm", "novig",
    "fanatics", "caesars",
}

SOFT_BOOK_DISPLAY = {
    "fanduel":    "FanDuel",
    "draftkings": "DraftKings",
    "hardrockbet":"Hard Rock Bet",
    "fliff":      "Fliff",
    "bet365":     "Bet365",
    "ballybet":   "Bally Bet",
    "betrivers":  "BetRivers",
    "thescore":   "theScore Bet",
    "betmgm":     "BetMGM",
    "novig":      "Novig",
    "fanatics":   "Fanatics",
    "caesars":    "Caesars",
    "espnbet":    "ESPN Bet",
}

CACHE_DIR = Path("data/cache/odds")


def _to_prob(odds: float) -> float:
    if odds == 0:
        return 0.5
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _devig(p1: float, p2: float) -> tuple[float, float]:
    """Normalize two raw implied probs to sum to 1.0 (remove vig)."""
    total = p1 + p2
    if total <= 0:
        return 0.5, 0.5
    return p1 / total, p2 / total


def _odds_from_prob(prob: float) -> int:
    """Convert fair probability to American odds."""
    if prob <= 0 or prob >= 1:
        return 0
    if prob >= 0.5:
        return int(round(-prob / (1 - prob) * 100))
    return int(round((1 - prob) / prob * 100))


def find_ev_bets(
    sport: str = "baseball_mlb",
    min_ev_pct: float = 2.0,
    min_odds: int = -300,
    verbose: bool = True,
) -> list[dict]:
    """
    Scan all soft books for bets that beat Pinnacle's no-vig fair line.

    Returns list of +EV opportunities sorted by EV% descending.
    Each entry: {team, market, direction, odds, book, fair_prob, ev_pct, matchup}

    min_ev_pct: minimum edge vs fair price in percentage points (2.0 = 2%)
    min_odds:   skip bets with odds worse than this (-300 filters huge favorites)
    """
    cache = CACHE_DIR / f"{sport}_latest.json"
    if not cache.exists():
        if verbose:
            print(f"  [line shop] No odds cache for {sport}. Run chef.py picks first.")
        return []

    try:
        raw = json.load(open(cache))
    except (json.JSONDecodeError, ValueError):
        return []

    bets: list[dict] = []

    for game in raw:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        matchup = f"{away} @ {home}"
        commence = game.get("commence_time", "")

        # Step 1: find Pinnacle no-vig fair probabilities for each market
        pin_fair: dict[str, dict] = {}  # market_key -> {side: fair_prob}

        for book in game.get("bookmakers", []):
            if book.get("key") != "pinnacle":
                continue
            for market in book.get("markets", []):
                key = market.get("key")
                outcomes = market.get("outcomes", [])
                if len(outcomes) < 2:
                    continue

                if key == "h2h":
                    o1, o2 = outcomes[0], outcomes[1]
                    raw1, raw2 = _to_prob(o1["price"]), _to_prob(o2["price"])
                    f1, f2 = _devig(raw1, raw2)
                    pin_fair["h2h"] = {
                        o1["name"]: f1,
                        o2["name"]: f2,
                    }

                elif key == "spreads":
                    o1, o2 = outcomes[0], outcomes[1]
                    raw1, raw2 = _to_prob(o1["price"]), _to_prob(o2["price"])
                    f1, f2 = _devig(raw1, raw2)
                    pin_fair["spreads"] = {
                        (o1["name"], o1.get("point")): f1,
                        (o2["name"], o2.get("point")): f2,
                    }

                elif key == "totals":
                    over  = next((o for o in outcomes if o["name"] == "Over"),  None)
                    under = next((o for o in outcomes if o["name"] == "Under"), None)
                    if over and under:
                        ro, ru = _to_prob(over["price"]), _to_prob(under["price"])
                        fo, fu = _devig(ro, ru)
                        point = over.get("point")
                        pin_fair[f"totals_{point}"] = {"Over": fo, "Under": fu}

        if not pin_fair:
            continue

        # Step 2: scan every soft book for bets beating fair price
        for book in game.get("bookmakers", []):
            bkey = book.get("key", "")
            if bkey not in PREFERRED_BOOKS:
                continue
            book_name = SOFT_BOOK_DISPLAY.get(bkey, bkey)

            for market in book.get("markets", []):
                mkey = market.get("key")
                outcomes = market.get("outcomes", [])

                if mkey == "h2h" and "h2h" in pin_fair:
                    for o in outcomes:
                        name  = o["name"]
                        odds  = o["price"]
                        if odds < min_odds:
                            continue
                        fair = pin_fair["h2h"].get(name)
                        if fair is None:
                            continue
                        book_prob = _to_prob(odds)
                        ev = (fair - book_prob) * 100  # positive = we're getting better than fair
                        if ev >= min_ev_pct:
                            bets.append({
                                "matchup":    matchup,
                                "team":       name,
                                "market":     "moneyline",
                                "direction":  "HOME" if name == home else "AWAY",
                                "odds":       int(odds),
                                "fair_odds":  _odds_from_prob(fair),
                                "fair_prob":  round(fair, 4),
                                "book_prob":  round(book_prob, 4),
                                "ev_pct":     round(ev, 2),
                                "book":       book_name,
                                "commence":   commence,
                            })

                elif mkey == "spreads" and "spreads" in pin_fair:
                    for o in outcomes:
                        name  = o["name"]
                        point = o.get("point")
                        odds  = o["price"]
                        if odds < min_odds:
                            continue
                        fair = pin_fair["spreads"].get((name, point))
                        if fair is None:
                            continue
                        book_prob = _to_prob(odds)
                        ev = (fair - book_prob) * 100
                        if ev >= min_ev_pct:
                            bets.append({
                                "matchup":    matchup,
                                "team":       f"{name} {'+' if point > 0 else ''}{point}",
                                "market":     "spread",
                                "direction":  "COVER",
                                "line":       point,
                                "odds":       int(odds),
                                "fair_odds":  _odds_from_prob(fair),
                                "fair_prob":  round(fair, 4),
                                "book_prob":  round(book_prob, 4),
                                "ev_pct":     round(ev, 2),
                                "book":       book_name,
                                "commence":   commence,
                            })

                elif mkey == "totals":
                    for o in outcomes:
                        name  = o["name"]   # "Over" or "Under"
                        point = o.get("point")
                        odds  = o["price"]
                        if odds < min_odds:
                            continue
                        fair_key = f"totals_{point}"
                        if fair_key not in pin_fair:
                            continue
                        fair = pin_fair[fair_key].get(name)
                        if fair is None:
                            continue
                        book_prob = _to_prob(odds)
                        ev = (fair - book_prob) * 100
                        if ev >= min_ev_pct:
                            bets.append({
                                "matchup":    matchup,
                                "team":       f"{name} {point}",
                                "market":     "total",
                                "direction":  name.upper(),
                                "line":       point,
                                "odds":       int(odds),
                                "fair_odds":  _odds_from_prob(fair),
                                "fair_prob":  round(fair, 4),
                                "book_prob":  round(book_prob, 4),
                                "ev_pct":     round(ev, 2),
                                "book":       book_name,
                                "commence":   commence,
                            })

    # Deduplicate: keep highest EV per (team, market, book)
    seen: dict[tuple, float] = {}
    unique: list[dict] = []
    for b in bets:
        key = (b["team"], b["market"], b["book"])
        if b["ev_pct"] > seen.get(key, -99):
            seen[key] = b["ev_pct"]
            unique.append(b)

    unique.sort(key=lambda x: x["ev_pct"], reverse=True)

    if verbose and unique:
        W = 66
        print(f"\n  {'═'*W}")
        print(f"  LINE SHOP — BEATS PINNACLE FAIR LINE  (min +{min_ev_pct}% EV)")
        print(f"  {'─'*W}")
        print(f"  {'BET':<32} {'ODDS':>5}  {'FAIR':>5}  {'EV%':>5}  {'BOOK'}")
        print(f"  {'─'*W}")
        for b in unique:
            fair_str = f"{b['fair_odds']:+d}" if b['fair_odds'] else "—"
            print(
                f"  {b['team'][:32]:<32} {b['odds']:>+5}  {fair_str:>5}  "
                f"{b['ev_pct']:>+4.1f}%  {b['book']}"
            )
        print(f"  {'─'*W}")
        print(f"  {len(unique)} +EV bets vs Pinnacle fair line  |  sport={sport}")
        print(f"  {'═'*W}\n")

    elif verbose:
        print(f"  [line shop] No +EV bets found above {min_ev_pct}% for {sport}.")

    return unique
