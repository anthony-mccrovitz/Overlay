"""Regression tests for the 2026-07-12 phantom-edge incident.

Root cause was two stacked date bugs:
1. night_pipeline.tomorrow_str() used the runner's UTC clock, so the
   9:30 PM ET job (01:33Z = next UTC day) requested a slate one day past
   the intended one — and worse when Actions cron fired late.
2. The MLB odds board was never filtered to the slate date before the
   team-name join in value_bets, so mid-series (same teams on the board
   for consecutive days) the wrong day's line priced the slate.
"""

from datetime import date, datetime, timezone

import pandas as pd

from scripts.night_pipeline import slate_date_for
from src.data.slate import filter_df_to_slate, filter_to_slate


class TestNightSlateDate:
    def test_on_time_run_targets_next_et_day(self):
        # 9:30 PM ET July 10 == 01:33Z July 11. Intended slate: July 11.
        now = datetime(2026, 7, 11, 1, 33, tzinfo=timezone.utc)
        assert slate_date_for(now) == "20260711"

    def test_delayed_cron_past_midnight_et_targets_same_slate(self):
        # The incident: cron fired at 04:42Z (00:42 ET July 11). The old
        # UTC-based tomorrow returned 20260712; the slate being opened
        # that evening was still July 11.
        now = datetime(2026, 7, 11, 4, 42, tzinfo=timezone.utc)
        assert slate_date_for(now) == "20260711"

    def test_afternoon_manual_run_targets_tomorrow(self):
        # 1:00 PM ET July 11 — a manual "night" run in the afternoon
        # legitimately pre-generates July 12 at line-open.
        now = datetime(2026, 7, 11, 17, 0, tzinfo=timezone.utc)
        assert slate_date_for(now) == "20260712"


class TestOddsBoardSlateFilter:
    def _board(self):
        # Same team pair on consecutive days — a normal MLB series. This is
        # exactly the shape that let July 11 odds price July 12 predictions.
        return pd.DataFrame(
            [
                {"GameID": "a", "HomeTeam": "New York Mets", "AwayTeam": "Boston Red Sox",
                 "CommenceTime": "2026-07-11T20:11:00Z", "Sportsbook": "FanDuel"},
                {"GameID": "b", "HomeTeam": "New York Mets", "AwayTeam": "Boston Red Sox",
                 "CommenceTime": "2026-07-12T17:41:00Z", "Sportsbook": "FanDuel"},
            ]
        )

    def test_keeps_only_slate_date_rows(self):
        out = filter_df_to_slate(self._board(), date(2026, 7, 12))
        assert list(out["GameID"]) == ["b"]

    def test_accepts_yyyymmdd_string(self):
        out = filter_df_to_slate(self._board(), "20260711")
        assert list(out["GameID"]) == ["a"]

    def test_late_night_et_game_stays_on_its_et_date(self):
        # 02:05Z July 12 is 10:05 PM ET July 11 — belongs to the July 11 slate.
        df = pd.DataFrame(
            [{"GameID": "west", "CommenceTime": "2026-07-12T02:05:00Z"}]
        )
        assert list(filter_df_to_slate(df, date(2026, 7, 11))["GameID"]) == ["west"]
        assert filter_df_to_slate(df, date(2026, 7, 12)).empty

    def test_unparseable_commence_time_dropped(self):
        df = pd.DataFrame([{"GameID": "x", "CommenceTime": "not-a-time"}])
        assert filter_df_to_slate(df, date(2026, 7, 12)).empty

    def test_empty_frame_passthrough(self):
        df = pd.DataFrame()
        assert filter_df_to_slate(df, date(2026, 7, 12)).empty


class TestEventListSlateFilter:
    def test_event_filter_matches_df_filter_semantics(self):
        events = [
            {"commence_time": "2026-07-11T20:11:00Z"},
            {"commence_time": "2026-07-12T17:41:00Z"},
        ]
        kept = filter_to_slate(events, date(2026, 7, 12))
        assert len(kept) == 1
        assert kept[0]["commence_time"].startswith("2026-07-12")
