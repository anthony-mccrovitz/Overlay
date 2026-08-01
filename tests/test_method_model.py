"""The method model must say something fight-specific, or say nothing.

THE BUG IT REPLACES. `ufc_model.simulate_fight` returned 27% KO / 21% sub /
52% decision for six different bouts on the 2026-08-01 card — byte-identical,
because 49% of its style profiles sit at the 0.50 default and comparing 0.50
against 0.50 reproduces the league base rate every time. It never said so; it
printed a confident-looking distribution. A constant wearing the costume of a
prediction is worse than a refusal, because a refusal cannot be bet on.

So the tests that matter here are not "is the number plausible" but:
  - does it DIFFERENTIATE between fights (the regression), and
  - does it REFUSE when it has no history, instead of falling back to a
    constant with a straight face.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pytest

from src.models.method_model import (
    CLASSES, FEATURES, MethodLedger, MethodModel, MethodState, classify_method,
    read_method,
)

_ARTIFACT = Path("data/models/ufc/method_model.json")
needs_model = pytest.mark.skipif(not _ARTIFACT.exists(),
                                 reason="method model not trained")


# ── the label map ────────────────────────────────────────────────────────────
def test_submission_to_punches_is_a_striking_finish():
    """The loser tapped, but to strikes. Filing it under submissions would
    credit a grappler for a beating — this is the judgement call most likely
    to be silently 'fixed' later, so it is pinned."""
    assert classify_method("TKO (Submission to Punches)") == "ko_tko"
    assert classify_method("Submission (Rear-Naked Choke)") == "submission"


def test_method_families_are_read_from_the_leading_token():
    for raw, want in [
        ("Decision (Unanimous)", "decision"), ("Decision (Split)", "decision"),
        ("KO (Punch)", "ko_tko"), ("TKO (Doctor Stoppage)", "ko_tko"),
        ("TKO", "ko_tko"), ("Submission (Armbar)", "submission"),
        ("Technical Submission (Choke)", "submission"),
    ]:
        assert classify_method(raw) == want, raw


def test_non_methods_are_dropped_not_bucketed():
    """1,375 'N/A' rows exist. Forcing them into a class would put noise into
    every probability the model emits."""
    for raw in ("N/A", "", "Draw", "No Contest", "DQ", "Disqualification"):
        assert classify_method(raw) is None, raw


# ── point-in-time discipline ─────────────────────────────────────────────────
def test_features_never_see_the_bout_being_predicted():
    led = MethodLedger()
    led.apply_bout("alpha", "beta", "KO (Punch)")
    before = led.features_for("alpha", "beta")
    led.apply_bout("alpha", "beta", "KO (Punch)")
    after = led.features_for("alpha", "beta")
    assert before != after, "state did not advance — the replay is not live"
    assert before["ko_offense"] < after["ko_offense"]


def test_reading_features_does_not_mutate_state():
    """Reads must be pure, or a backtest silently trains on its own output."""
    led = MethodLedger()
    for i in range(6):
        led.apply_bout("alpha", f"opp{i}", "Submission (Armbar)")
    snap = {k: (v.n, v.win_ko, v.win_sub, v.win_dec) for k, v in led.book.items()}
    led.features_for("alpha", "opp0")
    led.base_rates()
    led.state("alpha")
    after = {k: (v.n, v.win_ko, v.win_sub, v.win_dec) for k, v in led.book.items()}
    assert snap == after, "a read moved fighter state"


# ── the orientation contract ─────────────────────────────────────────────────
def test_features_are_symmetric_in_the_two_fighters():
    """'This fight ends by KO' does not depend on who is listed first. An
    asymmetric feature could encode WHO wins, which this model does not predict
    and whose label would leak straight in from the (winner, loser) source
    ordering."""
    led = MethodLedger()
    for i in range(8):
        led.apply_bout("striker", f"x{i}", "KO (Punch)")
    for i in range(8):
        led.apply_bout("grappler", f"y{i}", "Submission (Armbar)")
    ab = led.features_for("striker", "grappler")
    ba = led.features_for("grappler", "striker")
    assert ab == ba, "feature vector changed when the fighters were swapped"


# ── refusal ──────────────────────────────────────────────────────────────────
def test_two_unknown_fighters_get_no_read_not_a_base_rate():
    """THE REGRESSION. The old simulator answered this case with the league
    base rate and called it a prediction."""
    led = MethodLedger()
    assert led.features_for("nobody-1", "nobody-2") is None
    r = read_method(led, "nobody-1", "nobody-2")
    assert r.basis == "no_data"
    assert r.ko_tko == 0.0 and r.decision == 0.0


def test_a_thin_record_is_flagged_rather_than_hidden():
    led = MethodLedger()
    for i in range(30):
        led.apply_bout("veteran", f"opp{i}", "Decision (Unanimous)")
    led.apply_bout("rookie", "someone", "KO (Punch)")
    r = read_method(led, "veteran", "rookie")
    if r.basis == "model":
        assert r.note, "a 1-bout fighter produced an unqualified read"


def test_shrinkage_keeps_a_tiny_record_near_the_base_rate():
    """2 KOs in 2 bouts is not a 100% KO rate; it is 2 bouts."""
    thin, thick = MethodState(n=2, win_ko=2), MethodState(n=40, win_ko=40)
    base = 0.36
    assert thin.rate(thin.win_ko, base) < thick.rate(thick.win_ko, base)
    assert thin.rate(thin.win_ko, base) < 0.75


# ── the artifact ─────────────────────────────────────────────────────────────
@needs_model
def test_artifact_beat_the_base_rate_on_held_out_years():
    meta = json.loads(_ARTIFACT.read_text())["metadata"]
    assert meta["mean_holdout_log_loss"] < meta["mean_base_log_loss"], \
        "shipped a model that loses to a constant"
    assert len(meta["walk_forward"]) >= 3
    assert meta["years_better_than_base"] >= len(meta["walk_forward"]) - 1


@needs_model
def test_probabilities_are_a_distribution():
    m = MethodModel()
    assert m.ok
    led = MethodLedger()
    for i in range(10):
        led.apply_bout("a", f"o{i}", "KO (Punch)")
        led.apply_bout("b", f"p{i}", "Decision (Unanimous)")
    p = m.predict_from_features(led.features_for("a", "b"))
    assert set(p) == set(CLASSES)
    assert all(0.0 <= v <= 1.0 for v in p.values())
    assert sum(p.values()) == pytest.approx(1.0)


@needs_model
def test_the_model_differentiates_between_fights():
    """THE CENTRAL REGRESSION TEST — the reason this model was built.

    Two maximally different matchups (two finishers who have never seen a
    judge, versus two decision-going fighters who have never been stopped)
    must produce visibly different distributions. The retired simulator
    returned the SAME three numbers for both.
    """
    m = MethodModel()
    led = MethodLedger()
    for i in range(25):
        led.apply_bout("finisher_a", f"fa{i}", "KO (Punch)")
        led.apply_bout("finisher_b", f"fb{i}", "KO (Punches)")
        led.apply_bout("pointer_a", f"pa{i}", "Decision (Unanimous)")
        led.apply_bout("pointer_b", f"pb{i}", "Decision (Unanimous)")

    ko_fight = m.predict_from_features(led.features_for("finisher_a", "finisher_b"))
    dec_fight = m.predict_from_features(led.features_for("pointer_a", "pointer_b"))

    assert ko_fight["ko_tko"] > dec_fight["ko_tko"] + 0.15, (
        "two knockout artists and two decision merchants priced the same — "
        "the model is a constant again")
    assert dec_fight["decision"] > ko_fight["decision"] + 0.15


@needs_model
def test_grapplers_move_the_submission_probability():
    """A distinct lens on the same contract: the sub class must respond to
    submission history specifically, not just to 'finishes'."""
    m = MethodModel()
    led = MethodLedger()
    for i in range(25):
        led.apply_bout("sub_a", f"sa{i}", "Submission (Armbar)")
        led.apply_bout("sub_b", f"sb{i}", "Submission (Rear-Naked Choke)")
        led.apply_bout("ko_a", f"ka{i}", "KO (Punch)")
        led.apply_bout("ko_b", f"kb{i}", "KO (Punch)")
    grap = m.predict_from_features(led.features_for("sub_a", "sub_b"))
    strike = m.predict_from_features(led.features_for("ko_a", "ko_b"))
    assert grap["submission"] > strike["submission"], \
        "submission probability ignores submission history"
