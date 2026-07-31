"""This week's PGA Tour event and its field, from ESPN's public scoreboard.

WHY ESPN. The Odds API carries golf as four majors-only futures boards — there
is simply no weekly-event key to fetch, so "what is being played this week and
who is in it" cannot come from the odds side at all. The existing PGA model
sidestepped this by deriving the FIELD from the odds board itself, which is
exactly why it only ever worked four weeks a year. ESPN's scoreboard is free,
keyless, already used by this repo for club soccer, and carries the current
event, its full field, dates, status and live scores.

No odds live here. Odds, when a board exists for an event, come from the Odds
API as before — this module answers "what tournament, who's playing", nothing
else.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
_CACHE = Path("data/cache/golf/espn_scoreboard.json")
# The field barely changes; live scores do. 30 minutes keeps a card session on
# one fetch without serving yesterday's leaderboard.
_TTL_S = 1800


@dataclass(frozen=True)
class FieldPlayer:
    name: str
    score: str = ""          # live/total score as ESPN formats it ("-9", "E")
    status: str = ""         # "active", "cut", "wd", ...


@dataclass(frozen=True)
class GolfEvent:
    event_id: str
    name: str
    start: str               # ISO date
    end: str
    status: str              # "Scheduled" | "In Progress" | "Final" | ...
    players: list[FieldPlayer] = field(default_factory=list)

    @property
    def in_progress(self) -> bool:
        return "progress" in self.status.lower()

    @property
    def finished(self) -> bool:
        return "final" in self.status.lower()


def _fetch(allow_network: bool = True) -> dict | None:
    if _CACHE.exists() and time.time() - _CACHE.stat().st_mtime < _TTL_S:
        try:
            return json.loads(_CACHE.read_text())
        except (OSError, ValueError):
            pass
    if not allow_network:
        try:
            return json.loads(_CACHE.read_text())
        except (OSError, ValueError):
            return None
    try:
        import requests
        r = requests.get(_URL, timeout=25)
        r.raise_for_status()
        data = r.json()
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(data))
        return data
    except Exception:
        # Last-good cache beats nothing, and its age is visible in the event
        # dates it reports — a stale event says its own dates.
        try:
            return json.loads(_CACHE.read_text())
        except (OSError, ValueError):
            return None


def parse_events(data: dict) -> list[GolfEvent]:
    """ESPN scoreboard JSON → events. Tolerates missing fields everywhere:
    a partially-parsed event with a real field beats an exception."""
    out: list[GolfEvent] = []
    for e in (data or {}).get("events", []) or []:
        comps = (e.get("competitions") or [{}])[0]
        players: list[FieldPlayer] = []
        for c in comps.get("competitors", []) or []:
            nm = ((c.get("athlete") or {}).get("displayName") or "").strip()
            if not nm:
                continue
            players.append(FieldPlayer(
                name=nm,
                score=str(c.get("score", "") or ""),
                status=str(((c.get("status") or {}).get("type") or {})
                           .get("name", "") or "").lower(),
            ))
        out.append(GolfEvent(
            event_id=str(e.get("id", "")),
            name=str(e.get("name", "")).strip(),
            start=str(e.get("date", ""))[:10],
            end=str(e.get("endDate", ""))[:10],
            status=str(((e.get("status") or {}).get("type") or {})
                       .get("description", "") or ""),
            players=players,
        ))
    return out


def current_event(allow_network: bool = True) -> GolfEvent | None:
    """The event ESPN considers current this week, or None."""
    data = _fetch(allow_network)
    if data is None:
        return None
    events = parse_events(data)
    return events[0] if events else None
