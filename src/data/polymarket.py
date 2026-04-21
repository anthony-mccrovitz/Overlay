"""
Polymarket prediction market client.

Polymarket is a crypto-based decentralized prediction market. Markets are binary
YES/NO contracts where prices represent probabilities (0.0–1.0). No auth required
for reading public market data.

APIs:
  Gamma API:  https://gamma-api.polymarket.com  (market listings + metadata)
  CLOB API:   https://clob.polymarket.com        (live orderbook prices)

Fees: Polymarket charges ~2% on winnings (taken from LPs, effectively reduces
payout slightly). Use effective_cost properties for arb math.

Docs: https://docs.polymarket.com
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
CACHE_DIR = Path("data/cache/polymarket")

# Polymarket LP fees (~2% of winnings effectively)
FEE_RATE = 0.02

# Tag normalization to our internal categories
TAG_MAP = {
    "sports": "sports",
    "baseball": "sports",
    "basketball": "sports",
    "football": "sports",
    "soccer": "sports",
    "nfl": "sports",
    "mlb": "sports",
    "nba": "sports",
    "politics": "politics",
    "elections": "politics",
    "us-politics": "politics",
    "economics": "economics",
    "crypto": "crypto",
    "bitcoin": "crypto",
    "ethereum": "crypto",
    "entertainment": "entertainment",
    "movies": "entertainment",
    "awards": "entertainment",
}


@dataclass
class PolyMarket:
    market_id: str
    question: str
    category: str
    yes_prob: float          # 0–1
    no_prob: float           # 0–1
    volume_usd: float
    liquidity_usd: float
    end_date: str | None
    active: bool
    url: str
    token_ids: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def effective_yes_cost(self) -> float:
        """YES cost after fee (buy YES at this price to break even)."""
        return self.yes_prob + FEE_RATE * (1 - self.yes_prob)

    @property
    def effective_no_cost(self) -> float:
        """NO cost after fee."""
        return self.no_prob + FEE_RATE * (1 - self.no_prob)


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.json"


def _get(url: str, params: dict | None = None, timeout: int = 20) -> Any:
    # Explicitly request gzip to avoid brotli encoding issues with some requests versions
    headers = {"Accept-Encoding": "gzip, deflate"}
    resp = requests.get(url, params=params or {}, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_markets(
    tag: str | None = None,
    limit: int = 100,
    refresh: bool = False,
    min_volume: float = 1000.0,
) -> list[PolyMarket]:
    """
    Fetch active Polymarket markets.

    Args:
        tag:         Filter by tag (e.g. "sports", "politics", "crypto"). None = all.
        limit:       Max markets to fetch.
        refresh:     Ignore cache.
        min_volume:  Minimum USD volume to include (filters dust markets).

    Returns:
        List of PolyMarket objects sorted by volume descending.
    """
    cache_key = f"markets_{tag or 'all'}_{limit}"
    cache = _cache_path(cache_key)

    if cache.exists() and not refresh:
        age = time.time() - cache.stat().st_mtime
        if age < 900:
            with open(cache) as f:
                raw = json.load(f)
            markets = [_parse_market(m) for m in raw]
            return [m for m in markets if m.volume_usd >= min_volume and 0.01 < m.yes_prob < 0.99]

    params: dict = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "volume",
        "ascending": "false",
    }
    if tag:
        params["tag"] = tag

    try:
        data = _get(f"{GAMMA_BASE}/markets", params=params)

        # Gamma API returns list directly or wrapped in "markets" key
        if isinstance(data, list):
            raw_markets = data
        else:
            raw_markets = data.get("markets", data) if isinstance(data, dict) else []

        with open(cache, "w") as f:
            json.dump(raw_markets, f)

        markets = [_parse_market(m) for m in raw_markets]
        # Filter: min volume + exclude already-resolved (prob at 0 or 1)
        result = [
            m for m in markets
            if m.volume_usd >= min_volume and 0.01 < m.yes_prob < 0.99
        ]
        print(f"  [polymarket] Fetched {len(result)} active markets (tag={tag or 'all'}, min_vol=${min_volume:,.0f})")
        return result

    except Exception as e:
        print(f"  [polymarket] Fetch error: {e}")
        if cache.exists():
            with open(cache) as f:
                markets = [_parse_market(m) for m in json.load(f)]
                return [m for m in markets if m.volume_usd >= min_volume]
        return []


def _parse_market(m: dict) -> PolyMarket:
    """Normalize raw Gamma API market dict into PolyMarket."""
    mid = m.get("id", m.get("conditionId", ""))
    question = m.get("question", m.get("title", ""))
    slug = m.get("slug", "")

    # Best price: use live bid/ask mid first, fall back to lastTradePrice, then outcomePrices
    bid = m.get("bestBid")
    ask = m.get("bestAsk")
    last = m.get("lastTradePrice")

    if bid is not None and ask is not None:
        try:
            yes_prob = (float(bid) + float(ask)) / 2
        except (TypeError, ValueError):
            yes_prob = 0.5
    elif last is not None:
        try:
            yes_prob = float(last)
        except (TypeError, ValueError):
            yes_prob = 0.5
    else:
        # Parse outcome prices — stored as JSON string "["0.62","0.38"]"
        outcome_prices_raw = m.get("outcomePrices", "[]")
        outcomes_raw = m.get("outcomes", "[]")
        try:
            prices = json.loads(outcome_prices_raw) if isinstance(outcome_prices_raw, str) else outcome_prices_raw
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        except (json.JSONDecodeError, TypeError):
            prices, outcomes = [], []

        yes_prob = 0.5
        if prices and outcomes:
            for i, outcome in enumerate(outcomes):
                if str(outcome).lower() in ("yes", "true", "1"):
                    try:
                        yes_prob = float(prices[i])
                    except (ValueError, IndexError):
                        pass
                    break
            else:
                try:
                    yes_prob = float(prices[0]) if prices else 0.5
                except (ValueError, IndexError):
                    pass

    no_prob = 1.0 - yes_prob

    # Category from events[0] slug/ticker (keywords), falling back to question text
    category = "other"
    events = m.get("events") or []
    searchable = " ".join([
        (events[0].get("slug", "") + " " + events[0].get("ticker", "")) if events else "",
        question,
        slug,
    ]).lower()

    # Keyword-based category detection
    sports_kws = ["nba", "mlb", "nfl", "nhl", "soccer", "tennis", "golf", "esport",
                  "wimbledon", "world cup", "premier league", "la liga", "bundesliga",
                  "champions league", "super bowl", "playoff", "match winner",
                  "knockout", "tournament winner", "championship", "relegated",
                  "lpl", "lck", "league of legends", "valorant", "csgo", "dota"]
    politics_kws = ["election", "president", "senate", "congress", "prime minister",
                    "vote", "governor", "republican", "democrat", "parliament", "midterm",
                    "administration", "minister", "tariff", "sanction", "nominee",
                    "presidential", "political party", "balance of power"]
    economics_kws = ["federal reserve", "fed rate", "cpi", "inflation", "gdp", "recession",
                     "interest rate", "s&p", "nasdaq", "dow", "stock market", "unemployment"]
    crypto_kws = ["bitcoin", "ethereum", "crypto", "btc", "eth", "solana", "token", "defi",
                  "nft", "blockchain", "coinbase", "binance"]

    for kw in sports_kws:
        if kw in searchable:
            category = "sports"
            break
    if category == "other":
        for kw in politics_kws:
            if kw in searchable:
                category = "politics"
                break
    if category == "other":
        for kw in economics_kws:
            if kw in searchable:
                category = "economics"
                break
    if category == "other":
        for kw in crypto_kws:
            if kw in searchable:
                category = "crypto"
                break

    # CLOB token IDs
    clob_ids = m.get("clobTokenIds", "[]")
    try:
        token_ids = json.loads(clob_ids) if isinstance(clob_ids, str) else (clob_ids or [])
    except (json.JSONDecodeError, TypeError):
        token_ids = []

    volume = float(m.get("volume", m.get("volumeNum", 0)) or 0)
    liquidity = float(m.get("liquidity", m.get("liquidityNum", 0)) or 0)

    event_slug = events[0].get("slug", "") if events else ""
    url = f"https://polymarket.com/event/{event_slug}" if event_slug else f"https://polymarket.com/event/{slug}"

    return PolyMarket(
        market_id=mid,
        question=question,
        category=category,
        yes_prob=round(min(max(yes_prob, 0.0), 1.0), 4),
        no_prob=round(min(max(no_prob, 0.0), 1.0), 4),
        volume_usd=volume,
        liquidity_usd=liquidity,
        end_date=m.get("endDate"),
        active=m.get("active", True),
        url=url,
        token_ids=token_ids,
        raw=m,
    )


def fetch_live_price(token_id: str) -> float | None:
    """
    Fetch live mid-price from the CLOB orderbook for a specific token.
    More up-to-date than the Gamma API cache, costs an extra request.

    Returns probability float or None on error.
    """
    try:
        data = _get(f"{CLOB_BASE}/midpoint", params={"token_id": token_id})
        mid = data.get("mid")
        return float(mid) if mid is not None else None
    except Exception:
        return None


def fetch_sports_markets(refresh: bool = False) -> list[PolyMarket]:
    """Fetch sports prediction markets."""
    return fetch_markets(tag="sports", refresh=refresh)


def fetch_politics_markets(refresh: bool = False) -> list[PolyMarket]:
    """Fetch political prediction markets."""
    return fetch_markets(tag="politics", refresh=refresh)


def fetch_crypto_markets(refresh: bool = False) -> list[PolyMarket]:
    """Fetch crypto prediction markets."""
    return fetch_markets(tag="crypto", refresh=refresh)


def fetch_all_markets(refresh: bool = False, min_volume: float = 5000.0) -> list[PolyMarket]:
    """Fetch all active markets with meaningful liquidity."""
    return fetch_markets(tag=None, limit=200, refresh=refresh, min_volume=min_volume)
