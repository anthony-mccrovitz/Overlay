#!/usr/bin/env python3
"""
Polymarket-vs-Pinnacle price scanner — shadow strategy `polymarket_ev`.

The thesis (same as devig_ev, different venue): Pinnacle's devigged price is
the best public estimate of true probability. When Polymarket lets you buy a
team's win contract CHEAPER than Pinnacle fair, that's +EV.

HOW you enter decides whether any edge survives. Measured on 2026-07-20 across
MLB, WNBA, MLS, K-League and Brazil: crossing the spread was negative on 28 of
29 sides (median -4.6% once the real sports_fees_v2 taker fee is applied),
while resting an order inside the bid — which pays NO fee, the schedule is
takerOnly — was positive on 19 of 29. The spread plus fee is about the size of
the edge being hunted, so the scanner defaults to maker pricing (ENTRY_MODE).

The catch, and the reason this is still an experiment: a maker price is only
achievable IF the order fills, and resting orders fill preferentially when the
counterparty knows something you don't. scripts/polymarket_fills.py replays
the price history to measure the real fill rate and that adverse selection.
Until it reports, a maker EV here is a hypothesis, not a number to bet.

Everything is shadow-first: finds are logged to picks.json with
card_pick=False, stake=0, strategy="polymarket_ev", snapshot their opening
implied prob, and get scored against the real-book close by the existing CLV
pipeline. The 300-bet PROMOTE/SHADOW/RETIRE verdict decides whether the $112
pilot account ever places a real order. No execution here, ever.

Polymarket game markets come in two shapes; both are handled:
  - two-outcome team markets: outcomes ["Team A", "Team B"], one CLOB token
    per outcome — each outcome is priced off its own order book
  - Yes/No markets: "Will X win/beat Y?" — YES = the subject team; NO maps to
    the opponent's moneyline (2-way sports only; in draw sports NO includes
    the draw and has no book twin, so it is skipped)

Usage:
  python3 scripts/polymarket_scanner.py --dry-run       # scan, print, no writes
  python3 scripts/polymarket_scanner.py                 # scan + log shadow picks
  python3 scripts/polymarket_scanner.py --bankroll 112 --min-ev 2 --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.polymarket import (          # noqa: E402
    PolyMarket,
    fetch_game_events,
    fetch_order_book,
    maker_limit,
    max_stake_at_ev,
    walk_book,
)

_ET = ZoneInfo("America/New_York")
PICKS_FILE = Path("data/pnl/picks.json")

MIN_EV_PCT = 2.0          # same bar as devig_ev/consensus_ev — comparable verdicts
MIN_LIQUIDITY_USD = 1000  # below this the "price" is a ghost; fills would move it
PILOT_STAKE_FRAC = 0.04   # flat 4% of bankroll per pick (guidance only)
# Default execution style. "make" rests an order inside the bid and pays no
# fee (sports_fees_v2 is takerOnly); "take" crosses the spread at the ask.
# Maker is the default because on 2026-07-20 every taker entry across MLB,
# WNBA, MLS, K-League and Brazil was negative (median -4.6% under the real
# fee) while the same board was positive on 19 of 29 sides as a maker. A
# maker cost is CONDITIONAL on filling — scripts/polymarket_fills.py measures
# the fill rate and adverse selection that decide whether it is real.
ENTRY_MODE = "make"
# Event fetch window: main game events carry endDate = game + ~7 days (a
# resolution buffer — verified 2026-07-19 on mlb-tb-bos events), so the fetch
# window must be wide. The PRECISE slate gate is per-market gameStartTime.
_EVENT_WINDOW_DAYS = 8
_END_DATE_FALLBACK_H = 30   # markets with no gameStartTime: end within slate+30h

# Sports whose moneyline includes a draw — NO-side inference is disabled there
# (NO on "Team X wins" includes the draw; no sportsbook twin for the CLV join).
_DRAW_SPORT_TOKENS = ("soccer",)

# Odds-API sport key → Polymarket Gamma tag_slug (verified 2026-07-19).
# tennis_* keys rotate per tournament — prefix-mapped below.
_TAG_SLUGS: dict[str, str] = {
    "baseball_mlb":           "mlb",
    "basketball_wnba":        "wnba",
    "basketball_nba":         "nba",
    "mma_mixed_martial_arts": "ufc",
    "soccer_usa_mls":         "mls",
    "soccer_mexico_ligamx":   "liga-mx",   # no coverage today; harmless if empty
    "soccer_fifa_world_cup":  "soccer",
    "icehockey_nhl":          "nhl",
    # Summer leagues that run while Europe is dark. Each one below was checked
    # to have BOTH Polymarket moneyline depth and Pinnacle on the Odds API
    # board — without a Pinnacle fair there is nothing to price against, which
    # is why e.g. UCL qualification (14 games, zero Pinnacle) is absent.
    "soccer_korea_kleague1":  "k-league",
    "soccer_brazil_campeonato": "brazil-serie-a",
    "soccer_sweden_allsvenskan": "allsvenskan",
}


def _tag_slug(sport: str) -> str | None:
    if sport in _TAG_SLUGS:
        return _TAG_SLUGS[sport]
    if str(sport).startswith("tennis"):
        return "tennis"
    return None

# Tokens too generic to identify a team on their own ("new" matching both
# New York teams, "city", "united", ...).
_GENERIC_TOKENS = {
    "new", "york", "los", "san", "las", "city", "united", "fc", "cf", "sc",
    "club", "real", "state", "the", "of", "de", "afc", "town",
}


# ── Price/odds helpers ───────────────────────────────────────────────────────

def prob_to_american(p: float) -> int:
    """Probability → American odds. 0.25 → +300, 0.60 → −150."""
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    if p >= 0.5:
        return -int(round(p / (1 - p) * 100))
    return int(round((1 - p) / p * 100))


# ── Team-name matching ───────────────────────────────────────────────────────

def _tokens(name: str) -> set[str]:
    return {t for t in re.sub(r"[^\w\s]", " ", str(name).lower()).split() if t}


def team_matches(label: str, team_name: str) -> bool:
    """Does a Polymarket outcome label refer to this Odds-API team?

    Polymarket says "Yankees", the Odds API says "New York Yankees";
    UFC says "McGregor" vs "Conor McGregor". Rule: every significant token of
    the SHORTER name must appear in the longer one, and at least one shared
    token must be distinctive (not in the generic-word list).
    """
    a, b = _tokens(label), _tokens(team_name)
    if not a or not b:
        return False
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    if not small <= big:
        return False
    return any(t not in _GENERIC_TOKENS for t in small & big)


def _is_draw_sport(sport: str) -> bool:
    return any(tok in str(sport).lower() for tok in _DRAW_SPORT_TOKENS)


def _on_slate(pm: PolyMarket, eff_date: str) -> bool:
    """Is this market's GAME on the slate date (ET)?

    gameStartTime is authoritative — without this gate, tomorrow's
    "Liberty vs. Wings" contract cross-matched today's Wings game and printed
    a phantom +62% (different game, different price, same team name). Markets
    lacking gameStartTime fall back to an endDate bound of slate+30h.
    """
    if pm.game_start_time:
        try:
            dt = datetime.fromisoformat(
                str(pm.game_start_time).replace("Z", "+00:00").replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(_ET).date().isoformat() == eff_date
        except (ValueError, TypeError):
            pass
    if not pm.end_date:
        return True   # no dates at all: the team-pair match must gate it
    try:
        end = datetime.fromisoformat(str(pm.end_date).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    slate = datetime.fromisoformat(eff_date).replace(tzinfo=_ET)
    return slate <= end <= slate + timedelta(hours=_END_DATE_FALLBACK_H)


def _outcome_labels(pm: PolyMarket) -> list[str]:
    raw = pm.raw.get("outcomes", "[]")
    try:
        labels = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (json.JSONDecodeError, TypeError):
        labels = []
    return [str(x) for x in labels]


# Question patterns that mark DERIVATIVE markets (spread/total/period/prop/
# method) — pricing these against a full-game moneyline fair produced phantom
# +20-60% "edges" on the first live scan (a Wings -9.5 spread contract at 0.49
# vs their 0.78 ML fair is not an edge, it's a category error).
_DERIVATIVE_Q = re.compile(
    r"(?i)\bo/u\b|spread|inning|quarter|\bhalf\b|1st|first to|round \d|"
    r"method|by (ko|tko|submission|decision)|series|to win the|double result"
)


# Polymarket labels the 3-way DRAW contract sportsMarketType="moneyline" and
# names both clubs in the question ("Will Jeju SK FC vs. Gangwon FC end in a
# draw?"). Team matching then reads it as a win contract for whichever club it
# matched, and prices the draw's cost against that club's WIN fair. On
# 2026-07-21 that printed "Gangwon FC +35.5%" — draw ask 0.31 vs a 0.439 win
# fair — the single largest fake edge the scanner has produced.
_DRAW_Q = re.compile(r"(?i)\bend in a draw\b|\bdraw\b\s*\?$|: *draw\b")


def _is_moneyline_market(pm: PolyMarket) -> bool:
    """Only full-game/fight moneyline markets may be priced against the
    Pinnacle h2h fair. Prefer Gamma's own sportsMarketType label; fall back to
    shape heuristics for markets that lack it."""
    if _DRAW_Q.search(pm.question or ""):
        # A draw has no two-way book twin to price against or to join for CLV.
        return False
    smt = pm.raw.get("sportsMarketType")
    if smt is not None:
        return str(smt).lower() == "moneyline"
    if pm.raw.get("line") is not None:
        return False
    return not _DERIVATIVE_Q.search(pm.question or "")


# ── Core matching + edge math ────────────────────────────────────────────────

def _games_from_board(odds_df) -> list[dict]:
    """Unique games on the (already today-filtered) board."""
    games: dict[str, dict] = {}
    for _, row in odds_df.iterrows():
        gid = str(row.get("GameID", ""))
        if not gid or gid in games:
            continue
        games[gid] = {
            "game_id": gid,
            "home": str(row.get("HomeTeam", "")),
            "away": str(row.get("AwayTeam", "")),
        }
    return list(games.values())


def _match_team_to_games(label: str, games: list[dict]) -> tuple[dict, str] | None:
    """Match an outcome label to exactly ONE (game, side). Ambiguous (e.g.
    doubleheaders) or unmatched → None."""
    hits: list[tuple[dict, str]] = []
    for g in games:
        if team_matches(label, g["home"]):
            hits.append((g, "home"))
        if team_matches(label, g["away"]):
            hits.append((g, "away"))
    return hits[0] if len(hits) == 1 else None


def _entry_cost_for_outcome(pm: PolyMarket, idx: int,
                            mode: str = ENTRY_MODE,
                            stake_usd: float = 0.0) -> tuple[float, dict]:
    """Entry cost for outcome idx in the requested execution mode, preferring
    that outcome's own CLOB book.

    Records the full book state (bid/ask/limit) alongside the cost, because
    that is what scripts/polymarket_fills.py needs later to decide whether a
    resting order would actually have filled. Without the bid recorded at
    entry time, a maker experiment is unfalsifiable after the fact.
    """
    token = pm.token_ids[idx] if idx < len(pm.token_ids) else None
    book = fetch_order_book(token) if token else None
    if book and book.get("best_ask") is not None:
        bid, ask = book.get("best_bid"), book.get("best_ask")
        cost = pm.entry_cost("yes", book=book, mode=mode)
        asks = book.get("asks") or []
        # Taker cost at the SIZE we would actually trade, not at the top tick.
        # A best ask with 27 shares behind it is a headline, not a fill.
        walked = walk_book(asks, stake_usd, pm.fee_schedule) if asks else None
        return cost, {"token_id": token, "poly_bid": bid, "poly_ask": ask,
                      "poly_limit": maker_limit(bid, ask) if mode == "make" else ask,
                      "poly_taker_cost": pm.entry_cost("yes", book=book, mode="take"),
                      "poly_taker_cost_at_size": (walked or {}).get("avg_cost"),
                      "poly_top_depth_usd": (round(asks[0][0] * asks[0][1], 2)
                                             if asks else None),
                      "asks": asks,
                      "source": "clob"}
    # Fallback: Gamma snapshot. Outcome 0 = the market's YES side; outcome 1's
    # ask ≈ 1 − YES best bid, so its book is the mirror of the YES book.
    side = "yes" if idx == 0 else "no"
    cost = pm.entry_cost(side, mode=mode)
    if side == "yes":
        bid, ask = pm.best_bid, pm.best_ask
    else:
        bid = None if pm.best_ask is None else 1.0 - pm.best_ask
        ask = None if pm.best_bid is None else 1.0 - pm.best_bid
    return cost, {"token_id": token, "poly_bid": bid, "poly_ask": ask,
                  "poly_limit": maker_limit(bid, ask) if mode == "make" else ask,
                  "poly_taker_cost": pm.entry_cost(side, mode="take"),
                  # Gamma has no depth ladder, so size-aware cost is unknown.
                  # Left None rather than defaulted — an unknown depth must not
                  # look like a deep book.
                  "poly_taker_cost_at_size": None,
                  "poly_top_depth_usd": None,
                  "asks": [],
                  "source": "gamma"}


def scan_sport(sport: str, odds_df, poly_markets: list[PolyMarket],
               eff_date: str, min_ev: float = MIN_EV_PCT,
               min_liquidity: float = MIN_LIQUIDITY_USD,
               entry_mode: str = ENTRY_MODE,
               stake_usd: float = 0.0) -> list[dict]:
    """Scan one sport's board against the Polymarket list. Pure — no I/O
    besides order-book fetches. Returns raw pick dicts."""
    from src.data.pinnacle_fair import build_fair_prob_map

    if odds_df is None or odds_df.empty:
        return []
    games = _games_from_board(odds_df)
    if not games:
        return []
    fair_map = build_fair_prob_map(odds_df)
    draw_sport = _is_draw_sport(sport)

    picks: list[dict] = []
    for pm in poly_markets:
        if pm.liquidity_usd < min_liquidity or not pm.active:
            continue
        if not _on_slate(pm, eff_date):
            continue
        if not _is_moneyline_market(pm):
            continue

        labels = _outcome_labels(pm)
        lower = [x.lower() for x in labels]

        # (outcome_idx, game, side) candidates for this market
        candidates: list[tuple[int, dict, str]] = []
        if len(labels) == 2 and set(lower) == {"yes", "no"}:
            # "Will X win/beat Y?" — subject from the question text
            hit = _match_team_to_games(pm.question, games)
            if hit is None:
                continue
            game, side = hit
            yes_idx = lower.index("yes")
            candidates.append((yes_idx, game, side))
            if not draw_sport:
                # NO = opponent moneyline (only valid without a draw outcome)
                no_idx = lower.index("no")
                opp_side = "away" if side == "home" else "home"
                candidates.append((no_idx, game, opp_side))
        else:
            # Two-outcome team market: BOTH labels must resolve to the SAME
            # game on opposite sides. Single-label matching let tomorrow's
            # "Liberty vs. Wings" contract attach to today's Wings game.
            team_labels = [(i, x) for i, x in enumerate(labels)
                           if x.lower() != "draw"]   # draws: no clean CLV twin
            if draw_sport and len(labels) == 2:
                # A 2-outcome market in a 3-way sport has ambiguous draw
                # semantics (DNB? void?) — cannot price it against a fair
                # win prob. Skip the whole market.
                continue
            hits = {i: _match_team_to_games(x, games) for i, x in team_labels}
            if len(team_labels) == 2:
                h0, h1 = (hits[i] for i, _ in team_labels)
                if (h0 is None or h1 is None
                        or h0[0]["game_id"] != h1[0]["game_id"]
                        or h0[1] == h1[1]):
                    continue   # unmatched, cross-game, or same-side: skip
            for idx, _label in team_labels:
                hit = hits.get(idx)
                if hit is None:
                    continue
                candidates.append((idx, hit[0], hit[1]))

        for idx, game, side in candidates:
            fair_entry = fair_map.get(game["game_id"], {}).get("h2h") or {}
            fair = fair_entry.get(side)
            if fair is None or not (0.0 < float(fair) < 1.0):
                continue
            fair = float(fair)

            cost, dbg = _entry_cost_for_outcome(pm, idx, mode=entry_mode,
                                                stake_usd=stake_usd)
            if not (0.005 < cost < 0.995):
                continue
            ev_pct = (fair / cost - 1.0) * 100.0
            if ev_pct < min_ev:
                continue

            team = game["home"] if side == "home" else game["away"]
            picks.append({
                "sport":         sport,
                "market":        "moneyline",
                "direction":     "WIN",
                "team":          team,                      # Odds-API name — CLV join key
                "matchup":       f"{game['away']} @ {game['home']}",
                "odds":          prob_to_american(cost),    # American — pipeline-wide assumption
                "sportsbook":    "Polymarket",
                "model_prob":    round(fair, 4),
                "edge_pct":      round(ev_pct, 2),
                "fair_source":   fair_entry.get("source"),
                # Extras (survive via append_picks_safe merge) — the receipt:
                "poly_market_id": pm.market_id,
                "poly_question":  pm.question,
                "poly_token_id":  dbg.get("token_id"),
                "poly_cost":      round(cost, 4),
                "poly_bid":       dbg.get("poly_bid"),
                "poly_ask":       dbg.get("poly_ask"),
                "poly_mid":       pm.yes_prob if idx == 0 else pm.no_prob,
                # The experiment's receipt: the price a resting order was
                # posted at, the mode it assumed, and what crossing the spread
                # would have cost instead. polymarket_fills.py reads these to
                # decide whether the order would have filled and what the
                # spread was actually worth.
                "poly_entry_mode": entry_mode,
                "poly_limit":     dbg.get("poly_limit"),
                "poly_taker_cost": (round(dbg["poly_taker_cost"], 4)
                                    if dbg.get("poly_taker_cost") is not None else None),
                # Depth, so a headline edge can't masquerade as a position.
                "poly_taker_cost_at_size": (round(dbg["poly_taker_cost_at_size"], 4)
                                            if dbg.get("poly_taker_cost_at_size") is not None
                                            else None),
                "poly_top_depth_usd": dbg.get("poly_top_depth_usd"),
                "poly_max_stake_usd": (max_stake_at_ev(dbg["asks"], fair, min_ev,
                                                       pm.fee_schedule)
                                       if dbg.get("asks") else None),
                "poly_price_source": dbg.get("source"),
                "poly_liquidity_usd": pm.liquidity_usd,
                "poly_game_start": pm.game_start_time,
                "poly_url":       pm.url,
            })
    return picks


# ── Logging tail (mirrors shadow_strategies.log_shadow_strategies) ──────────

def log_polymarket_picks(raw_picks: list[dict], eff_date: str) -> int:
    from src.tracking.schema import append_picks_safe, normalize_pick

    now_ts = datetime.now(tz=timezone.utc).isoformat()
    out: list[dict] = []
    for raw in raw_picks:
        pick = normalize_pick({
            **raw,
            "date":        eff_date,
            "stake":       0.0,
            "card_pick":   False,
            "strategy":    "polymarket_ev",
            "recorded_at": now_ts,
        })
        if pick is None:
            continue
        # Namespace like every shadow strategy so identical team/market picks
        # from other strategies never collide or dedup against these.
        pick["pick_id"] = f"polymarket_ev__{pick['pick_id']}"
        out.append({**raw, **pick})   # extras + canonical fields

    added = append_picks_safe(PICKS_FILE, out)
    if added:
        try:
            from src.analytics.clv_tracker import snapshot_from_pnl
            snapshot_from_pnl(eff_date)
        except Exception as e:
            print(f"  [polymarket] snapshot warning: {e}")
    return added


# ── Orchestration ────────────────────────────────────────────────────────────

def run(date_str: str | None = None, min_ev: float = MIN_EV_PCT,
        min_liquidity: float = MIN_LIQUIDITY_USD, bankroll: float = 112.0,
        dry_run: bool = False, as_json: bool = False) -> list[dict]:
    from src.data.odds_api import fetch_odds
    from src.strategies.shadow_strategies import (
        DEFAULT_SPORTS,
        _active_tennis_sports,
    )

    eff_date = date_str or _date.today().isoformat()
    # The scanner is market-vs-market, not model-vs-market: it needs a Pinnacle
    # board and a Polymarket tag, NOT a trained model for the league. So it
    # scans every mapped sport, including summer leagues we do not model.
    sports = sorted(set(DEFAULT_SPORTS) | set(_TAG_SLUGS)) + _active_tennis_sports()

    # Event fetch window: wide, because main game events carry endDate = game
    # + ~7 days (resolution buffer). Per-market gameStartTime does the precise
    # slate gating inside scan_sport.
    end_min = f"{eff_date}T00:00:00Z"
    end_max = (datetime.fromisoformat(eff_date)
               + timedelta(days=_EVENT_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    stake = round(bankroll * PILOT_STAKE_FRAC, 2)
    all_picks: list[dict] = []
    for sport in sports:
        slug = _tag_slug(sport)
        if slug is None:
            continue
        poly = fetch_game_events(slug, end_min, end_max, refresh=True)
        if not poly:
            continue
        print(f"  [polymarket] {sport}: {len(poly)} market(s) on tag '{slug}'")
        try:
            # refresh=False: reuse the ≤2h cached board from the daily pipeline
            # (zero Odds API credits when fresh; ~1 credit per sport otherwise)
            odds_df = fetch_odds(markets="h2h", sport=sport, refresh=False)
        except Exception as e:
            print(f"  [polymarket] {sport}: odds fetch failed — {e}")
            continue
        if odds_df is None or odds_df.empty:
            continue
        # Today-ET slate only — same fail-safe as shadow_strategies: without
        # CommenceTime we can't confirm today's games, so skip the sport.
        if "CommenceTime" not in odds_df.columns:
            print(f"  [polymarket] {sport}: no CommenceTime — skipping")
            continue

        def _is_today(ct) -> bool:
            try:
                dt = datetime.fromisoformat(str(ct).replace("Z", "+00:00"))
                return dt.astimezone(_ET).date().isoformat() == eff_date
            except (ValueError, TypeError):
                return False

        board = odds_df[odds_df["CommenceTime"].map(_is_today)]
        if board.empty:
            continue

        picks = scan_sport(sport, board, poly, eff_date,
                           min_ev=min_ev, min_liquidity=min_liquidity,
                           stake_usd=stake)
        if picks:
            print(f"  [polymarket] {sport}: {len(picks)} edge(s)")
        all_picks.extend(picks)

    # ── Report ────────────────────────────────────────────────────────────
    if all_picks:
        print(f"\n  POLYMARKET vs PINNACLE — {eff_date}   "
              f"(pilot ${bankroll:.0f}, flat ${stake:.2f}/pick)")
        print(f"  {'':6} {'team':<22} {'rest@':>6} {'fair':>6} {'MAKE':>7} "
              f"{'TAKE':>7} {'tradeable':>10}")
        print("  " + "─" * 74)
        for p in sorted(all_picks, key=lambda x: -x["edge_pct"]):
            # Sign comes from the format spec, never a literal "+" — a hardcoded
            # plus in front of a negative number renders "+-3.1%", which reads
            # as a positive edge at a glance. That is the one typo in a betting
            # tool that costs money.
            tc = p.get("poly_taker_cost")
            take_ev = (100 * (p["model_prob"] / tc - 1)) if tc else None
            take_s = f"{take_ev:>+6.1f}%" if take_ev is not None else "     —"
            gap = f"{(p['edge_pct'] - take_ev):>+5.1f}pp" if take_ev is not None else "     —"
            # "tradeable" = notional deployable before the blended taker cost
            # stops clearing min_ev. A big edge on a shallow book is a rounding
            # error wearing a percentage sign.
            ms = p.get("poly_max_stake_usd")
            size_s = (f"${ms:>8,.0f}" if ms else ("     thin" if ms == 0 else "        ?"))
            print(f"  {'':6} {p['team']:<22.22} {p['poly_cost']:>6.3f} "
                  f"{p['model_prob']:>6.3f} {p['edge_pct']:>+6.1f}% {take_s} {size_s}")
        print("  " + "─" * 74)
        print(f"  MAKE = rest inside the bid, no fee, fills only if the market comes to you.")
        print(f"  tradeable = $ that clears {min_ev:.0f}% EV after walking the ask ladder,")
        print(f"              i.e. TAKER capacity right now. 'thin' means you cannot")
        print(f"              deploy into it by crossing — it says nothing about maker")
        print(f"              capacity, which is unknown until fills are measured.")
        print(f"  TAKE = cross the spread at the ask + sports_fees_v2 taker fee.")
        print(f"  Flat ${stake:.2f}/pick at {PILOT_STAKE_FRAC:.0%} of a ${bankroll:.0f} bankroll.")
        print("  Shadow only — the $112 stays parked until fills + CLV say otherwise.")
    else:
        print(f"\n  No Polymarket edges ≥ {min_ev}% today — "
              "tight boards are the normal state; the edge is patience.")

    if as_json:
        print(json.dumps(all_picks, indent=2, default=str))

    if all_picks and not dry_run:
        added = log_polymarket_picks(all_picks, eff_date)
        print(f"  Logged {added} shadow pick(s) (strategy=polymarket_ev)")
    elif dry_run:
        print("  (dry run — nothing written)")
    return all_picks


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Polymarket-vs-Pinnacle scanner (shadow)")
    ap.add_argument("--date", help="slate date YYYY-MM-DD (default: today)")
    ap.add_argument("--min-ev", type=float, default=MIN_EV_PCT)
    ap.add_argument("--min-liquidity", type=float, default=MIN_LIQUIDITY_USD)
    ap.add_argument("--bankroll", type=float, default=112.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args()
    run(date_str=a.date, min_ev=a.min_ev, min_liquidity=a.min_liquidity,
        bankroll=a.bankroll, dry_run=a.dry_run, as_json=a.as_json)
