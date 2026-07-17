"""
Client for the-odds-api.com to fetch live sportsbook odds.

Free tier: 500 requests/month. Tournament = ~67 games × ~3 checks = ~200 requests.
We cache aggressively to stay within limits.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from src.data.team_names import try_normalize

load_dotenv()

# --- Main-market sanity (filters junk / alternate lines that poison "best odds") ---
# Full-game MLB moneylines almost never exceed these at major US books.
ML_AMERICAN_MIN = -800   # biggest favorite we trust
ML_AMERICAN_MAX = 800    # biggest underdog we trust (+2200 etc. → dropped)
SPREAD_PRICE_MIN = -400
SPREAD_PRICE_MAX = 400
# Full-game totals (rough MLB band); 14.5+ often alt / wrong market.
TOTAL_LINE_MIN = 5.0
TOTAL_LINE_MAX = 14.0
# Run lines beyond this are usually alt markets or bad data (e.g. 7.5 RL).
SPREAD_LINE_ABS_MAX = 3.5

CACHE_DIR = Path("data/cache/odds")
API_BASE = "https://api.the-odds-api.com/v4"

# ── Anthony's sportsbook accounts ─────────────────────────────────────────────
# API keys used in all bookmakers= params. Edit here to add/remove a book.
# espnbet  = ESPN Bet (shows as "theScore Bet" in API — same platform)
# fliff    = Fliff (social sportsbook, limited markets but included)
MY_BOOKS_KEYS: list[str] = [
    "draftkings",
    "fanduel",
    "betmgm",
    "betrivers",
    "espnbet",       # ESPN Bet / theScore Bet
    "fliff",
    "hardrockbet",
    "caesars",
    "fanatics",
    "ballybet",
    "thescore",
    "betparx",
    "bet365",
    "tipico",
]
MY_BOOKS_PARAM = ",".join(MY_BOOKS_KEYS)

# Display names matching the Odds API title field (used for filtering response objects)
# These are the ONLY books we ever show as bet destinations — no offshore, no EU books.
MY_BOOKS_TITLES = frozenset({
    "DraftKings", "FanDuel", "BetMGM", "BetRivers",
    "theScore Bet", "Fliff", "Hard Rock Bet", "Hard Rock Bet (OH)",
    "Caesars", "Fanatics", "Bally Bet", "betPARX", "Bet365", "Tipico",
})

# Sharp books used for de-vigged true probability (CLV/EV baseline).
# Pinnacle is the gold standard — no-vig reference only, never shown as bet destination.
SHARP_BOOKS     = frozenset({"Pinnacle", "Matchbook", "DraftKings", "FanDuel"})
SHARP_BOOK_KEYS = frozenset({"pinnacle", "matchbook", "draftkings", "fanduel"})

# Legacy aliases kept for any callers that imported these names
PREFERRED_BOOKS = MY_BOOKS_TITLES
TIER1_BOOKS     = MY_BOOKS_TITLES

# Books requested from the Odds API. Using the `bookmakers` param instead of
# `regions` costs markets×1 for up to 10 books (vs markets×3 for us,us2,eu) —
# proven 3× cheaper, and keeps every market. Edit this list to change coverage;
# KEEP IT ≤10 books or the per-call cost doubles. 9 US books for best-price
# line-shopping + Pinnacle as the sharp no-vig fair-line anchor.
# hardrockbet/ballybet added 2026-07-16 (free — still ≤10): both bettable
# (already in MY_BOOKS_TITLES) and slow-moving, which widens the cross-book
# consensus AND gives consensus_ev real destinations where stale prices live.
BOOKMAKERS = ("draftkings,fanduel,betmgm,williamhill_us,betrivers,espnbet,"
              "fanatics,hardrockbet,ballybet,pinnacle")

# Single source of truth: every odds fetch (all sport runners) uses these books.
# Override the older MY_BOOKS_PARAM so nothing line-shops across books we can't
# bet — CLV/EV must be measured against lines actually available to us, never
# foreign sportsbooks or exchanges (e.g. 888sport, betfair_ex_uk).
MY_BOOKS_PARAM = BOOKMAKERS

SUPPORTED_SPORTS = {
    "basketball_ncaab",
    "basketball_nba",
    "basketball_wnba",
    "baseball_mlb",
    "americanfootball_nfl",
    "icehockey_nhl",
    "soccer_fifa_world_cup",
    "mma_mixed_martial_arts",
    # Club soccer (models built 2026-07-16). European leagues resume in August;
    # off-season keys return an empty board for 3 credits, so gate-listing them
    # is free — just don't put them in a daily fetch loop until they're live.
    "soccer_usa_mls",
    "soccer_mexico_ligamx",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
}

# Sport-key prefixes accepted in addition to the exact set above. Tennis keys
# are tournament-scoped (tennis_atp_wimbledon, ...) and rotate through the
# season, so they can't be enumerated — any tennis_* key parses identically
# (2-way h2h with player names in home_team/away_team).
SUPPORTED_SPORT_PREFIXES = ("tennis_",)


def _get_api_key() -> str | None:
    """Get API key from environment."""
    return os.environ.get("ODDS_API_KEY")


def _cache_path(event_id: str = "latest", sport: str = "basketball_ncaab") -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{sport}_{event_id}.json"


def _validate_sport(sport: str) -> None:
    if sport in SUPPORTED_SPORTS or sport.startswith(SUPPORTED_SPORT_PREFIXES):
        return
    raise ValueError(
        f"Unsupported sport '{sport}'. Supported: {', '.join(sorted(SUPPORTED_SPORTS))}"
        f" (plus prefixes: {', '.join(SUPPORTED_SPORT_PREFIXES)})"
    )


def fetch_odds(
    markets: str = "h2h,spreads,totals",
    sport: str = "basketball_ncaab",
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch current NCAA basketball tournament odds from multiple sportsbooks.

    Args:
        markets: Comma-separated market types (h2h = moneyline, spreads, totals)
        refresh: If True, fetch fresh even if cache exists

    Returns:
        DataFrame with columns:
        [GameID, HomeTeam, AwayTeam, HomeTeamCanonical, AwayTeamCanonical,
         Sportsbook, HomeOdds, AwayOdds, Spread, SpreadOdds, Total, OverOdds, UnderOdds,
         HomeImpliedProb, AwayImpliedProb, Timestamp]
    """
    api_key = _get_api_key()
    if not api_key or api_key == "your_key_here":
        print(
            "Warning: No ODDS_API_KEY set. Skipping odds analysis.\n"
            "  Get a free key at https://the-odds-api.com\n"
            "  Add to .env: ODDS_API_KEY=your_key_here"
        )
        return pd.DataFrame()

    _validate_sport(sport)

    cache = _cache_path("latest", sport=sport)
    if cache.exists() and not refresh:
        cache_age = time.time() - cache.stat().st_mtime
        cache_min = cache_age / 60
        # Use cache if less than 2 hours old — but always warn so caller knows
        if cache_age < 7200:
            with open(cache) as f:
                data = json.load(f)
            print(f"  ⚠  Using cached odds ({cache_min:.0f} min old). Run with --refresh for live prices.")
            return _parse_odds_response(data, normalize_names=(sport == "basketball_ncaab"))

    url = f"{API_BASE}/sports/{sport}/odds"
    params = {
        "apiKey": api_key,
        # Named books (see BOOKMAKERS) instead of regions: 3× cheaper, keeps
        # every market. Includes Pinnacle for the sharp CLV/EV baseline.
        "bookmakers": BOOKMAKERS,
        "markets": markets,
        "oddsFormat": "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)

        if resp.status_code == 401:
            print("Warning: Invalid ODDS_API_KEY. Skipping odds analysis.")
            return pd.DataFrame()
        if resp.status_code == 429:
            print("Warning: Odds API rate limit reached. Using cached data.")
            if cache.exists():
                with open(cache) as f:
                    return _parse_odds_response(
                        json.load(f),
                        normalize_names=(sport == "basketball_ncaab"),
                    )
            return pd.DataFrame()

        resp.raise_for_status()
        data = resp.json()

        # Cache the response
        with open(cache, "w") as f:
            json.dump(data, f)

        # Log remaining requests and fetch time
        remaining = resp.headers.get("x-requests-remaining", "unknown")
        fetched_at = datetime.now().strftime("%H:%M:%S")
        print(f"  ✓  Live odds fetched at {fetched_at}. API requests remaining: {remaining}")

        return _parse_odds_response(data, normalize_names=(sport == "basketball_ncaab"))

    except requests.RequestException as e:
        print(f"Warning: Odds API unreachable ({e}). ", end="")
        if cache.exists():
            print("Using cached odds.")
            with open(cache) as f:
                return _parse_odds_response(
                    json.load(f),
                    normalize_names=(sport == "basketball_ncaab"),
                )
        print("Skipping odds analysis.")
        return pd.DataFrame()


def _parse_odds_response(data: list[dict], normalize_names: bool = True) -> pd.DataFrame:
    """Parse the-odds-api response into a clean DataFrame."""
    rows = []
    now_utc = datetime.now(timezone.utc)
    skipped_started = 0

    for event in data:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        game_id = event.get("id", "")
        commence = event.get("commence_time", "")

        # Drop any game that has already started (commence_time <= now UTC).
        # Books pull lines at first pitch — picks on started games can't be placed.
        if commence:
            try:
                ct = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                if ct <= now_utc:
                    skipped_started += 1
                    continue
            except ValueError:
                pass  # malformed timestamp — keep the event rather than silently drop

        if normalize_names:
            home_canonical = try_normalize(home)
            away_canonical = try_normalize(away)
        else:
            home_canonical = home
            away_canonical = away

        for bookmaker in event.get("bookmakers", []):
            book_name = bookmaker.get("title", "")
            last_update = bookmaker.get("last_update", "")

            row = {
                "GameID": game_id,
                "HomeTeam": home,
                "AwayTeam": away,
                "HomeTeamCanonical": home_canonical,
                "AwayTeamCanonical": away_canonical,
                "Sportsbook": book_name,
                "CommenceTime": commence,
                "OddsUpdatedAt": last_update,
            }

            for market in bookmaker.get("markets", []):
                key = market.get("key", "")
                outcomes = market.get("outcomes", [])

                if key == "h2h":
                    for outcome in outcomes:
                        if outcome["name"] == home:
                            row["HomeMoneyline"] = outcome["price"]
                        elif outcome["name"] == away:
                            row["AwayMoneyline"] = outcome["price"]
                        elif str(outcome.get("name", "")).lower() == "draw":
                            # 3-way markets (soccer): the draw carries 15-30% of
                            # the probability mass — dropping it is what made
                            # 2-way devigs print phantom EV on every side.
                            row["DrawOdds"] = outcome["price"]

                elif key == "spreads":
                    for outcome in outcomes:
                        if outcome["name"] == home:
                            row["HomeSpread"] = outcome.get("point", 0)
                            row["HomeSpreadOdds"] = outcome["price"]
                        elif outcome["name"] == away:
                            row["AwaySpread"] = outcome.get("point", 0)
                            row["AwaySpreadOdds"] = outcome["price"]

                elif key == "totals":
                    for outcome in outcomes:
                        if outcome["name"] == "Over":
                            row["Total"] = outcome.get("point", 0)
                            row["OverOdds"] = outcome["price"]
                        elif outcome["name"] == "Under":
                            row["UnderOdds"] = outcome["price"]

            rows.append(row)

    if skipped_started:
        print(f"  ⏱  Filtered {skipped_started} game(s) already started — picks only include upcoming games.")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = _sanitize_parsed_odds_df(df)

    # Calculate implied probabilities from moneyline
    if "HomeMoneyline" in df.columns:
        df["HomeImpliedProb"] = df["HomeMoneyline"].apply(_american_to_prob)
        df["AwayImpliedProb"] = df["AwayMoneyline"].apply(_american_to_prob)

    return df


def american_moneyline_sane(odds: float) -> bool:
    """True if odds look like a normal full-game ML (not alt / bad feed)."""
    if pd.isna(odds):
        return False
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return False
    if o == 0:
        return False
    return ML_AMERICAN_MIN <= o <= ML_AMERICAN_MAX


def _sanitize_parsed_odds_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Null out insane prices so idxmax() cannot pick alternate-market outliers.
    Call after _parse_odds_response builds df.
    """
    if df.empty:
        return df
    out = df.copy()
    for col in ("HomeMoneyline", "AwayMoneyline"):
        if col in out.columns:
            mask = out[col].apply(lambda x: american_moneyline_sane(x) if pd.notna(x) else False)
            out.loc[~mask, col] = float("nan")
    for col in ("HomeSpreadOdds", "AwaySpreadOdds"):
        if col in out.columns:
            def _ok_sp(x):
                if pd.isna(x):
                    return False
                try:
                    v = float(x)
                except (TypeError, ValueError):
                    return False
                return SPREAD_PRICE_MIN <= v <= SPREAD_PRICE_MAX

            mask = out[col].apply(_ok_sp)
            out.loc[~mask, col] = float("nan")
    return out


def _american_to_prob(odds: float) -> float:
    """
    Convert American odds to implied probability.
    +150 → 0.40 (bet $100 to win $150)
    -200 → 0.667 (bet $200 to win $100)
    """
    if pd.isna(odds):
        return 0.5
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def get_best_odds(
    odds_df: pd.DataFrame, market: str = "h2h", all_books: bool = False
) -> pd.DataFrame:
    """
    For each game, find the best available odds across all sportsbooks.

    Args:
        odds_df: Raw odds DataFrame from fetch_odds()
        market: "h2h" (moneyline), "spreads", or "totals"

    Returns one row per game with the best odds for the requested market.
    """
    if odds_df.empty:
        return odds_df

    # Filter to US books only (DraftKings, FanDuel, BetMGM + BetRivers as backup)
    # all_books=True bypasses the filter — used by Method B to find line discrepancies.
    if all_books:
        working_df = odds_df
    else:
        # Always filter to US books — never fall back to offshore/EU books
        working_df = odds_df[odds_df["Sportsbook"].isin(PREFERRED_BOOKS)]

    best = []
    for game_id in working_df["GameID"].unique():
        game = working_df[working_df["GameID"] == game_id]
        row = {
            "GameID": game_id,
            "HomeTeam": game["HomeTeamCanonical"].iloc[0],
            "AwayTeam": game["AwayTeamCanonical"].iloc[0],
            "CommenceTime": game["CommenceTime"].iloc[0],
        }

        if market == "h2h" and "HomeMoneyline" in game.columns:
            valid_h = game.dropna(subset=["HomeMoneyline"])
            valid_a = game.dropna(subset=["AwayMoneyline"])
            if not valid_h.empty:
                best_home_idx = valid_h["HomeMoneyline"].idxmax()
                row["BestHomeML"] = game.loc[best_home_idx, "HomeMoneyline"]
                row["BestHomeSportsbook"] = game.loc[best_home_idx, "Sportsbook"]
                row["HomeImpliedProb"] = _american_to_prob(row["BestHomeML"])
            else:
                row["BestHomeML"] = float("nan")
                row["BestHomeSportsbook"] = ""
                row["HomeImpliedProb"] = 0.5
            if not valid_a.empty:
                best_away_idx = valid_a["AwayMoneyline"].idxmax()
                row["BestAwayML"] = game.loc[best_away_idx, "AwayMoneyline"]
                row["BestAwaySportsbook"] = game.loc[best_away_idx, "Sportsbook"]
                row["AwayImpliedProb"] = _american_to_prob(row["BestAwayML"])
            else:
                row["BestAwayML"] = float("nan")
                row["BestAwaySportsbook"] = ""
                row["AwayImpliedProb"] = 0.5

        if "HomeSpread" in game.columns:
            row["ConsensusSpread"] = game["HomeSpread"].median()

        if market == "spreads" and "HomeSpreadOdds" in game.columns:
            valid_home = game.dropna(subset=["HomeSpreadOdds"])
            valid_away = game.dropna(subset=["AwaySpreadOdds"])
            if not valid_home.empty:
                best_hs_idx = valid_home["HomeSpreadOdds"].idxmax()
                row["BestHomeSpreadOdds"] = int(valid_home.loc[best_hs_idx, "HomeSpreadOdds"])
                row["BestHomeSpreadBook"] = valid_home.loc[best_hs_idx, "Sportsbook"]
                row["HomeSpread"] = valid_home.loc[best_hs_idx, "HomeSpread"]
            if not valid_away.empty:
                best_as_idx = valid_away["AwaySpreadOdds"].idxmax()
                row["BestAwaySpreadOdds"] = int(valid_away.loc[best_as_idx, "AwaySpreadOdds"])
                row["BestAwaySpreadBook"] = valid_away.loc[best_as_idx, "Sportsbook"]
                row["AwaySpread"] = valid_away.loc[best_as_idx, "AwaySpread"]

        if market == "totals" and "OverOdds" in game.columns:
            row["Total"] = game["Total"].median()
            valid_over = game.dropna(subset=["OverOdds"])
            valid_under = game.dropna(subset=["UnderOdds"])
            if not valid_over.empty:
                best_o_idx = valid_over["OverOdds"].idxmax()
                row["BestOverOdds"] = int(valid_over.loc[best_o_idx, "OverOdds"])
                row["BestOverBook"] = valid_over.loc[best_o_idx, "Sportsbook"]
            if not valid_under.empty:
                best_u_idx = valid_under["UnderOdds"].idxmax()
                row["BestUnderOdds"] = int(valid_under.loc[best_u_idx, "UnderOdds"])
                row["BestUnderBook"] = valid_under.loc[best_u_idx, "Sportsbook"]

        best.append(row)

    return pd.DataFrame(best)


def odds_freshness_summary(odds_df: pd.DataFrame) -> str:
    """
    Return a one-line summary of how fresh the odds data is.

    Uses the OddsUpdatedAt field per bookmaker (from the Odds API last_update field).
    Shows the oldest and newest update times across all books.
    """
    if odds_df.empty or "OddsUpdatedAt" not in odds_df.columns:
        return "  Odds freshness: unknown (no timestamp in data)"

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC for comparison
    ages_min: list[float] = []

    for ts_str in odds_df["OddsUpdatedAt"].dropna().unique():
        if not ts_str:
            continue
        try:
            # ISO 8601 e.g. "2026-04-09T15:30:00Z"
            ts = datetime.strptime(ts_str.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
            ages_min.append((now - ts).total_seconds() / 60)
        except ValueError:
            continue

    if not ages_min:
        return "  Odds freshness: timestamps not parseable"

    oldest = max(ages_min)
    newest = min(ages_min)

    freshness = "LIVE" if newest < 5 else f"{newest:.0f}m old"
    warning = ""
    if oldest > 30:
        warning = f"  ⚠  STALE: oldest line is {oldest:.0f} min old — run --refresh before betting"
    elif oldest > 10:
        warning = f"  ⚠  Some lines up to {oldest:.0f} min old — verify before placing bets"

    lines = [f"  Odds freshness: {freshness} (range {newest:.0f}–{oldest:.0f} min old)"]
    if warning:
        lines.append(warning)
    return "\n".join(lines)


def get_consensus_prob(
    odds_df: pd.DataFrame,
) -> dict[tuple[str, str], tuple[float, float]]:
    """
    Compute de-vigged sharp consensus probability from DK + FD + BetMGM.

    For each game, averages the no-vig probability across all sharp books.
    No-vig: home_prob_nv = home_implied / (home_implied + away_implied)

    Returns {(home_canonical, away_canonical): (home_prob_nv, away_prob_nv)}
    """
    if odds_df.empty or "HomeMoneyline" not in odds_df.columns:
        return {}

    sharp = odds_df[odds_df["Sportsbook"].isin(SHARP_BOOKS)]
    if sharp.empty:
        return {}

    result: dict[tuple[str, str], tuple[float, float]] = {}

    for game_id in sharp["GameID"].unique():
        game = sharp[sharp["GameID"] == game_id]
        valid = game.dropna(subset=["HomeMoneyline", "AwayMoneyline"])
        if valid.empty:
            continue

        home_col = "HomeTeamCanonical" if "HomeTeamCanonical" in game.columns else "HomeTeam"
        away_col = "AwayTeamCanonical" if "AwayTeamCanonical" in game.columns else "AwayTeam"
        home = game[home_col].iloc[0]
        away = game[away_col].iloc[0]
        if pd.isna(home):
            home = game["HomeTeam"].iloc[0]
        if pd.isna(away):
            away = game["AwayTeam"].iloc[0]

        home_novig: list[float] = []
        for _, row in valid.iterrows():
            h = _american_to_prob(row["HomeMoneyline"])
            a = _american_to_prob(row["AwayMoneyline"])
            total = h + a
            if total > 0:
                home_novig.append(h / total)

        if not home_novig:
            continue

        hp = sum(home_novig) / len(home_novig)
        result[(home, away)] = (hp, 1.0 - hp)

    return result


def fetch_event_odds(
    event_id: str,
    markets: str = "pitcher_strikeouts,batter_hits,batter_total_bases,batter_home_runs,h2h_1st_1_innings",
    sport: str = "baseball_mlb",
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch per-event odds for player props and game period markets.

    The Odds API requires per-event calls for these markets (1 call per game).
    This is more expensive on the free tier, so use judiciously.

    Returns DataFrame with columns depending on market type:
    - For props: PlayerName, Market, Line, OverOdds, UnderOdds, Sportsbook
    - For game period: HomeTeam, AwayTeam, Market, Odds fields, Sportsbook
    """
    api_key = _get_api_key()
    if not api_key or api_key == "your_key_here":
        return pd.DataFrame()

    # Hash the markets list — with the full prop catalog (17 keys) the raw string
    # makes a 289-char filename that hits the OS limit (Errno 63), which crashed
    # the props fetch and silently killed all prop closing-line capture (→ 0 CLV).
    import hashlib
    _mkt_tag = hashlib.md5(markets.encode()).hexdigest()[:12]
    cache = _cache_path(f"event_{event_id}_{_mkt_tag}", sport=sport)
    if cache.exists() and not refresh:
        cache_age = time.time() - cache.stat().st_mtime
        if cache_age < 3600:
            with open(cache) as f:
                data = json.load(f)
            return _parse_event_odds(data)

    url = f"{API_BASE}/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "bookmakers": BOOKMAKERS,
        "markets": markets,
        "oddsFormat": "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code in (401, 404, 429):
            if cache.exists():
                with open(cache) as f:
                    return _parse_event_odds(json.load(f))
            return pd.DataFrame()

        resp.raise_for_status()
        data = resp.json()

        with open(cache, "w") as f:
            json.dump(data, f)

        remaining = resp.headers.get("x-requests-remaining", "unknown")
        print(f"  Event odds fetched (event={event_id[:8]}...). Requests remaining: {remaining}")

        return _parse_event_odds(data)

    except requests.RequestException:
        if cache.exists():
            with open(cache) as f:
                return _parse_event_odds(json.load(f))
        return pd.DataFrame()


def _parse_event_odds(data: dict) -> pd.DataFrame:
    """Parse per-event odds response into a DataFrame."""
    rows = []

    home = data.get("home_team", "")
    away = data.get("away_team", "")
    event_id = data.get("id", "")

    for bookmaker in data.get("bookmakers", []):
        book_name = bookmaker.get("title", "")

        for market in bookmaker.get("markets", []):
            market_key = market.get("key", "")
            outcomes = market.get("outcomes", [])

            for outcome in outcomes:
                row = {
                    "EventID": event_id,
                    "HomeTeam": home,
                    "AwayTeam": away,
                    "Sportsbook": book_name,
                    "Market": market_key,
                    "Name": outcome.get("description", outcome.get("name", "")),
                    "Selection": outcome.get("name", ""),
                    "Odds": outcome.get("price", 0),
                    "Line": outcome.get("point"),
                }
                rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def fetch_events_list(
    sport: str = "baseball_mlb",
    refresh: bool = False,
) -> list[dict]:
    """
    Fetch the list of upcoming events (games) for a sport.
    Returns list of {id, home_team, away_team, commence_time}.
    """
    api_key = _get_api_key()
    if not api_key or api_key == "your_key_here":
        return []

    cache = _cache_path("events_list", sport=sport)
    if cache.exists() and not refresh:
        cache_age = time.time() - cache.stat().st_mtime
        if cache_age < 3600:
            with open(cache) as f:
                return json.load(f)

    url = f"{API_BASE}/sports/{sport}/events"
    params = {"apiKey": api_key}

    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            if cache.exists():
                with open(cache) as f:
                    return json.load(f)
            return []

        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)

        return [
            {
                "id": e.get("id"),
                "home_team": e.get("home_team"),
                "away_team": e.get("away_team"),
                "commence_time": e.get("commence_time"),
            }
            for e in data
        ]
    except requests.RequestException:
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


def fetch_golf_outrights(
    sport: str = "golf_masters_tournament_winner",
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch golf outright winner odds from the Odds API.

    Returns DataFrame with columns: Player, Sportsbook, Odds
    sorted by Odds ascending (favorites first).
    """
    api_key = _get_api_key()
    if not api_key or api_key == "your_key_here":
        print("Warning: No ODDS_API_KEY set.")
        return pd.DataFrame()

    cache = _cache_path("outrights", sport=sport)
    if cache.exists() and not refresh:
        cache_age = time.time() - cache.stat().st_mtime
        if cache_age < 3600:
            with open(cache) as f:
                data = json.load(f)
            return _parse_golf_outrights(data)

    url = f"{API_BASE}/sports/{sport}/odds"
    params = {
        "apiKey": api_key,
        "bookmakers": BOOKMAKERS,
        "markets": "outrights",
        "oddsFormat": "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            print("Warning: Invalid ODDS_API_KEY.")
            return pd.DataFrame()
        if resp.status_code == 422:
            print(f"Warning: {sport} not available or no outright market.")
            return pd.DataFrame()
        resp.raise_for_status()
        data = resp.json()

        with open(cache, "w") as f:
            json.dump(data, f)

        remaining = resp.headers.get("x-requests-remaining", "unknown")
        print(f"  Golf outrights fetched. Requests remaining: {remaining}")

        return _parse_golf_outrights(data)

    except requests.RequestException as e:
        print(f"Warning: Odds API unreachable ({e}).")
        if cache.exists():
            with open(cache) as f:
                return _parse_golf_outrights(json.load(f))
        return pd.DataFrame()


def _parse_golf_outrights(data: list[dict]) -> pd.DataFrame:
    """Parse golf outrights API response → DataFrame of Player/Sportsbook/Odds."""
    rows = []
    for event in data:
        for bookmaker in event.get("bookmakers", []):
            book_name = bookmaker.get("title", "")
            for market in bookmaker.get("markets", []):
                if market.get("key") != "outrights":
                    continue
                for outcome in market.get("outcomes", []):
                    rows.append({
                        "Player": outcome.get("name", ""),
                        "Sportsbook": book_name,
                        "Odds": outcome.get("price", 0),
                    })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Filter to preferred US books
    preferred = df[df["Sportsbook"].isin(PREFERRED_BOOKS)]
    df = preferred if not preferred.empty else df
    return df.sort_values("Odds").reset_index(drop=True)


def get_best_golf_odds(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each player, return the best (highest) odds across books.
    Returns DataFrame with Player, BestOdds, BestBook sorted by BestOdds.
    """
    if df.empty:
        return df

    best_rows = []
    for player in df["Player"].unique():
        player_df = df[df["Player"] == player]
        idx = player_df["Odds"].idxmax()
        best_rows.append({
            "Player": player,
            "BestOdds": int(player_df.loc[idx, "Odds"]),
            "BestBook": player_df.loc[idx, "Sportsbook"],
        })

    result = pd.DataFrame(best_rows).sort_values("BestOdds").reset_index(drop=True)
    return result


def list_sports(refresh: bool = False) -> pd.DataFrame:
    """
    Return available sports from the Odds API.
    """
    api_key = _get_api_key()
    if not api_key or api_key == "your_key_here":
        return pd.DataFrame()

    cache = _cache_path("sports_catalog", sport="all")
    if cache.exists() and not refresh:
        cache_age = time.time() - cache.stat().st_mtime
        if cache_age < 86400:
            with open(cache) as f:
                return pd.DataFrame(json.load(f))

    url = f"{API_BASE}/sports"
    try:
        resp = requests.get(url, params={"apiKey": api_key}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        return pd.DataFrame(data)
    except requests.RequestException:
        if cache.exists():
            with open(cache) as f:
                return pd.DataFrame(json.load(f))
        return pd.DataFrame()
