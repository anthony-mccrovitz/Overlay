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

# Canonical sport key aliases — same table as schema.py so CLV join always matches.
_SPORT_ALIASES: dict[str, str] = {
    "baseball_mlb":                 "mlb",
    "basketball_nba":               "nba",
    "basketball_nba_summer_league": "nba",
    "basketball_wnba":              "wnba",
    "americanfootball_nfl":         "nfl",
    "americanfootball_ncaaf":       "ncaaf",
    "basketball_ncaab":             "ncaab",
    "icehockey_nhl":                "nhl",
}


def _normalize_sport(sport: str) -> str:
    """Normalize Odds API sport key to short canonical form (e.g. baseball_mlb → mlb)."""
    s = str(sport).lower().strip()
    return _SPORT_ALIASES.get(s, s)


def _odds_to_implied(odds: float | int) -> float:
    """Convert American odds to implied probability (no vig removed)."""
    if odds == 0:
        return 0.5
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _devig_prob(picked_odds: float, opponent_odds: float) -> float:
    """
    De-vig a two-sided market using the additive (Pinnacle) method.
    Returns the fair probability for the picked side.

    Example: picked=-150, opponent=+130
      raw_picked   = 150/250 = 0.600
      raw_opponent = 100/230 = 0.435
      overround    = 1.035
      fair         = 0.600 / 1.035 = 0.580
    """
    raw_picked   = _odds_to_implied(picked_odds)
    raw_opponent = _odds_to_implied(opponent_odds)
    overround    = raw_picked + raw_opponent
    if overround <= 0:
        return raw_picked
    return raw_picked / overround


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
        # Support both old format (Team/BestOdds) and canonical schema (team/odds)
        team = str(pick.get("Team") or pick.get("team") or "").strip()
        if not team:
            continue
        key = (date_str, team.lower().strip())
        if key in snap_keys:
            continue

        odds = float(pick.get("BestOdds") or pick.get("odds") or pick.get("best_odds") or 0)
        snap = {
            "date":                 date_str,
            "team":                 team,
            "opponent":             str(pick.get("Opponent") or pick.get("matchup") or "?").strip(),
            "sport":                _normalize_sport(sport),
            "market":               str(pick.get("market") or pick.get("Market") or "moneyline"),
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


def snapshot_from_pnl(date_str: str | None = None) -> int:
    """
    Snapshot opening lines for all picks on date_str directly from picks.json.
    Works for all sports (MLB, NBA, NHL, WNBA, soccer, tennis, PGA).
    Returns number of new snapshots added.
    """
    from datetime import date as _date
    PNL_FILE = Path("data/pnl/picks.json")
    if not PNL_FILE.exists():
        return 0

    effective_date = date_str or _date.today().isoformat()
    try:
        all_picks = json.loads(PNL_FILE.read_text()).get("picks", [])
    except (json.JSONDecodeError, OSError):
        return 0

    day_picks = [p for p in all_picks if isinstance(p, dict) and p.get("date") == effective_date]
    if not day_picks:
        return 0

    snapshots = _load_snapshots()
    snap_keys = {
        (s.get("date", ""), s.get("team", "").lower().strip(), s.get("market", ""))
        for s in snapshots
    }

    now_ts = datetime.now(tz=timezone.utc).isoformat()
    added = 0

    for pick in day_picks:
        team = str(pick.get("team") or "").strip()
        if not team:
            continue
        market = str(pick.get("market") or "moneyline")
        key = (effective_date, team.lower().strip(), market)
        if key in snap_keys:
            continue

        odds = float(pick.get("odds") or pick.get("best_odds") or 0)
        snap = {
            "date":                 effective_date,
            "team":                 team,
            "opponent":             str(pick.get("matchup") or "?").strip(),
            "sport":                _normalize_sport(str(pick.get("sport") or "mlb")),
            "market":               market,
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


def backfill_snapshots_from_pnl() -> int:
    """
    Backfill opening-line snapshots for all dates in picks.json.
    Safe to run multiple times (deduplicates).
    """
    PNL_FILE = Path("data/pnl/picks.json")
    if not PNL_FILE.exists():
        return 0
    try:
        all_picks = json.loads(PNL_FILE.read_text()).get("picks", [])
    except (json.JSONDecodeError, OSError):
        return 0

    dates = sorted({p.get("date") for p in all_picks if isinstance(p, dict) and p.get("date")})
    total = 0
    for d in dates:
        n = snapshot_from_pnl(d)
        if n:
            print(f"  [CLV backfill] {d}: {n} picks snapshotted")
            total += n
    print(f"  [CLV backfill] Total: {total} new snapshots added across {len(dates)} dates")
    return total


def fetch_closing_pairs(
    date_str: str | None = None,
    sport: str = "baseball_mlb",
) -> dict[str, tuple[float, float]]:
    """
    Like fetch_closing_lines but returns two-sided data for de-vig.
    Returns {team_lower: (team_odds, opponent_odds)} from the closing archive.
    Only available for archive files (not live cache fallback).
    """
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    short_sport = (sport
                   .replace("baseball_", "")
                   .replace("basketball_", "")
                   .replace("hockey_", ""))

    for prefix in [sport, short_sport]:
        archive_path = Path("data/clv/closing") / f"{prefix}_{date_str}.json"
        if not archive_path.exists():
            continue
        try:
            records = json.loads(archive_path.read_text())
            pairs: dict[str, tuple[float, float]] = {}
            for row in records:
                home = str(row.get("HomeTeam") or "").lower().strip()
                away = str(row.get("AwayTeam") or "").lower().strip()
                home_ml = row.get("BestHomeML")
                away_ml = row.get("BestAwayML")
                if home and away and home_ml is not None and away_ml is not None:
                    pairs[home] = (float(home_ml), float(away_ml))
                    pairs[away] = (float(away_ml), float(home_ml))
            if pairs:
                return pairs
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
    return {}


def fetch_closing_lines(
    date_str: str | None = None,
    sport: str = "baseball_mlb",
) -> dict[str, float]:
    """
    Read closing lines from the date-specific archive first, then fall back
    to today's live odds cache.

    Returns a dict mapping team name (lower-case) -> best moneyline odds.
    """
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    closing: dict[str, list[float]] = {}

    # Try date-specific closing archive (most accurate — captured at game time).
    # Closing files may use either the full sport key (e.g. baseball_mlb_DATE.json)
    # or the short key (e.g. mlb_DATE.json). Try both in order.
    short_sport = (sport
                   .replace("baseball_", "")
                   .replace("basketball_", "")
                   .replace("hockey_", ""))
    for prefix in [sport, short_sport]:
        archive_path = Path("data/clv/closing") / f"{prefix}_{date_str}.json"
        if not archive_path.exists():
            continue
        try:
            records = json.loads(archive_path.read_text())
            for row in records:
                home = str(row.get("HomeTeam") or "").lower().strip()
                away = str(row.get("AwayTeam") or "").lower().strip()
                home_ml = row.get("BestHomeML")
                away_ml = row.get("BestAwayML")
                if home and home_ml is not None:
                    closing.setdefault(home, []).append(float(home_ml))
                if away and away_ml is not None:
                    closing.setdefault(away, []).append(float(away_ml))
            if closing:
                return {
                    team: max(prices, key=lambda p: p if p > 0 else -10000 / abs(p))
                    for team, prices in closing.items()
                }
        except (json.JSONDecodeError, ValueError, KeyError):
            pass  # fall through to next prefix or live cache

    # Fall back to live odds cache (today's picks only — don't mix dates)
    cache_path = ODDS_CACHE_DIR / f"{sport}_latest.json"
    if not cache_path.exists():
        print(f"  [CLV] No closing archive for {date_str} and no live cache found.")
        return {}

    try:
        raw = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, ValueError):
        print(f"  [CLV] Could not parse odds cache: {cache_path}")
        return {}

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
        return []

    # Normalize sport keys in snapshots (may have been written with old Odds API slug)
    for s in day_snaps:
        s["sport"] = _normalize_sport(s.get("sport", "mlb"))

    # Build per-sport closing maps for all sports present that day
    sports_today = {s.get("sport", "mlb") for s in day_snaps}
    closing_maps: dict[str, dict] = {}
    closing_pairs: dict[str, dict] = {}  # two-sided for de-vig
    for sport in sports_today:
        closing_maps[sport]  = fetch_closing_lines(date_str=date_str, sport=sport)
        closing_pairs[sport] = fetch_closing_pairs(date_str=date_str, sport=sport)

    # Merged maps: all teams from all sports (used as fallback)
    merged_map: dict[str, float] = {}
    merged_pairs: dict[str, tuple] = {}
    for sport in sports_today:
        merged_map.update(closing_maps[sport])
        merged_pairs.update(closing_pairs[sport])

    updated = 0
    for snap in day_snaps:
        team_lower = snap["team"].lower().strip()
        snap_sport = snap.get("sport", "baseball_mlb")

        # Try sport-specific map first, then merged fallback
        sport_map   = closing_maps.get(snap_sport, {})
        sport_pairs = closing_pairs.get(snap_sport, {})
        closing_odds = sport_map.get(team_lower) or merged_map.get(team_lower)

        if closing_odds is None:
            # Partial match
            for cm in (sport_map, merged_map):
                for key, val in cm.items():
                    if team_lower in key or key in team_lower:
                        closing_odds = val
                        break
                if closing_odds is not None:
                    break

        if closing_odds is None:
            continue  # no closing line available yet

        # De-vig closing probability using two-sided data when available.
        # Falls back to raw implied prob for markets without a paired opponent line
        # (e.g. live-cache fallback, totals, props).
        pair = sport_pairs.get(team_lower) or merged_pairs.get(team_lower)
        if pair:
            closing_imp = _devig_prob(pair[0], pair[1])
        else:
            closing_imp = _odds_to_implied(closing_odds)

        clv = closing_imp - snap["opening_implied_prob"]

        snap["closing_odds"]         = closing_odds
        snap["closing_implied_prob"] = round(closing_imp, 6)
        snap["clv"]                  = round(clv, 6)
        snap["clv_pct"]              = round(clv * 100, 3)
        snap["clv_devigged"]         = pair is not None  # flag for reporting
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

    # Group by sport
    sport_buckets: dict[str, list[float]] = {}
    for s in with_clv:
        sp = (s.get("sport") or "unknown").lower()
        # Normalize to short form
        if "mlb" in sp or sp == "baseball": sp = "mlb"
        elif "nba" in sp or sp == "basketball": sp = "nba"
        elif "nhl" in sp or sp == "hockey": sp = "nhl"
        sport_buckets.setdefault(sp, []).append(s["clv_pct"])

    clv_by_sport = {
        sp: {"count": len(vals), "avg_clv_pct": round(sum(vals) / len(vals), 3)}
        for sp, vals in sport_buckets.items()
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
        "clv_by_sport":     clv_by_sport,
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
