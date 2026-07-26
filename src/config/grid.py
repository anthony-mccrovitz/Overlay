"""
The model grid — the canonical board of every sport×market lane, built or not.

The registry (`models.py`) tracks lanes that EXIST (live / shadow / paused /
retired). This grid adds the lanes we haven't built yet ("planned") so the
whole opportunity board is visible in one place — the empty cells are the
to-do list. `chef.py grid` renders it.

Each cell maps a display lane to one or more registry market keys (props and
period lanes fold several keys into one cell). State aggregates across them.
"""
from __future__ import annotations

from src.config.models import MODELS, _key, model_status, model_tier, is_retired

# Display lane → the registry market key(s) it covers, per sport. Order matters
# (left-to-right in the view). Sourced from the Odds API menu + rebuild roadmap.
GRID: dict[str, list[tuple[str, list[str]]]] = {
    "mlb": [
        ("moneyline", ["moneyline"]),
        ("total", ["total"]),
        ("spread", ["spread"]),
        ("period", ["f5_total", "nrfi"]),
        ("props", ["prop", "batter_home_runs", "batter_hits", "batter_total_bases",
                   "batter_rbis", "batter_walks", "pitcher_strikeouts"]),
    ],
    "wnba": [
        ("moneyline", ["moneyline"]),
        ("total", ["total"]),
        ("spread", ["spread"]),
        ("props", ["prop", "player_points", "player_rebounds", "player_assists"]),
    ],
    "nba": [
        ("moneyline", ["moneyline"]),
        ("total", ["total"]),
        ("spread", ["spread"]),
        ("props", ["prop", "player_points", "player_rebounds", "player_assists",
                   "player_pra", "player_threes", "player_blocks", "player_steals"]),
    ],
    "nhl": [
        ("moneyline", ["moneyline"]),
        ("puck_line", ["puck_line"]),
        ("total", ["total"]),
        ("props", ["player_points", "player_goals", "player_assists",
                   "player_shots_on_goal", "player_blocked_shots"]),
    ],
    "nfl": [
        ("moneyline", ["moneyline"]),
        ("total", ["total"]),
        ("spread", ["spread"]),
        ("props", ["prop"]),
    ],
    "tennis": [
        ("moneyline", ["moneyline"]),
        ("total", ["total"]),
    ],
    "ufc": [
        ("moneyline", ["moneyline"]),
        ("total", ["total"]),
    ],
    "pga": [
        ("outright", ["outright"]),
    ],
}

# Soccer is per-league — each league is its own row/model/gate (Liga MX and MLS
# never share a verdict). Labels match _key('soccer_x') → 'x'.
_SOCCER_LEAGUES = [
    "mexico_ligamx", "usa_mls", "epl", "spain_la_liga",
    "italy_serie_a", "germany_bundesliga", "france_ligue_one",
]
for _lg in _SOCCER_LEAGUES:
    GRID[_lg] = [
        ("moneyline", ["moneyline"]),
        ("total", ["total"]),
        ("btts", ["btts"]),
        ("anytime_scorer", ["anytime_scorer"]),
    ]

# State priority when a lane folds several market keys — show the "furthest
# along" state present.
_PRIORITY = {"live": 4, "shadow": 3, "paused": 2, "retired": 1, "planned": 0}


def is_registered(sport: str, market: str) -> bool:
    """True if this exact (sport, market) has a registry entry (i.e. a model)."""
    return _key(sport, market) in MODELS


def _market_state(sport: str, market: str) -> str:
    """Resolve one registry market key to a grid state."""
    if not is_registered(sport, market):
        return "planned"
    if is_retired(sport, market):
        return "retired"
    if model_status(sport, market) == "live":
        return "live"
    return "paused" if model_tier(sport, market) == "paused" else "shadow"


def cell_state(sport: str, market_keys: list[str]) -> str:
    """Aggregate state for a display lane (max over its market keys)."""
    states = [_market_state(sport, k) for k in market_keys]
    return max(states, key=lambda s: _PRIORITY[s])


def iter_grid():
    """Yield (sport, lane_label, market_keys, state) for every cell."""
    for sport, lanes in GRID.items():
        for label, keys in lanes:
            yield sport, label, keys, cell_state(sport, keys)


def grid_counts() -> dict[str, int]:
    """Tally cells by state across the whole grid."""
    counts = {s: 0 for s in _PRIORITY}
    for _sport, _label, _keys, state in iter_grid():
        counts[state] += 1
    return counts
