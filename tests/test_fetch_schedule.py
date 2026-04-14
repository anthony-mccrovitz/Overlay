"""
Tests for mlb_stats.fetch_schedule() game state filtering.
"""
from datetime import date
from unittest.mock import patch

from src.data.mlb_stats import fetch_schedule


def _make_game(abstract_state: str, coded_state: str, game_type: str = "R") -> dict:
    return {
        "gameType": game_type,
        "status": {
            "abstractGameState": abstract_state,
            "codedGameState": coded_state,
            "detailedState": f"{abstract_state}/{coded_state}",
        },
        "teams": {"home": {"team": {"id": 1, "name": "Home"}},
                  "away": {"team": {"id": 2, "name": "Away"}}},
    }


def _mock_api_response(games: list) -> dict:
    return {"dates": [{"date": "2026-04-13", "games": games}]}


def _patch_cached_get(games):
    return patch(
        "src.data.mlb_stats._cached_get",
        return_value=_mock_api_response(games),
    )


# ── State filtering ───────────────────────────────────────────────────────────

def test_scheduled_game_included():
    """Preview/Scheduled games are tomorrow's slate — include them."""
    with _patch_cached_get([_make_game("Preview", "S")]):
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 1


def test_pregame_included():
    """Preview/Pre-Game is still bettable — include it."""
    with _patch_cached_get([_make_game("Preview", "P")]):
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 1


def test_in_progress_excluded():
    """Live/In Progress games cannot be bet pre-game — exclude them."""
    with _patch_cached_get([_make_game("Live", "I")]):
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 0


def test_warmup_excluded():
    """Live/Warmup means first pitch is seconds away — exclude."""
    with _patch_cached_get([_make_game("Live", "P")]):
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 0


def test_delayed_game_excluded():
    """Live/Delayed is already in progress — exclude."""
    with _patch_cached_get([_make_game("Live", "I", "R")]):
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 0


def test_final_game_excluded():
    """Final games are over — exclude."""
    with _patch_cached_get([_make_game("Final", "F")]):
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 0


def test_postponed_game_excluded():
    """Postponed games show as Final/D in the API — correctly excluded."""
    with _patch_cached_get([_make_game("Final", "D")]):
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 0


def test_non_regular_season_excluded():
    """Exhibition/spring training games excluded by gameType filter."""
    with _patch_cached_get([_make_game("Preview", "S", "E")]):  # E = Exhibition
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 0


def test_mixed_slate_filters_correctly():
    """Realistic slate: 1 live, 1 final, 8 scheduled → 8 returned."""
    games_input = (
        [_make_game("Live", "I")] +
        [_make_game("Final", "F")] +
        [_make_game("Preview", "S")] * 8
    )
    with _patch_cached_get(games_input):
        games = fetch_schedule(date(2026, 4, 13))
    assert len(games) == 8
