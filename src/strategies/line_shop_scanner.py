"""
line_shop_scanner.py — the MARKET track.

Two tracks now run against every sport, and they answer different questions:

  MODEL  track  — "what do I think will happen?"  (predict.py, run_nba.py, ...)
                  Judged on whether it beats the close. Over 10,161 scored picks
                  it beats it 47.7% of the time, i.e. it doesn't.

  MARKET track  — "who is priced wrong?"  (this module)
                  Predicts nothing. Takes the sharp no-vig price as truth and
                  looks for a bettable book offering a better number. The edge,
                  when it exists, is the soft book's staleness — not skill.

Both log to the same ledger with a `strategy` tag, so the existing CLV pipeline
scores them head to head on identical machinery. That comparison is the entire
point: it's the only way to learn which approach deserves the bankroll.

FAIR PRICE
──────────
Pinnacle's two-sided de-vig is the primary anchor — it's the sharpest number
publicly available and the closest thing to a true probability. When Pinnacle
doesn't price a market, fall back to a cross-book consensus: de-vig EVERY book's
own two-sided market, then take the median (Kaunitz). The median is robust to
one book hanging a stale or erroneous number, which a mean is not.

A consensus fair built from the same books we bet is weaker evidence than
Pinnacle — it partly measures our own pool's agreement — so every scan row
carries `fair_source` and the promotion gate should judge the two separately.

COST
────
Reads `data/cache/odds/{sport}_latest.json`, written by every odds fetch, so a
scan costs ZERO API credits. `fetch=True` refreshes the board first and costs
credits; keep it off unless the board is genuinely stale.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

CACHE_DIR = Path("data/cache/odds")

# Books we can actually bet. An edge against a book with no account is not an
# edge, so Pinnacle (sharp anchor, not bettable here) is deliberately excluded.
BETTABLE = {
    "draftkings":  "DraftKings",
    "fanduel":     "FanDuel",
    "betmgm":      "BetMGM",
    "betrivers":   "BetRivers",
    "espnbet":     "ESPN BET",
    "fanatics":    "Fanatics",
    "hardrockbet": "Hard Rock",
    "ballybet":    "Bally Bet",
    "williamhill_us": "Caesars",
}

SHARP = "pinnacle"

# A board this old is not an entry market — prices have moved and any "edge"
# it shows is against a number nobody is offering.
MAX_BOARD_AGE_MIN = 90.0

# Below this the "edge" is inside the noise of de-vig methodology itself.
MIN_EV_PCT = 2.0

# Above this, it is not an edge — it is a bug. Real line-shop edges against a
# de-vigged sharp price live at 1-5%; books do not leave 15% on the table across
# a whole board. Historically every double-digit "edge" in this repo has been a
# market-structure error (3-way markets de-vigged as 2-way, mismatched lines,
# a stale board). Rows above the ceiling are DROPPED and counted, so the bug
# surfaces as a diagnostic instead of as a bet.
MAX_EV_PCT = 15.0

# Heavy favourites carry the worst payoff asymmetry and get limited fastest;
# longshots are where stale-line artefacts cluster. Bet the middle.
MIN_ODDS = -350
MAX_ODDS = 600

# A consensus fair needs enough books to be a median rather than an opinion.
MIN_CONSENSUS_BOOKS = 4


# ─────────────────────────── odds math ───────────────────────────────────────

def implied(odds: float) -> float:
    """American odds → raw (with-vig) implied probability."""
    odds = float(odds)
    if odds == 0:
        return 0.5
    return 100.0 / (odds + 100.0) if odds > 0 else abs(odds) / (abs(odds) + 100.0)


def decimal_odds(odds: float) -> float:
    odds = float(odds)
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / abs(odds))


def american_from_prob(p: float) -> int:
    if not 0 < p < 1:
        return 0
    return int(round(-p / (1 - p) * 100)) if p >= 0.5 else int(round((1 - p) / p * 100))


def ev_pct(fair_prob: float, odds: float) -> float:
    """True expected value per unit staked, in percent.

    EV = fair × (decimal − 1) − (1 − fair). Note this is NOT `(fair − implied)`,
    the probability-point gap the old line_shop reported — that understates the
    return on longshots and overstates it on favourites, because a point of
    probability is worth more the longer the price.
    """
    d = decimal_odds(odds)
    return (fair_prob * (d - 1.0) - (1.0 - fair_prob)) * 100.0


def kelly_fraction(fair_prob: float, odds: float) -> float:
    """Full-Kelly stake as a fraction of bankroll. Callers scale it down."""
    b = decimal_odds(odds) - 1.0
    if b <= 0:
        return 0.0
    f = (fair_prob * b - (1.0 - fair_prob)) / b
    return max(0.0, f)


def _devig_pair(p_a: float, p_b: float) -> tuple[float, float] | None:
    total = p_a + p_b
    if total <= 0:
        return None
    return p_a / total, p_b / total


# ─────────────────────────── board parsing ───────────────────────────────────

def load_board(sport_key: str) -> tuple[list[dict], float] | None:
    """(events, age_minutes) from the odds cache, or None if missing/stale."""
    path = CACHE_DIR / f"{sport_key}_latest.json"
    if not path.exists():
        return None
    age = (time.time() - path.stat().st_mtime) / 60.0
    try:
        events = json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    if not isinstance(events, list):
        return None
    return events, round(age, 1)


def _selection_key(market_key: str, outcome: dict) -> tuple | None:
    """A stable identity for one side of one market, comparable across books.

    The `point` is part of the identity for spreads and totals: FanDuel's
    UNDER 8.5 and DraftKings' UNDER 9.0 are different bets, and comparing them
    is how a scanner invents edges that don't exist.
    """
    name = outcome.get("name")
    if name is None:
        return None
    if market_key == "h2h":
        return ("moneyline", name, None)
    if market_key == "spreads":
        return ("spread", name, outcome.get("point"))
    if market_key == "totals":
        return ("total", name, outcome.get("point"))
    return None


def _collect(event: dict) -> dict:
    """Index one event as {selection_key: {book_key: price}}."""
    table: dict[tuple, dict[str, float]] = {}
    for book in event.get("bookmakers", []):
        bkey = book.get("key", "")
        for market in book.get("markets", []):
            mkey = market.get("key")
            if mkey not in ("h2h", "spreads", "totals"):
                continue
            for out in market.get("outcomes", []):
                sel = _selection_key(mkey, out)
                price = out.get("price")
                if sel is None or price is None:
                    continue
                table.setdefault(sel, {})[bkey] = float(price)
    return table


def _siblings(sel: tuple, table: dict) -> list[tuple]:
    """EVERY other outcome in the same market — the full de-vig set.

    This must be complete, not just "the opposite side". Soccer moneylines are
    THREE-way (Home / Draw / Away): de-vigging a draw against one opponent while
    ignoring the third outcome divides by an overround that's missing a third of
    its mass, which inflates the draw's fair probability enormously and
    manufactures +250% edges on every draw on the board. That exact bug has bitten
    this project before via Polymarket, where draw contracts are typed "moneyline".
    """
    market, name, point = sel
    out = []
    for other in table:
        if other == sel or other[0] != market:
            continue
        o_name, o_point = other[1], other[2]
        if market == "total":
            # Over/Under form a pair only at the same line.
            if o_point == point and o_name != name:
                out.append(other)
        elif market == "spread":
            # Spread pairs have equal-and-opposite points (-1.5 / +1.5).
            if o_name != name and point is not None and o_point is not None:
                if abs(o_point + point) < 1e-6:
                    out.append(other)
        else:
            # Moneyline: 2-way (h2h) or 3-way (soccer, with a Draw). Take all.
            if o_name != name:
                out.append(other)
    return out


def _devig_group(prices_by_sel: list[float]) -> float | None:
    """Additive de-vig of an N-way market: picked / sum(all outcomes)."""
    total = sum(prices_by_sel)
    if total <= 0:
        return None
    return prices_by_sel[0] / total


def fair_probability(sel: tuple, table: dict) -> tuple[float, str, int] | None:
    """(fair_prob, source, n_books) for one selection, or None.

    Pinnacle de-vig across the FULL outcome set first; cross-book median as
    fallback. A book only contributes to the consensus if it prices every
    outcome in the market — a partial book can't be de-vigged honestly.
    """
    sibs = _siblings(sel, table)
    if not sibs:
        return None

    prices = table[sel]

    # Pinnacle, if it prices the complete market.
    pin = prices.get(SHARP)
    if pin is not None:
        sib_pins = [table[s].get(SHARP) for s in sibs]
        if all(p is not None for p in sib_pins):
            fair = _devig_group([implied(pin)] + [implied(p) for p in sib_pins])
            if fair is not None:
                return fair, "pinnacle", 1

    # Fallback: every book pricing the COMPLETE market de-vigs its own board,
    # then take the median. Robust to one book hanging a stale number.
    fairs = []
    for bkey, price in prices.items():
        sib_prices = [table[s].get(bkey) for s in sibs]
        if any(p is None for p in sib_prices):
            continue
        fair = _devig_group([implied(price)] + [implied(p) for p in sib_prices])
        if fair is not None:
            fairs.append(fair)
    if len(fairs) >= MIN_CONSENSUS_BOOKS:
        return median(fairs), "consensus", len(fairs)
    return None


# ─────────────────────────── the scan ────────────────────────────────────────

def scan_event(event: dict, sport: str, min_ev: float = MIN_EV_PCT,
               rejected: list | None = None) -> list[dict]:
    table = _collect(event)
    home, away = event.get("home_team", ""), event.get("away_team", "")
    matchup = f"{away} @ {home}"
    out: list[dict] = []

    for sel, prices in table.items():
        market, name, point = sel
        fair = fair_probability(sel, table)
        if fair is None:
            continue
        fair_prob, source, n_books = fair

        for bkey, price in prices.items():
            if bkey not in BETTABLE:
                continue
            if not (MIN_ODDS <= price <= MAX_ODDS):
                continue
            ev = ev_pct(fair_prob, price)
            if ev < min_ev:
                continue
            if ev > MAX_EV_PCT:
                # Not an edge — a bug. Surface it as a diagnostic, never a bet.
                if rejected is not None:
                    rejected.append({"matchup": matchup, "market": market,
                                     "selection": name, "line": point,
                                     "book": bkey, "odds": int(price),
                                     "ev_pct": round(ev, 1), "source": source})
                continue
            out.append({
                "sport":       sport,
                "market":      market,
                "selection":   name,
                "line":        point,
                "matchup":     matchup,
                "book":        BETTABLE[bkey],
                "book_key":    bkey,
                "odds":        int(price),
                "fair_prob":   round(fair_prob, 4),
                "fair_odds":   american_from_prob(fair_prob),
                "ev_pct":      round(ev, 2),
                "kelly":       round(kelly_fraction(fair_prob, price), 4),
                "fair_source": source,
                "n_books":     n_books,
                "commence":    event.get("commence_time", ""),
            })
    return out


def scan_sport(sport_key: str, min_ev: float = MIN_EV_PCT,
               max_age_min: float = MAX_BOARD_AGE_MIN) -> tuple[list[dict], dict]:
    """Scan one sport's cached board. Returns (opportunities, diagnostics)."""
    board = load_board(sport_key)
    if board is None:
        return [], {"sport": sport_key, "status": "no board", "events": 0}
    events, age = board
    if age > max_age_min:
        return [], {"sport": sport_key, "status": f"stale ({age:.0f}m)",
                    "events": len(events), "age_min": age}

    rows: list[dict] = []
    rejected: list[dict] = []
    n_sharp = 0
    for ev in events:
        if any(b.get("key") == SHARP for b in ev.get("bookmakers", [])):
            n_sharp += 1
        rows.extend(scan_event(ev, sport_key, min_ev, rejected))

    rows.sort(key=lambda r: -r["ev_pct"])
    return rows, {
        "sport": sport_key, "status": "ok", "events": len(events),
        "with_sharp": n_sharp, "age_min": age, "found": len(rows),
        "rejected": len(rejected), "rejected_rows": rejected[:5],
    }


# ─────────────────────────── logging ─────────────────────────────────────────

def to_pick(row: dict, date_str: str, stake: float = 0.0) -> dict:
    """Shape a scan row as a ledger pick, tagged for the MARKET track.

    card_pick is always False: this strategy has not earned a live slot, and it
    earns one the same way everything else does — by beating the close over
    enough settled bets, not by looking convincing on the board.
    """
    sel_slug = str(row["selection"]).lower().replace(" ", "-")
    line_part = f"_{row['line']}" if row.get("line") is not None else ""
    return {
        "pick_id":    f"lineshop_{row['sport']}_{date_str.replace('-','')}_"
                      f"{sel_slug}_{row['market']}{line_part}_{row['book_key']}",
        "date":       date_str,
        "sport":      row["sport"],
        "market":     row["market"],
        "direction":  row["selection"],
        "team":       row["selection"],
        "matchup":    row["matchup"],
        "odds":       row["odds"],
        "line":       row.get("line"),
        "sportsbook": row["book"],
        "model_prob": row["fair_prob"],
        "edge_pct":   row["ev_pct"],
        "stake":      stake,
        "card_pick":  False,
        "strategy":   "line_shop",
        "fair_source": row["fair_source"],
        "result":     None,
        "profit":     None,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "resulted_at": None,
    }
