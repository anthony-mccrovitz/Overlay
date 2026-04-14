"""
Shared game ID generation for consistent tracking across the pipeline.

Every component that records or looks up a pick (daily pipeline, closing line
capture, grading, CLV tracker, P&L tracker) MUST use make_game_id() to ensure
IDs match.
"""
from __future__ import annotations

from datetime import date


def make_game_id(game_date: date | str, team_name: str, sport: str = "mlb") -> str:
    if isinstance(game_date, date):
        date_str = game_date.strftime("%Y%m%d")
    else:
        date_str = game_date.replace("-", "")

    clean_team = team_name.strip().replace(" ", "_")
    return f"{sport}_{date_str}_{clean_team}"
