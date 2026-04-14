"""
CLV Tracker — Closing Line Value analysis.

CLV = the line at game time vs the line you got.
Positive CLV over many bets = your process is +EV regardless of results.

How to use:
  1. After running `predict.py --daily`, call snapshot_opening_lines() to
     freeze today's odds as the "opening" (pick-time) line.
  2. After games start (or at game time), call fetch_closing_lines() to pull
     the final odds from the cache.
  3. Call compute_clv(date_str) to score each pick.
  4. Call print_clv_report() to see the dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


# ── Paths ──────────────────────────────────────────────────────────────────────

SNAPSHOTS_FILE = Path("data/clv/snapshots.json")
ODDS_CACHE_DIR  = Path("data/cache/odds")
PICKS_OUTPUT_DIR = Path("output/picks")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _odds_to_implied(odds: float | int) -> float:
    """Convert American odds to implied probability (no vig removed)."""
    if odds == 0:
        return 0.5
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _load_snapshots() -> list[dict]:
    SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SNAPSHOTS_FILE.exists():
        return []
    try:
        return json.loads(SNAPSHOTS_FILE.read_text())
    except (json.JSONDecodeError, ValueError):
        return []


def _save_snapshots(records: list[dict]) -> None:
    SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_FILE.write_text(json.dumps(records, indent=2))


# ── Core functions ─────────────────────────────────────────────────────────────

def snapshot_opening_lines(
    picks_json_path: str | Path | None = None,
    sport: str = "baseball_mlb",
    game_date: "date | None" = None,
) -> int:
    """
    Read today's generated picks from output/picks/<sport>/YYYYMMDD/picks.json
    and store each pick's current odds as the "opening line" in
    data/clv/snapshots.json.

    Returns the number of new snapshots added.

    Schema stored per pick:
      {date, team, opponent, opening_odds, opening_implied_prob, snapshot_time}
    """
    from datetime import date as _date

    effective_date = game_date or _date.today()
    today_str = effective_date.strftime("%Y%m%d")

    if picks_json_path is None:
        picks_json_path = PICKS_OUTPUT_DIR / sport / today_str / "picks.json"

    picks_json_path = Path(picks_json_path)
    if not picks_json_path.exists():
        print(f"  [CLV] No picks file found at {picks_json_path}")
        return 0

    try:
        picks = json.loads(picks_json_path.read_text())
    except (json.JSONDecodeError, ValueError):
        print(f"  [CLV] Could not parse {picks_json_path}")
        return 0

    snapshots = _load_snapshots()
    snap_keys = {
        (s.get("date", ""), s.get("team", "").lower().strip())
        for s in snapshots
    }

    now_ts   = datetime.now(tz=timezone.utc).isoformat()
    date_str = effective_date.isoformat()
    added    = 0

    for pick in picks:
        team = str(pick.get("Team", "")).strip()
        if not team:
            continue
        key = (date_str, team.lower().strip())
        if key in snap_keys:
            continue

        odds = float(pick.get("BestOdds") or 0)
        snap = {
            "date":                 date_str,
            "team":                 team,
            "opponent":             str(pick.get("Opponent", "?")).strip(),
            "sport":                sport,
            "opening_odds":         odds,
            "opening_implied_prob": round(_odds_to_implied(odds), 6),
            "snapshot_time":        now_ts,
            "closing_odds":         None,
            "closing_implied_prob": None,
            "clv":                  None,
            "clv_pct":              None,
        }
        snapshots.append(snap)
        snap_keys.add(key)
        added += 1

    if added > 0:
        _save_snapshots(snapshots)

    return added


def fetch_closing_lines(
    date_str: str | None = None,
    sport: str = "baseball_mlb",
) -> dict[str, float]:
    """
    Read the odds cache from data/cache/odds/<sport>_latest.json and extract
    the best available moneyline for each team.

    Returns a dict mapping team name (lower-case) -> best moneyline odds.
    """
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    cache_path = ODDS_CACHE_DIR / f"{sport}_latest.json"
    if not cache_path.exists():
        print(f"  [CLV] Odds cache not found: {cache_path}")
        return {}

    try:
        raw = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, ValueError):
        print(f"  [CLV] Could not parse odds cache: {cache_path}")
        return {}

    # raw is a list of game objects from the Odds API
    # Each game has bookmakers -> markets -> outcomes with name/price
    closing: dict[str, list[float]] = {}

    for game in raw:
        for book in game.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    team_lower = outcome.get("name", "").lower().strip()
                    price      = outcome.get("price")
                    if team_lower and price is not None:
                        closing.setdefault(team_lower, []).append(float(price))

    # Use the best (most favorable) odds per team across all books
    return {
        team: max(prices, key=lambda p: p if p > 0 else -10000 / abs(p))
        for team, prices in closing.items()
    }


def compute_clv(date_str: str | None = None) -> list[dict]:
    """
    For each snapshot on date_str, fill in closing odds from the cache and
    compute CLV:

      clv     = closing_implied_prob - opening_implied_prob
      clv_pct = clv * 100

    Positive CLV means you got a better number than the closing line —
    a sign of genuine edge.

    Updates snapshots in-place and returns the updated records for that date.
    """
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    snapshots = _load_snapshots()
    day_snaps = [s for s in snapshots if s.get("date") == date_str]

    if not day_snaps:
        print(f"  [CLV] No opening-line snapshots for {date_str}.")
        print(f"        Run snapshot_opening_lines() after generating picks.")
        return []

    # Guess sport from first snapshot (default to baseball_mlb)
    sport = day_snaps[0].get("sport", "baseball_mlb")
    closing_map = fetch_closing_lines(date_str=date_str, sport=sport)

    updated = 0
    for snap in day_snaps:
        team_lower = snap["team"].lower().strip()

        # Try exact match first, then partial
        closing_odds = closing_map.get(team_lower)
        if closing_odds is None:
            for key, val in closing_map.items():
                if team_lower in key or key in team_lower:
                    closing_odds = val
                    break

        if closing_odds is None:
            continue  # no closing line available yet

        closing_imp = _odds_to_implied(closing_odds)
        clv         = closing_imp - snap["opening_implied_prob"]

        snap["closing_odds"]         = closing_odds
        snap["closing_implied_prob"] = round(closing_imp, 6)
        snap["clv"]                  = round(clv, 6)
        snap["clv_pct"]              = round(clv * 100, 3)
        updated += 1

    if updated > 0:
        _save_snapshots(snapshots)

    return day_snaps


def get_clv_summary() -> dict:
    """
    Aggregate CLV stats across all snapshots with closing-line data.

    Returns:
      total_picks, with_clv, avg_clv_pct, positive_clv_pct,
      clv_by_tier (dict of tier -> {count, avg_clv_pct})
    """
    snapshots = _load_snapshots()
    with_clv  = [s for s in snapshots if s.get("clv") is not None]

    if not with_clv:
        return {
            "total_picks":    len(snapshots),
            "with_clv":       0,
            "avg_clv_pct":    0.0,
            "positive_clv_pct": 0.0,
            "clv_by_tier":    {},
            "verdict":        "No CLV data yet — run compute_clv() after games start.",
        }

    clv_vals = [s["clv_pct"] for s in with_clv]
    avg_clv  = sum(clv_vals) / len(clv_vals)
    pos_pct  = sum(1 for v in clv_vals if v > 0) / len(clv_vals) * 100

    # Group by edge tier if available in snapshot (from picks.json source)
    # We infer tier from opening_implied_prob vs model pick data if present
    tier_buckets: dict[str, list[float]] = {"HIGH": [], "MED": [], "LOW": [], "UNKNOWN": []}
    for s in with_clv:
        edge = s.get("edge")
        if edge is None:
            tier_buckets["UNKNOWN"].append(s["clv_pct"])
        elif edge >= 0.08:
            tier_buckets["HIGH"].append(s["clv_pct"])
        elif edge >= 0.04:
            tier_buckets["MED"].append(s["clv_pct"])
        else:
            tier_buckets["LOW"].append(s["clv_pct"])

    clv_by_tier = {}
    for tier, vals in tier_buckets.items():
        if vals:
            clv_by_tier[tier] = {
                "count":       len(vals),
                "avg_clv_pct": round(sum(vals) / len(vals), 3),
            }

    n = len(with_clv)
    if n < 20:
        verdict = f"EARLY DATA — {n} picks with CLV (need 50+ for significance)"
    elif avg_clv > 2.0:
        verdict = "STRONG EDGE — consistently beating the closing line"
    elif avg_clv > 0.5:
        verdict = "POSITIVE CLV — model shows real edge against the market"
    elif avg_clv > -0.5:
        verdict = "NEUTRAL — model roughly matches closing line efficiency"
    else:
        verdict = "NEGATIVE CLV — getting worse lines than closing"

    return {
        "total_picks":      len(snapshots),
        "with_clv":         n,
        "avg_clv_pct":      round(avg_clv, 3),
        "positive_clv_pct": round(pos_pct, 1),
        "clv_by_tier":      clv_by_tier,
        "verdict":          verdict,
    }


def print_clv_report() -> None:
    """Print a formatted CLV dashboard to the terminal."""
    W = 60
    summary = get_clv_summary()

    print(f"\n{'═' * W}")
    print(f"  CLV REPORT — CLOSING LINE VALUE")
    print(f"{'═' * W}")
    print(f"  Total picks tracked : {summary['total_picks']}")
    print(f"  Picks with CLV data : {summary['with_clv']}")

    if summary["with_clv"] == 0:
        print(f"\n  {summary['verdict']}")
        print(f"\n  Run after generating picks:")
        print(f"    from src.analytics.clv_tracker import snapshot_opening_lines, compute_clv")
        print(f"    snapshot_opening_lines()   # right after predict.py --daily")
        print(f"    compute_clv()              # at game time / after lines move")
        print(f"{'═' * W}\n")
        return

    sign = "+" if summary["avg_clv_pct"] >= 0 else ""
    print(f"  Avg CLV             : {sign}{summary['avg_clv_pct']:.2f}%")
    print(f"  % bets positive CLV : {summary['positive_clv_pct']:.1f}%")
    print(f"\n  VERDICT: {summary['verdict']}")

    if summary["clv_by_tier"]:
        print(f"\n  CLV by Edge Tier:")
        print(f"  {'Tier':<10} {'Count':>6}  {'Avg CLV':>8}")
        print(f"  {'─'*30}")
        for tier in ("HIGH", "MED", "LOW", "UNKNOWN"):
            if tier in summary["clv_by_tier"]:
                d    = summary["clv_by_tier"][tier]
                s    = "+" if d["avg_clv_pct"] >= 0 else ""
                print(f"  {tier:<10} {d['count']:>6}  {s}{d['avg_clv_pct']:>7.2f}%")

    snapshots = _load_snapshots()
    recent = [s for s in snapshots if s.get("clv") is not None][-10:]
    if recent:
        print(f"\n  Recent picks:")
        print(f"  {'Date':<12} {'Team':<28} {'Open':>6}  {'Close':>6}  {'CLV':>7}")
        print(f"  {'─'*62}")
        for s in recent:
            open_s  = f"{int(s['opening_odds']):+d}"  if s.get("opening_odds") else "  —"
            close_s = f"{int(s['closing_odds']):+d}" if s.get("closing_odds") else "  —"
            clv_s   = f"{s['clv_pct']:+.1f}%" if s.get("clv_pct") is not None else "  —"
            print(f"  {s['date']:<12} {s['team']:<28} {open_s:>6}  {close_s:>6}  {clv_s:>7}")

    print(f"{'═' * W}\n")
