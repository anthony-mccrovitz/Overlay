"""
redraft_adp.py — redraft ADP from real mock drafts, matched to Sleeper IDs.

Sleeper's projections endpoint publishes exactly one ADP field, `adp_dd_ppr`,
and it is DYNASTY draft ADP. This league is redraft, and the two markets price
players very differently: dynasty pays for age, so a 26-year-old coming off an
NFL rushing title slides (James Cook: dynasty 23, redraft 14) and a 27-year-old
lead back craters (Travis Etienne: dynasty 71, redraft 37). Feeding dynasty
prices into a redraft room corrupts every downstream consumer at once — the
survival model tells you a player "will likely be there later" two rounds after
the room actually takes him, and the simulator's opponents wait on veteran RBs
in a way no redraft room ever would.

FantasyFootballCalculator publishes ADP from thousands of real mock drafts in
the current week, split by format (PPR/half/standard) and league size — i.e.
the actual quantity we want, from rooms shaped like ours. This module fetches
it and matches names to Sleeper player IDs. Where FFC has a price it wins;
players outside FFC's ~250 keep their dynasty number, which is fine because
deep-bench dynasty and redraft prices converge on "basically free".

Matching is by normalized name + position, with team as the tiebreaker. Name
normalization exists because the two sources disagree on suffixes ("James Cook
III" vs "James Cook") and punctuation — the exact players this module exists to
fix are the ones a naive string match silently drops.
"""
from __future__ import annotations

import re

from src.fantasy import sleeper

URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams={teams}&year={year}"
TTL = 3600                               # same cadence as preseason ADP drift

# FFC's kicker position code differs from Sleeper's.
_POS_MAP = {"PK": "K"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _norm(name: str) -> str:
    """Lowercase, strip punctuation and generational suffixes.

    "Travis Etienne Jr." and "Travis Etienne" must collide; so must
    "Ja'Marr Chase" spelled with and without the apostrophe.
    """
    s = re.sub(r"[^a-z ]", "", name.lower().replace(".", " "))
    return " ".join(p for p in s.split() if p not in _SUFFIXES)


def fetch(fmt: str = "ppr", teams: int = 12, year: int = 2026) -> list[dict]:
    """FFC ADP rows, cached on disk like every other preseason feed."""
    url = URL.format(fmt=fmt, teams=teams, year=year)
    data = sleeper._cached(f"ffc_adp_{fmt}_{teams}_{year}", url, TTL)
    players = (data or {}).get("players") or []
    if not players:
        raise sleeper.SleeperError(f"FFC ADP feed returned no players: {url}")
    return players


def match(rows: list[dict], players_db: dict) -> dict[str, float]:
    """{sleeper_player_id: redraft_adp} for every FFC row we can identify.

    Position must agree and, when two players share a normalized name at the
    same position, team decides. An unmatched row is dropped rather than
    guessed — a wrong ID silently reprices the wrong player.
    """
    fp = sleeper.fantasy_players(players_db)
    by_key: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for pid, p in fp.items():
        key = (_norm(sleeper.display_name(p)), p["position"])
        by_key.setdefault(key, []).append((pid, p))

    out: dict[str, float] = {}
    for row in rows:
        name, pos = row.get("name"), row.get("position")
        adp = row.get("adp")
        if not name or not pos or not isinstance(adp, (int, float)):
            continue
        pos = _POS_MAP.get(pos, pos)
        candidates = by_key.get((_norm(name), pos), [])
        if len(candidates) > 1:
            candidates = [(pid, p) for pid, p in candidates
                          if p.get("team") == row.get("team")]
        if len(candidates) == 1:
            out[candidates[0][0]] = float(adp)
    return out


def adp_by_player_id(players_db: dict, fmt: str = "ppr",
                     teams: int = 12, year: int = 2026) -> dict[str, float]:
    """Fetch + match in one call. Raises on an empty or unreachable feed —
    the caller decides how loudly to degrade, but degrading must be visible."""
    return match(fetch(fmt, teams, year), players_db)
