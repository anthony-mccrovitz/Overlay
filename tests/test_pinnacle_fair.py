"""
tests/test_pinnacle_fair.py — the fair-probability anchor.

build_fair_prob_map is the reference every edge in this system is measured
against: devig_ev, consensus_ev, the Polymarket scanner, predict.py and
run_nba.py all price against it. A wrong fair here does not produce a wrong
number somewhere downstream — it produces a CONFIDENT wrong number, an edge
that looks real and has size behind it.

The bug these tests exist for: the median fallback took a median of raw
AMERICAN ODDS. American odds are discontinuous across ±100 (they run
... -102, -101, +100, +101 ... with nothing between -100 and +100), so a
median of prices straddling that gap lands in a numerically meaningless
region. A real WNBA board quoted the away side of a coin-flip game at
[-108, -105, -102, +100, +100, +100]; the numeric median is -1.0, which is a
1% probability, and the devigged fair came out 0.982 for a pick'em. The
scanner then reported +81.9% EV with $5,204 of depth behind it.

Run: python3 -m pytest tests/test_pinnacle_fair.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest

from src.data.pinnacle_fair import _median_prob, build_fair_prob_map


def _board(rows):
    return pd.DataFrame(rows)


def _game(book, home_ml, away_ml, gid="g1",
          home="Los Angeles Sparks", away="Phoenix Mercury"):
    return {"GameID": gid, "HomeTeam": home, "AwayTeam": away,
            "Sportsbook": book, "HomeMoneyline": home_ml, "AwayMoneyline": away_ml,
            "CommenceTime": "2026-07-22T19:00:00Z"}


class TestMedianAcrossTheOddsDiscontinuity:
    """The exact board that produced the phantom 98.2%."""

    AWAY = [-108.0, -105.0, -102.0, 100.0, 100.0, 100.0]
    HOME = [-112.0, -120.0, -120.0, -118.0, -125.0, -120.0]

    def test_median_prob_ignores_the_sign_cliff(self):
        # Every one of these prices means "about even money".
        med = _median_prob(pd.Series(self.AWAY))
        assert 0.48 < med < 0.53, f"even-money book should be ~0.5, got {med}"

    def test_naive_numeric_median_would_have_been_absurd(self):
        """Documents the trap: the old path is still arithmetically reachable,
        and lands at a 1% probability for a coin-flip market."""
        naive = pd.Series(self.AWAY).median()
        assert naive == pytest.approx(-1.0)
        # abs(-1)/(abs(-1)+100) — a 1% chance for an even-money side.
        assert abs(naive) / (abs(naive) + 100.0) < 0.02

    def test_coin_flip_game_devigs_to_a_coin_flip(self):
        books = ["FanDuel", "Fanatics", "theScore Bet", "DraftKings",
                 "Hard Rock Bet", "Caesars"]
        board = _board([_game(b, h, a) for b, h, a
                        in zip(books, self.HOME, self.AWAY)])
        h2h = build_fair_prob_map(board)["g1"]["h2h"]
        assert h2h["source"] == "median"          # no Pinnacle on this board
        assert 0.50 < h2h["home"] < 0.56, h2h
        assert 0.44 < h2h["away"] < 0.50, h2h
        assert h2h["home"] + h2h["away"] == pytest.approx(1.0)

    def test_no_fair_probability_is_ever_extreme_on_a_close_game(self):
        """The guard that would have caught the +81.9% before it printed."""
        books = ["FanDuel", "Fanatics", "theScore Bet", "DraftKings",
                 "Hard Rock Bet", "Caesars"]
        board = _board([_game(b, h, a) for b, h, a
                        in zip(books, self.HOME, self.AWAY)])
        h2h = build_fair_prob_map(board)["g1"]["h2h"]
        assert max(h2h["home"], h2h["away"]) < 0.95


class TestPinnacleStillPreferred:
    def test_pinnacle_row_wins_over_the_median(self):
        board = _board([
            _game("Pinnacle", 380.0, -513.0),
            _game("FanDuel", 370.0, -520.0),
        ])
        h2h = build_fair_prob_map(board)["g1"]["h2h"]
        assert h2h["source"] == "pinnacle"
        # +380 / -513 devigs to roughly 20/80.
        assert h2h["home"] == pytest.approx(0.199, abs=0.01)

    def test_median_used_only_when_pinnacle_absent(self):
        board = _board([_game("FanDuel", 380.0, -520.0)])
        assert build_fair_prob_map(board)["g1"]["h2h"]["source"] == "median"


class TestDegenerateInput:
    def test_all_nan_column_yields_no_h2h(self):
        board = _board([_game("FanDuel", float("nan"), float("nan"))])
        assert "h2h" not in build_fair_prob_map(board).get("g1", {})

    def test_empty_board_is_safe(self):
        assert build_fair_prob_map(pd.DataFrame()) == {}

    def test_median_prob_empty_is_nan(self):
        assert pd.isna(_median_prob(pd.Series([], dtype=float)))
