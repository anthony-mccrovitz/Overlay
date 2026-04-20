"""
src/tracking/schema.py — Canonical pick schema for ChefTonyBets.

Every pick written to data/pnl/picks.json uses this schema.
Both MLB and NBA write paths import from here — one format, no surprises.

SCHEMA (all fields, all sports)
────────────────────────────────────────────────────────────────────
  pick_id     str    "{sport}_{YYYYMMDD}_{team-slug}_{market}_{direction}"
  date        str    "YYYY-MM-DD"  game date in Eastern time
  sport       str    "mlb" | "nba" | "nfl"
  market      str    "moneyline" | "spread" | "total" | "nrfi" | "prop"
  direction   str    "WIN" | "COVER" | "OVER" | "UNDER" | "NRFI" | "YRFI"
  team        str    the bet side: team name, or "OVER 8.5" for totals
  matchup     str    "Away @ Home"  canonical game string
  odds        int    American odds: +140 or -110
  line        float  spread/total line; None for moneyline/NRFI
  sportsbook  str    "DraftKings" | "FanDuel" | "BetMGM" | "BetRivers" | None
  model_prob  float  model win probability [0, 1]
  edge_pct    float  (model_prob − implied_prob) × 100 — percentage points, not fraction
  stake       float  units staked: 1.0 = card pick; 0.0 = logged-only (not counted)
  card_pick   bool   True → posted on pick card → counts toward official record
  result      str    None | "win" | "loss" | "push"
  profit      float  units profit: +1.40 for +140 win on 1u; −1.0 for any loss
  recorded_at str    ISO 8601 UTC when pick was created
  resulted_at str    ISO 8601 UTC when result was set; None if pending
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import re
from typing import Any


# Required fields — every canonical pick must have these.
CANONICAL_FIELDS = (
    "pick_id", "date", "sport", "market", "direction",
    "team", "matchup", "odds", "line", "sportsbook",
    "model_prob", "edge_pct", "stake", "card_pick",
    "result", "profit", "recorded_at", "resulted_at",
)

_MARKET_ALIASES: dict[str, str] = {
    "h2h":        "moneyline",
    "ml":         "moneyline",
    "money_line": "moneyline",
    "moneylines": "moneyline",
    "run_line":   "spread",
    "runline":    "spread",
    "rl":         "spread",
    "spreads":    "spread",
    "over_under": "total",
    "totals":     "total",
    "ou":         "total",
}

_DEFAULT_DIRECTION: dict[str, str] = {
    "moneyline": "WIN",
    "spread":    "COVER",
    "nrfi":      "NRFI",
    "prop":      "OVER",
}


# ─────────────────────────── Public helpers ─────────────────────────────────

def make_pick_id(sport: str, date: str, team: str, market: str, direction: str) -> str:
    """
    Deterministic pick ID — safe to use as a deduplication key.

    Format: "{sport}_{YYYYMMDD}_{team-slug}_{market}_{direction}"
    Examples:
      mlb_20260418_milwaukee-brewers_moneyline_win
      nba_20260417_orlando-magic_spread_cover
      mlb_20260418_over-8.5_total_over
    """
    date_c = date.replace("-", "")[:8]
    slug   = re.sub(r"[^a-z0-9]+", "-", team.lower()).strip("-")[:40]
    return f"{sport}_{date_c}_{slug}_{market}_{direction}".lower()


def profit_from_odds(odds: int | float, stake: float, won: bool) -> float:
    """
    Compute units profit from American odds.

    Canonical profit scale: stake=1.0 → 1 unit.
      win  +140 → +1.40u
      win  −110 → +0.909u
      loss any  → −stake
      push any  → 0.0u  (caller passes won=False, profit=0.0)
    """
    if not won:
        return -stake
    o = float(odds)
    if o >= 0:
        return stake * o / 100.0
    return stake * 100.0 / abs(o)


def validate_pick(pick: dict) -> list[str]:
    """Return a list of schema violations. Empty list means valid."""
    issues: list[str] = []
    for f in CANONICAL_FIELDS:
        if f not in pick:
            issues.append(f"missing field: {f}")

    market = pick.get("market", "")
    if market not in ("moneyline", "spread", "total", "nrfi", "prop", "unknown"):
        issues.append(f"invalid market: {market!r}")

    direction = pick.get("direction", "")
    if direction not in ("WIN", "COVER", "OVER", "UNDER", "NRFI", "YRFI", ""):
        issues.append(f"invalid direction: {direction!r}")

    result = pick.get("result")
    if result not in (None, "win", "loss", "push"):
        issues.append(f"invalid result: {result!r}")

    odds = pick.get("odds")
    if odds is not None and not isinstance(odds, (int, float)):
        issues.append(f"odds must be numeric, got {type(odds).__name__}")

    profit = pick.get("profit")
    result_v = pick.get("result")
    odds_v   = pick.get("odds")
    # NRFI picks have odds=None (market not available on standard books)
    # so profit=None on a settled NRFI is acceptable.
    if result_v in ("win", "loss") and profit is None and odds_v is not None:
        issues.append("profit is None but result is set — grading bug")

    return issues


# ─────────────────────────── Normalization ──────────────────────────────────

def normalize_pick(raw: dict[str, Any]) -> dict | None:
    """
    Map any legacy pick dict to the canonical schema.

    Returns None for entries that are fundamentally corrupted and should be
    removed (e.g. paper-trade dollar-scale entries with bet_type instead of
    market, or entries with no identifiable team or date).

    The normalizer is idempotent: passing an already-canonical pick returns
    an identical pick. It never re-calculates profit for picks that already
    have a result — it trusts the stored value.
    """
    # ── Filter corrupted entries ─────────────────────────────────────────────
    # Paper-trade entries from an old code path use bet_type (not market) and
    # store dollar-scale profits (e.g. profit=96.15 on bet_size=100).
    if raw.get("bet_type") and not raw.get("market"):
        return None
    if not raw.get("team") or not raw.get("date"):
        return None

    # ── Sport ────────────────────────────────────────────────────────────────
    sport = str(raw.get("sport") or "mlb").lower().strip()

    # ── Market ───────────────────────────────────────────────────────────────
    raw_market = str(raw.get("market") or "moneyline").lower().strip()
    market = _MARKET_ALIASES.get(raw_market, raw_market)

    # ── Team ─────────────────────────────────────────────────────────────────
    team = str(raw.get("team") or "").strip()

    # ── Date ─────────────────────────────────────────────────────────────────
    date_ = str(raw.get("date") or "").strip()
    # Normalize YYYY-MM-DD; leave YYYYMMDD as-is (pick_id will strip dashes)
    if len(date_) == 8 and "-" not in date_:
        date_ = f"{date_[:4]}-{date_[4:6]}-{date_[6:]}"

    # ── Direction ────────────────────────────────────────────────────────────
    direction = str(raw.get("direction") or "").upper().strip()
    if not direction:
        if market == "total":
            parts = team.upper().split()
            direction = parts[0] if parts and parts[0] in ("OVER", "UNDER") else "OVER"
        else:
            direction = _DEFAULT_DIRECTION.get(market, "WIN")

    # ── Line ─────────────────────────────────────────────────────────────────
    line: float | None = raw.get("line") or raw.get("bet_line")
    if line is None and market == "total":
        parts = team.upper().split()
        try:
            line = float(parts[1]) if len(parts) > 1 else None
        except (ValueError, IndexError):
            line = None
    if line is not None:
        try:
            line = float(line)
        except (ValueError, TypeError):
            line = None

    # ── Matchup ──────────────────────────────────────────────────────────────
    matchup = str(raw.get("matchup") or "").strip()
    if not matchup:
        opponent = str(raw.get("opponent") or "").strip()
        if market == "nrfi":
            matchup = team      # NRFI team field IS the matchup ("Away @ Home")
        elif market == "total" and opponent:
            matchup = opponent  # totals opponent = "Away @ Home" already
        elif opponent:
            matchup = f"{team} vs {opponent}"

    # ── Sportsbook ───────────────────────────────────────────────────────────
    sportsbook = raw.get("sportsbook") or raw.get("book") or None
    if sportsbook:
        sportsbook = str(sportsbook).strip() or None

    # ── Odds ─────────────────────────────────────────────────────────────────
    odds_raw = raw.get("odds") or raw.get("best_odds")
    odds: int | None = None
    if odds_raw is not None:
        try:
            odds = int(float(odds_raw))
        except (ValueError, TypeError):
            odds = None

    # ── Stake ────────────────────────────────────────────────────────────────
    stake_raw = raw.get("stake") or raw.get("bet_size") or 0.0
    try:
        stake = float(stake_raw)
    except (ValueError, TypeError):
        stake = 0.0

    # ── Card pick ────────────────────────────────────────────────────────────
    # Existing entries may have card_pick set. For old entries without it,
    # treat stake > 0 as the card-pick signal.
    if "card_pick" in raw:
        card_pick = bool(raw["card_pick"])
    else:
        card_pick = stake > 0

    # ── Model prob ───────────────────────────────────────────────────────────
    model_prob_raw = raw.get("model_prob") or raw.get("win_prob")
    model_prob: float | None = None
    if model_prob_raw is not None:
        try:
            model_prob = float(model_prob_raw)
        except (ValueError, TypeError):
            model_prob = None

    # ── Edge (percentage points) ──────────────────────────────────────────────
    # Canonical: edge_pct is already a percentage (2.52 = 2.52%).
    # Legacy "edge" field was also stored as percentage (confirmed from data).
    edge_pct: float | None = None
    edge_raw = raw.get("edge_pct") or raw.get("edge")
    if edge_raw is not None:
        try:
            edge_pct = float(edge_raw)
        except (ValueError, TypeError):
            edge_pct = None

    # ── Result / Profit ───────────────────────────────────────────────────────
    result = raw.get("result")
    if result not in (None, "win", "loss", "push"):
        result = None

    profit_raw = raw.get("profit")
    profit: float | None = None
    if profit_raw is not None:
        try:
            profit = float(profit_raw)
        except (ValueError, TypeError):
            profit = None

    # ── Timestamps ────────────────────────────────────────────────────────────
    recorded_at = str(raw.get("recorded_at") or "")
    resulted_at = raw.get("resulted_at") or None

    # ── Pick ID ───────────────────────────────────────────────────────────────
    pick_id = raw.get("pick_id") or make_pick_id(sport, date_, team, market, direction)

    return {
        "pick_id":     pick_id,
        "date":        date_,
        "sport":       sport,
        "market":      market,
        "direction":   direction,
        "team":        team,
        "matchup":     matchup,
        "odds":        odds,
        "line":        line,
        "sportsbook":  sportsbook,
        "model_prob":  round(model_prob, 4) if model_prob is not None else None,
        "edge_pct":    round(edge_pct, 2) if edge_pct is not None else None,
        "stake":       stake,
        "card_pick":   card_pick,
        "result":      result,
        "profit":      round(profit, 4) if profit is not None else None,
        "recorded_at": recorded_at,
        "resulted_at": resulted_at,
    }


def migrate_picks_file(path_in: str, path_out: str | None = None) -> dict:
    """
    Migrate a picks.json file to the canonical schema.

    - Normalizes all picks to canonical fields.
    - Removes corrupted entries (bet_type schema, no team/date).
    - Deduplicates on pick_id, keeping the first occurrence by recorded_at.
    - Writes atomically: writes to a temp path then renames.

    Returns summary: {total_in, removed, deduplicated, total_out}
    """
    import json
    import os
    import tempfile
    from pathlib import Path

    src = Path(path_in)
    dst = Path(path_out or path_in)

    if not src.exists():
        return {"error": f"{src} not found"}

    with open(src, encoding="utf-8") as f:
        data = json.load(f)

    raw_picks = data.get("picks", [])
    total_in  = len(raw_picks)
    removed   = 0
    normalized: list[dict] = []

    for raw in raw_picks:
        pick = normalize_pick(raw)
        if pick is None:
            removed += 1
            continue
        normalized.append(pick)

    # Deduplicate: sort by recorded_at ascending, keep first per pick_id
    normalized.sort(key=lambda p: p.get("recorded_at") or "")
    seen_ids: set[str] = set()
    deduped:  list[dict] = []
    deduplicated = 0
    for p in normalized:
        pid = p["pick_id"]
        if pid in seen_ids:
            deduplicated += 1
            continue
        seen_ids.add(pid)
        deduped.append(p)

    # Restore chronological order
    deduped.sort(key=lambda p: p.get("recorded_at") or "")

    out_data = {**data, "picks": deduped}

    # Atomic write
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(out_data, f, indent=2)
        os.replace(tmp, dst)
    except Exception:
        os.unlink(tmp)
        raise

    return {
        "total_in":     total_in,
        "removed":      removed,
        "deduplicated": deduplicated,
        "total_out":    len(deduped),
    }
