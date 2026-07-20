#!/usr/bin/env python3
"""
Polymarket-vs-Pinnacle price scanner — shadow strategy `polymarket_ev`.

The thesis (same as devig_ev, different venue): Pinnacle's devigged price is
the best public estimate of true probability. When Polymarket lets you buy a
team's win contract CHEAPER than Pinnacle fair — after crossing the spread
(you buy at the ASK, never the mid) and the ~2% fee — that's +EV.

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
)

_ET = ZoneInfo("America/New_York")
PICKS_FILE = Path("data/pnl/picks.json")

MIN_EV_PCT = 2.0          # same bar as devig_ev/consensus_ev — comparable verdicts
MIN_LIQUIDITY_USD = 1000  # below this the "price" is a ghost; fills would move it
PILOT_STAKE_FRAC = 0.04   # flat 4% of bankroll per pick (guidance only)
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


def _is_moneyline_market(pm: PolyMarket) -> bool:
    """Only full-game/fight moneyline markets may be priced against the
    Pinnacle h2h fair. Prefer Gamma's own sportsMarketType label; fall back to
    shape heuristics for markets that lack it."""
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


def _entry_cost_for_outcome(pm: PolyMarket, idx: int) -> tuple[float, dict]:
    """True entry cost (ask + fee) for outcome idx, preferring that outcome's
    own CLOB book. Returns (cost, debug_info)."""
    token = pm.token_ids[idx] if idx < len(pm.token_ids) else None
    book = fetch_order_book(token) if token else None
    if book and book.get("best_ask") is not None:
        cost = pm.entry_cost("yes", book=book)
        return cost, {"token_id": token, "poly_ask": book["best_ask"], "source": "clob"}
    # Fallback: Gamma snapshot. Outcome 0 = the market's YES side; outcome 1's
    # ask ≈ 1 − YES best bid.
    side = "yes" if idx == 0 else "no"
    cost = pm.entry_cost(side)
    return cost, {"token_id": token,
                  "poly_ask": pm.best_ask if idx == 0 else None,
                  "source": "gamma"}


def scan_sport(sport: str, odds_df, poly_markets: list[PolyMarket],
               eff_date: str, min_ev: float = MIN_EV_PCT,
               min_liquidity: float = MIN_LIQUIDITY_USD) -> list[dict]:
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

            cost, dbg = _entry_cost_for_outcome(pm, idx)
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
                "poly_ask":       dbg.get("poly_ask"),
                "poly_mid":       pm.yes_prob if idx == 0 else pm.no_prob,
                "poly_price_source": dbg.get("source"),
                "poly_liquidity_usd": pm.liquidity_usd,
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
    sports = DEFAULT_SPORTS + _active_tennis_sports()

    # Event fetch window: wide, because main game events carry endDate = game
    # + ~7 days (resolution buffer). Per-market gameStartTime does the precise
    # slate gating inside scan_sport.
    end_min = f"{eff_date}T00:00:00Z"
    end_max = (datetime.fromisoformat(eff_date)
               + timedelta(days=_EVENT_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

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
                           min_ev=min_ev, min_liquidity=min_liquidity)
        if picks:
            print(f"  [polymarket] {sport}: {len(picks)} edge(s)")
        all_picks.extend(picks)

    # ── Report ────────────────────────────────────────────────────────────
    stake = round(bankroll * PILOT_STAKE_FRAC, 2)
    if all_picks:
        print(f"\n  POLYMARKET vs PINNACLE — {eff_date}   "
              f"(pilot ${bankroll:.0f}, flat ${stake:.2f}/pick)")
        print("  " + "─" * 74)
        for p in sorted(all_picks, key=lambda x: -x["edge_pct"]):
            print(f"  +{p['edge_pct']:>4.1f}%  {p['team']:<28.28} "
                  f"cost {p['poly_cost']:.3f} vs fair {p['model_prob']:.3f} "
                  f"[{p['fair_source'] or '?':<8}] ~${stake:.2f}")
        print("  " + "─" * 74)
        print("  Shadow only — the $112 stays parked until the 300-bet CLV verdict.")
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
