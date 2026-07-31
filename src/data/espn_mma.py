"""The OFFICIAL UFC card for a date — bout list, bout order, status — from ESPN.

WHY THIS EXISTS. The card reader used to reconstruct events from Odds API
timestamps: fights sharing a commence_time were assumed to be one promotion's
card. On 2026-08-01 that filed four real UFC prelims under an Oktagon block,
invented a bout order, and the error survived until the user produced
screenshots of the actual card. An odds feed is a market menu — it says what is
priced, not what is scheduled, and it carries no bout order at all.

ESPN's scoreboard is the official card: every bout, in order, with per-bout
status (SCHEDULED / CANCELED / FINAL). It is the SPINE; odds join onto it by
fighter-name pair, and a priced fight that is not on the official card never
appears — that is the promotion-mixing bug made structurally impossible.

ESPN lists bouts chronologically (first prelim first, main event last), so the
broadcast card reads bottom-up. `bouts` preserves ESPN's order; callers wanting
main-event-first reverse it.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
_CACHE_DIR = Path("data/cache/espn_mma")
_TTL_S = 1800     # fight cards change during fight week; 30 min keeps us honest


@dataclass(frozen=True)
class EspnBout:
    fighter_a: str            # ESPN's first-listed competitor
    fighter_b: str
    status: str               # STATUS_SCHEDULED / STATUS_CANCELED / ...
    order: int                # 0 = first fight of the night

    @property
    def scheduled(self) -> bool:
        return "SCHEDULED" in self.status.upper() or "IN_PROGRESS" in self.status.upper()


@dataclass(frozen=True)
class EspnCard:
    name: str                 # "UFC Fight Night: Medić vs. Rodriguez"
    date: str                 # YYYYMMDD
    bouts: list[EspnBout] = field(default_factory=list)


def parse_scoreboard(data: dict, date: str) -> EspnCard | None:
    events = (data or {}).get("events", []) or []
    if not events:
        return None
    ev = events[0]
    bouts: list[EspnBout] = []
    for i, c in enumerate(ev.get("competitions", []) or []):
        names = [(x.get("athlete") or {}).get("displayName") or ""
                 for x in c.get("competitors", []) or []]
        names = [n.strip() for n in names if n and n.strip()]
        if len(names) != 2:
            continue
        bouts.append(EspnBout(
            fighter_a=names[0], fighter_b=names[1],
            status=str(((c.get("status") or {}).get("type") or {}).get("name", "")),
            order=i,
        ))
    return EspnCard(name=str(ev.get("name", "")).strip(), date=date, bouts=bouts)


def fetch_card(date: str, allow_network: bool = True) -> EspnCard | None:
    """Official UFC card for YYYYMMDD, or None when ESPN lists no event.

    None is a real answer — most days have no UFC card — and callers fall back
    to the old time-grouping for non-UFC promotions, clearly labelled as such.
    """
    cache = _CACHE_DIR / f"{date}.json"
    data = None
    if cache.exists() and time.time() - cache.stat().st_mtime < _TTL_S:
        try:
            data = json.loads(cache.read_text())
        except (OSError, ValueError):
            data = None
    if data is None and allow_network:
        try:
            import requests
            r = requests.get(_URL, params={"dates": date}, timeout=25)
            r.raise_for_status()
            data = r.json()
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
        except Exception:
            try:
                data = json.loads(cache.read_text())
            except (OSError, ValueError):
                return None
    if data is None:
        try:
            data = json.loads(cache.read_text())
        except (OSError, ValueError):
            return None
    return parse_scoreboard(data, date)
