"""
Train an NHL moneyline / puck-line / total model from historical game data.

Data path:
  1. For seasons SEASONS_TRAIN, pull end-of-season team stats (one call/stat/season)
     → per-team strength rating (GF/G, GA/G, PP%, PK%, SV%)
  2. For each season's regular-season window, walk day-by-day and pull
     /score/{date} for completed games → game-level outcomes
  3. Build feature matrix: each game gets the PRIOR season's strength rating
     for both teams (simple, clean, avoids same-season leakage)
  4. Train sklearn LogisticRegression on home_win label
  5. Save model + season ratings to models/nhl_logreg.pkl
"""
from __future__ import annotations

import json
import pickle
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


API_BASE = "https://api.nhle.com/stats/rest/en"
SCHEDULE_BASE = "https://api-web.nhle.com/v1"
CACHE_DIR = Path("data/cache/nhl_train")
MODELS_DIR = Path("models")
OUT_PATH = MODELS_DIR / "nhl_logreg.pkl"

# Seasons formatted as NHL season IDs (start year + end year concatenated)
SEASONS_TRAIN = [20222023, 20232024, 20242025]
SEASON_DATE_RANGES = {
    20222023: (date(2022, 10, 7),  date(2023, 6, 13)),
    20232024: (date(2023, 10, 10), date(2024, 6, 24)),
    20242025: (date(2024, 10, 4),  date(2025, 6, 17)),
    20252026: (date(2025, 10, 7),  date(2026, 6, 30)),  # current, for live use
}


def _cache(key: str, max_age_s: int = 7 * 86400):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{key}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < max_age_s:
        with open(p) as f:
            return json.load(f)
    return None


def _save_cache(key: str, data):
    with open(CACHE_DIR / f"{key}.json", "w") as f:
        json.dump(data, f)


def fetch_team_summary(season_id: int, game_type: int = 2) -> list[dict]:
    """End-of-season team stats. game_type 2=regular, 3=playoffs."""
    key = f"team_summary_{season_id}_t{game_type}"
    cached = _cache(key)
    if cached is not None:
        return cached
    url = f"{API_BASE}/team/summary"
    params = {"cayenneExp": f"seasonId={season_id} and gameTypeId={game_type}", "limit": -1}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", [])
    _save_cache(key, data)
    return data


def fetch_goalie_summary(season_id: int, game_type: int = 2) -> list[dict]:
    key = f"goalie_summary_{season_id}_t{game_type}"
    cached = _cache(key)
    if cached is not None:
        return cached
    url = f"{API_BASE}/goalie/summary"
    params = {"cayenneExp": f"seasonId={season_id} and gameTypeId={game_type}", "limit": -1}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", [])
    _save_cache(key, data)
    return data


_NAME_TO_ABBREV = {
    "Anaheim Ducks": "ANA", "Arizona Coyotes": "ARI", "Boston Bruins": "BOS",
    "Buffalo Sabres": "BUF", "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR",
    "Chicago Blackhawks": "CHI", "Colorado Avalanche": "COL",
    "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL", "Detroit Red Wings": "DET",
    "Edmonton Oilers": "EDM", "Florida Panthers": "FLA", "Los Angeles Kings": "LAK",
    "Minnesota Wild": "MIN", "Montréal Canadiens": "MTL", "Montreal Canadiens": "MTL",
    "Nashville Predators": "NSH", "New Jersey Devils": "NJD",
    "New York Islanders": "NYI", "New York Rangers": "NYR", "Ottawa Senators": "OTT",
    "Philadelphia Flyers": "PHI", "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJS",
    "Seattle Kraken": "SEA", "St. Louis Blues": "STL", "Tampa Bay Lightning": "TBL",
    "Toronto Maple Leafs": "TOR", "Utah Hockey Club": "UTA", "Utah Mammoth": "UTA",
    "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
}


def build_team_ratings(season_id: int) -> dict[str, dict]:
    """Per-team strength ratings keyed by abbreviation (e.g. 'BOS')."""
    teams = fetch_team_summary(season_id, game_type=2)
    goalies = fetch_goalie_summary(season_id, game_type=2)

    # Best goalie per team (by games started)
    # Goalie response uses teamAbbrevs OR maps via name — try both
    team_top_sv: dict[str, float] = {}
    for g in sorted(goalies, key=lambda x: x.get("gamesStarted", 0), reverse=True):
        # Try abbreviations field first, then fall back to mapping team name
        abbrevs_field = (g.get("teamAbbrevs") or "")
        abbrevs = [a for a in abbrevs_field.upper().split(",") if a]
        if not abbrevs:
            full = g.get("teamFullName", "") or ""
            mapped = _NAME_TO_ABBREV.get(full)
            if mapped:
                abbrevs = [mapped]
        for a in abbrevs:
            if a not in team_top_sv:
                team_top_sv[a] = g.get("savePct") or 0.898

    out = {}
    for t in teams:
        full = t.get("teamFullName", "")
        abbr = _NAME_TO_ABBREV.get(full)
        if not abbr:
            # Fallback to teamAbbrevs if present, else skip
            abbr_field = (t.get("teamAbbrevs") or "").upper().split(",")[0]
            abbr = abbr_field or None
        if not abbr:
            continue
        out[abbr] = {
            "gf_pg": t.get("goalsForPerGame", 3.05),
            "ga_pg": t.get("goalsAgainstPerGame", 3.05),
            "pp_pct": t.get("powerPlayPct", 0.200),
            "pk_pct": t.get("penaltyKillPct", 0.800),
            "sf_pg": t.get("shotsForPerGame", 30.0),
            "sa_pg": t.get("shotsAgainstPerGame", 30.0),
            "point_pct": t.get("pointPct", 0.5),
            "sv_pct": team_top_sv.get(abbr, 0.898),
        }
    return out


def fetch_day_games(d: date) -> list[dict]:
    """Completed games on date d."""
    key = f"score_{d.isoformat()}"
    cached = _cache(key, max_age_s=30 * 86400)
    if cached is not None:
        return cached
    url = f"{SCHEDULE_BASE}/score/{d.isoformat()}"
    raw = None
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            raw = r.json()
            break
        except Exception:
            time.sleep(0.5 + attempt)
    if raw is None:
        return []  # don't cache failures — retry next run
    games = []
    for g in raw.get("games", []):
        if g.get("gameState") not in ("OFF", "FINAL"):
            continue
        games.append({
            "date": d.isoformat(),
            "home_abbrev": g["homeTeam"].get("abbrev", "").upper(),
            "away_abbrev": g["awayTeam"].get("abbrev", "").upper(),
            "home_score": int(g["homeTeam"].get("score", 0) or 0),
            "away_score": int(g["awayTeam"].get("score", 0) or 0),
            "game_type": g.get("gameType", 2),
        })
    _save_cache(key, games)
    return games


def collect_season_games(season_id: int) -> list[dict]:
    """Walk every date in the season and collect completed games."""
    start, end = SEASON_DATE_RANGES[season_id]
    games = []
    d = start
    n_days = 0
    while d <= end:
        day_games = fetch_day_games(d)
        for g in day_games:
            g["season_id"] = season_id
            games.append(g)
        d += timedelta(days=1)
        n_days += 1
        # Gentle pacing to avoid rate limits — only when not cache-hit
        if n_days % 30 == 0:
            print(f"  [{season_id}] {n_days} days scanned, {len(games)} games so far...", flush=True)
    return games


def make_features(game: dict, ratings: dict[str, dict]) -> list[float] | None:
    """Feature vector for one game using prior-season strength ratings."""
    h = ratings.get(game["home_abbrev"])
    a = ratings.get(game["away_abbrev"])
    if not h or not a:
        return None
    return [
        h["gf_pg"] - a["ga_pg"],          # home expected scoring vs away defense
        a["gf_pg"] - h["ga_pg"],          # away expected scoring vs home defense
        h["point_pct"] - a["point_pct"],  # overall strength differential
        h["sv_pct"] - a["sv_pct"],        # goalie differential
        h["pp_pct"] - a["pk_pct"],        # home PP vs away PK
        a["pp_pct"] - h["pk_pct"],        # away PP vs home PK
        h["sf_pg"] - a["sa_pg"],
        a["sf_pg"] - h["sa_pg"],
        1.0,                              # home-ice indicator (constant — capture with intercept)
    ]


FEATURE_NAMES = [
    "home_xg_off", "away_xg_off", "point_pct_diff", "sv_pct_diff",
    "home_pp_adv", "away_pp_adv", "home_shots_adv", "away_shots_adv", "home_ice",
]


def main() -> None:
    print("=== NHL Training Pipeline ===")

    # 1. Build per-season ratings (we need PRIOR season ratings, so include the
    #    season before SEASONS_TRAIN[0])
    rating_seasons = [20212022] + SEASONS_TRAIN  # noqa: F841
    SEASON_DATE_RANGES[20212022] = (date(2021, 10, 12), date(2022, 6, 26))

    season_ratings: dict[int, dict[str, dict]] = {}
    for s in [20212022] + SEASONS_TRAIN:
        print(f"Fetching team ratings for {s}...")
        season_ratings[s] = build_team_ratings(s)
        print(f"  → {len(season_ratings[s])} teams")

    # 2. Walk training seasons, collect games
    all_games = []
    for s in SEASONS_TRAIN:
        print(f"Collecting games for season {s}...")
        gms = collect_season_games(s)
        print(f"  → {len(gms)} games")
        all_games.extend(gms)

    print(f"\nTotal games collected: {len(all_games)}")

    # 3. Build feature matrix using PRIOR season ratings
    prior_season = {s: prev for prev, s in zip([20212022] + SEASONS_TRAIN[:-1], SEASONS_TRAIN)}
    X, y = [], []
    for g in all_games:
        prev = prior_season.get(g["season_id"])
        if not prev:
            continue
        feats = make_features(g, season_ratings[prev])
        if not feats:
            continue
        X.append(feats)
        y.append(1 if g["home_score"] > g["away_score"] else 0)

    X = np.array(X)
    y = np.array(y)
    print(f"\nFeature matrix: {X.shape}, home_win_rate={y.mean():.3f}")

    # 4. Time-based split: hold out the last training season
    cutoff = SEASONS_TRAIN[-1]
    train_mask = np.array(
        [g["season_id"] != cutoff for g in all_games
         if g["season_id"] in prior_season
         and make_features(g, season_ratings[prior_season[g["season_id"]]])],
        dtype=bool,
    )
    Xtr, Xval = X[train_mask], X[~train_mask]
    ytr, yval = y[train_mask], y[~train_mask]
    print(f"Train: {Xtr.shape}, Holdout({cutoff}): {Xval.shape}")

    model = LogisticRegression(C=1.0, max_iter=1000)
    model.fit(Xtr, ytr)

    pred = model.predict_proba(Xval)[:, 1]
    print(f"\nHoldout metrics (season {cutoff}):")
    print(f"  Brier: {brier_score_loss(yval, pred):.4f}")
    print(f"  LogLoss: {log_loss(yval, pred):.4f}")
    print(f"  AUC: {roc_auc_score(yval, pred):.4f}")
    print(f"  Naive home-win baseline Brier: {brier_score_loss(yval, np.full_like(yval, 0.55, dtype=float)):.4f}")

    print("\nFeature coefficients:")
    for name, coef in zip(FEATURE_NAMES, model.coef_[0]):
        print(f"  {name:20s} {coef:+.4f}")
    print(f"  intercept            {model.intercept_[0]:+.4f}")

    # 5. Save model + ratings (using most recent rating set for live inference)
    MODELS_DIR.mkdir(exist_ok=True)
    payload = {
        "model": model,
        "feature_names": FEATURE_NAMES,
        "ratings_by_season": season_ratings,
        "latest_season": SEASONS_TRAIN[-1],
        "trained_at": datetime.utcnow().isoformat(),
    }
    with open(OUT_PATH, "wb") as f:
        pickle.dump(payload, f)
    print(f"\n✓ Saved → {OUT_PATH}")


if __name__ == "__main__":
    main()
