"""
Tennis player data — dual-tour (ATP + WTA) surface Elo from tennis-data.co.uk.

Rebuilt 2026-07-13. The previous engine fetched JeffSackmann/tennis_atp (repo
now 404s — the "live Elo" cache had been silently EMPTY), covered no WTA at
all, and defaulted every unknown player to 1750 Elo. Result: most matches were
rated 1750-vs-1750 → 50/50 → phantom "edges" on every non-even price. This
version is built on the published playbook:

  - Elo win prob = 1/(1+10^(-d/400))              (standard)
  - K = 250 / (matches + 5)^0.4                   (FiveThirtyEight tennis Elo)
  - Rating = ½·overall + ½·surface Elo            (Tennis Abstract: uniform
                                                   blend tested optimal)
  - Ranking-based prior for sparse players        (Kovalchik 2016: ranking
                                                   regressions beat everything
                                                   for low-data players; all
                                                   models degrade 10-20pts on
                                                   lower-ranked players)
  - New players start at 1500, NOT 1750.

Data source: tennis-data.co.uk yearly workbooks (both tours). One source
provides match results (Elo training + grading), set scores (totals grading),
world rankings (sparse-player prior), and Pinnacle closing odds (calibration
backtests). Cached under data/cache/tennis/.

References:
  Kovalchik (2016) "Searching for the GOAT of tennis win prediction", JQAS.
  FiveThirtyEight (2016) "How We're Forecasting The U.S. Open".
  Tennis Abstract (2019) "An Introduction to Tennis Elo".
"""
from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from pathlib import Path

CACHE_DIR = Path("data/cache/tennis")

_TD_BASE = "http://www.tennis-data.co.uk"
# Years of history to train on. Elo converges after a season; four years keeps
# ratings current without dragging in retired-player noise.
DEFAULT_YEARS = [2023, 2024, 2025, 2026]

# 538 K-factor: K = 250/(m+5)^0.4 (m = player's matches seen so far).
_K_NUM, _K_OFF, _K_SHAPE = 250.0, 5.0, 0.4

# Surface blend: rating = _BLEND·overall + (1-_BLEND)·surface.
# Tennis Abstract found uniform 50/50 optimal across surfaces
# (FiveThirtyEight used 0.71/0.29 for hard courts — close enough that the
# simpler constant wins).
_BLEND = 0.5

# Sparse-player handling (Kovalchik: rankings carry the signal when match
# history doesn't). Observed Elo is shrunk toward a rank-implied prior with
# weight m/(m+_PRIOR_M): at 0 matches you're purely your ranking, at 30 matches
# ranking is a third of the estimate, at 100+ it barely matters.
_PRIOR_M = 15.0

MIN_MATCHES_KNOWN = 10   # below this a player is "sparse" — callers should
                         # anchor hard to the market (see tennis_model)


def elo_win_prob(elo_a: float, elo_b: float) -> float:
    """P(player A beats player B) given Elo ratings."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def elo_from_rank(rank: float | None) -> float:
    """Rank-implied Elo prior (log-linear, anchored to observed Elo ladders:
    #1 ≈ 2250, #10 ≈ 1990, #100 ≈ 1730, #300 ≈ 1600, unranked ≈ 1450)."""
    if rank is None or rank <= 0:
        return 1450.0
    return max(1450.0, 2250.0 - 260.0 * math.log10(float(rank)))


# ─────────────────────────── name normalization ─────────────────────────────
# tennis-data.co.uk stores "Sinner J." / "Auger-Aliassime F." / "De Minaur A.".
# The Odds API sends "Jannik Sinner" / "Felix Auger-Aliassime" / "Alex De
# Minaur". Both are normalized to the key "<lastname> <first-initial>".

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_td_name(name: str) -> str:
    """'Auger-Aliassime F.' → 'auger-aliassime f'"""
    s = _strip_accents(str(name)).lower().strip().rstrip(".")
    return re.sub(r"\s+", " ", s)


def norm_odds_name(name: str) -> str:
    """'Felix Auger-Aliassime' → 'auger-aliassime f'.

    Rule: everything after the first token is the surname (handles De Minaur,
    Van Assche, Auger-Aliassime); the first token contributes the initial.
    """
    s = _strip_accents(str(name)).strip()
    parts = s.split()
    if len(parts) < 2:
        return s.lower()
    first, last = parts[0], " ".join(parts[1:])
    return f"{last.lower()} {first[0].lower()}"


def last_name_of(key: str) -> str:
    """Surname portion of a normalized key ('auger-aliassime f' → 'auger-aliassime')."""
    return key.rsplit(" ", 1)[0] if " " in key else key


# ─────────────────────────── match data loading ─────────────────────────────

def _td_url(tour: str, year: int) -> str:
    """tennis-data.co.uk workbook URL. ATP lives at /YYYY/, WTA at /YYYYw/."""
    suffix = "w" if tour == "wta" else ""
    return f"{_TD_BASE}/{year}{suffix}/{year}.xlsx"


def _td_cache_path(tour: str, year: int) -> Path:
    return CACHE_DIR / f"td_{tour}_{year}.xlsx"


def load_matches(tour: str, years: list[int] | None = None,
                 refresh_current: bool = True, verbose: bool = False):
    """Load tennis-data.co.uk matches for one tour as a DataFrame sorted by
    date. Past years cache forever; the current year re-downloads when the
    cache is older than 12h (the site updates daily during tournaments).
    Returns an empty DataFrame when nothing could be loaded.
    """
    import pandas as pd
    import requests

    years = years or DEFAULT_YEARS
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    from datetime import date as _date
    cur_year = _date.today().year

    for year in years:
        path = _td_cache_path(tour, year)
        stale = (year >= cur_year and refresh_current and path.exists()
                 and time.time() - path.stat().st_mtime > 12 * 3600)
        if not path.exists() or stale:
            try:
                resp = requests.get(_td_url(tour, year), timeout=30)
                resp.raise_for_status()
                path.write_bytes(resp.content)
                if verbose:
                    print(f"  [tennis-data] downloaded {tour} {year} "
                          f"({len(resp.content)//1024} KB)")
            except Exception as e:
                if verbose:
                    print(f"  [tennis-data] {tour} {year} fetch failed: {e}")
                if not path.exists():
                    continue
        try:
            df = pd.read_excel(path)
            # NB: no leading underscore — itertuples() renames those positionally
            df["SrcYear"] = year
            frames.append(df)
        except Exception as e:
            if verbose:
                print(f"  [tennis-data] {tour} {year} parse failed: {e}")

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    return out.sort_values("Date").reset_index(drop=True)


# ─────────────────────────── Elo engine ─────────────────────────────────────

def _surface_key(surface: str) -> str:
    s = str(surface or "").lower()
    if "clay" in s:
        return "clay"
    if "grass" in s:
        return "grass"
    return "hard"   # hard + carpet + indoor


def build_ratings(matches, verbose: bool = False) -> dict:
    """Chronological Elo over a tennis-data match frame.

    Returns {player_key: {"overall": elo, "clay": elo, "hard": elo,
                          "grass": elo, "matches": n, "rank": latest_rank}}.
    Surface Elos start from 1500 independently; K decays with the player's
    total match count (538 formula) so early results move ratings fast and a
    veteran's rating is stable.
    """
    import pandas as pd

    players: dict[str, dict] = {}

    def _get(name_key: str) -> dict:
        return players.setdefault(name_key, {
            "overall": 1500.0, "clay": 1500.0, "hard": 1500.0,
            "grass": 1500.0, "matches": 0, "rank": None,
        })

    def _k(m: int) -> float:
        return _K_NUM / ((m + _K_OFF) ** _K_SHAPE)

    n_used = 0
    for row in matches.itertuples(index=False):
        w_raw, l_raw = getattr(row, "Winner", None), getattr(row, "Loser", None)
        if not isinstance(w_raw, str) or not isinstance(l_raw, str):
            continue
        # Retirements/walkovers carry little skill signal but tennis-data
        # includes them; "Completed" and "Retired" both count a real result —
        # only walkovers are excluded.
        comment = str(getattr(row, "Comment", "") or "").lower()
        if "walkover" in comment:
            continue
        wk, lk = norm_td_name(w_raw), norm_td_name(l_raw)
        surf = _surface_key(getattr(row, "Surface", ""))
        w, l = _get(wk), _get(lk)

        for field in ("overall", surf):
            exp_w = elo_win_prob(w[field], l[field])
            kw, kl = _k(w["matches"]), _k(l["matches"])
            w[field] = w[field] + kw * (1.0 - exp_w)
            l[field] = l[field] - kl * (1.0 - exp_w)

        w["matches"] += 1
        l["matches"] += 1
        wr, lr = getattr(row, "WRank", None), getattr(row, "LRank", None)
        if pd.notna(wr):
            w["rank"] = float(wr)
        if pd.notna(lr):
            l["rank"] = float(lr)
        n_used += 1

    if verbose:
        print(f"  [tennis-elo] rated {len(players)} players from {n_used} matches")
    return players


# ─────────────────────────── rating store ───────────────────────────────────

_RATINGS_CACHE = CACHE_DIR / "ratings_v2.json"
_RATINGS_TTL_S = 12 * 3600
_ratings_mem: dict[str, dict] | None = None


def refresh_ratings(years: list[int] | None = None, verbose: bool = False) -> dict:
    """(Re)build both tours' ratings from tennis-data and cache to disk."""
    out: dict[str, dict] = {}
    for tour in ("atp", "wta"):
        matches = load_matches(tour, years=years, verbose=verbose)
        if len(matches) == 0:
            if verbose:
                print(f"  [tennis-elo] no {tour} matches loaded")
            out[tour] = {}
            continue
        out[tour] = build_ratings(matches, verbose=verbose)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _RATINGS_CACHE.write_text(json.dumps(out))
    global _ratings_mem
    _ratings_mem = out
    return out


def get_ratings(verbose: bool = False) -> dict:
    """Load ratings from memory → disk cache (12h TTL) → full rebuild."""
    global _ratings_mem
    if _ratings_mem is not None:
        return _ratings_mem
    if _RATINGS_CACHE.exists():
        age = time.time() - _RATINGS_CACHE.stat().st_mtime
        if age < _RATINGS_TTL_S:
            try:
                _ratings_mem = json.loads(_RATINGS_CACHE.read_text())
                # An empty cache is a failed build, not a valid one — the old
                # engine served {} for months and nobody noticed.
                if any(_ratings_mem.get(t) for t in ("atp", "wta")):
                    return _ratings_mem
            except (json.JSONDecodeError, OSError):
                pass
    return refresh_ratings(verbose=verbose)


def _lookup(ratings_tour: dict[str, dict], odds_name: str) -> dict | None:
    """Find a player record from an Odds API display name. Exact normalized
    key first, then unique surname+initial, then unique surname."""
    key = norm_odds_name(odds_name)
    rec = ratings_tour.get(key)
    if rec is not None:
        return rec
    # surname + initial (handles middle names: "Juan Manuel Cerundolo")
    last, initial = last_name_of(key), key[-1]
    cands = [r for k, r in ratings_tour.items()
             if last_name_of(k).split()[-1] == last.split()[-1] and k[-1] == initial]
    if len(cands) == 1:
        return cands[0]
    # unique bare surname
    cands = [r for k, r in ratings_tour.items()
             if last_name_of(k).split()[-1] == last.split()[-1]]
    if len(cands) == 1:
        return cands[0]
    return None


def get_rating_info(odds_name: str, surface: str = "hard",
                    tour: str = "atp") -> tuple[float, int]:
    """(blended Elo, matches seen) for an Odds API player name.

    Blend = ½ overall + ½ surface (Tennis Abstract), then shrink toward the
    rank-implied prior by m/(m+15) (Kovalchik: rankings carry the signal for
    sparse players). Unknown players: (1500, 0) — the caller must treat a
    0-match player as pure market.
    """
    ratings = get_ratings()
    rec = _lookup(ratings.get(tour, {}), odds_name)
    if rec is None:
        return 1500.0, 0
    surf = _surface_key(surface)
    observed = _BLEND * rec["overall"] + (1.0 - _BLEND) * rec.get(surf, 1500.0)
    m = int(rec.get("matches", 0))
    w = m / (m + _PRIOR_M)
    prior = elo_from_rank(rec.get("rank"))
    return w * observed + (1.0 - w) * prior, m


# ─────────────────────────── legacy compatibility ────────────────────────────
# Old callers import these names. get_player_rating now routes through the new
# engine (ATP by default) and returns 1500 — not 1750 — for unknowns.

SERVE_WIN_BY_SURFACE: dict[str, float] = {
    "clay":  0.620,
    "hard":  0.640,
    "grass": 0.680,
}
SERVE_WIN_STD = 0.035


def get_player_rating(name: str, surface: str = "clay") -> float:
    elo, _m = get_rating_info(name, surface=surface, tour="atp")
    return elo


def load_cached_elo(verbose: bool = False) -> bool:
    """Legacy shim: warm the new ratings cache. True if ratings available."""
    r = get_ratings(verbose=verbose)
    return any(r.get(t) for t in ("atp", "wta"))


