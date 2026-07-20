"""
src/data/ufc_data.py — Real UFC fighter ratings from fight history.

THE PROBLEM this fixes: the UFC model shipped with a hand-typed dict of ~70
champions (ufc_model.FIGHTER_RATINGS). Any card with mid-tier or prelim fighters
came back "both fighters unknown" and got skipped — a 12-fight card produced one
rated fight. You can't hand-maintain every active fighter.

THE FIX (same play as the tennis v2 rebuild): compute Glicko/Elo ratings from the
ACTUAL UFC fight record. We pull the maintained ufcstats.com scrape (Greco1899),
run Elo chronologically over all ~8,700 bouts on the model's native 1500/400
scale, and derive a style profile from each fighter's win-method mix. That covers
every fighter who has ever fought in the UFC — hundreds, not seventy.

The curated FIGHTER_RATINGS still win as an overlay (expert priors + good styles
for the elite), but everyone else now gets a data-driven rating instead of a skip.

Refresh:  python3 -m src.data.ufc_data
Cache:    data/ufc/{fight_results.csv, event_details.csv, fighter_ratings_computed.json}
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path

_BASE = "https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/main/"
_RESULTS_URL = _BASE + "ufc_fight_results.csv"
_EVENTS_URL = _BASE + "ufc_event_details.csv"

_DIR = Path("data/ufc")
_RESULTS_CSV = _DIR / "fight_results.csv"
_EVENTS_CSV = _DIR / "event_details.csv"
_RATINGS_JSON = _DIR / "fighter_ratings_computed.json"

# Elo on the model's native scale (GlickoRating.win_prob_vs uses /400).
_ELO_START = 1500.0
_K_DECISION = 28.0
_K_FINISH = 40.0    # KO/TKO or submission — a cleaner signal of skill gap


# ── fetch + cache ────────────────────────────────────────────────────────────
def _fetch(url: str, cache: Path, allow_network: bool) -> str | None:
    """Return CSV text: fresh fetch (cached on success) or the last-good cache."""
    if allow_network:
        try:
            import requests
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(r.text)
            return r.text
        except Exception as e:
            print(f"  [ufc_data] fetch failed ({url.rsplit('/', 1)[-1]}): {e}")
    if cache.exists():
        return cache.read_text()
    return None


def _parse_date(s: str) -> date | None:
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def load_fight_history(allow_network: bool = True) -> list[dict]:
    """All UFC bouts as {date, winner, loser, method} sorted oldest→newest.

    Draws / no-contests are dropped — they carry no ordering signal for Elo.
    """
    results_txt = _fetch(_RESULTS_URL, _RESULTS_CSV, allow_network)
    events_txt = _fetch(_EVENTS_URL, _EVENTS_CSV, allow_network)
    if not results_txt or not events_txt:
        return []

    dates: dict[str, date] = {}
    for row in csv.DictReader(io.StringIO(events_txt)):
        d = _parse_date(row.get("DATE", ""))
        if d:
            dates[row.get("EVENT", "").strip()] = d

    fights: list[dict] = []
    for row in csv.DictReader(io.StringIO(results_txt)):
        bout = row.get("BOUT", "")
        if " vs. " not in bout:
            continue
        a, b = (x.strip() for x in bout.split(" vs. ", 1))
        outcome = (row.get("OUTCOME") or "").strip()
        if outcome == "W/L":
            winner, loser = a, b
        elif outcome == "L/W":
            winner, loser = b, a
        else:
            continue   # D/D, NC, or blank — no signal
        method = (row.get("METHOD") or "").strip()
        d = dates.get(row.get("EVENT", "").strip())
        fights.append({"date": d.isoformat() if d else "",
                       "winner": winner, "loser": loser, "method": method})
    # Undated fights sort to the front (early history) — stable and harmless.
    fights.sort(key=lambda f: f["date"])
    return fights


# ── ratings + styles from results ────────────────────────────────────────────
def _is_finish(method: str) -> bool:
    m = method.lower()
    return "ko" in m or "tko" in m or "submission" in m or "sub" in m


def _style_from_methods(ko: int, sub: int, dec: int) -> dict:
    """Data-driven style profile from a fighter's WIN-method mix.

    KO wins → striking, submission wins → grappling, decision wins → wrestling
    (grind/control). Mapped to the model's 0–1 style scale with a neutral 0.5
    floor so a thin record doesn't produce a lopsided profile.
    """
    total = ko + sub + dec
    if total < 2:
        return {"striking": 0.5, "wrestling": 0.5, "grappling": 0.5}
    return {
        "striking":  round(0.45 + 0.5 * (ko / total), 3),
        "grappling": round(0.45 + 0.5 * (sub / total), 3),
        "wrestling": round(0.45 + 0.5 * (dec / total), 3),
    }


def compute_ratings(fights: list[dict]) -> dict[str, dict]:
    """Chronological Elo + style profile per fighter → {name: {mu, style, n}}."""
    mu: dict[str, float] = {}
    methods: dict[str, list[int]] = {}   # name -> [ko, sub, dec] wins
    bouts: dict[str, int] = {}

    def get(f: str) -> float:
        return mu.get(f, _ELO_START)

    for fight in fights:
        w, l = fight["winner"], fight["loser"]
        rw, rl = get(w), get(l)
        exp_w = 1.0 / (1.0 + 10.0 ** ((rl - rw) / 400.0))
        k = _K_FINISH if _is_finish(fight["method"]) else _K_DECISION
        mu[w] = rw + k * (1.0 - exp_w)
        mu[l] = rl - k * (1.0 - exp_w)
        bouts[w] = bouts.get(w, 0) + 1
        bouts[l] = bouts.get(l, 0) + 1
        m = methods.setdefault(w, [0, 0, 0])
        meth = fight["method"].lower()
        if "ko" in meth or "tko" in meth:
            m[0] += 1
        elif "sub" in meth:
            m[1] += 1
        else:
            m[2] += 1

    out: dict[str, dict] = {}
    for name, rating in mu.items():
        ko, sub, dec = methods.get(name, [0, 0, 0])
        out[name] = {"mu": round(rating, 1),
                     "style": _style_from_methods(ko, sub, dec),
                     "n": bouts.get(name, 0)}
    return out


def refresh(allow_network: bool = True) -> dict[str, dict]:
    """Rebuild the computed-ratings cache from the latest fight history."""
    fights = load_fight_history(allow_network=allow_network)
    if not fights:
        print("  [ufc_data] no fight history available — cache unchanged.")
        return load_cached_ratings()
    ratings = compute_ratings(fights)
    _DIR.mkdir(parents=True, exist_ok=True)
    _RATINGS_JSON.write_text(json.dumps(
        {"computed_on": date.today().isoformat(), "n_fights": len(fights),
         "ratings": ratings}, indent=2, sort_keys=True))
    return ratings


def load_cached_ratings() -> dict[str, dict]:
    """Computed ratings from cache ({name: {mu, style, n}}); {} if none."""
    try:
        data = json.loads(_RATINGS_JSON.read_text())
        return data.get("ratings", {})
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    r = refresh()
    if r:
        top = sorted(r.items(), key=lambda kv: -kv[1]["mu"])[:15]
        print(f"  [ufc_data] {len(r)} fighters rated from fight history. Top 15:")
        for name, d in top:
            print(f"    {name:26s} mu={d['mu']:.0f}  ({d['n']} bouts)")
