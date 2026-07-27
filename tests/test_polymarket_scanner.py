"""
Polymarket-vs-Pinnacle scanner tests — all network mocked.

The scanner's contract: only emit when Polymarket's TRUE entry cost
(best ask + 2% fee, never the mid) is under Pinnacle's devigged fair prob by
the shared 2% EV bar, with picks shaped so the existing CLV pipeline scores
them for free (Odds-API team name, American odds, market=moneyline).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.polymarket import (   # noqa: E402
    DEFAULT_FEE_SCHEDULE, PolyMarket, maker_fee, maker_limit, max_stake_at_ev,
    taker_fee, walk_book,
)
from scripts.polymarket_scanner import (
    _is_moneyline_market,                # noqa: E402
    log_polymarket_picks,
    prob_to_american,
    scan_sport,
    team_matches,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _pm(question="Yankees vs. Red Sox", outcomes=("New York Yankees", "Boston Red Sox"),
        bid=0.55, ask=0.58, liquidity=5000.0, tokens=("tok0", "tok1"), **over):
    raw = {"outcomes": json.dumps(list(outcomes))}
    kw = dict(
        market_id="m1", question=question, category="sports",
        yes_prob=round((bid + ask) / 2, 4), no_prob=round(1 - (bid + ask) / 2, 4),
        volume_usd=10000.0, liquidity_usd=liquidity, end_date=None, active=True,
        url="https://polymarket.com/event/x", token_ids=list(tokens),
        best_bid=bid, best_ask=ask, raw=raw,
    )
    kw.update(over)
    return PolyMarket(**kw)


def _board(home="New York Yankees", away="Boston Red Sox",
           pin_home=-150, pin_away=130, sport_rows=None):
    """Odds board with a Pinnacle row so build_fair_prob_map gets a sharp anchor."""
    rows = sport_rows or [
        {"GameID": "g1", "HomeTeam": home, "AwayTeam": away, "Sportsbook": "Pinnacle",
         "HomeMoneyline": pin_home, "AwayMoneyline": pin_away,
         "CommenceTime": "2026-07-19T23:00:00Z"},
        {"GameID": "g1", "HomeTeam": home, "AwayTeam": away, "Sportsbook": "FanDuel",
         "HomeMoneyline": -145, "AwayMoneyline": 125,
         "CommenceTime": "2026-07-19T23:00:00Z"},
    ]
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _no_clob(monkeypatch):
    """No CLOB network: default to 'no live book' so entry_cost uses the Gamma
    snapshot. Individual tests override with a fake book."""
    import scripts.polymarket_scanner as sc
    monkeypatch.setattr(sc, "fetch_order_book", lambda *a, **k: None)
    yield


# ── unit: odds + costs + matching ────────────────────────────────────────────

class TestHelpers:
    def test_prob_to_american(self):
        assert prob_to_american(0.25) == 300
        assert prob_to_american(0.60) == -150
        assert prob_to_american(0.50) == -100

    def test_taker_fee_peaks_at_a_coin_flip(self):
        # sports_fees_v2: rate * min(p, 1-p)^exponent. The old flat 2%*(1-p)
        # got this backwards — it charged LEAST at p=0.5, where the real
        # schedule charges most.
        assert taker_fee(0.50) == pytest.approx(0.025)
        assert taker_fee(0.10) == pytest.approx(0.005)
        assert taker_fee(0.90) == pytest.approx(0.005)
        assert taker_fee(0.50) > taker_fee(0.10)

    def test_taker_fee_reads_the_market_schedule(self):
        assert taker_fee(0.50, {"rate": 0.10, "exponent": 1}) == pytest.approx(0.05)

    def test_maker_pays_nothing_while_taker_only(self):
        assert maker_fee(0.44) == 0.0
        assert maker_fee(0.44, {"rate": 0.05, "exponent": 1,
                                "takerOnly": False}) == pytest.approx(taker_fee(0.44))

    def test_maker_limit_improves_bid_only_when_there_is_room(self):
        assert maker_limit(0.43, 0.47) == pytest.approx(0.44)   # room to improve
        assert maker_limit(0.43, 0.44) == pytest.approx(0.43)   # 1-tick spread
        assert maker_limit(None, 0.44) is None

    def test_entry_cost_take_uses_ask_plus_real_fee_not_mid(self):
        pm = _pm(bid=0.36, ask=0.40)     # mid 0.38
        cost = pm.entry_cost("yes", mode="take")
        assert cost == pytest.approx(0.40 + taker_fee(0.40))
        assert cost > pm.yes_prob        # strictly worse than the mid

    def test_entry_cost_no_side_uses_one_minus_bid(self):
        pm = _pm(bid=0.36, ask=0.40)
        cost_no = pm.entry_cost("no", mode="take")
        px = 1 - 0.36
        assert cost_no == pytest.approx(px + taker_fee(px))

    def test_entry_cost_prefers_live_book(self):
        pm = _pm(bid=0.36, ask=0.40)
        cost = pm.entry_cost("yes", book={"best_bid": 0.30, "best_ask": 0.33},
                             mode="take")
        assert cost == pytest.approx(0.33 + taker_fee(0.33))

    def test_make_is_cheaper_than_take_by_spread_plus_fee(self):
        pm = _pm(bid=0.36, ask=0.40)
        make = pm.entry_cost("yes", mode="make")
        take = pm.entry_cost("yes", mode="take")
        assert make == pytest.approx(0.37)       # bid improved one tick, no fee
        assert make < take
        # The whole thesis: the gap is what crossing the spread costs you.
        assert take - make == pytest.approx(0.40 + taker_fee(0.40) - 0.37)

    def test_make_falls_back_to_take_without_a_book(self):
        pm = _pm(best_bid=None, best_ask=None)   # no book at all
        assert pm.entry_cost("yes", mode="make") == pytest.approx(
            pm.entry_cost("yes", mode="take"))

    def test_entry_cost_rejects_unknown_mode(self):
        with pytest.raises(ValueError):
            _pm().entry_cost("yes", mode="teleport")

    def test_market_schedule_overrides_default(self):
        pm = _pm(bid=0.36, ask=0.40,
                 raw={"outcomes": json.dumps(["Yes", "No"]),
                      "feeSchedule": {"rate": 0.20, "exponent": 1,
                                      "takerOnly": True}})
        assert pm.fee_schedule["rate"] == 0.20
        assert pm.entry_cost("yes", mode="take") == pytest.approx(
            0.40 + 0.20 * 0.40)

    def test_team_matches(self):
        assert team_matches("Yankees", "New York Yankees")
        assert team_matches("New York Yankees", "New York Yankees")
        assert team_matches("McGregor", "Conor McGregor")
        assert not team_matches("Yankees", "Boston Red Sox")
        # generic tokens alone never match
        assert not team_matches("New", "New York Yankees")
        assert not team_matches("City", "Kansas City Royals")


# ── scan_sport behavior ──────────────────────────────────────────────────────

class TestScanSport:
    def test_fires_when_poly_cheaper_than_fair(self):
        # Pinnacle -150/+130 → fair home ≈ 0.593. Poly ask 0.55 → cost 0.559
        # → EV ≈ +6.1% ≥ 2% → fire on the home team.
        pm = _pm(bid=0.53, ask=0.55)
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        assert len(picks) >= 1
        p = next(x for x in picks if x["team"] == "New York Yankees")
        assert p["sportsbook"] == "Polymarket"
        assert p["market"] == "moneyline"
        assert p["edge_pct"] > 2.0
        assert p["odds"] == prob_to_american(p["poly_cost"])
        assert isinstance(p["odds"], int)

    def test_taker_silent_when_ask_above_fair(self):
        # Crossing the spread: ask 0.62 + fee > fair 0.593 on the YES side, and
        # the away side's 1-bid=0.40 ask clears no bar either. Silent.
        pm = _pm(bid=0.60, ask=0.62)
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19",
                           entry_mode="take")
        assert picks == []

    def test_maker_finds_edge_where_taker_finds_none(self):
        """The central claim, pinned: the same board is silent to a taker and
        live to a maker. Resting one tick inside the 0.60 bid costs 0.61 with
        no fee, versus 0.62 + fee to cross — and that difference is the whole
        edge. If this ever stops holding, the maker thesis is dead and the
        scanner should go back to taker pricing."""
        pm = _pm(bid=0.60, ask=0.62)
        board, date = _board(), "2026-07-19"
        assert scan_sport("baseball_mlb", board, [pm], date, entry_mode="take") == []
        made = scan_sport("baseball_mlb", board, [pm], date, entry_mode="make")
        assert made, "maker pricing should surface the edge a taker cannot reach"
        p = made[0]
        assert p["poly_entry_mode"] == "make"
        assert p["poly_cost"] < p["poly_taker_cost"]
        # The edge lands on the AWAY side, whose book is the mirror of YES:
        # bid 1-0.62=0.38, ask 1-0.60=0.40, so a passive buy rests at 0.39
        # against a 0.4202 fair. Crossing would have cost 0.42 — nearly the
        # whole edge handed to whoever was already resting there.
        assert p["team"] == "Boston Red Sox"
        assert p["poly_bid"] == pytest.approx(0.38)
        assert p["poly_ask"] == pytest.approx(0.40)
        assert p["poly_limit"] == pytest.approx(0.39)
        assert p["poly_taker_cost"] == pytest.approx(0.42)

    def test_maker_picks_record_the_book_for_later_fill_checks(self):
        """A maker experiment is unfalsifiable unless the bid it was posted
        against is recorded at entry time — polymarket_fills.py replays these."""
        pm = _pm(bid=0.60, ask=0.62)
        made = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19",
                          entry_mode="make")
        p = made[0]
        for field in ("poly_bid", "poly_ask", "poly_limit", "poly_token_id",
                      "poly_entry_mode", "poly_taker_cost"):
            assert p.get(field) is not None, f"{field} missing — fills unmeasurable"

    def test_two_outcome_market_prices_each_side_off_own_token(self, monkeypatch):
        import scripts.polymarket_scanner as sc
        books = {
            "tok0": {"best_bid": 0.53, "best_ask": 0.55},   # home cheap
            "tok1": {"best_bid": 0.44, "best_ask": 0.46},
        }
        monkeypatch.setattr(sc, "fetch_order_book", lambda t, **k: books.get(t))
        pm = _pm()
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        teams = {p["team"] for p in picks}
        assert "New York Yankees" in teams          # 0.593/0.559 → +6%
        assert "Boston Red Sox" not in teams        # 0.407/0.471 → −13%

    def test_yes_no_market_maps_no_to_opponent(self):
        # "Will the Red Sox win?" YES=away team; NO=Yankees ML.
        # YES ask 0.50 → cost 0.51 vs fair away 0.407 → −20% (silent).
        # NO cost = 1−bid = 0.52 → 0.5296 vs fair home 0.593 → +12% (fires).
        pm = _pm(question="Will the Boston Red Sox win?",
                 outcomes=("Yes", "No"), bid=0.48, ask=0.50)
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        assert [p["team"] for p in picks] == ["New York Yankees"]

    def test_draw_sport_skips_no_side_and_two_outcome_markets(self):
        board = _board(home="Club América", away="Chivas Guadalajara",
                       pin_home=-120, pin_away=250)
        # Yes/No in a draw sport: only YES side may fire
        pm_yesno = _pm(question="Will Club América win?", outcomes=("Yes", "No"),
                       bid=0.42, ask=0.44)
        picks = scan_sport("soccer_mexico_ligamx", board, [pm_yesno], "2026-07-19")
        assert all(p["team"] == "Club América" for p in picks)
        # 2-outcome team market in a draw sport: ambiguous draw semantics → skip
        pm_teams = _pm(question="América vs Chivas",
                       outcomes=("Club América", "Chivas Guadalajara"),
                       bid=0.30, ask=0.32)
        assert scan_sport("soccer_mexico_ligamx", board, [pm_teams], "2026-07-19") == []

    def test_unmatched_and_thin_markets_skipped(self):
        unmatched = _pm(question="Will the Lakers win?",
                        outcomes=("Yes", "No"), bid=0.10, ask=0.12)
        thin = _pm(bid=0.10, ask=0.12, liquidity=50.0)
        picks = scan_sport("baseball_mlb", _board(), [unmatched, thin], "2026-07-19")
        assert picks == []

    def test_derivative_markets_never_priced_as_moneylines(self):
        # A spread contract at spread-market prices vs full-game ML fair is a
        # category error, not an edge (first live scan printed +62% on these).
        spread = _pm(question="Spread: New York Yankees (-1.5)",
                     bid=0.40, ask=0.42)
        spread.raw["sportsMarketType"] = "spreads"
        spread.raw["line"] = -1.5
        f5 = _pm(question="New York Yankees winning after 5 innings?",
                 outcomes=("Yes", "No"), bid=0.40, ask=0.42)   # no smt field
        prop = _pm(question="Aaron Judge: Home Runs O/U 0.5",
                   outcomes=("Over", "Under"), bid=0.30, ask=0.32)
        picks = scan_sport("baseball_mlb", _board(), [spread, f5, prop], "2026-07-19")
        assert picks == []
        # …while an explicit moneyline-typed market still fires
        ml = _pm(bid=0.53, ask=0.55)
        ml.raw["sportsMarketType"] = "moneyline"
        assert scan_sport("baseball_mlb", _board(), [ml], "2026-07-19")

    def test_wrong_date_game_never_matches_todays_board(self):
        # Tomorrow's "Liberty vs. Wings" contract must not attach to today's
        # Wings game (this printed a phantom +62% on the first live scan).
        pm = _pm(question="New York Liberty vs. New York Yankees",
                 outcomes=("New York Liberty", "New York Yankees"),
                 bid=0.40, ask=0.42)
        pm.game_start_time = "2026-07-20T23:00:00Z"       # tomorrow
        assert scan_sport("baseball_mlb", _board(), [pm], "2026-07-19") == []
        # …and even with today's start time, a market whose two outcomes span
        # DIFFERENT games (one team not on today's board) is skipped.
        pm2 = _pm(question="New York Liberty vs. New York Yankees",
                  outcomes=("New York Liberty", "New York Yankees"),
                  bid=0.40, ask=0.42)
        pm2.game_start_time = "2026-07-19T23:00:00Z"
        assert scan_sport("baseball_mlb", _board(), [pm2], "2026-07-19") == []

    def test_todays_game_start_time_passes(self):
        pm = _pm(bid=0.53, ask=0.55)
        pm.game_start_time = "2026-07-19 23:00:00+00"     # Gamma's space format
        picks = scan_sport("baseball_mlb", _board(), [pm], "2026-07-19")
        assert any(p["team"] == "New York Yankees" for p in picks)

    def test_ambiguous_doubleheader_skipped(self):
        rows = []
        for gid in ("g1", "g2"):   # same matchup twice = doubleheader
            rows.append({"GameID": gid, "HomeTeam": "New York Yankees",
                         "AwayTeam": "Boston Red Sox", "Sportsbook": "Pinnacle",
                         "HomeMoneyline": -150, "AwayMoneyline": 130,
                         "CommenceTime": "2026-07-19T23:00:00Z"})
        pm = _pm(bid=0.40, ask=0.42)
        picks = scan_sport("baseball_mlb", _board(sport_rows=rows), [pm], "2026-07-19")
        assert picks == []


# ── logging tail ─────────────────────────────────────────────────────────────

class TestLogging:
    def _pick(self):
        return {
            "sport": "baseball_mlb", "market": "moneyline", "direction": "WIN",
            "team": "New York Yankees", "matchup": "Boston Red Sox @ New York Yankees",
            "odds": -128, "sportsbook": "Polymarket", "model_prob": 0.593,
            "edge_pct": 6.1, "poly_market_id": "m1", "poly_cost": 0.559,
            "poly_question": "Yankees vs. Red Sox",
        }

    def test_logged_shape_and_dedup(self, tmp_path, monkeypatch):
        import scripts.polymarket_scanner as sc
        monkeypatch.setattr(sc, "PICKS_FILE", tmp_path / "picks.json")
        monkeypatch.setattr("src.analytics.clv_tracker.snapshot_from_pnl",
                            lambda *a, **k: 0)

        added = log_polymarket_picks([self._pick()], "2026-07-19")
        assert added == 1
        stored = json.loads((tmp_path / "picks.json").read_text())["picks"][0]
        assert stored["strategy"] == "polymarket_ev"
        assert stored["pick_id"].startswith("polymarket_ev__mlb_")   # namespaced + canonical sport
        assert stored["card_pick"] is False and stored["stake"] == 0.0
        assert stored["sportsbook"] == "Polymarket"
        assert stored["poly_market_id"] == "m1"                      # extras survive
        # second run: same pick dedups
        assert log_polymarket_picks([self._pick()], "2026-07-19") == 0


class TestDrawContractsNeverPricedAsWins:
    """Polymarket labels the 3-way DRAW contract sportsMarketType="moneyline"
    and names BOTH clubs in the question. Team matching would otherwise read it
    as a win contract for whichever club matched and price the draw's cheap ask
    against that club's WIN fair — pure fabricated edge.

    Live on 2026-07-21 this printed "Gangwon FC +35.5%": the draw asked 0.31
    while Gangwon's win fair was 0.439. The real Gangwon win contract asked
    0.44 and was correctly -2.8%. Numbers below are that market.
    """

    def test_draw_market_is_not_a_moneyline(self):
        draw = _pm(question="Will Jeju SK FC vs. Gangwon FC end in a draw?",
                   bid=0.30, ask=0.31,
                   raw={"outcomes": json.dumps(["Yes", "No"]),
                        "sportsMarketType": "moneyline"})
        assert _is_moneyline_market(draw) is False

    def test_real_win_market_still_prices(self):
        win = _pm(question="Will Gangwon FC win on 2026-07-21?",
                  bid=0.43, ask=0.44,
                  raw={"outcomes": json.dumps(["Yes", "No"]),
                       "sportsMarketType": "moneyline"})
        assert _is_moneyline_market(win) is True

    def test_draw_never_reaches_the_report(self):
        board = _board(home="Jeju SK FC", away="Gangwon FC",
                       pin_home=120, pin_away=128)
        draw = _pm(question="Will Jeju SK FC vs. Gangwon FC end in a draw?",
                   bid=0.30, ask=0.31, liquidity=13863.0,
                   game_start_time="2026-07-21T10:30:00Z",
                   raw={"outcomes": json.dumps(["Yes", "No"]),
                        "sportsMarketType": "moneyline"})
        picks = scan_sport("soccer_korea_kleague1", board, [draw],
                           "2026-07-21", min_ev=-100.0)
        assert picks == []


class TestBookDepth:
    """Top-of-book is a headline, not a size.

    Live on 2026-07-20 a WNBA market Gamma reported at $45,052 "liquidity" had
    27 shares at its best ask. The quoted +5.4% edge was $4.86 deep and the
    very next level priced at 0.0% EV. Gamma's liquidity is total depth across
    ALL levels, so the MIN_LIQUIDITY_USD filter passed it happily. Pricing any
    stake at the best ask assumes infinite depth there.
    """

    # (price, size) — the real Seattle Storm ask ladder from that market.
    STORM = [(0.18, 27.0), (0.19, 3001.6), (0.20, 15454.63), (0.21, 13561.97)]

    def test_small_stake_fills_at_the_top(self):
        w = walk_book(self.STORM, 4.48)
        assert w["filled"] is True
        assert w["shares"] == pytest.approx(4.48 / 0.18, rel=1e-3)
        assert w["avg_cost"] == pytest.approx(0.18 + taker_fee(0.18), rel=1e-3)

    def test_bigger_stake_eats_worse_levels(self):
        """$500 cannot trade at 0.18 — only $4.86 exists there."""
        w = walk_book(self.STORM, 500.0)
        assert w["filled"] is True
        assert w["avg_cost"] > 0.18 + taker_fee(0.18)
        # blended cost lands between the 0.19 and 0.20 rungs
        assert 0.19 < w["avg_cost"] < 0.21

    def test_edge_survives_only_at_tiny_size(self):
        """The number that decides position vs rounding error."""
        fair = 0.1993
        assert max_stake_at_ev(self.STORM, fair, min_ev_pct=2.0) == pytest.approx(4.86, abs=0.01)
        # At a 2% bar only the top rung clears; nothing deeper does.
        assert max_stake_at_ev(self.STORM, fair, min_ev_pct=5.0) == pytest.approx(4.86, abs=0.01)
        # Demanding 20% clears nothing at all.
        assert max_stake_at_ev(self.STORM, fair, min_ev_pct=20.0) == 0.0

    def test_running_out_of_book_is_reported(self):
        w = walk_book([(0.18, 27.0)], 500.0)
        assert w["filled"] is False
        assert w["spent"] == pytest.approx(4.86, abs=0.01)

    def test_empty_book_is_safe(self):
        w = walk_book([], 100.0)
        assert w["filled"] is False and w["avg_cost"] is None
        assert max_stake_at_ev([], 0.5, 2.0) == 0.0

    def test_scan_records_depth_so_size_is_never_assumed(self, monkeypatch):
        import scripts.polymarket_scanner as sc
        monkeypatch.setattr(sc, "fetch_order_book",
                            lambda t, refresh=False: {
                                "best_bid": 0.36, "best_ask": 0.40,
                                "bids": [(0.36, 500.0)],
                                "asks": [(0.40, 10.0), (0.45, 5000.0)]})
        picks = scan_sport("baseball_mlb", _board(), [_pm(bid=0.36, ask=0.40)],
                           "2026-07-19", min_ev=-100.0, stake_usd=4.48)
        assert picks
        p = picks[0]
        assert p["poly_top_depth_usd"] == pytest.approx(4.0)   # 0.40 * 10
        assert p["poly_max_stake_usd"] is not None


class TestCorruptBookData:
    """Prices derived from an impossible book are fiction, not bad trades.

    Found by fuzzing: maker_limit(bid=0.60, ask=0.40) returned 0.60 — a
    "passive" limit sitting ABOVE the offer, which is a taker price wearing a
    maker label. A real book cannot be crossed, so a crossed one means the two
    sides were read from different snapshots or the feed is stale.
    """

    def test_maker_limit_refuses_a_crossed_book(self):
        assert maker_limit(0.60, 0.40) is None
        assert maker_limit(0.43, 0.44) == pytest.approx(0.43)   # healthy, 1 tick

    def test_scanner_skips_crossed_markets_entirely(self):
        picks = scan_sport("baseball_mlb", _board(), [_pm(bid=0.60, ask=0.40)],
                           "2026-07-19", min_ev=-100.0)
        assert picks == []

    def test_healthy_book_still_prices(self):
        assert scan_sport("baseball_mlb", _board(), [_pm(bid=0.36, ask=0.40)],
                          "2026-07-19", min_ev=-100.0)
