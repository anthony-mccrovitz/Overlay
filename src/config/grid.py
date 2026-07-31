"""
The model grid — the canonical board of every sport×market lane, built or not.

The registry (`models.py`) tracks lanes that EXIST (live / shadow / paused /
retired). This grid adds the lanes we haven't built yet ("planned") so the
whole opportunity board is visible in one place — the empty cells are the
to-do list. `chef.py grid` renders it.

Every bet type is its OWN market/cell — player props and game props are never
lumped into a generic "props" bucket; the bet type IS the market (e.g.
batter_home_runs, player_points, player_shots_on_goal). Soccer is per-league.
Cells with no model yet are "planned" — the to-do list. `chef.py grid` renders it.
"""
from __future__ import annotations

from src.config.models import MODELS, _key, model_status, model_tier, is_retired

# Core game & period markets per sport — each its own cell (bet type = market).
_CORE: dict[str, list[str]] = {
    "mlb":    ["moneyline", "total", "spread", "f5_total", "nrfi"],
    "wnba":   ["moneyline", "total", "spread"],
    "nba":    ["moneyline", "total", "spread"],
    "nhl":    ["moneyline", "puck_line", "total"],
    "nfl":    ["moneyline", "total", "spread"],
    "ncaaf":  ["total", "spread"],
    "tennis": ["moneyline", "total"],
    "ufc":    ["moneyline", "total"],
    "pga":    ["outright"],
}

# Player & game PROP markets per sport — from the Odds API menu. Each IS its own
# market (never a lumped "props" cell), so each is gated + validated on its own.
_PROPS: dict[str, list[str]] = {
    "mlb": ["batter_home_runs", "batter_hits", "batter_total_bases", "batter_rbis",
            "batter_runs_scored", "batter_walks", "batter_singles", "batter_doubles",
            "batter_stolen_bases", "pitcher_strikeouts", "pitcher_hits_allowed",
            "pitcher_walks", "pitcher_earned_runs", "pitcher_outs"],
    "wnba": ["player_points", "player_rebounds", "player_assists", "player_threes",
             "player_pra", "player_blocks", "player_steals"],
    "nba": ["player_points", "player_rebounds", "player_assists", "player_threes",
            "player_pra", "player_blocks", "player_steals", "player_double_double"],
    "nhl": ["player_points", "player_goals", "player_assists", "player_shots_on_goal",
            "player_blocked_shots", "player_saves", "player_goal_scorer_anytime"],
    "nfl": ["player_pass_yds", "player_pass_tds", "player_rush_yds", "player_rush_tds",
            "player_receptions", "player_reception_yds", "player_anytime_td"],
    "ufc": ["method_of_victory", "fight_goes_distance"],
}

# Soccer is per-league — each league its own row/model/gate (Liga MX and MLS never
# share a verdict). Labels match _key('soccer_x') → 'x'.
_SOCCER_LEAGUES = [
    "mexico_ligamx", "usa_mls", "epl", "spain_la_liga",
    "italy_serie_a", "germany_bundesliga", "france_ligue_one",
]
_SOCCER_MARKETS = ["moneyline", "total", "btts", "anytime_scorer"]

# Assemble the grid: one lane per market, each mapping to its own registry key.
GRID: dict[str, list[tuple[str, list[str]]]] = {}
for _sport, _core in _CORE.items():
    GRID[_sport] = [(m, [m]) for m in _core] + [(m, [m]) for m in _PROPS.get(_sport, [])]
for _lg in _SOCCER_LEAGUES:
    GRID[_lg] = [(m, [m]) for m in _SOCCER_MARKETS]


def is_prop(market: str) -> bool:
    """True if a market is a player/game prop (its own bet-type market)."""
    return any(market in props for props in _PROPS.values()) or market == "anytime_scorer"

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
