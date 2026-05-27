"""
Historical CLV Backfiller — src/analytics/historical_clv.py

Uses The Odds API historical endpoint (20K plan) to retroactively capture
closing lines for all past picks that are missing CLV data.

Endpoint:
    GET /v4/historical/sports/{sport}/odds
        ?date={ISO}&markets=h2h,spreads,totals
        &regions=us&oddsFormat=american

Cost: 10 credits per call.  Group by (sport, date) to minimise calls.

Usage:
    from src.analytics.historical_clv import backfill_historical_clv
    backfill_historical_clv(days_back=30, dry_run=False)

CLI:
    python3 src/analytics/historical_clv.py --days-back 30 --dry-run
    python3 src/analytics/historical_clv.py --days-back 60
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────

PNL_FILE       = Path("data/pnl/picks.json")
SNAPSHOTS_FILE = Path("data/clv/snapshots.json")
CLOSING_DIR    = Path("data/clv/closing")

API_BASE = "https://api.the-odds-api.com/v4"

# ── Market mapping ─────────────────────────────────────────────────────────────
# pick.market  → Odds API market key (None = skip)
# pick.sport short name → Odds API sport key
SPORT_KEY_MAP: dict[str, str] = {
    "mlb":           "baseball_mlb",
    "nba":           "basketball_nba",
    "nhl":           "icehockey_nhl",
    "nfl":           "americanfootball_nfl",
    "ncaaf":         "americanfootball_ncaaf",
    "ncaab":         "basketball_ncaab",
    "wnba":          "basketball_wnba",
    "soccer":        "soccer_usa_mls",
    "tennis":        "tennis_atp_french_open",
    # already-full keys pass through unchanged
    "baseball_mlb":  "baseball_mlb",
    "basketball_nba":"basketball_nba",
    "icehockey_nhl": "icehockey_nhl",
}

MARKET_MAP: dict[str, Optional[str]] = {
    "moneyline": "h2h",
    "spread":    "spreads",
    "total":     "totals",
    # skip these — props need per-event endpoint, NRFI is MLB only
    "nrfi":      None,
    "prop":      None,
    "pitcher_strikeouts": None,
    "batter_hits":        None,
    "batter_home_runs":   None,
    "batter_rbis":        None,
    "player_points":      None,
    "player_rebounds":    None,
    "player_assists":     None,
    "player_threes":      None,
    "player_points_rebounds_assists": None,
    "player_blocks":      None,
    "player_steals":      None,
    "f5_total":           None,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _odds_to_implied(odds: float) -> float:
    if odds == 0:
        return 0.5
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _fuzzy_match(name: str, candidates: list[str]) -> Optional[str]:
    """Return the best fuzzy match from candidates, or None if below threshold."""
    name_lower = name.lower().strip()
    best_ratio = 0.0
    best_match = None
    for c in candidates:
        c_lower = c.lower().strip()
        # Exact / substring match first
        if name_lower == c_lower or name_lower in c_lower or c_lower in name_lower:
            return c
        ratio = SequenceMatcher(None, name_lower, c_lower).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = c
    return best_match if best_ratio >= 0.6 else None


def _api_key() -> Optional[str]:
    return os.environ.get("ODDS_API_KEY")


def _credits_remaining(resp: requests.Response) -> Optional[int]:
    try:
        return int(resp.headers.get("x-requests-remaining", -1))
    except (ValueError, TypeError):
        return None


def _credits_used(resp: requests.Response) -> Optional[int]:
    try:
        return int(resp.headers.get("x-requests-used", -1))
    except (ValueError, TypeError):
        return None


# ── Snapshot helpers (mirrors clv_tracker.py) ─────────────────────────────────

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


# ── Historical snapshot fetcher ────────────────────────────────────────────────

def _fetch_historical_snapshot(
    sport_key: str,
    iso_timestamp: str,
    markets: str = "h2h,spreads,totals",
) -> Optional[dict]:
    """
    Fetch a single historical odds snapshot from The Odds API.

    iso_timestamp: RFC 3339/ISO 8601, e.g. "2026-04-15T17:30:00Z"
    Returns the parsed JSON dict, or None on error.
    Costs 10 credits.
    """
    key = _api_key()
    if not key:
        print("  [historical_clv] No ODDS_API_KEY in environment.")
        return None

    url = f"{API_BASE}/historical/sports/{sport_key}/odds"
    params = {
        "apiKey":      key,
        "date":        iso_timestamp,
        "regions":     "us",
        "markets":     markets,
        "oddsFormat":  "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        remaining = _credits_remaining(resp)
        used = _credits_used(resp)
        print(f"  [API] {sport_key} @ {iso_timestamp[:10]} — used={used}, remaining={remaining}")
        return data
    except requests.exceptions.HTTPError as e:
        print(f"  [historical_clv] HTTP error {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"  [historical_clv] Request error: {e}")
        return None


def _extract_closing_odds(
    snapshot_data: dict,
    team_name: str,
    api_market: str,
    direction: str,
) -> Optional[float]:
    """
    Parse the historical odds snapshot and return the best available closing odds
    for the given team, market, and direction.

    Tries Pinnacle first, then best across all bookmakers.
    direction: 'WIN' | 'OVER' | 'UNDER' | 'COVER' — used for totals/spreads
    """
    events = snapshot_data.get("data", [])
    if not events:
        # Some responses wrap differently
        events = snapshot_data if isinstance(snapshot_data, list) else []

    team_lower = team_name.lower().strip()

    # Build a list of all (event, home_team, away_team) whose names match
    matching_events: list[tuple[dict, str, str]] = []
    for event in events:
        home = str(event.get("home_team", "")).strip()
        away = str(event.get("away_team", "")).strip()
        candidates = [home, away]
        if _fuzzy_match(team_lower, [c.lower() for c in candidates]):
            matching_events.append((event, home, away))

    if not matching_events:
        return None

    event, home, away = matching_events[0]
    is_home = _fuzzy_match(team_lower, [home.lower()]) is not None

    best_price: Optional[float] = None

    # Prefer Pinnacle for sharpest closing line; fall back to best available
    def _try_bookmakers(bookmakers: list[dict]) -> Optional[float]:
        nonlocal best_price
        pinnacle_price: Optional[float] = None
        all_prices: list[float] = []

        for book in bookmakers:
            book_key = book.get("key", "").lower()
            for market in book.get("markets", []):
                mkey = market.get("key", "")
                if mkey != api_market:
                    continue
                outcomes = market.get("outcomes", [])

                if api_market == "h2h":
                    # Find outcome for this team
                    for outcome in outcomes:
                        oname = outcome.get("name", "").lower()
                        if _fuzzy_match(team_lower, [oname]):
                            price = float(outcome.get("price", 0))
                            all_prices.append(price)
                            if book_key == "pinnacle":
                                pinnacle_price = price

                elif api_market == "spreads":
                    for outcome in outcomes:
                        oname = outcome.get("name", "").lower()
                        if _fuzzy_match(team_lower, [oname]):
                            price = float(outcome.get("price", 0))
                            all_prices.append(price)
                            if book_key == "pinnacle":
                                pinnacle_price = price

                elif api_market == "totals":
                    dir_upper = direction.upper()
                    for outcome in outcomes:
                        oname = outcome.get("name", "").upper()
                        if oname in (dir_upper, "OVER", "UNDER") and oname == dir_upper:
                            price = float(outcome.get("price", 0))
                            all_prices.append(price)
                            if book_key == "pinnacle":
                                pinnacle_price = price

        if pinnacle_price is not None:
            return pinnacle_price
        if all_prices:
            # Return best available (most generous to the bettor)
            positives = [p for p in all_prices if p > 0]
            negatives = [p for p in all_prices if p <= 0]
            if positives:
                return max(positives)
            if negatives:
                return max(negatives)  # least negative = best
        return None

    result = _try_bookmakers(event.get("bookmakers", []))
    return result


# ── Core backfill function ─────────────────────────────────────────────────────

def backfill_historical_clv(
    days_back: int = 30,
    dry_run: bool = False,
    sport_filter: Optional[str] = None,
) -> dict:
    """
    Backfill closing-line CLV for all settled card picks missing CLV data.

    Parameters
    ----------
    days_back : int
        How many days back to look (default 30). Set to 0 to scan all time.
    dry_run : bool
        If True, print what would happen but make no API calls and write nothing.
    sport_filter : str or None
        Limit to a specific sport key, e.g. "baseball_mlb".

    Returns
    -------
    dict with keys: picks_checked, picks_updated, api_calls, credits_used
    """
    if not PNL_FILE.exists():
        print("  [historical_clv] No picks.json found.")
        return {}

    try:
        pnl_data = json.loads(PNL_FILE.read_text())
        if isinstance(pnl_data, list):
            all_picks = pnl_data
        else:
            all_picks = pnl_data.get("picks", [])
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [historical_clv] Could not load picks.json: {e}")
        return {}

    # ── 1. Identify picks that need CLV ───────────────────────────────────────
    snapshots = _load_snapshots()
    snap_keys_with_clv = {
        (s.get("date", ""), s.get("team", "").lower().strip(), s.get("market", ""))
        for s in snapshots
        if s.get("clv") is not None
    }

    cutoff_date: Optional[date] = None
    if days_back > 0:
        cutoff_date = date.today() - timedelta(days=days_back)

    candidates: list[dict] = []
    for pick in all_picks:
        if not isinstance(pick, dict):
            continue
        # Only settled picks (card or shadow — we want CLV on all of them)
        if pick.get("result") not in ("win", "loss", "push"):
            continue

        pick_date_str = str(pick.get("date", ""))[:10]   # YYYY-MM-DD
        if not pick_date_str:
            continue

        # Date range filter
        if cutoff_date:
            try:
                pd = date.fromisoformat(pick_date_str)
            except ValueError:
                continue
            if pd < cutoff_date:
                continue

        # Sport filter
        sport = str(pick.get("sport", "")).lower().replace(" ", "_")
        if sport_filter and sport != sport_filter.lower():
            continue

        # Market must be mappable
        market = str(pick.get("market", "moneyline")).lower()
        api_market = MARKET_MAP.get(market)
        if api_market is None:
            continue  # skip props, nrfi, f5

        team = str(pick.get("team", "")).strip()
        if not team:
            continue

        # Skip if we already have CLV
        snap_key = (pick_date_str, team.lower().strip(), market)
        if snap_key in snap_keys_with_clv:
            continue

        candidates.append(pick)

    print(f"\n{'='*60}")
    print(f"  Historical CLV Backfiller")
    print(f"  days_back={days_back}  |  dry_run={dry_run}")
    print(f"{'='*60}")
    print(f"  {len(all_picks)} total picks in pnl")
    print(f"  {len(candidates)} picks need CLV data")

    if not candidates:
        print("  Nothing to backfill.")
        return {"picks_checked": len(all_picks), "picks_updated": 0, "api_calls": 0, "credits_used": 0}

    # ── 2. Group by (sport, date) to batch API calls ───────────────────────────
    groups: dict[tuple[str, str], list[dict]] = {}
    for pick in candidates:
        raw_sport = str(pick.get("sport", "")).lower().replace(" ", "_")
        sport = SPORT_KEY_MAP.get(raw_sport, raw_sport)
        date_str = str(pick.get("date", ""))[:10]
        key = (sport, date_str)
        groups.setdefault(key, []).append(pick)

    print(f"  {len(groups)} (sport, date) groups → {len(groups)} API calls needed")
    print(f"  Estimated credits: {len(groups) * 10}")

    if dry_run:
        print("\n  DRY RUN — no API calls will be made.\n")
        for (sport, date_str), picks_in_group in sorted(groups.items()):
            print(f"    Would call: {sport} on {date_str} ({len(picks_in_group)} picks)")
        return {
            "picks_checked": len(candidates),
            "picks_updated": 0,
            "api_calls": 0,
            "credits_used": 0,
            "dry_run": True,
        }

    # ── 3. Check API key ───────────────────────────────────────────────────────
    if not _api_key():
        print("  ERROR: No ODDS_API_KEY found in environment. Set it in .env")
        return {}

    # ── 4. Fetch + process each group ─────────────────────────────────────────
    CLOSING_DIR.mkdir(parents=True, exist_ok=True)

    api_calls_made = 0
    credits_used_total = 0
    picks_updated = 0

    # Re-load snapshots (they may have been updated by clv_tracker elsewhere)
    snapshots = _load_snapshots()
    snap_lookup: dict[tuple[str, str, str], dict] = {
        (s.get("date", ""), s.get("team", "").lower().strip(), s.get("market", "")): s
        for s in snapshots
    }

    for (sport, date_str), picks_in_group in sorted(groups.items()):
        print(f"\n  [{sport}] {date_str} — {len(picks_in_group)} picks")

        # Build closing timestamp = noon ET on game day (safe "near-close" proxy
        # when we don't have exact commence_time in PnL data)
        # Best would be commence_time - 30 min, but we approximate.
        try:
            game_date = date.fromisoformat(date_str)
        except ValueError:
            print(f"    Skipping bad date: {date_str}")
            continue

        # Use 17:30 UTC (1:30 PM ET) — most MLB/NBA games haven't started yet,
        # this gives us the "opening of game day" line rather than true closing.
        # For a true closing line we'd need commence_time per event.
        closing_iso = f"{date_str}T17:30:00Z"

        # Determine markets needed for this group
        needed_markets = set()
        for pick in picks_in_group:
            m = MARKET_MAP.get(str(pick.get("market", "moneyline")).lower())
            if m:
                needed_markets.add(m)

        if not needed_markets:
            print(f"    No mappable markets — skipping")
            continue

        markets_param = ",".join(sorted(needed_markets))

        # Fetch
        snapshot = _fetch_historical_snapshot(sport, closing_iso, markets=markets_param)
        api_calls_made += 1
        credits_used_total += 10  # each call costs 10

        if snapshot is None:
            print(f"    API call failed — skipping group")
            continue

        # Cache the raw snapshot to closing dir
        cache_path = CLOSING_DIR / f"{sport}_{date_str}_historical.json"
        if not cache_path.exists():
            try:
                cache_path.write_text(json.dumps(snapshot, indent=2))
            except OSError:
                pass

        # Process each pick in the group
        for pick in picks_in_group:
            pick_date = str(pick.get("date", ""))[:10]
            team      = str(pick.get("team", "")).strip()
            market    = str(pick.get("market", "moneyline")).lower()
            direction = str(pick.get("direction", "WIN")).upper()
            api_market = MARKET_MAP.get(market)

            if not api_market:
                continue

            # For totals, team field is "OVER 219.5" — use matchup to find the event
            lookup_team = team
            if api_market == "totals" and not team or (
                api_market == "totals" and team.upper().startswith(("OVER", "UNDER"))
            ):
                matchup = str(pick.get("matchup", ""))
                if " @ " in matchup:
                    lookup_team = matchup.split(" @ ")[1].strip()  # home team
                elif " vs " in matchup:
                    lookup_team = matchup.split(" vs ")[0].strip()

            if not lookup_team:
                continue

            closing_odds = _extract_closing_odds(snapshot, lookup_team, api_market, direction)

            if closing_odds is None:
                print(f"    No closing line found for: {team} ({market})")
                continue

            # Look up existing snapshot for this pick
            snap_key = (pick_date, team.lower().strip(), market)
            snap = snap_lookup.get(snap_key)

            if snap is None:
                # Create a new snapshot entry using the pick's recorded odds as opening
                opening_odds = float(pick.get("odds") or 0)
                snap = {
                    "date":                 pick_date,
                    "team":                 team,
                    "opponent":             str(pick.get("matchup") or "?").strip(),
                    "sport":                sport,
                    "market":               market,
                    "opening_odds":         opening_odds,
                    "opening_implied_prob": round(_odds_to_implied(opening_odds), 6),
                    "snapshot_time":        str(pick.get("recorded_at", "")),
                    "closing_odds":         None,
                    "closing_implied_prob": None,
                    "clv":                  None,
                    "clv_pct":              None,
                }
                snapshots.append(snap)
                snap_lookup[snap_key] = snap

            # Fill in closing data
            closing_imp = _odds_to_implied(closing_odds)
            clv = closing_imp - snap["opening_implied_prob"]

            snap["closing_odds"]         = closing_odds
            snap["closing_implied_prob"] = round(closing_imp, 6)
            snap["clv"]                  = round(clv, 6)
            snap["clv_pct"]              = round(clv * 100, 3)
            snap["backfilled"]           = True
            snap["backfilled_at"]        = datetime.now(timezone.utc).isoformat()

            picks_updated += 1
            sign = "+" if clv >= 0 else ""
            print(
                f"    {team:<28}  open={int(snap['opening_odds']):+d}  "
                f"close={int(closing_odds):+d}  CLV={sign}{clv*100:.1f}%"
            )

        # Small delay to be polite to the API
        time.sleep(0.3)

    # ── 5. Persist updated snapshots ──────────────────────────────────────────
    if picks_updated > 0:
        _save_snapshots(snapshots)
        print(f"\n  Saved {picks_updated} CLV entries to {SNAPSHOTS_FILE}")

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"  Picks examined:  {len(candidates)}")
    print(f"  Picks updated:   {picks_updated}")
    print(f"  API calls made:  {api_calls_made}")
    print(f"  Credits used:    ~{credits_used_total}")
    print(f"{'='*60}\n")

    return {
        "picks_checked": len(candidates),
        "picks_updated": picks_updated,
        "api_calls": api_calls_made,
        "credits_used": credits_used_total,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill historical CLV data for past picks using The Odds API"
    )
    parser.add_argument(
        "--days-back", type=int, default=30,
        help="How many days back to scan (0 = all time, default 30)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without making API calls",
    )
    parser.add_argument(
        "--sport", type=str, default=None,
        help="Limit to one sport key, e.g. baseball_mlb (default: all)",
    )
    args = parser.parse_args()
    backfill_historical_clv(
        days_back=args.days_back,
        dry_run=args.dry_run,
        sport_filter=args.sport,
    )
