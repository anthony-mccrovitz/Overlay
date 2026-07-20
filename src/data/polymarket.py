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

# Polymarket "sports_fees_v2", read live off Gamma market dicts on 2026-07-20
# and identical across every game moneyline checked:
#     {"rate": 0.05, "exponent": 1, "takerOnly": true, "rebateRate": 0.15}
#
#     fee_per_share = rate * min(p, 1 - p) ** exponent
#
# Two properties matter more than the number itself:
#   1. The fee peaks at p=0.50 and vanishes at the extremes, so it is NOT the
#      flat 2% this module asserted before (uncited, and wrong in both
#      directions — it understated the cost of a coin-flip market by ~2x and
#      overstated it on heavy favourites).
#   2. takerOnly: a RESTING order pays nothing. That single flag is why maker
#      entries can be +EV on boards where every taker entry is negative.
DEFAULT_FEE_SCHEDULE = {"rate": 0.05, "exponent": 1.0, "takerOnly": True}

# Smallest price increment on the CLOB; a maker order must move by at least
# this much to improve the book.
TICK = 0.01


def taker_fee(price: float, schedule: dict | None = None) -> float:
    """Fee per share paid by a TAKER entering at `price`.

    Pass the market's own `feeSchedule` when available — Polymarket varies it
    by market type, and hardcoding one number is what caused the original bug.
    """
    s = schedule or DEFAULT_FEE_SCHEDULE
    rate = float(s.get("rate", DEFAULT_FEE_SCHEDULE["rate"]))
    exponent = float(s.get("exponent", DEFAULT_FEE_SCHEDULE["exponent"]))
    p = min(max(float(price), 0.0), 1.0)
    return rate * (min(p, 1.0 - p) ** exponent)


def maker_fee(price: float, schedule: dict | None = None) -> float:
    """Fee per share paid by a MAKER whose resting order gets filled.

    Zero while the schedule is takerOnly. Kept as a function rather than a
    literal 0 so a future schedule change is one edit, not an audit.
    """
    s = schedule or DEFAULT_FEE_SCHEDULE
    if s.get("takerOnly", True):
        return 0.0
    return taker_fee(price, s)


def walk_book(levels: list[tuple[float, float]], stake_usd: float,
              schedule: dict | None = None) -> dict:
    """Fill `stake_usd` against ascending ask levels; return the real blended cost.

    Top-of-book is a headline, not a size. On 2026-07-20 a WNBA market Gamma
    reported at $45,052 "liquidity" had 27 shares at its best ask — the quoted
    +5.4% edge was $4.86 deep, and the next level was 0.0% EV. Pricing any
    stake at the best ask silently assumes infinite depth there.

    Returns avg_cost (all-in per share, fee included per level), shares,
    spent (notional ex-fee) and filled (False when the book runs dry).
    """
    remaining = float(stake_usd)
    shares = 0.0
    total = 0.0          # all-in outlay, fee included
    spent = 0.0          # notional only
    for price, size in sorted(levels):
        if remaining <= 1e-9:
            break
        price = float(price)
        if price <= 0:
            continue
        want = remaining / price
        take = min(want, float(size))
        if take <= 0:
            continue
        shares += take
        spent += take * price
        total += take * (price + taker_fee(price, schedule))
        remaining -= take * price
    if shares <= 0:
        return {"avg_cost": None, "shares": 0.0, "spent": 0.0, "filled": False}
    return {"avg_cost": total / shares, "shares": shares, "spent": spent,
            "filled": remaining <= 1e-6}


def max_stake_at_ev(levels: list[tuple[float, float]], fair: float,
                    min_ev_pct: float, schedule: dict | None = None) -> float:
    """Largest notional deployable while blended EV stays at/above min_ev_pct.

    Answers "how much is this edge actually worth?" — the number that decides
    whether a signal is a position or a rounding error.
    """
    shares = 0.0
    total = 0.0
    spent = 0.0
    best = 0.0
    for price, size in sorted(levels):
        price, size = float(price), float(size)
        if price <= 0 or size <= 0:
            continue
        shares += size
        spent += size * price
        total += size * (price + taker_fee(price, schedule))
        ev = (fair / (total / shares) - 1.0) * 100.0
        if ev >= min_ev_pct:
            best = spent          # whole level clears the bar
        else:
            break                 # levels only get worse
    return round(best, 2)


def maker_limit(bid: float | None, ask: float | None, tick: float = TICK) -> float | None:
    """Price a passive buy order should rest at.

    Improve the bid by one tick to take price priority, unless that would
    cross or join the ask — in which case the spread is already one tick wide
    and there is nothing to gain by posting, so sit on the bid.
    """
    if bid is None:
        return None
    if ask is not None and bid + tick >= ask:
        return float(bid)
    return round(float(bid) + tick, 4)

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
    yes_prob: float          # 0–1 (bid/ask mid)
    no_prob: float           # 0–1
    volume_usd: float
    liquidity_usd: float
    end_date: str | None
    active: bool
    url: str
    token_ids: list[str] = field(default_factory=list)
    best_bid: float | None = None   # YES-side best bid (Gamma snapshot)
    best_ask: float | None = None   # YES-side best ask (Gamma snapshot)
    game_start_time: str | None = None   # sports markets: actual first pitch/tip
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def fee_schedule(self) -> dict:
        """This market's own fee schedule, falling back to the observed default."""
        fs = self.raw.get("feeSchedule")
        if isinstance(fs, str):
            try:
                fs = json.loads(fs)
            except (ValueError, TypeError):
                fs = None
        if isinstance(fs, dict) and fs:
            return fs
        return DEFAULT_FEE_SCHEDULE

    @property
    def effective_yes_cost(self) -> float:
        """YES cost at the mid, after taker fee. Diagnostic only — never price
        an entry off the mid; see entry_cost."""
        return self.yes_prob + taker_fee(self.yes_prob, self.fee_schedule)

    @property
    def effective_no_cost(self) -> float:
        """NO cost at the mid, after taker fee. Diagnostic only."""
        return self.no_prob + taker_fee(self.no_prob, self.fee_schedule)

    def _book_prices(self, book: dict | None) -> tuple[float | None, float | None]:
        b = (book or {}).get("best_bid", self.best_bid)
        a = (book or {}).get("best_ask", self.best_ask)
        return b, a

    def entry_cost(self, side: str = "yes", book: dict | None = None,
                   mode: str = "take") -> float:
        """All-in cost per share to ENTER, by execution style.

        mode="take" crosses the spread: you pay the ASK plus the taker fee.
        Never the midpoint — an edge model priced off the mid overstates EV by
        half the spread, which on thin sports books exceeds the edge itself.

        mode="make" rests an order one tick inside the bid and pays NO fee
        (the schedule is takerOnly). This is the cheaper entry by roughly a
        full spread plus the fee, but it only fills when the market comes to
        you, so the cost it reports is conditional on being filled at all.
        Fill rate and adverse selection are measured separately by
        scripts/polymarket_fills.py — do not read a maker cost as achievable
        on its own.

        side="yes" buys the YES token; side="no" buys NO, whose ask is
        1 − YES best bid (selling pressure on YES is buying pressure on NO).
        """
        if side not in ("yes", "no"):
            raise ValueError(f"side must be 'yes' or 'no', got {side!r}")
        if mode not in ("take", "make"):
            raise ValueError(f"mode must be 'take' or 'make', got {mode!r}")
        bid, ask = self._book_prices(book)
        sched = self.fee_schedule

        if mode == "make":
            # Buying NO passively means resting on the NO book, whose bid is
            # 1 − (YES ask). Mirror the whole book, then post inside it.
            if side == "yes":
                limit = maker_limit(bid, ask)
            else:
                limit = maker_limit(None if ask is None else 1.0 - ask,
                                    None if bid is None else 1.0 - bid)
            if limit is None:                     # no book — fall back to taking
                return self.entry_cost(side, book, mode="take")
            limit = min(max(float(limit), 0.0), 1.0)
            return limit + maker_fee(limit, sched)

        if side == "yes":
            px = ask if ask is not None else self.yes_prob
        else:
            px = (1.0 - bid) if bid is not None else self.no_prob
        px = min(max(float(px), 0.0), 1.0)
        return px + taker_fee(px, sched)


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

    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

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
        best_bid=_f(bid),
        best_ask=_f(ask),
        game_start_time=m.get("gameStartTime"),
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


def fetch_order_book(token_id: str, refresh: bool = False) -> dict | None:
    """
    Fetch the live CLOB order book for a token, or None.

    Returns {"best_bid", "best_ask", "bids": [(price, size)], "asks": [...]}.
    The LEVELS are the point: best_ask alone says nothing about how much size
    sits there, and a headline edge that is 27 shares deep is not a position.
    Cached 300s — sports books move, but the scanner does not need tick-level
    freshness.
    """
    cache = _cache_path(f"book_{token_id[:32]}")
    if cache.exists() and not refresh:
        if time.time() - cache.stat().st_mtime < 300:
            try:
                with open(cache) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
    try:
        data = _get(f"{CLOB_BASE}/book", params={"token_id": token_id})
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        # CLOB returns price levels as {"price": "0.42", "size": "..."};
        # best bid = highest bid, best ask = lowest ask.
        def _levels(rows):
            out = []
            for r in rows:
                try:
                    out.append((float(r["price"]), float(r.get("size") or 0)))
                except (KeyError, TypeError, ValueError):
                    continue
            return out

        bid_lv, ask_lv = _levels(bids), _levels(asks)
        best_bid = max((p for p, _ in bid_lv), default=None)
        best_ask = min((p for p, _ in ask_lv), default=None)
        book = {"best_bid": best_bid, "best_ask": best_ask,
                "bids": sorted(bid_lv, reverse=True), "asks": sorted(ask_lv)}
        with open(cache, "w") as f:
            json.dump(book, f)
        return book
    except Exception:
        return None


def fetch_price_history(token_id: str, interval: str = "1w",
                        fidelity: int = 10, refresh: bool = False) -> list[dict]:
    """Timestamped price series for a token → [{"t": epoch, "p": price}, ...].

    Used to replay whether a resting order would have filled: if the series
    traded down to a buy limit after it was posted, a passive order at that
    price could have been hit.

    This is the market's price track, NOT a record of your own queue position,
    so "price touched the limit" is an OPTIMISTIC proxy for a fill — real
    orders sit behind whatever size is already resting there. Treat the fill
    rate it produces as an upper bound.

    Cached 1h: history for a past game does not change.
    """
    cache = _cache_path(f"hist_{token_id[:32]}_{interval}")
    if cache.exists() and not refresh:
        if time.time() - cache.stat().st_mtime < 3600:
            try:
                with open(cache) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
    try:
        data = _get(f"{CLOB_BASE}/prices-history",
                    params={"market": token_id, "interval": interval,
                            "fidelity": fidelity})
        hist = [{"t": int(x["t"]), "p": float(x["p"])}
                for x in (data.get("history") or [])
                if x.get("t") is not None and x.get("p") is not None]
        with open(cache, "w") as f:
            json.dump(hist, f)
        return hist
    except Exception:
        return []


def fetch_game_events(
    tag_slug: str,
    end_min: str,
    end_max: str,
    refresh: bool = False,
) -> list[PolyMarket]:
    """
    Fetch GAME markets for a sport via /events?tag_slug=… with an end-date
    window, flattening each event's markets.

    Why not fetch_markets(tag=…): the Gamma /markets `tag` param is silently
    IGNORED (verified 2026-07-19 — identical top-volume results for
    tag=mlb/ufc/tennis, including weather and earnings markets), so
    fetch_sports_markets never actually filtered. /events?tag_slug=… does
    filter, and the end-date window keeps game markets while dropping both
    season futures (end too far) and Polymarket's stale never-closed events
    (end in the past).

    end_min/end_max: ISO datetimes, e.g. "2026-07-19T00:00:00Z".
    """
    cache_key = f"events_{tag_slug}_{end_min[:10]}"
    cache = _cache_path(cache_key)
    if cache.exists() and not refresh:
        if time.time() - cache.stat().st_mtime < 900:
            try:
                with open(cache) as f:
                    return [_parse_market(m) for m in json.load(f)]
            except (json.JSONDecodeError, OSError):
                pass
    try:
        data = _get(f"{GAMMA_BASE}/events", params={
            "tag_slug": tag_slug,
            "active": "true",
            "closed": "false",
            "end_date_min": end_min,
            "end_date_max": end_max,
            "limit": 100,
        })
        events = data if isinstance(data, list) else []
        raw_markets: list[dict] = []
        for ev in events:
            for m in ev.get("markets", []) or []:
                m.setdefault("events", [{"slug": ev.get("slug", ""),
                                         "ticker": ev.get("ticker", "")}])
                raw_markets.append(m)
        with open(cache, "w") as f:
            json.dump(raw_markets, f)
        return [_parse_market(m) for m in raw_markets]
    except Exception as e:
        print(f"  [polymarket] events fetch error ({tag_slug}): {e}")
        if cache.exists():
            try:
                with open(cache) as f:
                    return [_parse_market(m) for m in json.load(f)]
            except (json.JSONDecodeError, OSError):
                pass
        return []


def fetch_sports_markets(refresh: bool = False) -> list[PolyMarket]:
    """Fetch sports prediction markets.

    WARNING: the Gamma `tag` param is ignored server-side — this returns the
    top-volume markets of EVERY category. Kept for backward compatibility;
    game scanning should use fetch_game_events(tag_slug=…) instead."""
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
