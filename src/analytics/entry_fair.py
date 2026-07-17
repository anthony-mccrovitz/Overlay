"""
src/analytics/entry_fair.py — entry-side (bet-time) no-vig fair probabilities.

CLV was asymmetric: the CLOSE is devigged (fetch_closing_pairs / Pinnacle pairs)
but the ENTRY was the raw vigged implied prob of the price we took. Fair-close
minus vigged-entry deflates every price-CLV by roughly the entry vig share
(~1.5-2.5%), so a genuinely break-even strategy reads negative. This module
devigs the ENTRY from the same raw odds board the pick was generated from
(data/cache/odds/{odds_api_sport}_latest.json — written by fetch_odds on every
fresh pull, so reading it costs zero API credits).

Attached snapshot fields (all optional — absent when the board doesn't cover
the pick or is stale):

  opening_fair_prob      no-vig prob of the picked side, best price both sides
                         (methodology-matched to fetch_closing_pairs at close,
                         so clv_novig = fair_close - fair_entry is apples-to-apples)
  opening_fair_sharp     no-vig prob from PINNACLE's two-sided entry market
  opening_opp_odds       opponent-side best price used in the devig
  opening_draw_odds      draw price for 3-way (soccer) markets
  entry_ev_vs_fair_pct   (pinnacle_fair / raw_implied(entry price) - 1) * 100 —
                         the STALE-OPENER signal: how much better your entry
                         price is than the sharp market's fair estimate AT BET
                         TIME. Positive = the soft book's number lagged the
                         sharp market when you bet it. This is expected CLV
                         known at entry, before any close exists.
  entry_overround        sum of raw implied probs of the entry pair (vig sanity)
  entry_board_age_min    age of the odds board used (staleness disclosure)
  commence_time          event start (ISO) from the entry board — lets CLV
                         compute entry_lead_min (how early the bet was) without
                         waiting for the closing archive
  consensus_fair_prob    median of every book's OWN two-sided devig of the
                         picked side (Kaunitz cross-book consensus, robust at
                         small n) — analysis metadata alongside the
                         Pinnacle-only opening_fair_sharp
  consensus_n_books      how many books that consensus averaged (disclosure)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.strategies.consensus import loo_consensus, per_book_fair

CACHE_DIR = Path("data/cache/odds")

# Snapshots store the SHORT canonical sport ("mlb"); cache files are keyed by
# the full Odds API sport ("baseball_mlb_latest.json"). Reverse of the
# _SPORT_ALIASES normalization. Sports not listed here (soccer_*, tennis_*,
# golf_*, mma_*) already store their full Odds API key in snapshots.
_REVERSE_SPORT = {
    "mlb":  "baseball_mlb",
    "nba":  "basketball_nba",
    "wnba": "basketball_wnba",
    "nhl":  "icehockey_nhl",
    "nfl":  "americanfootball_nfl",
    "ncaaf": "americanfootball_ncaaf",
    "ncaab": "basketball_ncaab",
}

# A board older than this can't honestly claim to be the "entry" market —
# don't attach fair probs from it. Snapshots normally run minutes after the
# odds fetch that produced the picks, so this is a wide safety net, not a knob.
MAX_BOARD_AGE_MIN = 12 * 60.0

PINNACLE = "Pinnacle"


def _odds_to_implied(odds: float) -> float:
    """American odds → raw (with-vig) implied probability."""
    odds = float(odds)
    if odds == 0:
        return 0.5
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _devig(picked: float, *others: float) -> float | None:
    """Additive de-vig for an N-way market: picked / sum(all outcomes)."""
    raw = _odds_to_implied(picked)
    overround = raw + sum(_odds_to_implied(o) for o in others if o is not None)
    if overround <= 0:
        return None
    return raw / overround


def load_board(short_sport: str) -> tuple[list[dict], float] | None:
    """Load the raw Odds API event list for a sport from the latest-odds cache.

    Returns (events, age_minutes) or None when the cache is missing, unreadable,
    or older than MAX_BOARD_AGE_MIN (a stale board is not an entry market).
    """
    api_sport = _REVERSE_SPORT.get(short_sport, short_sport)
    path = CACHE_DIR / f"{api_sport}_latest.json"
    if not path.exists():
        return None
    age_min = (time.time() - path.stat().st_mtime) / 60.0
    if age_min > MAX_BOARD_AGE_MIN:
        return None
    try:
        events = json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    if not isinstance(events, list):
        return None
    return events, round(age_min, 1)


def build_indexes(events: list[dict]) -> dict:
    """Index a raw event list for entry-fair lookups.

    Returns:
      {
        "ml":     {team_lower: {"best": {sel_lower: best_odds},
                                "pin":  {sel_lower: pinnacle_odds},
                                "sels": [sel_lower, ...]}},   # shared per event
        "totals": {frozenset({away,home}): {line: {"over_best","under_best",
                                                   "over_pin","under_pin"}}},
      }
    """
    ml_index: dict[str, dict] = {}
    totals_index: dict[frozenset, dict] = {}
    commence_index: dict[frozenset, str] = {}

    for ev in events:
        home = str(ev.get("home_team") or "").lower().strip()
        away = str(ev.get("away_team") or "").lower().strip()
        if not home or not away:
            continue
        commence = str(ev.get("commence_time") or "") or None
        if commence:
            commence_index[frozenset({away, home})] = commence

        best: dict[str, float] = {}
        pin: dict[str, float] = {}
        books: dict[str, dict[str, float]] = {}  # per-book h2h quotes (consensus)
        tot: dict[float, dict] = {}

        for bk in ev.get("bookmakers", []):
            book = str(bk.get("title") or bk.get("key") or "")
            is_pin = book == PINNACLE
            for mk in bk.get("markets", []):
                mkey = mk.get("key")
                if mkey == "h2h":
                    for oc in mk.get("outcomes", []):
                        sel = str(oc.get("name") or "").lower().strip()
                        price = oc.get("price")
                        if not sel or price is None:
                            continue
                        p = float(price)
                        if sel not in best or p > best[sel]:
                            best[sel] = p
                        if is_pin:
                            pin[sel] = p
                        books.setdefault(book, {})[sel] = p
                elif mkey == "totals":
                    for oc in mk.get("outcomes", []):
                        side = str(oc.get("name") or "").lower().strip()
                        price = oc.get("price")
                        point = oc.get("point")
                        if side not in ("over", "under") or price is None or point is None:
                            continue
                        p, ln = float(price), float(point)
                        entry = tot.setdefault(ln, {})
                        bkey = f"{side}_best"
                        if bkey not in entry or p > entry[bkey]:
                            entry[bkey] = p
                        if is_pin:
                            entry[f"{side}_pin"] = p

        if best:
            rec = {"best": best, "pin": pin, "sels": sorted(best),
                   "books": books, "commence": commence}
            ml_index[home] = rec
            ml_index[away] = rec
        if tot:
            totals_index[frozenset({away, home})] = tot

    return {"ml": ml_index, "totals": totals_index, "commence": commence_index}


class EntryBoards:
    """Lazy per-sport board loader shared across one snapshot run."""

    def __init__(self) -> None:
        self._cache: dict[str, dict | None] = {}

    def get(self, short_sport: str) -> dict | None:
        if short_sport not in self._cache:
            loaded = load_board(short_sport)
            if loaded is None:
                self._cache[short_sport] = None
            else:
                events, age_min = loaded
                idx = build_indexes(events)
                idx["age_min"] = age_min
                self._cache[short_sport] = idx
        return self._cache[short_sport]


def _attach_common(snap: dict, fair: float | None, fair_sharp: float | None,
                   opp_odds: float | None, draw_odds: float | None,
                   overround: float | None, age_min: float) -> bool:
    """Stamp the entry-fair fields onto a snapshot. Returns True if anything set."""
    wrote = False
    if fair is not None:
        snap["opening_fair_prob"] = round(fair, 6)
        wrote = True
    if fair_sharp is not None:
        snap["opening_fair_sharp"] = round(fair_sharp, 6)
        # Stale-opener signal: your actual entry price vs the sharp fair prob.
        # EV% = fair / implied(entry) - 1. Uses the snapshot's own opening_odds
        # (the price you'd bet), not the board best, so line-shopping shows up.
        entry_imp = snap.get("opening_implied_prob")
        if entry_imp:
            snap["entry_ev_vs_fair_pct"] = round((fair_sharp / entry_imp - 1.0) * 100, 3)
        wrote = True
    if opp_odds is not None:
        snap["opening_opp_odds"] = opp_odds
    if draw_odds is not None:
        snap["opening_draw_odds"] = draw_odds
    if overround is not None:
        snap["entry_overround"] = round(overround, 4)
    if wrote:
        snap["entry_board_age_min"] = age_min
    return wrote


def attach_entry_fair(snap: dict, boards: EntryBoards) -> bool:
    """Attach entry-side no-vig fields to one snapshot, if the board covers it.

    Supported markets: moneyline (2-way and 3-way) and full-game totals.
    Everything else returns False untouched (line-CLV is their primary metric).
    """
    market = str(snap.get("market") or "").lower()
    sport = str(snap.get("sport") or "").lower()
    idx = boards.get(sport)
    if idx is None:
        return False
    age_min = idx["age_min"]

    if market in ("moneyline", "h2h", "ml", ""):
        team = str(snap.get("team") or "").lower().strip()
        rec = idx["ml"].get(team)
        if rec is None:
            # partial-name fallback, mirrors compute_clv's closing join
            for k, v in idx["ml"].items():
                if team and (team in k or k in team):
                    rec, team = v, k
                    break
        if rec is None or team not in rec["best"]:
            return False
        if rec.get("commence"):
            snap["commence_time"] = rec["commence"]
        best = rec["best"]
        others = [best[s] for s in rec["sels"] if s != team]
        if not others:
            return False
        fair = _devig(best[team], *others)
        overround = (_odds_to_implied(best[team])
                     + sum(_odds_to_implied(o) for o in others))
        pin = rec["pin"]
        fair_sharp = None
        if team in pin and len(pin) == len(rec["sels"]):
            fair_sharp = _devig(pin[team], *[pin[s] for s in rec["sels"] if s != team])
        # Cross-book consensus (Kaunitz): median of each book's OWN devig of
        # the picked side, over books quoting the full market. Metadata
        # alongside the Pinnacle-only sharp fair — 2+ books, n disclosed.
        pairs = {
            b: tuple([q[team]] + [q[s] for s in rec["sels"] if s != team])
            for b, q in (rec.get("books") or {}).items()
            if all(s in q for s in rec["sels"])
        }
        cons = loo_consensus(per_book_fair(pairs), exclude=None, min_books=2)
        if cons is not None:
            snap["consensus_fair_prob"] = round(cons[0], 6)
            snap["consensus_n_books"] = cons[1]
        opp = next((best[s] for s in rec["sels"] if s not in (team, "draw")), None)
        draw = best.get("draw") if len(rec["sels"]) > 2 else None
        return _attach_common(snap, fair, fair_sharp, opp, draw, overround, age_min)

    if market in ("total", "totals"):
        mu = str(snap.get("opponent") or "")
        direction = str(snap.get("direction") or "").upper()
        line = snap.get("opening_line")
        if "@" not in mu or direction not in ("OVER", "UNDER") or line is None:
            return False
        a, h = [t.strip().lower() for t in mu.split("@", 1)]
        commence = (idx.get("commence") or {}).get(frozenset({a, h}))
        if commence:
            snap["commence_time"] = commence
        lines = idx["totals"].get(frozenset({a, h}))
        if not lines:
            return False
        entry = lines.get(float(line))
        if not entry or "over_best" not in entry or "under_best" not in entry:
            return False  # only devig at YOUR line — a different line is a different bet
        side, opp_side = (("over", "under") if direction == "OVER" else ("under", "over"))
        fair = _devig(entry[f"{side}_best"], entry[f"{opp_side}_best"])
        overround = (_odds_to_implied(entry[f"{side}_best"])
                     + _odds_to_implied(entry[f"{opp_side}_best"]))
        fair_sharp = None
        if f"{side}_pin" in entry and f"{opp_side}_pin" in entry:
            fair_sharp = _devig(entry[f"{side}_pin"], entry[f"{opp_side}_pin"])
        return _attach_common(snap, fair, fair_sharp,
                              entry[f"{opp_side}_best"], None, overround, age_min)

    return False
