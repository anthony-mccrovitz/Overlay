"""
scoring.py — turn a stat line into fantasy points under YOUR league's rules.

Sleeper publishes a league's exact `scoring_settings` as a flat
{stat_key: points_per_unit} map, and its stat rows use the same keys. So scoring
is a dot product and there is no reason to hardcode "half PPR" or guess at
bonuses — the league tells us. That matters more than it sounds: a 0.5 vs 1.0
reception point moves RB/WR ordering by whole rounds, and leagues quietly差
on things like TE premium, first downs, and return yards.

If no league settings are supplied we fall back to a documented half-PPR
default, clearly labelled so nobody mistakes it for the real league.
"""
from __future__ import annotations

# Documented fallback ONLY — replaced by the league's real settings whenever a
# league_id is available. Values are Sleeper's own stat keys.
HALF_PPR_DEFAULT: dict[str, float] = {
    "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0, "pass_2pt": 2.0,
    "rush_yd": 0.1,  "rush_td": 6.0, "rush_2pt": 2.0,
    "rec": 0.5,      "rec_yd": 0.1,  "rec_td": 6.0, "rec_2pt": 2.0,
    "fum_lost": -2.0,
    "fgm": 3.0, "xpm": 1.0,
    "def_td": 6.0, "def_st_td": 6.0, "st_td": 6.0,
}


def score(stats: dict, settings: dict[str, float] | None = None) -> float:
    """Fantasy points for one stat line under the given scoring settings.

    Unknown stat keys are ignored rather than assumed zero-weight-but-present:
    Sleeper stat rows carry dozens of non-scoring keys (ranks, percentages,
    snap counts) and multiplying those by a missing setting would be silent
    nonsense.
    """
    rules = settings or HALF_PPR_DEFAULT
    total = 0.0
    for key, per_unit in rules.items():
        v = stats.get(key)
        if isinstance(v, (int, float)):
            total += float(v) * float(per_unit)
    return round(total, 2)


def describe(settings: dict[str, float] | None) -> str:
    """One-line summary of the scoring rules that matter to a draft board."""
    r = settings or HALF_PPR_DEFAULT
    ppr = r.get("rec", 0.0)
    fmt = {0.0: "Standard", 0.5: "Half-PPR", 1.0: "Full PPR"}.get(ppr, f"{ppr}/rec")
    bits = [fmt]
    te = r.get("bonus_rec_te")
    if te:
        bits.append(f"TE premium +{te}/rec")
    if r.get("pass_td", 4.0) != 4.0:
        bits.append(f"{r['pass_td']}pt pass TD")
    if r.get("fd") or r.get("rush_fd") or r.get("rec_fd"):
        bits.append("first downs")
    return " · ".join(bits)
