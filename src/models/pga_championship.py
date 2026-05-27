"""
PGA Tour Major Picks — Monte Carlo simulation model.

Supports all four majors + The Players via COURSE_PROFILES. Auto-detects the
active tournament from the Odds API sport key, or defaults to Quail Hollow.

Live SG ratings: scraped from the same CDN pgatour.com uses for its stats pages
(statdata.pgatour.com). No API key required, cached 24h, fails silently.
Falls back to the static PLAYER_DB if the CDN is unreachable.

Model approach:
  1. Each player gets a skill rating = weighted SG composite
  2. Course-fit adjustments for the active venue
  3. Per-round score sampled from Normal(expected_score, σ)
  4. 4 rounds summed → lowest total wins
  5. 100k simulations → win probability per player
  6. Compare to market implied probability → edge
"""
from __future__ import annotations

import json
import math
import os
import random
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

_SG_CACHE_DIR = Path("data/cache/pgatour_sg")
_SG_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# PGA Tour stat IDs used on pgatour.com (stable across seasons)
_PGA_STAT_IDS = {
    "sg_total": "02674",
    "sg_ott":   "02567",
    "sg_app":   "02568",
    "sg_atg":   "02569",
    "sg_putt":  "02564",
}

# ── PGA Tour live SG ratings (free, no key required) ─────────────────────────

def _fetch_pgatour_stat(stat_id: str, season: int, refresh: bool = False) -> dict[str, float]:
    """
    Fetch a single SG stat for all players from the PGA Tour stats CDN.

    Uses statdata.pgatour.com — the same backend pgatour.com's stats pages hit.
    No authentication needed. Returns {player_name: value} or {} on error.
    Caches 24h.
    """
    cache = _SG_CACHE_DIR / f"{stat_id}_{season}.json"
    if not refresh and cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < 86400:
            try:
                with open(cache) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    try:
        import requests as req
        r = req.get(
            f"https://statdata.pgatour.com/r/{season}/{stat_id}.json",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        result: dict[str, float] = {}
        for row in data.get("plrs", []):
            name = row.get("n", "").strip()
            val  = row.get("v") or row.get("avg") or row.get("total") or "0"
            if name:
                try:
                    result[name] = float(str(val).replace(",", ""))
                except (ValueError, TypeError):
                    pass
        if result:
            with open(cache, "w") as f:
                json.dump(result, f)
        return result
    except Exception:
        return {}


def _fetch_pgatour_sg_ratings(season: int | None = None, refresh: bool = False) -> dict[str, dict]:
    """
    Fetch all five SG components from pgatour.com stats CDN.

    Returns {player_name: {sg_total, sg_app, sg_ott, sg_putt, sg_atg}} or {}
    if the CDN is unreachable (triggers static PLAYER_DB fallback in caller).
    """
    if season is None:
        from datetime import datetime as _dt
        season = _dt.now().year

    stats: dict[str, dict[str, float]] = {}
    for sg_key, stat_id in _PGA_STAT_IDS.items():
        player_vals = _fetch_pgatour_stat(stat_id, season, refresh=refresh)
        for name, val in player_vals.items():
            stats.setdefault(name, {})[sg_key] = val

    # Only return players where we got at least sg_total
    result = {
        name: vals
        for name, vals in stats.items()
        if "sg_total" in vals
    }
    if result:
        print(f"  [PGA Tour stats] Loaded live SG ratings for {len(result)} players.")
    return result


def _merge_live_ratings(static_db: dict[str, dict], live: dict[str, dict]) -> dict[str, dict]:
    """
    Merge live PGA Tour SG ratings into the static player DB.

    Live data overwrites sg_total/sg_app/sg_ott/sg_putt/sg_atg.
    form, major_exp, and course history carry over from the static DB.
    Players in live data but not in static DB get default bonuses.
    """
    merged: dict[str, dict] = {}
    for name, live_stats in live.items():
        static = static_db.get(name, {})
        merged[name] = {
            **live_stats,
            "form":      static.get("form", 1.0),
            "major_exp": static.get("major_exp", 0.02),
        }
        # Carry over any course-specific history keys (qh_history, masters_history, etc.)
        for k, v in static.items():
            if k.endswith("_history") and k not in merged[name]:
                merged[name][k] = v

    # Also include static DB players not in live data (keep them as-is)
    for name, static in static_db.items():
        if name not in merged:
            merged[name] = static

    return merged

# ── Player database ───────────────────────────────────────────────────────────
# sg_total:   season-avg strokes gained vs. field per round
# sg_app:     SG approach (most course-relevant at QH)
# sg_ott:     SG off the tee
# sg_putt:    SG putting
# sg_atg:     SG around the green
# form:       recent 8-week form multiplier (0.8=cold, 1.0=avg, 1.2=hot)
# major_exp:  PGA Championship specific bonus (wins=0.15/top5=0.08/top10=0.04)
# qh_history: course bonus for Quail Hollow (Wells Fargo wins / top finishes)
#
# Stats are 2025-2026 PGA Tour season approximations based on
# world rankings + known performance profiles. Live SG data is fetched from
# statdata.pgatour.com at runtime and merged on top of these entries.

PLAYER_DB: dict[str, dict] = {
    # ── Elite tier ─────────────────────────────────────────────────────────
    "Scottie Scheffler": {
        "sg_total": 3.45, "sg_app": 1.20, "sg_ott": 0.85,
        "sg_putt": 0.60, "sg_atg": 0.80,
        "form": 1.15, "major_exp": 0.10, "qh_history": 0.05,
    },
    "Rory McIlroy": {
        "sg_total": 2.50, "sg_app": 0.90, "sg_ott": 1.10,
        "sg_putt": 0.25, "sg_atg": 0.25,
        "form": 1.10, "major_exp": 0.08,
        "qh_history": 0.25,  # 4 Wells Fargo wins at Quail Hollow
    },
    "Cameron Young": {
        "sg_total": 2.20, "sg_app": 0.75, "sg_ott": 1.05,
        "sg_putt": 0.20, "sg_atg": 0.20,
        "form": 1.15, "major_exp": 0.04, "qh_history": 0.05,
    },
    "Jon Rahm": {
        "sg_total": 2.15, "sg_app": 1.00, "sg_ott": 0.60,
        "sg_putt": 0.25, "sg_atg": 0.30,
        "form": 1.10, "major_exp": 0.12, "qh_history": 0.05,
    },
    "Xander Schauffele": {
        "sg_total": 2.00, "sg_app": 0.85, "sg_ott": 0.65,
        "sg_putt": 0.25, "sg_atg": 0.25,
        "form": 1.05, "major_exp": 0.15, "qh_history": 0.0,
        # Won 2024 PGA Championship
    },
    "Ludvig Aberg": {
        "sg_total": 2.00, "sg_app": 0.95, "sg_ott": 0.70,
        "sg_putt": 0.15, "sg_atg": 0.20,
        "form": 1.08, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Bryson DeChambeau": {
        "sg_total": 1.80, "sg_app": 0.55, "sg_ott": 1.40,
        "sg_putt": -0.10, "sg_atg": -0.05,
        "form": 1.05, "major_exp": 0.12, "qh_history": 0.0,
    },
    "Matthew Fitzpatrick": {
        "sg_total": 1.80, "sg_app": 1.10, "sg_ott": 0.30,
        "sg_putt": 0.20, "sg_atg": 0.20,
        "form": 1.05, "major_exp": 0.10, "qh_history": 0.10,
    },
    "Tommy Fleetwood": {
        "sg_total": 1.70, "sg_app": 1.05, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.15,
        "form": 1.08, "major_exp": 0.06, "qh_history": 0.05,
    },
    "Brooks Koepka": {
        "sg_total": 1.50, "sg_app": 0.70, "sg_ott": 0.55,
        "sg_putt": 0.10, "sg_atg": 0.15,
        "form": 0.95, "major_exp": 0.20, "qh_history": 0.05,
        # 3 PGA Championship wins — massive major_exp bonus
    },
    "Collin Morikawa": {
        "sg_total": 1.55, "sg_app": 1.15, "sg_ott": 0.05,
        "sg_putt": 0.15, "sg_atg": 0.20,
        "form": 1.02, "major_exp": 0.12, "qh_history": 0.0,
    },
    "Patrick Cantlay": {
        "sg_total": 1.50, "sg_app": 0.80, "sg_ott": 0.30,
        "sg_putt": 0.25, "sg_atg": 0.15,
        "form": 1.00, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Justin Rose": {
        "sg_total": 1.30, "sg_app": 0.75, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.15,
        "form": 1.10, "major_exp": 0.08, "qh_history": 0.0,
    },
    "Christopher Gotterup": {
        "sg_total": 1.45, "sg_app": 0.65, "sg_ott": 0.70,
        "sg_putt": -0.05, "sg_atg": 0.15,
        "form": 1.15, "major_exp": 0.00, "qh_history": 0.05,
    },
    "Russell Henley": {
        "sg_total": 1.40, "sg_app": 0.70, "sg_ott": 0.40,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.05,
    },
    "Rickie Fowler": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.08, "major_exp": 0.04, "qh_history": 0.10,
    },
    "Justin Thomas": {
        "sg_total": 1.40, "sg_app": 0.70, "sg_ott": 0.45,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 0.95, "major_exp": 0.12, "qh_history": 0.08,
    },
    "Tyrrell Hatton": {
        "sg_total": 1.40, "sg_app": 0.75, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.15,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Sam Burns": {
        "sg_total": 1.40, "sg_app": 0.60, "sg_ott": 0.50,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.10,
    },
    "J. J. Spaun": {
        "sg_total": 1.35, "sg_app": 0.60, "sg_ott": 0.45,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.12, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Min Woo Lee": {
        "sg_total": 1.30, "sg_app": 0.55, "sg_ott": 0.50,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 1.10, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Jake Knapp": {
        "sg_total": 1.30, "sg_app": 0.55, "sg_ott": 0.65,
        "sg_putt": -0.05, "sg_atg": 0.15,
        "form": 1.08, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Nicolai Hojgaard": {
        "sg_total": 1.30, "sg_app": 0.65, "sg_ott": 0.40,
        "sg_putt": 0.10, "sg_atg": 0.15,
        "form": 1.05, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Adam Scott": {
        "sg_total": 1.20, "sg_app": 0.60, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 1.00, "major_exp": 0.06, "qh_history": 0.0,
    },
    "Viktor Hovland": {
        "sg_total": 1.50, "sg_app": 0.65, "sg_ott": 0.55,
        "sg_putt": 0.15, "sg_atg": 0.15,
        "form": 0.90, "major_exp": 0.04, "qh_history": 0.0,
        # Cold form in 2026
    },
    "Si Woo Kim": {
        "sg_total": 1.15, "sg_app": 0.50, "sg_ott": 0.40,
        "sg_putt": 0.20, "sg_atg": 0.05,
        "form": 1.10, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Robert Macintyre": {
        "sg_total": 1.25, "sg_app": 0.55, "sg_ott": 0.50,
        "sg_putt": 0.10, "sg_atg": 0.10,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Hideki Matsuyama": {
        "sg_total": 1.20, "sg_app": 0.70, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 0.95, "major_exp": 0.06, "qh_history": 0.0,
    },
    "Jordan Spieth": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.20,
        "sg_putt": 0.35, "sg_atg": 0.10,
        "form": 0.98, "major_exp": 0.10, "qh_history": 0.08,
    },
    "Kurt Kitayama": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.10,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Harris English": {
        "sg_total": 1.15, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 1.08, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Sepp Straka": {
        "sg_total": 1.15, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.10,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Shane Lowry": {
        "sg_total": 1.10, "sg_app": 0.55, "sg_ott": 0.25,
        "sg_putt": 0.20, "sg_atg": 0.10,
        "form": 1.02, "major_exp": 0.08, "qh_history": 0.0,
    },
    "Maverick Mcnealy": {
        "sg_total": 1.15, "sg_app": 0.60, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.05, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Keegan Bradley": {
        "sg_total": 1.10, "sg_app": 0.50, "sg_ott": 0.40,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 0.98, "major_exp": 0.06, "qh_history": 0.0,
    },
    "Kristoffer Reitan": {
        "sg_total": 1.10, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.10, "sg_atg": 0.10,
        "form": 1.08, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Akshay Bhatia": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.50,
        "sg_putt": 0.05, "sg_atg": 0.10,
        "form": 1.10, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Joaquin Niemann": {
        "sg_total": 1.15, "sg_app": 0.55, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Patrick Reed": {
        "sg_total": 1.00, "sg_app": 0.55, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 0.95, "major_exp": 0.08, "qh_history": 0.0,
    },
    "Tony Finau": {
        "sg_total": 1.15, "sg_app": 0.55, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.06, "qh_history": 0.05,
    },
    "Wyndham Clark": {
        "sg_total": 1.20, "sg_app": 0.60, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.05,
        "form": 0.92, "major_exp": 0.08, "qh_history": 0.0,
    },
    "Corey Conners": {
        "sg_total": 1.10, "sg_app": 0.70, "sg_ott": 0.25,
        "sg_putt": 0.05, "sg_atg": 0.10,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Denny McCarthy": {
        "sg_total": 1.00, "sg_app": 0.40, "sg_ott": 0.30,
        "sg_putt": 0.25, "sg_atg": 0.05,
        "form": 1.05, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Nick Taylor": {
        "sg_total": 1.05, "sg_app": 0.50, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.02, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Sungjae Im": {
        "sg_total": 1.10, "sg_app": 0.55, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Jason Day": {
        "sg_total": 1.00, "sg_app": 0.55, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.10, "qh_history": 0.0,
    },
    "Gary Woodland": {
        "sg_total": 0.90, "sg_app": 0.40, "sg_ott": 0.40,
        "sg_putt": 0.05, "sg_atg": 0.05,
        "form": 1.05, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Sahith Theegala": {
        "sg_total": 1.25, "sg_app": 0.60, "sg_ott": 0.50,
        "sg_putt": 0.05, "sg_atg": 0.10,
        "form": 0.95, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Tom Kim": {
        "sg_total": 1.20, "sg_app": 0.55, "sg_ott": 0.45,
        "sg_putt": 0.10, "sg_atg": 0.10,
        "form": 0.90, "major_exp": 0.04, "qh_history": 0.0,
    },
    "Max Homa": {
        "sg_total": 1.15, "sg_app": 0.60, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 0.88, "major_exp": 0.04, "qh_history": 0.05,
    },
    "Christiaan Bezuidenhout": {
        "sg_total": 1.05, "sg_app": 0.60, "sg_ott": 0.25,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.02, "qh_history": 0.0,
    },
    "Stephan Jaeger": {
        "sg_total": 1.05, "sg_app": 0.50, "sg_ott": 0.35,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.05, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Taylor Moore": {
        "sg_total": 0.95, "sg_app": 0.45, "sg_ott": 0.30,
        "sg_putt": 0.15, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.00, "qh_history": 0.0,
    },
    "Eric Cole": {
        "sg_total": 1.00, "sg_app": 0.50, "sg_ott": 0.35,
        "sg_putt": 0.10, "sg_atg": 0.05,
        "form": 1.00, "major_exp": 0.00, "qh_history": 0.0,
    },
}

# ── Course profiles ───────────────────────────────────────────────────────────
# course_adj_weights: how each SG component scores above/below average at this venue
# history_key:        player DB key that holds this venue's bonus (e.g. "qh_history")
# round_sigma:        per-round scoring std dev (tighter at augusta, wider at US Open)
# par:                course par
# description:        brief notes

COURSE_PROFILES: dict[str, dict] = {
    # PGA Championship venues
    "quail_hollow": {
        "course_adj_weights": {"sg_app": 0.15, "sg_ott": 0.05, "sg_putt": 0.05, "sg_atg": -0.02},
        "history_key": "qh_history",
        "round_sigma": 3.4,
        "par": 71,
        "description": "Quail Hollow, Charlotte NC — long par 71, bentgrass, ball-strikers",
    },
    "oak_hill": {
        "course_adj_weights": {"sg_app": 0.18, "sg_ott": 0.04, "sg_putt": 0.03, "sg_atg": -0.01},
        "history_key": "oak_hill_history",
        "round_sigma": 3.6,
        "par": 70,
        "description": "Oak Hill CC, Rochester NY — tight fairways, premium on accuracy",
    },
    # US Open venues
    "oakmont": {
        "course_adj_weights": {"sg_app": 0.20, "sg_ott": 0.02, "sg_putt": 0.08, "sg_atg": -0.03},
        "history_key": "oakmont_history",
        "round_sigma": 3.8,
        "par": 70,
        "description": "Oakmont CC — penal rough, lightning greens, shotmakers",
    },
    "shinnecock": {
        "course_adj_weights": {"sg_app": 0.15, "sg_ott": 0.06, "sg_putt": 0.06, "sg_atg": -0.02},
        "history_key": "shinnecock_history",
        "round_sigma": 3.9,
        "par": 70,
        "description": "Shinnecock Hills — wind exposure, USGA setup",
    },
    # The Masters
    "augusta": {
        "course_adj_weights": {"sg_app": 0.10, "sg_ott": 0.08, "sg_putt": 0.12, "sg_atg": 0.05},
        "history_key": "masters_history",
        "round_sigma": 3.2,
        "par": 72,
        "description": "Augusta National — premium on putting, second shot precision",
    },
    # The Open Championship (links)
    "royal_troon": {
        "course_adj_weights": {"sg_app": 0.08, "sg_ott": 0.12, "sg_putt": 0.06, "sg_atg": 0.08},
        "history_key": "open_history",
        "round_sigma": 4.2,
        "par": 71,
        "description": "Royal Troon — links, wind, bounces; creativity rewarded",
    },
    "st_andrews": {
        "course_adj_weights": {"sg_app": 0.05, "sg_ott": 0.14, "sg_putt": 0.08, "sg_atg": 0.10},
        "history_key": "open_history",
        "round_sigma": 4.0,
        "par": 72,
        "description": "St Andrews — wide fairways, pot bunkers, putting premium",
    },
    # The Players
    "tpc_sawgrass": {
        "course_adj_weights": {"sg_app": 0.18, "sg_ott": 0.03, "sg_putt": 0.08, "sg_atg": 0.02},
        "history_key": "sawgrass_history",
        "round_sigma": 3.3,
        "par": 72,
        "description": "TPC Sawgrass — island green 17th, Bermuda greens, approach-heavy",
    },
}

# Odds API sport key → course profile key
_SPORT_TO_COURSE: dict[str, str] = {
    "golf_pga_championship_winner":  "quail_hollow",
    "golf_masters_tournament_winner": "augusta",
    "golf_us_open_winner":            "oakmont",
    "golf_the_open_championship_winner": "st_andrews",
    "golf_the_players_championship_winner": "tpc_sawgrass",
}

# ── Course fit weights for Quail Hollow (legacy alias) ────────────────────────
QH_WEIGHTS = {
    "sg_app":  0.40,
    "sg_ott":  0.25,
    "sg_putt": 0.25,
    "sg_atg":  0.10,
}

# Per-round scoring standard deviation (PGA Tour typical)
ROUND_SIGMA = 3.4


def _course_adjusted_skill(
    player: str,
    db: dict[str, dict],
    course_profile: str = "quail_hollow",
) -> float:
    """
    Compute course-adjusted skill rating for the given venue.
    Returns expected strokes-gained per round vs. field (higher = better).

    Formula:
      base        = sg_total (primary predictor)
      course_adj  = component-level fit to this venue's profile
      form_adj    = form multiplier applied to base
      bonuses     = major exp + course-specific history (additive, capped at 0.4)
    """
    p = db.get(player, {})
    if not p:
        return 0.0

    base = p.get("sg_total", 0.0)

    profile = COURSE_PROFILES.get(course_profile, COURSE_PROFILES["quail_hollow"])
    weights = profile["course_adj_weights"]
    course_adj = (
        p.get("sg_app",  0) * weights.get("sg_app",  0) +
        p.get("sg_ott",  0) * weights.get("sg_ott",  0) +
        p.get("sg_putt", 0) * weights.get("sg_putt", 0) +
        p.get("sg_atg",  0) * weights.get("sg_atg",  0)
    )

    form_adj = base * (p.get("form", 1.0) - 1.0)

    history_key = profile.get("history_key", "qh_history")
    bonus = min(p.get("major_exp", 0.0) + p.get(history_key, 0.0), 0.40)

    return base + course_adj + form_adj + bonus


def _field_default_skill(odds: int) -> float:
    """
    Estimate skill rating for players not in DB using implied odds.
    Maps implied probability back to approximate SG total.
    """
    if odds > 0:
        impl_prob = 100 / (100 + odds)
    else:
        impl_prob = abs(odds) / (abs(odds) + 100)

    # Rough calibration: Scheffler (impl ~15%) → ~2.0 adjusted skill
    # 100/1 shot (impl ~1%) → ~0.3 adjusted skill
    # Linear interpolation in log-probability space
    if impl_prob <= 0:
        return 0.1
    # log-linear map: log(0.15) ≈ -1.9, log(0.001) ≈ -6.9
    log_p  = math.log(max(impl_prob, 0.001))
    # Scale to [0.1, 2.0]
    scaled = (log_p - math.log(0.001)) / (math.log(0.15) - math.log(0.001))
    return max(0.05, min(2.0, scaled * 2.0))


class SimulationOutput:
    """
    Stores the full simulation tensor for efficient multi-market pricing.
    Run once per tournament; query any market without re-simulating.
    """

    def __init__(
        self,
        players: list[str],
        totals: np.ndarray,   # shape (n_sim, n_players) — 4-round score totals
        round1: np.ndarray,   # shape (n_sim, n_players) — round 1 scores only
        skill_ratings: dict[str, float],
        n_sim: int,
    ) -> None:
        self.players = players
        self.idx     = {p: i for i, p in enumerate(players)}
        self.totals  = totals     # (n_sim, n_players)
        self.round1  = round1     # (n_sim, n_players)
        self.skill_ratings = skill_ratings
        self.n_sim   = n_sim
        # Precompute finish ranks (ascending = lower score = better)
        self._ranks  = np.argsort(totals, axis=1)    # (n_sim, n_players)
        self._ranks1 = np.argsort(round1, axis=1)    # for FRL
        # Precompute per-player finish position (inverse rank)
        self._finish = np.argsort(self._ranks, axis=1)  # _finish[s, i] = finish pos of player i in sim s

    def _pos(self, player: str) -> np.ndarray:
        """Finish position of player across all sims (0-indexed, 0=winner)."""
        i = self.idx[player]
        return self._finish[:, i]

    # ── Market pricing ─────────────────────────────────────────────────────────

    def win_prob(self, player: str) -> float:
        return float((self._pos(player) == 0).mean())

    def top_n_prob(self, player: str, n: int) -> float:
        return float((self._pos(player) < n).mean())

    def make_cut_prob(self, player: str, cut_line: int = 65) -> float:
        """Probability of finishing in top cut_line after 36 holes (approx)."""
        r2 = self.totals[:, self.idx[player]] / 2  # halve 4-round total as 2-round proxy
        r2_field = (self.totals / 2)
        pos_r2 = (r2_field < r2[:, np.newaxis]).sum(axis=1)
        return float((pos_r2 < cut_line).mean())

    def matchup_prob(self, player_a: str, player_b: str) -> float:
        """P(player_a finishes better than player_b over 72 holes)."""
        pa = self._pos(player_a)
        pb = self._pos(player_b)
        return float((pa < pb).mean())

    def three_ball_prob(self, player_a: str, player_b: str, player_c: str) -> float:
        """P(player_a beats both player_b and player_c over 72 holes)."""
        pa = self._pos(player_a)
        pb = self._pos(player_b)
        pc = self._pos(player_c)
        return float(((pa < pb) & (pa < pc)).mean())

    def frl_prob(self, player: str) -> float:
        """P(player leads / co-leads after round 1)."""
        i = self.idx[player]
        r1_pos = np.argsort(np.argsort(self.round1, axis=1), axis=1)
        return float((r1_pos[:, i] == 0).mean())

    def summary(self) -> dict[str, dict]:
        """Per-player probability dict (backward-compatible with old API)."""
        return {
            p: {
                "win_prob":    self.win_prob(p),
                "top5_prob":   self.top_n_prob(p, 5),
                "top10_prob":  self.top_n_prob(p, 10),
                "top20_prob":  self.top_n_prob(p, 20),
                "make_cut":    self.make_cut_prob(p),
                "frl_prob":    self.frl_prob(p),
                "skill":       self.skill_ratings.get(p, 0.0),
            }
            for p in self.players
        }


def run_simulation(
    players: list[str],
    skill_ratings: dict[str, float],
    n_sim: int = 150_000,
    seed: int = 42,
    round_sigma: float = ROUND_SIGMA,
) -> SimulationOutput:
    """
    Monte Carlo simulation: 4 rounds, 156 players.
    Returns a SimulationOutput object that can price any market.
    """
    rng = np.random.default_rng(seed)
    n   = len(players)

    field_avg  = 71.5
    exp_scores = np.array([field_avg - skill_ratings.get(p, 0.3) for p in players])

    rounds = rng.normal(
        loc   = exp_scores[np.newaxis, :, np.newaxis],
        scale = round_sigma,
        size  = (n_sim, n, 4),
    )
    totals = rounds.sum(axis=2)
    round1 = rounds[:, :, 0]

    return SimulationOutput(players, totals, round1, skill_ratings, n_sim)


def _american_to_decimal(odds: int) -> float:
    if odds > 0:
        return odds / 100 + 1
    return 100 / abs(odds) + 1


def _implied_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (100 + odds)
    return abs(odds) / (abs(odds) + 100)


def fetch_odds(sport_key: str = "golf_pga_championship_winner") -> dict[str, dict]:
    """Fetch outright winner odds for the given golf event from The Odds API."""
    import requests as req
    key = os.environ.get("ODDS_API_KEY", "")
    try:
        r = req.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
            params={
                "apiKey": key, "regions": "us,uk,eu",
                "markets": "outrights", "oddsFormat": "american",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return {}
        data = r.json()
        if not isinstance(data, list) or not data:
            return {}

        # Collect best (highest American odds = best payout) per player
        players: dict[str, dict] = {}
        for bm in data[0].get("bookmakers", []):
            book = bm["key"]
            for o in bm["markets"][0]["outcomes"]:
                name  = o["name"]
                price = int(o["price"])
                if name not in players or price > players[name]["best_odds"]:
                    players[name] = {
                        "best_odds":   price,
                        "best_book":   book,
                        "implied_prob": _implied_prob(price),
                    }
        return players
    except Exception as e:
        print(f"  [odds] fetch error: {e}")
        return {}


def run_pga_model(
    n_sim: int = 100_000,
    sport_key: str = "golf_pga_championship_winner",
    refresh: bool = False,
) -> list[dict]:
    """
    Full pipeline: fetch odds → load ratings → simulate → find edges.

    sport_key controls which major's odds to fetch and which course profile
    to apply. Supports all four majors + The Players.

    Live SG ratings are fetched from statdata.pgatour.com (no API key, cached
    24h). Falls back to the static PLAYER_DB if the CDN is unreachable.
    """
    course_profile = _SPORT_TO_COURSE.get(sport_key, "quail_hollow")
    profile = COURSE_PROFILES[course_profile]

    tournament = sport_key.replace("golf_", "").replace("_winner", "").replace("_", " ").title()
    print(f"  Tournament: {tournament}  |  Course: {profile['description']}")

    # 1. Fetch odds
    print("  Fetching odds...")
    market_odds = fetch_odds(sport_key=sport_key)
    if not market_odds:
        print("  ERROR: Could not fetch odds. Check ODDS_API_KEY.")
        return []
    print(f"  {len(market_odds)} players in market.")

    # 2. Load player ratings (live PGA Tour stats preferred, static fallback)
    from datetime import datetime as _dt
    live_ratings = _fetch_pgatour_sg_ratings(season=_dt.now().year, refresh=refresh)
    if live_ratings:
        player_db = _merge_live_ratings(PLAYER_DB, live_ratings)
    else:
        player_db = PLAYER_DB
        print("  Using static PLAYER_DB (pgatour.com CDN unavailable).")

    # 3. Build per-player skill ratings using the active course profile
    skill_ratings: dict[str, float] = {}
    for player, info in market_odds.items():
        if player in player_db:
            skill_ratings[player] = _course_adjusted_skill(player, player_db, course_profile)
        else:
            skill_ratings[player] = _field_default_skill(info["best_odds"])

    players = list(market_odds.keys())

    # 4. Simulate
    print(f"  Running {n_sim:,} simulations for {len(players)} players...")
    sim = run_simulation(
        players, skill_ratings, n_sim=n_sim,
        round_sigma=profile.get("round_sigma", ROUND_SIGMA),
    )
    sim_results = sim.summary()

    # 5. Build picks list with edges
    picks = []
    total_impl = sum(v["implied_prob"] for v in market_odds.values())
    vig_factor = total_impl

    for player in players:
        odds_info = market_odds[player]
        sr        = sim_results[player]

        raw_impl  = odds_info["implied_prob"]
        fair_impl = raw_impl / vig_factor

        model_win = sr["win_prob"]
        edge_pct  = round((model_win - fair_impl) * 100, 2)

        picks.append({
            "player":       player,
            "best_odds":    odds_info["best_odds"],
            "best_book":    odds_info["best_book"],
            "model_win":    round(model_win * 100, 2),
            "market_impl":  round(fair_impl * 100, 2),
            "edge_pct":     edge_pct,
            "top5_prob":    round(sr["top5_prob"] * 100, 1),
            "top10_prob":   round(sr["top10_prob"] * 100, 1),
            "top20_prob":   round(sr["top20_prob"] * 100, 1),
            "make_cut":     round(sr["make_cut"] * 100, 1),
            "frl_prob":     round(sr["frl_prob"] * 100, 2),
            "skill_rating": round(sr["skill"], 3),
            "course":       course_profile,
            "data_source":  "pgatour_live" if live_ratings and player in live_ratings else "static_db",
            "model_tier":   "tier2",
        })

    picks.sort(key=lambda x: x["edge_pct"], reverse=True)
    return picks


def price_matchups(
    sim: SimulationOutput,
    market_odds: dict[str, dict],
    player_pairs: list[tuple[str, str]],
    min_edge_pct: float = 3.0,
) -> list[dict]:
    """
    Price head-to-head tournament matchups from the simulation tensor.
    player_pairs: list of (player_a, player_b) tuples to evaluate.
    Returns edge dicts compatible with pnl schema.
    """
    edges = []
    total_impl = sum(v["implied_prob"] for v in market_odds.values())
    vig = total_impl

    for a, b in player_pairs:
        if a not in sim.idx or b not in sim.idx:
            continue
        p_a = sim.matchup_prob(a, b)

        # Pull best available odds for each side (use outright as proxy if no dedicated market)
        odds_a = market_odds.get(a, {}).get("best_odds", -110)
        odds_b = market_odds.get(b, {}).get("best_odds", -110)

        # Devig the pair
        impl_a = _implied_prob(odds_a) / (_implied_prob(odds_a) + _implied_prob(odds_b))
        impl_b = 1.0 - impl_a

        for player, model_p, imp_p, book_odds in [
            (a, p_a, impl_a, odds_a),
            (b, 1 - p_a, impl_b, odds_b),
        ]:
            edge = (model_p - imp_p) * 100.0
            if edge >= min_edge_pct:
                edges.append({
                    "market":       "matchup",
                    "player":       player,
                    "opponent":     b if player == a else a,
                    "odds":         int(book_odds),
                    "model_prob":   round(model_p, 4),
                    "implied_prob": round(imp_p, 4),
                    "edge_pct":     round(edge, 2),
                })

    return sorted(edges, key=lambda x: x["edge_pct"], reverse=True)


def print_report(picks: list[dict], top_n: int = 20) -> None:
    """Print human-readable edge report — modelled players only."""
    modelled = [p for p in picks if p["player"] in PLAYER_DB]
    modelled_by_edge = sorted(modelled, key=lambda x: x["edge_pct"], reverse=True)

    print("\n" + "=" * 82)
    print("  PGA CHAMPIONSHIP 2026 — QUAIL HOLLOW · MAY 14–17")
    print("  ChefTonyBets AI  |  Course-fit Monte Carlo  |  100k simulations")
    print("=" * 82)
    hdr = f"  {'PLAYER':<26} {'ODDS':>7} {'MODEL%':>7} {'MKT%':>6} {'EDGE':>7} {'TOP5%':>6} {'TOP10%':>7}"
    print(f"\n{hdr}")
    print("-" * 82)
    for p in modelled_by_edge[:top_n]:
        edge_str = f"+{p['edge_pct']:.1f}%" if p['edge_pct'] > 0 else f"{p['edge_pct']:.1f}%"
        flag = "  ★" if p["edge_pct"] >= 2.0 else ("  ·" if p["edge_pct"] >= 0 else "")
        print(
            f"  {p['player']:<26} {p['best_odds']:>+7d}  "
            f"{p['model_win']:>5.1f}%  {p['market_impl']:>4.1f}%  "
            f"{edge_str:>6}  {p['top5_prob']:>5.1f}%  {p['top10_prob']:>6.1f}%{flag}"
        )
    print("-" * 82)
    stars = [p for p in modelled if p["edge_pct"] >= 2.0]
    print(f"\n  ★ = edge ≥ +2.0%  |  {len(stars)} strong plays found")
    if stars:
        print("\n  TOP PLAYS:")
        for p in stars:
            print(f"    {p['player']} {p['best_odds']:+d}  — model {p['model_win']:.1f}% vs market {p['market_impl']:.1f}%  (+{p['edge_pct']:.1f}% edge)")
            print(f"      Top 5: {p['top5_prob']:.0f}%  |  Top 10: {p['top10_prob']:.0f}%  |  Top 20: {p['top20_prob']:.0f}%  |  Book: {p['best_book']}")


def save_picks(picks: list[dict], d: date | None = None) -> Path:
    d = d or date.today()
    out_dir = Path("output/picks/golf_pga") / d.strftime("%Y%m%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "picks.json"
    with open(out_path, "w") as f:
        json.dump(picks, f, indent=2)
    print(f"\n  Saved → {out_path}")
    return out_path


if __name__ == "__main__":
    picks = run_pga_model(n_sim=100_000)
    if picks:
        print_report(picks, top_n=25)
        save_picks(picks)
