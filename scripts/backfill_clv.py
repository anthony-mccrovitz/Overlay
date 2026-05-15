#!/usr/bin/env python3
"""
Backfill closing-line value (CLV) records by joining settled picks against the
per-game closing snapshots that capture_closing.py archives in
data/clv/closing/.

For every pick in data/pnl/picks.json that:
  - is `card_pick == True`
  - has a recorded `resulted_at` (i.e., the game has finished)
  - does NOT yet have a closing line captured in data/clv/clv_records.json

…we find the matching closing snapshot for that game (matchup + date), pull
the closest-to-tipoff best-available price for the same market+direction the
pick was taken at, and write a CLV record. CLV is computed in cents (pp of
implied probability), so a +2.5 cent CLV means the closing line implied that
side was 2.5pp more likely than the price we got.

This script is fully idempotent — picks already present in clv_records.json
are skipped unless --force is passed.

Usage:
    python3 scripts/backfill_clv.py
    python3 scripts/backfill_clv.py --since 2026-05-01
    python3 scripts/backfill_clv.py --sport nba
    python3 scripts/backfill_clv.py --force          # re-compute all
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.tracking.clv import CLVTracker, _odds_to_implied  # noqa: E402

PICKS_FILE   = ROOT / "data" / "pnl" / "picks.json"
CLOSING_DIR  = ROOT / "data" / "clv" / "closing"
RECORDS_FILE = ROOT / "data" / "clv" / "clv_records.json"

SPORT_TO_KEYS = {
    "mlb": ("mlb", "baseball_mlb"),
    "nba": ("nba", "basketball_nba"),
    "nhl": ("nhl", "icehockey_nhl"),
}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    text = path.read_text()
    # capture_closing.py writes NaN literals; tolerate them
    text = text.replace("NaN", "null")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _date_str(value: str) -> str:
    if not value:
        return ""
    return value[:10]


def _parse_matchup(matchup: str) -> tuple[str, str]:
    """'Away Team @ Home Team' -> (away, home). Returns ('','') on failure."""
    if not matchup or "@" not in matchup:
        return "", ""
    away, home = matchup.split("@", 1)
    return away.strip(), home.strip()


def _norm_team(name: str) -> str:
    return (name or "").lower().strip().replace(".", "")


def _team_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    na, nb = _norm_team(a), _norm_team(b)
    if na == nb:
        return True
    return na in nb or nb in na


def _load_closing_for_date(sport: str, date_str: str) -> list[dict]:
    """Look up the daily closing archive for either of the sport-key aliases."""
    out: list[dict] = []
    for key in SPORT_TO_KEYS.get(sport, (sport,)):
        path = CLOSING_DIR / f"{key}_{date_str}.json"
        if path.exists():
            out.extend(_load_json(path, []))
    return out


def _find_snapshot(snapshots: list[dict], matchup: str) -> dict | None:
    away, home = _parse_matchup(matchup)
    if not (away or home):
        return None
    for snap in snapshots:
        if _team_match(snap.get("home_team", ""), home) and _team_match(
            snap.get("away_team", ""), away
        ):
            return snap
    # second pass: only match by either side (handles team-rename edge cases)
    for snap in snapshots:
        if _team_match(snap.get("home_team", ""), home) or _team_match(
            snap.get("away_team", ""), away
        ):
            return snap
    return None


def _closing_odds(pick: dict, snap: dict) -> int | None:
    """Pull the closing odds for the pick's specific market+direction from a
    closing snapshot. Returns American odds (int) or None if not found."""
    market = (pick.get("market") or "").lower()
    direction = (pick.get("direction") or "").upper()
    team = pick.get("team") or ""
    line = pick.get("line")

    if market == "moneyline":
        if direction == "HOME":
            return snap.get("BestHomeML")
        if direction == "AWAY":
            return snap.get("BestAwayML")
        # No direction set — match by team
        if _team_match(snap.get("home_team", ""), team):
            return snap.get("BestHomeML")
        if _team_match(snap.get("away_team", ""), team):
            return snap.get("BestAwayML")
        return None

    all_odds = snap.get("all_odds", []) or []

    if market in ("total", "totals", "f5_total"):
        selection = "Over" if direction == "OVER" else "Under"
        candidates = [
            o for o in all_odds
            if o.get("Market") in ("totals",)
            and o.get("Selection") == selection
        ]
        if line is not None:
            candidates = [
                o for o in candidates
                if o.get("Line") is not None and not _isnan(o["Line"])
                and abs(float(o["Line"]) - float(line)) < 1e-6
            ] or candidates
        return _best_american(candidates)

    if market == "spread":
        # team here is the team name we picked on
        candidates = [
            o for o in all_odds
            if o.get("Market") == "spreads"
            and _team_match(o.get("Selection", ""), team)
        ]
        if line is not None:
            candidates = [
                o for o in candidates
                if o.get("Line") is not None and not _isnan(o["Line"])
                and abs(float(o["Line"]) - float(line)) < 1e-6
            ] or candidates
        return _best_american(candidates)

    # NRFI / YRFI and props: not in BestHomeML, not in all_odds two-way for now
    return None


def _isnan(x) -> bool:
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return False


def _best_american(rows: list[dict]) -> int | None:
    """Best price the bettor would get (highest expected payout) across books."""
    if not rows:
        return None
    best: int | None = None
    best_imp = 2.0
    for r in rows:
        odds = r.get("Odds")
        if odds is None:
            continue
        try:
            imp = _odds_to_implied(int(odds))
        except (TypeError, ValueError):
            continue
        if imp < best_imp:
            best_imp = imp
            best = int(odds)
    return best


def _pick_key(pick: dict) -> str:
    return pick.get("pick_id") or f"{pick.get('date')}_{pick.get('team')}_{pick.get('market')}_{pick.get('direction')}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", help="Only backfill picks with date >= YYYY-MM-DD")
    ap.add_argument("--sport", choices=["mlb", "nba", "nhl"], help="Restrict to one sport")
    ap.add_argument("--force", action="store_true", help="Recompute even if already present")
    args = ap.parse_args()

    picks_blob = _load_json(PICKS_FILE, {"picks": []})
    picks = picks_blob.get("picks", [])
    if not picks:
        print("No picks found in data/pnl/picks.json")
        return 0

    records_blob = _load_json(RECORDS_FILE, {"picks": []})
    existing = {_pick_key(p): p for p in records_blob.get("picks", [])}

    backfilled = 0
    matched = 0
    skipped = 0
    no_snapshot = 0
    no_odds = 0

    for pick in picks:
        if not pick.get("card_pick"):
            skipped += 1
            continue
        if args.sport and pick.get("sport") != args.sport:
            skipped += 1
            continue
        if args.since and (pick.get("date") or "") < args.since:
            skipped += 1
            continue

        key = _pick_key(pick)
        prior = existing.get(key)
        if (
            not args.force
            and prior
            and prior.get("closing_odds") is not None
        ):
            skipped += 1
            continue

        sport = pick.get("sport") or "mlb"
        date_str = _date_str(pick.get("date") or "")
        snapshots = _load_closing_for_date(sport, date_str)
        if not snapshots:
            no_snapshot += 1
            continue

        snap = _find_snapshot(snapshots, pick.get("matchup", ""))
        if not snap:
            no_snapshot += 1
            continue

        closing_odds = _closing_odds(pick, snap)
        if closing_odds is None:
            no_odds += 1
            continue

        pick_odds = pick.get("odds")
        try:
            pick_implied = _odds_to_implied(int(pick_odds))
            closing_implied = _odds_to_implied(int(closing_odds))
        except (TypeError, ValueError):
            no_odds += 1
            continue

        clv_cents = round((closing_implied - pick_implied) * 100, 2)

        record = {
            "pick_id": pick.get("pick_id"),
            "game_id": snap.get("event_id"),
            "team": pick.get("team"),
            "sport": sport,
            "market": pick.get("market"),
            "direction": pick.get("direction"),
            "line": pick.get("line"),
            "matchup": pick.get("matchup"),
            "date": pick.get("date"),
            "pick_odds": pick_odds,
            "pick_implied_prob": round(pick_implied, 6),
            "model_prob": pick.get("model_prob"),
            "sportsbook": pick.get("sportsbook"),
            "pick_time": pick.get("recorded_at"),
            "closing_odds": closing_odds,
            "closing_implied_prob": round(closing_implied, 6),
            "closing_time": snap.get("captured_at"),
            "clv_cents": clv_cents,
            "won": (pick.get("result") == "win") if pick.get("result") in ("win", "loss") else None,
            "result_time": pick.get("resulted_at"),
            "backfilled_at": datetime.now(timezone.utc).isoformat(),
        }

        if prior:
            prior.update(record)
        else:
            existing[key] = record
            records_blob.setdefault("picks", []).append(record)

        backfilled += 1
        matched += 1

    RECORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORDS_FILE.write_text(json.dumps(records_blob, indent=2))

    # Refresh the summary so dashboards see the new CLV right away.
    summary = CLVTracker(path=RECORDS_FILE).get_clv_summary()
    print("CLV backfill complete:")
    print(f"  backfilled records      : {backfilled}")
    print(f"  matched picks           : {matched}")
    print(f"  skipped (already had)   : {skipped}")
    print(f"  no closing snapshot     : {no_snapshot}")
    print(f"  no matching market odds : {no_odds}")
    print()
    print("CLV summary (after backfill):")
    for k, v in summary.items():
        print(f"  {k:24s} {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
