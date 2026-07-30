"""Stakes must be sized on the edge we actually realise, not the one we claim.

THE BUG (found 2026-07-30): `calibrate_edge` shrinks a lane's claimed edge by its
measured reliability k = realised_pp / claimed_pp, and `schema.py` applies that
to the edge RECORDED in the ledger. But `size_bets` passed the raw `ModelProb`
straight to `kelly_fraction`, so the shrink never reached the stake. Every bet
was written down at a shrunk edge and sized at an unshrunk one — the ledger and
the wallet disagreed about the same bet, and the wallet was the optimistic one.

mlb/total, the only live lane, sits at k=0.67 (claims 6.17pp, delivers 4.12pp).
Sizing on the claim rather than the delivery oversizes by roughly half, turning
a nominal quarter-Kelly into ~0.37 Kelly. That direction is the dangerous one:
overbetting Kelly loses growth much faster than underbetting, and past ~1.5x the
growth rate can go negative outright.

The correction belongs on the EDGE (prob − implied), never on the probability,
because "shrink toward the market" is the whole idea.
"""
import pytest

from src.betting.kelly import _implied_prob, kelly_fraction, shrunk_prob


def test_implied_prob_round_trips_both_signs():
    assert _implied_prob(100) == pytest.approx(0.5)
    assert _implied_prob(-110) == pytest.approx(110 / 210)
    assert _implied_prob(150) == pytest.approx(100 / 250)


def test_no_lane_given_means_no_change(monkeypatch):
    """Callers that can't name their lane keep the old behaviour rather than
    getting a silent, unlocatable adjustment."""
    assert shrunk_prob(0.60, -110) == 0.60


def test_shrink_pulls_toward_the_market_not_toward_a_half(monkeypatch):
    """k<1 must move the probability toward the IMPLIED price, which is the
    market's opinion — not toward 0.5, which is nobody's."""
    monkeypatch.setattr("src.analytics.calibration_gate.calibrate_edge",
                        lambda s, m, e: e * 0.5 if e is not None else None)
    odds = -110
    implied = _implied_prob(odds)          # ~0.5238
    p = shrunk_prob(0.70, odds, "mlb", "total")
    assert implied < p < 0.70
    # Exactly half the claimed edge survives.
    assert p == pytest.approx(implied + (0.70 - implied) * 0.5, abs=1e-9)


def test_shrink_reduces_the_stake(monkeypatch):
    """The point of the whole exercise."""
    monkeypatch.setattr("src.analytics.calibration_gate.calibrate_edge",
                        lambda s, m, e: e * 0.67 if e is not None else None)
    odds = -110
    raw = kelly_fraction(0.70, odds, fraction=0.25)
    adj = kelly_fraction(shrunk_prob(0.70, odds, "mlb", "total"), odds, fraction=0.25)
    assert 0 < adj < raw, "shrink did not reduce the stake"


def test_a_negative_claimed_edge_is_left_alone(monkeypatch):
    """Below the implied price there is no edge to shrink; Kelly already
    returns 0 there, and 'shrinking' a negative number would grow it."""
    called = []
    monkeypatch.setattr("src.analytics.calibration_gate.calibrate_edge",
                        lambda s, m, e: called.append(e) or e)
    p = shrunk_prob(0.40, -110, "mlb", "total")
    assert p == 0.40
    assert not called, "asked for a shrink on a bet with no claimed edge"


def test_a_reliable_lane_is_not_penalised(monkeypatch):
    """k=1 means the model delivers what it claims — sizing must be untouched."""
    monkeypatch.setattr("src.analytics.calibration_gate.calibrate_edge",
                        lambda s, m, e: e)
    assert shrunk_prob(0.65, -110, "mlb", "total") == pytest.approx(0.65, abs=1e-9)


def test_a_zeroed_lane_gets_no_stake(monkeypatch):
    """calibrate_edge returns 0.0 for lanes whose claimed edge is fiction
    (retired/overconfident markets). That must collapse the stake to nothing,
    not merely trim it."""
    monkeypatch.setattr("src.analytics.calibration_gate.calibrate_edge",
                        lambda s, m, e: 0.0)
    odds = -110
    p = shrunk_prob(0.70, odds, "wnba", "total")
    assert p == pytest.approx(_implied_prob(odds), abs=1e-9)
    assert kelly_fraction(p, odds, fraction=0.25) == 0.0


def test_size_bets_threads_the_lane_through(monkeypatch):
    """End-to-end: size_bets must actually apply the shrink, not just accept
    the arguments. This is the step that was missing."""
    import pandas as pd
    from src.betting.kelly import size_bets

    monkeypatch.setattr("src.analytics.calibration_gate.calibrate_edge",
                        lambda s, m, e: e * 0.5 if e is not None else None)
    df = pd.DataFrame([{"ModelProb": 0.70, "BestOdds": -110}])
    shrunk = size_bets(df, bankroll=1000, kelly_fraction_pct=0.25,
                       sport="mlb", market="total")
    plain = size_bets(df, bankroll=1000, kelly_fraction_pct=0.25)
    assert 0 < shrunk["BetSize"].iloc[0] < plain["BetSize"].iloc[0]
