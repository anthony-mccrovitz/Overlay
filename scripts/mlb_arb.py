#!/usr/bin/env python3
"""
MLB arb scanner: Kalshi prediction market vs sportsbook moneylines.

Fetches tonight's MLB Kalshi markets (KXMLBGAME series) via orderbook endpoint,
compares against live h2h moneylines from the Odds API, finds guaranteed arb
opportunities and value divergences.

Usage:
    python scripts/mlb_arb.py                    # today's games
    python scripts/mlb_arb.py --refresh          # force fresh odds
    python scripts/mlb_arb.py --date 20260420    # specific date (YYYYMMDD)
    python scripts/mlb_arb.py --bankroll 500     # stake calculations
    python scripts/mlb_arb.py --min-margin 2.0   # filter by minimum margin %
    python scripts/mlb_arb.py --tier1-only       # skip offshore books
    python scripts/mlb_arb.py --show-all         # show tier-1 + offshore
    python scripts/mlb_arb.py --save             # save to output/mlb_arb/
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.data.odds_api import fetch_odds, _american_to_prob, TIER1_BOOKS
from src.data.kalshi import _headers, _fetch_orderbook_mid, API_BASE, CACHE_DIR as K_CACHE

# --- Team name normalization: Kalshi ticker suffix → Odds API team name ---
# Kalshi KXMLBGAME tickers end in the team abbreviation:
#   KXMLBGAME-26APR17-ATL-CIN → Atlanta Braves @ Cincinnati Reds
KALSHI_TO_FULL: dict[str, str] = {
    "ANA": "Los Angeles Angels",
    "LAA": "Los Angeles Angels",
    "HOU": "Houston Astros",
    "ATH": "Oakland Athletics",
    "OAK": "Oakland Athletics",
    "TOR": "Toronto Blue Jays",
    "ATL": "Atlanta Braves",
    "MIL": "Milwaukee Brewers",
    "STL": "St. Louis Cardinals",
    "CHC": "Chicago Cubs",
    "ARI": "Arizona Diamondbacks",
    "AZ":  "Arizona Diamondbacks",
    "LAD": "Los Angeles Dodgers",
    "SF":  "San Francisco Giants",
    "SFG": "San Francisco Giants",
    "CLE": "Cleveland Guardians",
    "SEA": "Seattle Mariners",
    "MIA": "Miami Marlins",
    "NYM": "New York Mets",
    "WAS": "Washington Nationals",
    "WSH": "Washington Nationals",
    "BAL": "Baltimore Orioles",
    "SD":  "San Diego Padres",
    "SDP": "San Diego Padres",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "TEX": "Texas Rangers",
    "TB":  "Tampa Bay Rays",
    "BOS": "Boston Red Sox",
    "CIN": "Cincinnati Reds",
    "COL": "Colorado Rockies",
    "KC":  "Kansas City Royals",
    "DET": "Detroit Tigers",
    "MIN": "Minnesota Twins",
    "CWS": "Chicago White Sox",
    "NYY": "New York Yankees",
}

# Kalshi fee on winnings (~2%)
KALSHI_FEE = 0.02

# Minimum arb margin to report
DEFAULT_MIN_MARGIN = 0.005   # 0.5%

# Minimum absolute divergence (prediction market vs sportsbook) to flag as value
MIN_DIVERGENCE_PCT = 5.0


def american_to_prob(odds: float) -> float:
    return _american_to_prob(odds)


def _parse_yes_team_from_ticker(ticker: str) -> str:
    """
    Extract YES team abbreviation from Kalshi ticker.

    New format: KXMLBGAME-26APR172138SDLAA-SD  → YES team = "SD"
    Old format: KXMLBGAME-26APR17-SD-LAA        → YES team = "LAA" (last segment)

    Rule: last hyphen-segment = YES team abbreviation.
    """
    return ticker.split("-")[-1].upper()


def _parse_both_teams_from_event_ticker(event_ticker: str, yes_abbr: str) -> tuple[str, str]:
    """
    Extract both team abbreviations from event_ticker.

    event_ticker examples:
        KXMLBGAME-26APR172138SDLAA  → teams SDLAA → SD + LAA
        KXMLBGAME-26APR201810HOUCLE → teams HOUCLE → HOU + CLE

    YES team is known. We find the other team by trying known abbrevs against the tail.
    """
    # Event segment is last part of event_ticker
    event_seg = event_ticker.split("-")[-1]   # e.g. "26APR172138SDLAA"

    # Strip date+time prefix: "26APR17HHMM" pattern at start
    # Format: 2 digits + 3 letters + 2 digits + optional 4-digit time
    tail_match = re.match(r"^\d{2}[A-Z]{3}\d{2,6}([A-Z]+)$", event_seg)
    if tail_match:
        teams_str = tail_match.group(1)  # e.g. "SDLAA" or "HOUCLE"
    else:
        teams_str = event_seg

    # YES team is known — find it at start or end of teams_str
    if teams_str.startswith(yes_abbr):
        no_abbr = teams_str[len(yes_abbr):]
    elif teams_str.endswith(yes_abbr):
        no_abbr = teams_str[:-len(yes_abbr)]
    else:
        # Fall back: try other known abbrevs
        no_abbr = ""
        for abbr in KALSHI_TO_FULL:
            if abbr != yes_abbr and teams_str.replace(yes_abbr, "") == abbr:
                no_abbr = abbr
                break
        if not no_abbr:
            # Last resort: strip YES team from wherever it appears
            no_abbr = teams_str.replace(yes_abbr, "")

    return yes_abbr, no_abbr.upper()


def fetch_kalshi_mlb_today(date_str: str, refresh: bool = False) -> list[dict]:
    """
    Fetch all Kalshi KXMLBGAME markets for a given date.

    date_str: e.g. "APR17" (matches tickers like KXMLBGAME-26APR17*)
    Returns list of dicts with team names and live YES/NO prices.

    Ticker format: KXMLBGAME-26APR172138SDLAA-SD
      - YES team = last segment (SD)
      - Both teams parsed from event segment (SDLAA → SD + LAA)
    """
    cache_path = K_CACHE / f"mlb_today_{date_str}.json"
    K_CACHE.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and not refresh:
        age = time.time() - cache_path.stat().st_mtime
        if age < 600:  # 10-min cache
            with open(cache_path) as f:
                return json.load(f)

    print(f"  [kalshi] Fetching MLB markets for {date_str}...")

    try:
        resp = requests.get(
            f"{API_BASE}/markets",
            headers=_headers(),
            params={"status": "open", "series_ticker": "KXMLBGAME", "limit": 200},
            timeout=20,
        )
        resp.raise_for_status()
        all_markets = resp.json().get("markets", [])
    except Exception as e:
        print(f"  [kalshi] Error fetching market list: {e}")
        return []

    date_upper = date_str.upper()
    today_markets = [
        m for m in all_markets
        if date_upper in m.get("ticker", "").upper()
    ]
    print(f"  [kalshi] Found {len(today_markets)} MLB markets for {date_upper}, fetching prices...")

    results = []
    priced = 0
    for m in today_markets:
        ticker = m.get("ticker", "")
        event_ticker = m.get("event_ticker", "")
        title = m.get("title", m.get("subtitle", ticker))

        yes_abbr = _parse_yes_team_from_ticker(ticker)
        _, no_abbr = _parse_both_teams_from_event_ticker(event_ticker, yes_abbr)

        yes_full = KALSHI_TO_FULL.get(yes_abbr, yes_abbr)
        no_full = KALSHI_TO_FULL.get(no_abbr, no_abbr) if no_abbr else "Unknown"

        # Fetch live orderbook price
        yes_prob = _fetch_orderbook_mid(ticker)
        if yes_prob is None:
            yes_bid = (m.get("yes_bid") or 0) / 100
            yes_ask = (m.get("yes_ask") or 0) / 100
            last = (m.get("last_price") or 0) / 100
            if yes_bid > 0 and yes_ask > 0:
                yes_prob = (yes_bid + yes_ask) / 2.0
            elif last > 0:
                yes_prob = last
            else:
                continue  # no price — skip

        no_prob_approx = max(1.0 - yes_prob - KALSHI_FEE, 0.01)
        priced += 1

        results.append({
            "ticker": ticker,
            "event_ticker": event_ticker,
            "title": title,
            "yes_abbr": yes_abbr,
            "no_abbr": no_abbr,
            "yes_full": yes_full,
            "no_full": no_full,
            "kalshi_yes": round(yes_prob, 4),
            "kalshi_no": round(no_prob_approx, 4),
            "kalshi_url": f"https://kalshi.com/markets/{ticker}",
        })

    print(f"  [kalshi] {priced}/{len(today_markets)} markets with live prices")

    with open(cache_path, "w") as f:
        json.dump(results, f, indent=2)

    return results


def _normalize_team(name: str) -> str:
    """Lowercase + strip city prefix for fuzzy team matching."""
    # City prefixes to strip
    cities = [
        "los angeles", "new york", "san francisco", "san diego",
        "kansas city", "st. louis", "st louis", "tampa bay",
        "chicago", "boston", "houston", "atlanta", "miami",
        "minnesota", "colorado", "arizona", "philadelphia",
        "pittsburgh", "cincinnati", "detroit", "seattle",
        "baltimore", "toronto", "washington", "oakland",
        "cleveland", "milwaukee", "texas", "minnesota",
    ]
    n = name.lower().strip()
    for city in cities:
        if n.startswith(city):
            n = n[len(city):].strip()
            break
    return n


def match_sportsbook_game(
    kalshi: dict,
    sb_df,
) -> list[dict]:
    """
    Find sportsbook rows that match a Kalshi market.

    Returns list of {book, home_team, away_team, home_ml, away_ml, home_prob, away_prob}
    """
    import pandas as pd

    if sb_df.empty or "HomeMoneyline" not in sb_df.columns:
        return []

    t1 = _normalize_team(kalshi["yes_full"])
    t2 = _normalize_team(kalshi["no_full"])

    matches = []
    for _, row in sb_df.iterrows():
        home_n = _normalize_team(str(row.get("HomeTeam", "")))
        away_n = _normalize_team(str(row.get("AwayTeam", "")))

        # Both teams must appear (either orientation)
        teams_match = (
            (t1 in home_n or t1 in away_n or home_n in t1 or away_n in t1) and
            (t2 in home_n or t2 in away_n or home_n in t2 or away_n in t2)
        )

        if not teams_match:
            continue

        book = row.get("Sportsbook", "")
        home_ml = row.get("HomeMoneyline")
        away_ml = row.get("AwayMoneyline")

        if pd.isna(home_ml) or pd.isna(away_ml):
            continue

        home_ml = float(home_ml)
        away_ml = float(away_ml)

        if home_ml == 0 or away_ml == 0:
            continue

        home_prob = american_to_prob(home_ml)
        away_prob = american_to_prob(away_ml)

        home_team = str(row.get("HomeTeam", ""))
        away_team = str(row.get("AwayTeam", ""))

        matches.append({
            "book": book,
            "home_team": home_team,
            "away_team": away_team,
            "home_ml": home_ml,
            "away_ml": away_ml,
            "home_prob": home_prob,
            "away_prob": away_prob,
        })

    return matches


def find_arbs(
    kalshi_markets: list[dict],
    sb_df,
    min_margin: float = DEFAULT_MIN_MARGIN,
) -> list[dict]:
    """
    Find arb opportunities between Kalshi markets and sportsbooks.

    For each Kalshi market YES/NO × each sportsbook matching game:
      - Direction A: buy Kalshi YES + bet opposing team at sportsbook
      - Direction B: buy Kalshi NO + bet same team at sportsbook

    An arb exists when combined_cost < 1.0 (after fees).
    """
    arbs = []

    for km in kalshi_markets:
        k_yes = km["kalshi_yes"]
        k_no = km["kalshi_no"]

        sb_matches = match_sportsbook_game(km, sb_df)

        for sb in sb_matches:
            home = sb["home_team"]
            away = sb["away_team"]

            # YES = km["yes_full"] wins on Kalshi
            # So arb options:
            #   Kalshi YES + SB bet on (team that is NOT YES) → combined = k_yes + SB_no_prob
            #   Kalshi NO  + SB bet on (team that IS YES)     → combined = k_no + SB_yes_prob

            # Figure out which SB team corresponds to YES/NO
            yes_n = _normalize_team(km["yes_full"])
            home_n = _normalize_team(home)
            away_n = _normalize_team(away)

            yes_is_home = yes_n in home_n or home_n in yes_n
            if yes_is_home:
                sb_yes_prob = sb["home_prob"]
                sb_no_prob = sb["away_prob"]
                sb_yes_ml = sb["home_ml"]
                sb_no_ml = sb["away_ml"]
                sb_yes_name = home
                sb_no_name = away
            else:
                sb_yes_prob = sb["away_prob"]
                sb_no_prob = sb["home_prob"]
                sb_yes_ml = sb["away_ml"]
                sb_no_ml = sb["home_ml"]
                sb_yes_name = away
                sb_no_name = home

            candidates = [
                # Arb A: Kalshi YES + SB NO (bet opposing team at sportsbook)
                # Combined = k_yes + sb_no_prob (implied prob of NO team winning)
                # Arb exists when combined < 1.0 (accounting for vig)
                (k_yes + sb_no_prob,
                 f"YES {km['yes_abbr']} on Kalshi @ {k_yes:.3f}",
                 f"{sb_no_name} ML on {sb['book']} @ {sb_no_ml:+.0f}",
                 k_yes, sb_no_prob),
                # Arb B: Kalshi NO + SB YES (bet YES team at sportsbook)
                (k_no + sb_yes_prob,
                 f"NO {km['yes_abbr']} on Kalshi @ {k_no:.3f}",
                 f"{sb_yes_name} ML on {sb['book']} @ {sb_yes_ml:+.0f}",
                 k_no, sb_yes_prob),
            ]

            for combined, k_desc, sb_desc, k_cost, sb_cost in candidates:
                margin = 1.0 - combined
                if margin >= min_margin:
                    arbs.append({
                        "game": f"{away} @ {home}",
                        "ticker": km["ticker"],
                        "book": sb["book"],
                        "is_tier1": sb["book"] in TIER1_BOOKS,
                        "kalshi_leg": k_desc,
                        "sb_leg": sb_desc,
                        "kalshi_cost": round(k_cost, 4),
                        "sb_cost": round(sb_cost, 4),
                        "combined": round(combined, 4),
                        "margin_pct": round(margin * 100, 2),
                        "kalshi_url": km["kalshi_url"],
                        "title": km.get("title", ""),
                    })

    # Sort by margin descending
    arbs.sort(key=lambda x: x["margin_pct"], reverse=True)
    return arbs


def calculate_stakes(arb: dict, bankroll: float) -> tuple[float, float, float]:
    """
    Kelly-optimal stakes for a two-leg arb.
    Returns (kalshi_stake, sb_stake, guaranteed_profit).
    """
    k = arb["kalshi_cost"]
    s = arb["sb_cost"]
    combined = arb["combined"]

    if combined <= 0:
        return 0, 0, 0

    # Allocate bankroll proportionally
    k_stake = bankroll * s / combined
    s_stake = bankroll * k / combined
    profit = bankroll * (1.0 - combined) / combined

    return round(k_stake, 2), round(s_stake, 2), round(profit, 2)


def format_date_for_kalshi(date_str: str | None = None) -> str:
    """
    Convert date to Kalshi ticker format.
    None or 'today' → today's date (e.g. "APR17")
    "20260420" → "APR20"
    """
    if date_str is None or date_str.lower() == "today":
        d = datetime.now(timezone.utc)
    else:
        d = datetime.strptime(date_str, "%Y%m%d")

    month_abbr = d.strftime("%b").upper()  # APR
    day = d.strftime("%d").lstrip("0")     # 17 (no leading zero)
    return f"{month_abbr}{day}"


def print_report(
    arbs: list[dict],
    bankroll: float,
    date_label: str,
    tier1_only: bool = True,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M ET")
    print(f"\n  ChefTonyBets — MLB Kalshi Arb Scanner  ({now})")
    print(f"  Date: {date_label}  |  Bankroll: ${bankroll:,.0f}")
    print("  " + "─" * 68)

    tier1 = [a for a in arbs if a["is_tier1"]]
    offshore = [a for a in arbs if not a["is_tier1"]]

    def _print_section(items: list[dict], label: str) -> None:
        if not items:
            print(f"\n  {label}: none found")
            return

        print(f"\n  {label.upper()} ({len(items)} arbs)")
        print("  " + "─" * 68)

        for i, arb in enumerate(items, 1):
            k_stake, sb_stake, profit = calculate_stakes(arb, bankroll)
            print(f"\n  #{i}  {arb['game']}  [{arb['margin_pct']:.2f}% margin]")
            print(f"       Kalshi: {arb['kalshi_leg']}")
            print(f"       Book:   {arb['sb_leg']}")
            print(f"       Combined cost: {arb['combined']:.4f}  →  +${profit:.2f} guaranteed on ${bankroll:,.0f}")
            print(f"       Stakes: Kalshi ${k_stake:.2f} | {arb['book']} ${sb_stake:.2f}")
            print(f"       ⚠  Verify Kalshi price before placing: {arb['kalshi_url']}")

    _print_section(tier1, "Tier-1 Books (FD/DK/BetMGM/BetRivers/Caesars/bet365)")

    if not tier1_only:
        _print_section(offshore, "Offshore Books")
    elif offshore:
        print(f"\n  (+ {len(offshore)} offshore arbs hidden — run with --show-all to see)")

    print("\n  " + "─" * 68)
    print(f"  SUMMARY: {len(tier1)} tier-1 arbs | {len(offshore)} offshore arbs | {len(arbs)} total")
    if tier1:
        best = tier1[0]
        _, _, profit = calculate_stakes(best, bankroll)
        print(f"  Best tier-1: {best['margin_pct']:.2f}% → +${profit:.2f} on ${bankroll:,.0f}")
        print(f"    {best['game']}: {best['kalshi_leg']}")
        print(f"                 {best['sb_leg']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="MLB Kalshi vs sportsbook arb scanner")
    parser.add_argument("--date", default=None,
                        help="Date in YYYYMMDD format (default: today)")
    parser.add_argument("--refresh", action="store_true", help="Force fresh data")
    parser.add_argument("--bankroll", type=float, default=1000.0)
    parser.add_argument("--min-margin", type=float, default=0.5,
                        help="Minimum arb margin %% (default 0.5)")
    parser.add_argument("--tier1-only", action="store_true", default=True,
                        help="Show only tier-1 US books (default)")
    parser.add_argument("--show-all", action="store_true",
                        help="Show tier-1 + offshore books")
    parser.add_argument("--save", action="store_true",
                        help="Save results to output/mlb_arb/")
    args = parser.parse_args()

    date_str = format_date_for_kalshi(args.date)
    date_label = args.date or "today"
    tier1_only = not args.show_all

    # Fetch Kalshi MLB markets
    kalshi_markets = fetch_kalshi_mlb_today(date_str, refresh=args.refresh)
    if not kalshi_markets:
        print("\n  No Kalshi MLB markets found for today.")
        print("  Check: KALSHI_API_KEY in .env, and that games are listed at kalshi.com")
        sys.exit(0)

    # Fetch sportsbook odds
    print("\n  Fetching sportsbook h2h odds...")
    sb_df = fetch_odds(markets="h2h", sport="baseball_mlb", refresh=args.refresh)

    if sb_df.empty:
        print("  No sportsbook odds available.")
        sys.exit(0)

    games = sb_df.groupby("GameID")["HomeTeam"].first().reset_index()
    print(f"  → {len(kalshi_markets)} Kalshi markets, {len(games)} sportsbook games")

    # Find arbs
    min_margin = args.min_margin / 100.0
    arbs = find_arbs(kalshi_markets, sb_df, min_margin=min_margin)

    # Print report
    print_report(arbs, args.bankroll, date_label, tier1_only=tier1_only)

    # Save
    if args.save:
        today = datetime.now().strftime("%Y%m%d_%H%M")
        out_dir = Path(f"output/mlb_arb")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"arbs_{today}.json"

        with open(out_path, "w") as f:
            json.dump({
                "generated_at": datetime.now().isoformat(),
                "date": date_label,
                "bankroll": args.bankroll,
                "kalshi_markets": len(kalshi_markets),
                "arbs": arbs,
            }, f, indent=2)
        print(f"  Saved → {out_path}")


if __name__ == "__main__":
    main()
