"""Market-implied team context must be right, and must admit when it isn't.

The second half matters more than the first. This module exists to fix a known
blind spot in `valuation.py`, and the failure mode that would make it WORSE than
the blind spot is silently returning "no adjustment" when it means "no data" —
a projection that looks market-aware but isn't. That is this repo's recurring
bug (see project_pipeline_trust_program), so it gets the most tests here.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.fantasy import market


def _odds(rows: list[tuple[str, str, float, float]]) -> pd.DataFrame:
    """(home, away, total, home_spread) → the shape fetch_odds returns."""
    out = []
    for home, away, total, spread in rows:
        for book in ("DraftKings", "FanDuel", "BetMGM"):
            out.append({"HomeTeam": home, "AwayTeam": away, "Sportsbook": book,
                        "HomeSpread": spread, "Total": total})
    return pd.DataFrame(out)


@pytest.fixture
def slate(monkeypatch):
    """One two-game week: a blowout and a shootout."""
    monkeypatch.setattr(market, "_schedule",
                        lambda week, season: [("NYJ", "TEN"), ("TB", "CIN")])
    return market.week_market(1, odds_df=_odds([
        ("Tennessee Titans", "New York Jets", 38.5, -2.5),
        ("Cincinnati Bengals", "Tampa Bay Buccaneers", 51.5, 3.5),
    ]))


# ─────────────────────── the arithmetic ──────────────────────────────────────

def test_implied_totals_split_the_game_total(slate):
    for tw in slate.values():
        assert tw.implied_total + tw.opp_implied_total == pytest.approx(tw.game_total)


def test_the_favorite_is_implied_to_score_more(slate):
    # Titans lay 2.5 at home in a 38.5 game → 20.5 / 18.0.
    assert slate["TEN"].implied_total == pytest.approx(20.5)
    assert slate["NYJ"].implied_total == pytest.approx(18.0)
    assert slate["TEN"].implied_total > slate["NYJ"].implied_total


def test_home_and_away_see_each_other(slate):
    assert slate["TEN"].opp_implied_total == slate["NYJ"].implied_total
    assert slate["TEN"].is_home and not slate["NYJ"].is_home


# ───────────────── "couldn't check" is never "all clear" ─────────────────────

def test_unpriced_week_returns_empty_not_a_partial_slate(monkeypatch):
    """A week the book hasn't posted yields nothing at all."""
    monkeypatch.setattr(market, "_schedule",
                        lambda week, season: [("NYJ", "TEN")])
    assert market.week_market(18, odds_df=pd.DataFrame()) == {}


def test_unpriced_game_is_omitted_rather_than_invented(monkeypatch):
    """Two scheduled games, one priced — the unpriced one must not appear."""
    monkeypatch.setattr(market, "_schedule",
                        lambda week, season: [("NYJ", "TEN"), ("TB", "CIN")])
    out = market.week_market(1, odds_df=_odds([
        ("Tennessee Titans", "New York Jets", 38.5, -2.5)]))
    assert set(out) == {"TEN", "NYJ"}, (
        "an unpriced game leaked into the market view — every team present here "
        "is treated downstream as having a real, money-backed number"
    )


def test_unknown_context_is_none_and_never_neutral(slate):
    """The load-bearing guard.

    If this returns 1.0 for a team with no line, the caller cannot distinguish
    'the market says this is an average matchup' from 'there is no market'. The
    projection then LOOKS adjusted while carrying the exact stale team context
    this module was built to replace — strictly worse than not adjusting, because
    it is no longer visible.
    """
    assert market.context_multiplier("WR", "SEA", slate) is None
    assert market.context_multiplier("DEF", "SEA", slate) is None


def test_no_market_at_all_yields_no_multiplier():
    assert market.context_multiplier("WR", "TEN", {}) is None


# ───────────────────────── direction of the adjustment ───────────────────────

def test_defense_improves_as_its_opponent_gets_worse(slate):
    """DEF inverts: the Jets' 18.0 is a gift, the Bengals' 27.5 is a problem."""
    good = market.context_multiplier("DEF", "TEN", slate)   # faces NYJ, 18.0
    bad = market.context_multiplier("DEF", "CIN", slate)    # faces TB,  27.5
    assert good > 1.0 > bad
    assert good > bad


def test_skill_players_scale_with_their_own_offense(slate):
    """...and are damped, so context breaks ties instead of overturning ranks."""
    cin = market.context_multiplier("WR", "CIN", slate)     # 27.5 implied
    nyj = market.context_multiplier("WR", "NYJ", slate)     # 18.0 implied
    assert cin > 1.0 > nyj

    avg = market.league_average(slate)
    raw = slate["CIN"].implied_total / avg - 1.0
    assert cin - 1.0 == pytest.approx(market.SKILL_PASS_THROUGH * raw)
    assert abs(cin - 1.0) < abs(raw), (
        "the skill-player adjustment is not damped; an unfitted market "
        "multiplier applied at full strength would overturn projections built "
        "on real usage data"
    )


def test_kickers_are_damped_harder_than_skill_players(slate):
    k = market.context_multiplier("K", "CIN", slate)
    wr = market.context_multiplier("WR", "CIN", slate)
    assert 1.0 < k < wr


# ─────────────────────────── the DST board ───────────────────────────────────

def test_defenses_rank_by_opponent_not_by_own_strength(slate):
    ranked = market.rank_defenses(slate)
    assert [tw.team for tw in ranked] == ["TEN", "NYJ", "TB", "CIN"]
    assert ranked == sorted(ranked, key=lambda tw: tw.opp_implied_total)


def test_rostered_defenses_can_be_excluded(slate):
    ranked = market.rank_defenses(slate, exclude={"TEN", "NYJ"})
    assert [tw.team for tw in ranked] == ["TB", "CIN"]


# ─────────────────────────── the join ────────────────────────────────────────

def test_every_nfl_team_can_be_joined_from_odds_names_to_sleeper():
    """A missing club silently drops its whole game from the board."""
    assert len(market.TEAM_ABBR) == 32
    assert len(set(market.TEAM_ABBR.values())) == 32


def test_abbreviations_match_the_vocabulary_sleeper_actually_uses():
    """Pins the join against the live schedule, which is the other side of it."""
    try:
        games = market._schedule(1, 2026)
    except Exception as err:                      # offline / API down
        pytest.skip(f"schedule unavailable: {err}")
    if not games:
        pytest.skip("no week 1 schedule published yet")

    sleeper_teams = {t for game in games for t in game}
    unknown = sleeper_teams - set(market.TEAM_ABBR.values())
    assert not unknown, (
        f"Sleeper uses abbreviation(s) {sorted(unknown)} that TEAM_ABBR never "
        f"produces, so those games can never be priced and their teams will "
        f"read as 'unknown matchup' every week"
    )
