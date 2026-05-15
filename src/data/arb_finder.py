"""
Arbitrage opportunity finder for MLB slate.

An arb exists when the best available odds across all books for BOTH sides
of a market sum to less than 100% implied probability. Result: guaranteed
profit regardless of outcome if you bet both sides optimally.

arb_pct = implied(best_side_A) + implied(best_side_B)
If arb_pct < 1.0  →  guaranteed profit margin = (1 - arb_pct) * 100%

Usage:
    from src.data.arb_finder import find_arbs, format_arb_table
    arbs = find_arbs()          # live, uses today's cached odds
    print(format_arb_table(arbs))
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

from src.data.odds_api import MY_BOOKS_PARAM, MY_BOOKS_TITLES

CACHE_DIR = Path("data/cache/odds")
API_BASE = "https://api.the-odds-api.com/v4"

# Use the same book set as all other pipelines — Anthony's accounts only.
TIER1_BOOKS = MY_BOOKS_TITLES
ALL_BOOKS   = MY_BOOKS_TITLES


def _api_key() -> str | None:
    return os.environ.get("ODDS_API_KEY")


def _load_or_fetch_odds(sport: str = "baseball_mlb", refresh: bool = False) -> list[dict]:
    cache = CACHE_DIR / f"{sport}_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache.exists() and not refresh:
        age = time.time() - cache.stat().st_mtime
        if age < 1800:  # 30-min cache
            with open(cache) as f:
                return json.load(f)

    key = _api_key()
    if not key:
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []

    try:
        resp = requests.get(
            f"{API_BASE}/sports/{sport}/odds",
            params={
                "apiKey": key,
                "regions": "us,us2",
                "markets": "h2h,totals,spreads",
                "oddsFormat": "american",
                "bookmakers": MY_BOOKS_PARAM,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        print(f"  [arb] API error: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


def _to_decimal(american: float) -> float:
    if american >= 0:
        return american / 100 + 1.0
    return 100.0 / abs(american) + 1.0


def _to_implied(american: float) -> float:
    return 1.0 / _to_decimal(american)


def _calc_stakes(bankroll: float, arb_pct: float, dec1: float, dec2: float) -> tuple[float, float, float]:
    """
    Optimal arb stakes for a given bankroll.
    Returns (stake1, stake2, guaranteed_profit).
    """
    s1 = bankroll * (1 / dec1) / arb_pct
    s2 = bankroll * (1 / dec2) / arb_pct
    profit = bankroll * (1 / arb_pct - 1)
    return round(s1, 2), round(s2, 2), round(profit, 2)


def find_arbs(
    sport: str = "baseball_mlb",
    refresh: bool = False,
    tier1_only: bool = False,
    min_margin_pct: float = 0.1,
) -> list[dict]:
    """
    Scan today's MLB slate for arbitrage opportunities.

    Args:
        sport:          Odds API sport key.
        refresh:        Force-refresh odds cache.
        tier1_only:     Only use DK/FD/BetMGM/BetRivers (no offshore books).
        min_margin_pct: Minimum arb margin to include (default 0.1% = filter noise).

    Returns:
        List of arb dicts sorted by margin descending.
    """
    data = _load_or_fetch_odds(sport, refresh)
    if not data:
        return []

    now_utc = datetime.now(timezone.utc)
    arbs: list[dict] = []

    for event in data:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        commence = event.get("commence_time", "")
        game_id = event.get("id", "")

        # Skip games that have already started
        if commence:
            try:
                ct = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                if ct <= now_utc:
                    continue
            except ValueError:
                pass

        # Gather best odds per outcome per market across all books
        # Structure: market_key -> outcome_key -> {odds, book, point}
        best: dict[str, dict[str, dict]] = {}

        for bookmaker in event.get("bookmakers", []):
            book = bookmaker.get("title", "")
            if tier1_only and book not in TIER1_BOOKS:
                continue

            for market in bookmaker.get("markets", []):
                mkey = market.get("key", "")
                if mkey not in best:
                    best[mkey] = {}

                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    price = float(outcome.get("price", 0))
                    point = outcome.get("point")

                    # For totals use "Over" / "Under" as key
                    okey = name

                    if okey not in best[mkey] or price > best[mkey][okey]["odds"]:
                        best[mkey][okey] = {
                            "odds": price,
                            "book": book,
                            "point": point,
                            "is_tier1": book in TIER1_BOOKS,
                        }

        # Check each market for arbs
        for mkey, outcomes in best.items():
            keys = list(outcomes.keys())

            if mkey in ("h2h", "spreads") and len(keys) >= 2:
                # Moneyline / spread: 2-way market (home vs away)
                d1 = outcomes[keys[0]]
                d2 = outcomes[keys[1]]
                arb_pct = _to_implied(d1["odds"]) + _to_implied(d2["odds"])
                margin = (1 - arb_pct) * 100

                if margin >= min_margin_pct:
                    both_tier1 = d1["is_tier1"] and d2["is_tier1"]
                    arbs.append({
                        "game": f"{away} @ {home}",
                        "game_id": game_id,
                        "commence_time": commence,
                        "market": "moneyline" if mkey == "h2h" else "runline",
                        "side1": keys[0],
                        "odds1": d1["odds"],
                        "book1": d1["book"],
                        "side2": keys[1],
                        "odds2": d2["odds"],
                        "book2": d2["book"],
                        "arb_pct": round(arb_pct, 5),
                        "margin_pct": round(margin, 3),
                        "both_tier1": both_tier1,
                        "point": d1.get("point"),
                    })

            elif mkey == "totals" and "Over" in outcomes and "Under" in outcomes:
                d_over = outcomes["Over"]
                d_under = outcomes["Under"]
                arb_pct = _to_implied(d_over["odds"]) + _to_implied(d_under["odds"])
                margin = (1 - arb_pct) * 100

                if margin >= min_margin_pct:
                    both_tier1 = d_over["is_tier1"] and d_under["is_tier1"]
                    arbs.append({
                        "game": f"{away} @ {home}",
                        "game_id": game_id,
                        "commence_time": commence,
                        "market": "total",
                        "side1": f"OVER {d_over['point']}",
                        "odds1": d_over["odds"],
                        "book1": d_over["book"],
                        "side2": f"UNDER {d_under['point']}",
                        "odds2": d_under["odds"],
                        "book2": d_under["book"],
                        "arb_pct": round(arb_pct, 5),
                        "margin_pct": round(margin, 3),
                        "both_tier1": both_tier1,
                        "point": d_over.get("point"),
                    })

    arbs.sort(key=lambda x: x["margin_pct"], reverse=True)
    return arbs


def add_stakes(arbs: list[dict], bankroll: float) -> list[dict]:
    """Attach optimal stake sizes for a given bankroll to each arb."""
    for a in arbs:
        s1, s2, profit = _calc_stakes(
            bankroll,
            a["arb_pct"],
            _to_decimal(a["odds1"]),
            _to_decimal(a["odds2"]),
        )
        a["stake1"] = s1
        a["stake2"] = s2
        a["guaranteed_profit"] = profit
        a["roi_pct"] = round(profit / bankroll * 100, 3)
    return arbs


def format_arb_table(arbs: list[dict], bankroll: float = 1000.0) -> str:
    """Pretty terminal table of arb opportunities."""
    if not arbs:
        return "  No arb opportunities found on today's slate."

    arbs = add_stakes(arbs, bankroll)

    header = (
        f"\n{'ARB OPPORTUNITIES — MLB':^80}\n"
        f"{'Bankroll: $' + f'{bankroll:,.0f}':^80}\n"
        f"{'─' * 80}\n"
        f"{'GAME':<28}{'MARKET':<10}{'MARGIN':>7}  {'SIDE A':>20}  {'SIDE B':>20}\n"
        f"{'─' * 80}"
    )
    rows = [header]

    for a in arbs:
        game = a["game"][:27]
        mkt = a["market"][:9]
        margin = f"{a['margin_pct']:.2f}%"
        s1 = f"{a['side1']} {int(a['odds1']):+d} {a['book1']}"[-20:]
        s2 = f"{a['side2']} {int(a['odds2']):+d} {a['book2']}"[-20:]
        t1_flag = "" if a["both_tier1"] else " ⚠ offshore"
        rows.append(
            f"{game:<28}{mkt:<10}{margin:>7}  {s1:>20}  {s2:>20}{t1_flag}"
        )
        rows.append(
            f"  → Bet ${a['stake1']:.2f} on {a['side1']} | "
            f"${a['stake2']:.2f} on {a['side2']} | "
            f"Profit: +${a['guaranteed_profit']:.2f} guaranteed"
        )
        rows.append("")

    rows.append(
        f"Total arbs found: {len(arbs)}  |  "
        f"Tier-1 only: {sum(1 for a in arbs if a['both_tier1'])}  |  "
        f"Needs offshore: {sum(1 for a in arbs if not a['both_tier1'])}"
    )
    return "\n".join(rows)
