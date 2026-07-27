"""
Kalshi prediction market client.

Kalshi is a CFTC-regulated event contract exchange. Markets are binary YES/NO
contracts priced in cents (0–99). A YES at 62 cents means ~62% implied probability.

Auth: Kalshi requires an account. Set KALSHI_EMAIL + KALSHI_PASSWORD in .env,
OR set KALSHI_API_KEY (if you have a direct API key). The client will auto-login
and cache the token for the session.

Docs: https://trading-api.kalshi.com/trade-api/v2
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"  # no auth needed
CACHE_DIR = Path("data/cache/kalshi")

# UNVERIFIED — do not price a real entry off this without checking Kalshi's
# current schedule first.
#
# Its twin in polymarket.py was an identically-worded, identically-uncited
# "~2%" that turned out to be wrong in BOTH directions once the live schedule
# was read off the API (2026-07-20): the real fee is curved, peaking at a
# coin flip and vanishing at the extremes, and it is charged to takers only.
# A flat rate cannot express that shape, and Kalshi's published fee is also a
# curve (~0.07 * p * (1-p) per contract), so this constant is very likely
# wrong in the same way.
#
# Left as-is rather than swapped for a second guess, because guessing is what
# caused the original bug. Only src/data/prediction_arb.py reads it, and that
# module is reachable only from archive/experimental — nothing in the daily
# pipeline or chef.py touches it. Fix it against live data before reviving
# any Kalshi work.
FEE_RATE = 0.02

# Category mapping to our internal labels
CATEGORY_MAP = {
    "Sports": "sports",
    "Politics": "politics",
    "Economics": "economics",
    "Financials": "economics",
    "Crypto": "crypto",
    "Climate": "other",
    "Entertainment": "entertainment",
    "Science": "other",
}

_session_token: str | None = None


@dataclass
class KalshiMarket:
    ticker: str
    title: str
    category: str
    yes_prob: float          # 0–1, mid of bid/ask
    no_prob: float           # 0–1
    yes_bid: float           # 0–1
    yes_ask: float           # 0–1
    volume: int              # total contracts traded
    volume_24h: int
    close_time: str | None
    status: str
    url: str
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def effective_yes_cost(self) -> float:
        """YES cost after fee on potential winnings."""
        return self.yes_ask + FEE_RATE * (1 - self.yes_ask)

    @property
    def effective_no_cost(self) -> float:
        """NO cost after fee on potential winnings."""
        no_ask = 1 - self.yes_bid  # best NO = worst YES bid
        return no_ask + FEE_RATE * (1 - no_ask)


def _get_token() -> str | None:
    """Return cached session token or login to get one."""
    global _session_token
    if _session_token:
        return _session_token

    # API key is preferred — get from kalshi.com/profile/api
    api_key = os.environ.get("KALSHI_API_KEY", "").strip()
    if api_key:
        _session_token = api_key
        return api_key

    email = os.environ.get("KALSHI_EMAIL", "")
    password = os.environ.get("KALSHI_PASSWORD", "")
    if not email or not password:
        return None

    # Kalshi has migrated their API. Try both old and new base URLs.
    login_attempts = [
        (API_BASE, "/log_in"),
        (API_BASE, "/login"),
        ("https://trading-api.kalshi.com/trade-api/v2", "/log_in"),
    ]
    for base, path in login_attempts:
        try:
            resp = requests.post(
                f"{base}{path}",
                json={"email": email, "password": password},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                token = (
                    data.get("token")
                    or data.get("access_token")
                    or (data.get("member_session") or {}).get("token")
                )
                if token:
                    _session_token = token
                    return _session_token
        except Exception:
            continue

    print(
        "  [kalshi] Login failed. Email/password auth may no longer work.\n"
        "    Fix: Go to https://kalshi.com/profile/api → generate API key\n"
        "    Then set KALSHI_API_KEY=<your_key> in .env"
    )
    return None


def _headers() -> dict:
    token = _get_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def fetch_markets(
    category: str | None = None,
    limit: int = 200,
    refresh: bool = False,
    use_demo: bool = False,
) -> list[KalshiMarket]:
    """
    Fetch open Kalshi markets.

    Args:
        category:   Filter by category string (e.g. "Sports", "Politics"). None = all.
        limit:      Max markets to return (Kalshi paginates at 200).
        refresh:    Ignore cache.
        use_demo:   Use public demo API (no auth, limited data).

    Returns:
        List of KalshiMarket objects.
    """
    cache_key = f"markets_{category or 'all'}_{limit}"
    cache = _cache_path(cache_key)

    if cache.exists() and not refresh:
        age = time.time() - cache.stat().st_mtime
        if age < 900:  # 15-min cache
            with open(cache) as f:
                raw = json.load(f)
            return [_parse_market(m) for m in raw]

    base = DEMO_BASE if use_demo else API_BASE
    params: dict = {"status": "open", "limit": limit}
    if category:
        params["category"] = category

    try:
        resp = requests.get(
            f"{base}/markets",
            headers=_headers(),
            params=params,
            timeout=20,
        )
        if resp.status_code == 401:
            print("  [kalshi] Auth required — set KALSHI_EMAIL + KALSHI_PASSWORD in .env")
            return []
        resp.raise_for_status()
        data = resp.json()
        markets_raw = data.get("markets", [])

        with open(cache, "w") as f:
            json.dump(markets_raw, f)

        # Filter markets with actual prices (null prices = no active trading or auth required)
        parsed = [_parse_market(m) for m in markets_raw]
        priced = [m for m in parsed if m.yes_prob != 0.5 or m.yes_bid > 0]
        print(f"  [kalshi] Fetched {len(markets_raw)} markets, {len(priced)} with prices (category={category or 'all'})")
        return priced

    except Exception as e:
        print(f"  [kalshi] Fetch error: {e}")
        if cache.exists():
            with open(cache) as f:
                return [_parse_market(m) for m in json.load(f)]
        return []


def fetch_market(ticker: str, refresh: bool = False) -> KalshiMarket | None:
    """Fetch a single market by ticker, enriching with orderbook price."""
    cache = _cache_path(f"market_{ticker}")
    if cache.exists() and not refresh:
        age = time.time() - cache.stat().st_mtime
        if age < 300:
            with open(cache) as f:
                return _parse_market(json.load(f))

    try:
        resp = requests.get(
            f"{API_BASE}/markets/{ticker}",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("market", resp.json())
        # Enrich with orderbook price if the market listing has no prices
        if data.get("yes_bid") is None:
            ob_price = _fetch_orderbook_mid(ticker)
            if ob_price is not None:
                data["_ob_yes_prob"] = ob_price
        with open(cache, "w") as f:
            json.dump(data, f)
        return _parse_market(data)
    except Exception as e:
        print(f"  [kalshi] Error fetching {ticker}: {e}")
        return None


def _fetch_orderbook_mid(ticker: str) -> float | None:
    """
    Fetch best-bid mid-price from orderbook endpoint.

    Kalshi orderbooks return bid arrays sorted ascending (worst → best).
    Best YES bid = last entry of yes_dollars.
    Best NO bid  = last entry of no_dollars.
    Mid ≈ avg of (best YES bid, 1 - best NO bid).
    """
    try:
        resp = requests.get(
            f"{API_BASE}/markets/{ticker}/orderbook",
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        ob = resp.json().get("orderbook_fp", resp.json())
        yes_bids = ob.get("yes_dollars", [])
        no_bids = ob.get("no_dollars", [])

        best_yes = float(yes_bids[-1][0]) if yes_bids else None
        best_no = float(no_bids[-1][0]) if no_bids else None

        if best_yes is not None and best_no is not None:
            # Mid of bid-implied probabilities
            return round((best_yes + (1.0 - best_no)) / 2, 4)
        elif best_yes is not None:
            return round(best_yes, 4)
        elif best_no is not None:
            return round(1.0 - best_no, 4)
        return None
    except Exception:
        return None


def _parse_market(m: dict) -> KalshiMarket:
    """Normalize a raw Kalshi market dict into KalshiMarket."""
    ticker = m.get("ticker", "")

    # Prices come in cents (0–99); convert to probability (0–1)
    yes_bid = m.get("yes_bid", 0) / 100
    yes_ask = m.get("yes_ask", 0) / 100
    last = m.get("last_price", 0) / 100

    # Mid-price as best estimate when bid/ask available
    if yes_bid > 0 and yes_ask > 0:
        yes_mid = (yes_bid + yes_ask) / 2
    elif last > 0:
        yes_mid = last
    elif m.get("_ob_yes_prob") is not None:
        yes_mid = float(m["_ob_yes_prob"])
    else:
        yes_mid = 0.5

    no_mid = 1 - yes_mid

    raw_cat = m.get("category", "other")
    category = CATEGORY_MAP.get(raw_cat, raw_cat.lower())

    return KalshiMarket(
        ticker=ticker,
        title=m.get("title", m.get("subtitle", ticker)),
        category=category,
        yes_prob=round(yes_mid, 4),
        no_prob=round(no_mid, 4),
        yes_bid=round(yes_bid, 4),
        yes_ask=round(yes_ask, 4),
        volume=m.get("volume", 0),
        volume_24h=m.get("volume_24h", 0),
        close_time=m.get("close_time"),
        status=m.get("status", "open"),
        url=f"https://kalshi.com/markets/{ticker}",
        raw=m,
    )


def fetch_sports_markets(refresh: bool = False) -> list[KalshiMarket]:
    return fetch_markets(category="Sports", refresh=refresh)


def fetch_politics_markets(refresh: bool = False) -> list[KalshiMarket]:
    return fetch_markets(category="Politics", refresh=refresh)


def fetch_economics_markets(refresh: bool = False) -> list[KalshiMarket]:
    return fetch_markets(category="Economics", refresh=refresh) + \
           fetch_markets(category="Financials", refresh=refresh)


def fetch_all_markets(refresh: bool = False) -> list[KalshiMarket]:
    return fetch_markets(category=None, refresh=refresh)
