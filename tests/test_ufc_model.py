"""The UFC model's guarantees, as executable checks.

Each test here maps to a bug that actually shipped:

  point-in-time     the leakage guard — features must never see the future
  no-noise-swamp    the phi=350 bug that made every fight 50-53%
  name matching     "L'udovit Klein" vs "Ludovit Klein" reported an 11-bout
                    veteran as having no UFC record
  unknown honesty   a fighter we cannot see must never be priced as average
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pytest
from types import SimpleNamespace

from src.models.ufc_features import (
    DEBUT_WIN_RATE,
    FEATURES,
    Ledger,
    UFCFightModel,
    build_ledger,
    load_bouts,
    normalize_name,
)

_HAVE_DATA = (Path("data/ufc/fight_results.csv").exists()
              and Path("data/ufc/event_details.csv").exists())
_HAVE_MODEL = Path("data/models/ufc/fight_model.json").exists()

needs_data = pytest.mark.skipif(not _HAVE_DATA, reason="UFC fight data not cached")
needs_model = pytest.mark.skipif(not _HAVE_MODEL, reason="UFC model not trained")


# ── name matching ────────────────────────────────────────────────────────────
def test_normalize_folds_diacritics_and_apostrophes():
    """The exact bug: the odds feed and ufcstats spell the same fighter
    differently, and the mismatch produced a confident wrong answer."""
    assert normalize_name("L'udovit Klein") == normalize_name("Ludovit Klein")
    assert normalize_name("Cláudio Nardo") == normalize_name("Claudio Nardo")
    assert normalize_name("Borislav Nikolić") == normalize_name("Borislav Nikolic")
    assert normalize_name("  Jan   Blachowicz ") == "jan blachowicz"


def test_normalize_does_not_collapse_distinct_fighters():
    """Guards against 'fix' by fuzzy matching. This repo already ate a bug where
    last-name matching handed Michael Chandler the ratings of Michael Page."""
    assert normalize_name("Michael Chandler") != normalize_name("Michael Page")
    assert normalize_name("Jon Jones") != normalize_name("Jonny Jones")


def test_ledger_lookup_survives_a_spelling_variant():
    led = Ledger({}, {})
    led.apply_bout({"date": date(2024, 1, 1), "event": "E", "bout": "B",
                    "w": "Ludovit Klein", "l": "Someone Else",
                    "method": "Decision - Unanimous", "secs": 900.0})
    assert led.known("L'udovit Klein"), "diacritic variant must resolve to the same fighter"
    assert led.state("L'udovit Klein").n == 1


# ── the leakage guarantee ────────────────────────────────────────────────────
@needs_data
def test_features_never_see_the_fight_they_describe():
    """Point-in-time: a fight's features must equal those from a ledger built
    ONLY from strictly-earlier bouts.

    This is the check that makes the walk-forward scores meaningful. If state
    were folded in before the row was emitted, every fighter would carry the
    result of the fight being predicted and the model would look brilliant.
    """
    bouts, stats, tott = load_bouts()
    assert len(bouts) > 1000

    # Pick a bout deep in the stream whose fighters both have real history.
    target = None
    probe = Ledger(stats, tott)
    for b in bouts:
        if (probe.state(b["w"]).n >= 5 and probe.state(b["l"]).n >= 5
                and b["date"].year >= 2020):
            target = b
            break
        probe.apply_bout(b)
    assert target is not None, "expected a mid-career bout to probe"

    # Streamed: emit at the moment we reach the target.
    streamed = Ledger(stats, tott)
    for b in bouts:
        if b is target:
            break
        streamed.apply_bout(b)
    got = streamed.diff_vector(target["w"], target["l"], target["date"])

    # Rebuilt independently from strictly-earlier bouts only.
    rebuilt = Ledger(stats, tott)
    for b in bouts:
        if b["date"] < target["date"]:
            rebuilt.apply_bout(b)
    want = rebuilt.diff_vector(target["w"], target["l"], target["date"])

    for name, g, w in zip(FEATURES, got, want):
        if g is None or w is None:
            assert g == w, f"{name}: known-ness differs between builds"
        else:
            assert abs(g - w) < 1e-6, f"{name}: {g} != {w} — state leaked"


def test_reading_features_does_not_mutate_state():
    """Reads must be pure.

    Written after a mutation test embarrassed the check above: comparing a
    streamed ledger against a rebuilt one passes happily when BOTH carry the
    same leak, because they agree with each other. Agreement between two runs of
    the same code is not evidence. This asserts the invariant directly instead.
    """
    led = Ledger({}, {})
    for i in range(6):
        led.apply_bout({"date": date(2024, 1, 1 + i), "event": f"E{i}", "bout": "B",
                        "w": "Alpha Fighter", "l": f"Opp {i}",
                        "method": "Decision", "secs": 900.0})

    def snapshot():
        return {n: (s.elo, s.n, s.secs, s.sl, s.kd, tuple(s.results), s.last)
                for n, s in led.book.items()}

    before = snapshot()
    led.features_for("Alpha Fighter", date(2024, 7, 1))
    led.diff_vector("Alpha Fighter", "Opp 0", date(2024, 7, 1))
    led.known("Alpha Fighter")
    led.state("Alpha Fighter")
    assert snapshot() == before, "a read moved fighter state — features can see the future"


@needs_data
def test_trainer_emits_each_row_before_folding_the_bout_in():
    """The ordering lives in scripts/train_ufc.py, not in Ledger, so it needs its
    own check: a fighter's FIRST bout must carry no prior information."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "train_ufc", Path("scripts/train_ufc.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    X, Y, dates, minprior, _pairs = mod.build_matrix()
    assert len(Y) > 1000

    # The very first bout in history: both fighters unrated, so every difference
    # is either exactly zero (defaults cancel) or unknown. A non-zero Elo or
    # experience diff on row 0 means state was folded in before the row was cut.
    first = X[0]
    elo_i, exp_i = FEATURES.index("elo"), FEATURES.index("exp")
    assert first[elo_i] == 0.0, "row 0 already carries a rating difference"
    assert first[exp_i] == 0.0, "row 0 already carries an experience difference"
    assert (minprior[:1] == 0).all()

    # And leakage inflates scores: if the trainer could see results, held-out
    # accuracy would not sit near the market's.
    import numpy as np
    assert np.nanmax(np.abs(X[:, exp_i])) <= 25.0, "experience cap not applied"


@needs_data
def test_applying_a_bout_moves_state_forward_only_after_emission():
    """The ordering contract in one assertion: reading then writing must differ,
    and the read must reflect the PRE-bout world."""
    led = Ledger({}, {})
    b = {"date": date(2024, 6, 1), "event": "E", "bout": "B",
         "w": "Alpha Fighter", "l": "Beta Fighter",
         "method": "KO/TKO", "secs": 300.0}
    before = led.state("Alpha Fighter").elo
    assert not led.known("Alpha Fighter")
    led.apply_bout(b)
    assert led.known("Alpha Fighter")
    assert led.state("Alpha Fighter").elo > before, "winner's rating must rise"
    assert led.state("Beta Fighter").elo < before, "loser's rating must fall"


# ── the bug that made every fight a coin flip ────────────────────────────────
@needs_data
@needs_model
def test_a_clear_mismatch_is_not_reported_as_a_coin_flip():
    """THE regression test for the shipped defect.

    The old simulator gave every fighter phi=350 (the 'never seen this fighter'
    deviation) and injected it as ~5 sigma of logit noise, which pulled every
    prediction to 50-53%. Ten fights, one answer.

    A large, genuine skill gap must therefore produce a confident number. If
    someone reintroduces uniform maximal uncertainty, this fails.
    """
    model = UFCFightModel()
    led, _ = build_ledger()
    assert model.ok

    # Construct a lopsided matchup from the real book: highest-rated active
    # fighter against a heavily negative one, both with real history.
    rated = [(n, s) for n, s in led.book.items() if s.n >= 8]
    assert len(rated) > 50
    rated.sort(key=lambda kv: kv[1].elo)
    weak = rated[0][0]
    strong = rated[-1][0]

    r = model.predict(led, strong, weak, date(2026, 8, 1))
    assert r.basis == "model"
    assert r.confidence > 0.60, (
        f"a top-vs-bottom matchup priced at {r.confidence:.1%} — the model is "
        "not discriminating; check for uniform rating deviation")


@needs_data
@needs_model
def test_the_card_produces_a_spread_of_opinions_not_one_number():
    """The user-visible symptom was ten fights all reading 50-53%. Across a
    realistic set of matchups the model must actually vary."""
    model = UFCFightModel()
    led, _ = build_ledger()
    rated = [n for n, s in led.book.items() if s.n >= 6]
    assert len(rated) >= 40
    rated.sort()
    ps = [model.predict(led, rated[i], rated[-(i + 1)], date(2026, 8, 1)).p_a
          for i in range(20)]
    spread = max(ps) - min(ps)
    assert spread > 0.25, f"predictions span only {spread:.3f} — model is flat"


# ── honesty about what we cannot see ─────────────────────────────────────────
@needs_data
@needs_model
def test_a_fighter_with_no_ufc_record_is_never_priced_as_average():
    model = UFCFightModel()
    led, _ = build_ledger()
    known = next(n for n, s in led.book.items() if s.n >= 5)

    r = model.predict(led, "Definitely Not A Real Fighter", known, date(2026, 8, 1))
    assert r.basis == "debut_prior", "an unseen fighter must be flagged, not modelled"
    assert r.p_a == pytest.approx(DEBUT_WIN_RATE)
    assert "no UFC record" in r.note or "no UFC record" in " ".join(r.drivers)

    both = model.predict(led, "Nobody One", "Nobody Two", date(2026, 8, 1))
    assert both.basis == "no_data"
    assert both.p_a == 0.5
    assert "no read" in both.note.lower() or "cannot see" in both.note.lower()


@needs_data
@needs_model
def test_a_known_date_of_birth_is_used_even_with_no_fight_record():
    """The challenge that produced this: "are you sure we don't have data?"

    We did. A fighter with no UFC bouts still has a date of birth in the
    tale-of-the-tape file, and age is the strongest feature in the main model.
    Reporting a flat 43.4% for every such fighter threw that away. Measured over
    1,273 of these fights, using age plus the opponent's record beats the flat
    rate in six of seven holdout years (log-loss 0.6612 vs 0.6832, AUC 0.635).
    """
    model = UFCFightModel()
    if not model.debut_ok:
        pytest.skip("debut artifact not trained")
    led, _ = build_ledger()
    rated = next(n for n, s in led.book.items() if s.n >= 5)

    # Two synthetic unrated fighters, 15 years apart, same opponent.
    led.tott["young unrated"] = {"dob": date(2002, 1, 1), "reach": None,
                                 "height": None, "stance": ""}
    led.tott["old unrated"] = {"dob": date(1987, 1, 1), "reach": None,
                               "height": None, "stance": ""}
    young = model.predict(led, "young unrated", rated, date(2026, 8, 1))
    old = model.predict(led, "old unrated", rated, date(2026, 8, 1))

    assert young.basis == "debut_model" and old.basis == "debut_model"
    assert young.p_a != old.p_a, "age was ignored for a fighter with no UFC record"
    assert young.p_a > old.p_a, "the 39-year-old should not be favoured over the 24-year-old"


@needs_data
@needs_model
def test_without_a_date_of_birth_it_falls_back_to_the_flat_rate():
    """Graceful degradation, stated plainly rather than invented."""
    model = UFCFightModel()
    led, _ = build_ledger()
    rated = next(n for n, s in led.book.items() if s.n >= 5)
    r = model.predict(led, "totally unknown person", rated, date(2026, 8, 1))
    assert r.basis == "debut_prior"
    assert r.p_a == pytest.approx(DEBUT_WIN_RATE)
    assert "date of birth" in r.note


@needs_data
@needs_model
def test_two_unrated_fighters_still_get_no_read():
    """The other half of the same question, and the answer went the other way.
    Age alone across two unrated fighters scored AUC 0.490 — worse than chance —
    so this case must NOT be dressed up with a number."""
    model = UFCFightModel()
    led, _ = build_ledger()
    led.tott["nobody one"] = {"dob": date(2000, 1, 1), "reach": 72.0,
                              "height": 70.0, "stance": ""}
    led.tott["nobody two"] = {"dob": date(1990, 1, 1), "reach": 70.0,
                              "height": 68.0, "stance": ""}
    r = model.predict(led, "nobody one", "nobody two", date(2026, 8, 1))
    assert r.basis == "no_data", (
        "two unrated fighters must stay a no-read even when both have a DOB — "
        "that was measured and there is no signal there")
    assert r.p_a == 0.5


def test_debut_model_is_optional_and_absence_is_not_breakage(tmp_path):
    """An absent debut artifact means 'fall back to the base rate', not 'fail'.
    The trainer only writes it when it beats the flat rate, and deletes a stale
    one when it does not."""
    m = UFCFightModel(debut_artifact=tmp_path / "nothing.json")
    assert not m.debut_ok
    assert m.ok, "the main model must still load when the debut model is absent"


def test_missing_artifact_reports_no_data_rather_than_guessing(tmp_path):
    """A missing model must say so. 'Couldn't check' rendering as 'all clear' is
    the single most expensive bug class in this repo."""
    model = UFCFightModel(artifact=tmp_path / "nope.json")
    assert not model.ok
    r = model.predict(Ledger({}, {}), "A", "B", date(2026, 8, 1))
    assert r.basis == "no_data"
    assert "train_ufc" in r.note


# ── the artifact itself ──────────────────────────────────────────────────────
@needs_model
def test_artifact_records_honest_holdout_scores():
    blob = json.loads(Path("data/models/ufc/fight_model.json").read_text())
    meta = blob["metadata"]
    folds = meta["walk_forward"]
    assert len(folds) >= 3, "one good year is not evidence"
    assert meta["mean_holdout_log_loss"] < math.log(2), "no better than a coin flip"
    for f in folds:
        assert f["n"] >= 50
        assert 0.0 < f["accuracy"] < 1.0
    # Every shipped coefficient must be applied and every applied feature must
    # ship a coefficient. The artifact declares its own feature set
    # (feature_order): UFC-only, or +career columns when the trainer's gate
    # passed them (it did at 78.7% roster coverage, 2026-08-01). A runtime
    # that scores a different set than the artifact validated is a silently
    # different model — that is the drift this assertion exists to catch.
    order = blob.get("feature_order", FEATURES)
    assert set(blob["coefficients"]) == set(order)
    assert set(FEATURES) <= set(blob["coefficients"])
    m = UFCFightModel()
    assert m.ok
    assert set(m.order) == set(blob["coefficients"])


@needs_model
def test_age_matters_more_than_rating():
    """Not a style preference — a finding. Age carried the largest standardised
    weight in every holdout year of the UFC-only model. Since the career
    columns shipped (78.7% coverage retrain), gelo may absorb elo's signal —
    they measure the same thing on overlapping data — so the rating check is
    on the STRONGEST rating feature, not on elo alone. If a retrain flips a
    sign or rating collapses entirely, the feature build has probably broken
    and it should be looked at, not silently accepted."""
    coef = json.loads(Path("data/models/ufc/fight_model.json").read_text())["coefficients"]
    assert coef["age"] < 0, "older fighter should be less likely to win"
    assert coef["elo"] > 0, "higher-rated fighter should be more likely to win"
    if "gelo" in coef:
        assert coef["gelo"] > 0, "higher career-wide rating should help, not hurt"
    rating = max(abs(coef["elo"]), abs(coef.get("gelo", 0.0)))
    assert abs(coef["age"]) > 0.15 and rating > 0.15


@needs_model
def test_scorer_applies_every_artifact_coefficient(tmp_path):
    """The trainer's gate decides WHAT ships; this pins that the runtime
    scores WITH all of it. A scorer that iterates the hardcoded UFC-only list
    would silently ignore shipped career columns and run a model that was
    never validated — the exact drift the 78.7%-coverage retrain exposed."""
    blob = json.loads(Path("data/models/ufc/fight_model.json").read_text())
    # Synthetic artifact: UFC-only columns plus one career column whose weight
    # is so large it must dominate any base read — IF the scorer applies it.
    blob = {
        **blob,
        "feature_order": list(FEATURES) + ["gelo"],
        "coefficients": {**{k: blob["coefficients"].get(k, 0.0) for k in FEATURES},
                         "gelo": 50.0},
        "feature_mean": {**blob["feature_mean"], "gelo": 0.0},
        "feature_sd": {**blob["feature_sd"], "gelo": 1.0},
        "feature_median": {**blob["feature_median"], "gelo": 0.0},
    }
    p = tmp_path / "fight_model.json"
    p.write_text(json.dumps(blob))

    model = UFCFightModel(artifact=p)
    assert model.ok
    # Beta is vastly better by career rating; Alpha is better by UFC record.
    model._global_diffs = lambda ledger, a, b, on: {"gelo": -3.0}

    led = Ledger({}, {})
    for i in range(3):
        led.apply_bout({"date": date(2024, 1, 1 + i), "event": f"E{i}",
                        "bout": "B", "w": "Alpha Fighter", "l": "Beta Fighter",
                        "method": "Decision", "secs": 900.0})
    r = model.predict(led, "Alpha Fighter", "Beta Fighter", date(2026, 8, 1))
    assert r.basis == "model"
    assert r.p_a < 0.05, ("a -150-sigma career-rating edge must dominate; "
                          "the scorer ignored a shipped coefficient")


# ── the global fallback tier ─────────────────────────────────────────────────
def test_global_fallback_artifact_records_the_split_verdict():
    """Both halves of the experiment are recorded, because both are true:
    career features gated by the main model (refused below ~75% roster
    coverage, shipped at 78.7%), decisive on the refused population at every
    coverage level. The artifact must beat flat on its holdouts to exist."""
    import json
    from pathlib import Path
    p = Path("data/models/ufc/global_fallback.json")
    if not p.exists():
        pytest.skip("global fallback not trained")
    blob = json.loads(p.read_text())
    meta = blob["metadata"]
    assert meta["mean_model_log_loss"] < meta["mean_flat_log_loss"]
    assert len(meta["walk_forward"]) >= 3
    assert set(blob["coefficients"]) == {"gelo_diff", "top_share_diff",
                                         "pro_exp_diff"}


@needs_data
def test_global_tier_prices_two_ufc_unknowns_when_both_resolve(monkeypatch):
    """The Leka-vs-Poppeck case: no UFC record on either side, both known to
    the global graph — must produce a real probability, not 'no read'."""
    model = UFCFightModel()
    if not model.gf_ok:
        pytest.skip("global fallback not trained")
    led, _ = build_ledger()

    from src.models.global_elo import GlobalLedger
    gled = GlobalLedger()
    for i in range(12):
        gled.apply_bout({"date": date(2024, 1, 1 + i), "w": "Strong-One-1",
                         "l": f"Foe-{i}", "promotion": "Oktagon",
                         "method": "KO"})
        gled.apply_bout({"date": date(2024, 2, 1 + i), "w": f"Rival-{i}",
                         "l": "Weak-One-2", "promotion": "Oktagon",
                         "method": "Decision"})
    model._gled = gled
    model._slug_of = {}
    monkeypatch.setattr(
        "src.data.sherdog.resolve",
        lambda name, dob=None: SimpleNamespace(slug={"Strong Fighter": "Strong-One-1",
                                                     "Weak Fighter": "Weak-One-2"}[name]))
    r = model.predict(led, "Strong Fighter", "Weak Fighter", date(2026, 8, 1))
    assert r.basis == "global_record"
    assert r.p_a > 0.5, "a 12-0 career must be favoured over an 0-12 one"
    assert "professional record" in r.note


@needs_data
def test_global_tier_refuses_when_identity_does_not_resolve(monkeypatch):
    """Identity doubt falls through to the honest lower tiers, never a guess."""
    model = UFCFightModel()
    if not model.gf_ok:
        pytest.skip("global fallback not trained")
    led, _ = build_ledger()
    from src.models.global_elo import GlobalLedger
    model._gled = GlobalLedger()
    model._slug_of = {}
    monkeypatch.setattr("src.data.sherdog.resolve", lambda name, dob=None: None)
    r = model.predict(led, "Nobody One", "Nobody Two", date(2026, 8, 1))
    assert r.basis == "no_data", "unresolvable identity must stay a no-read"


@needs_data
def test_global_tier_never_outranks_the_main_model():
    """Where both fighters have UFC records the main model decides — career
    features were offered there and measurably did not help."""
    model = UFCFightModel()
    if not model.gf_ok or not model.ok:
        pytest.skip("artifacts not trained")
    led, _ = build_ledger()
    rated = sorted(n for n, s in led.book.items() if s.n >= 8)
    r = model.predict(led, rated[0], rated[1], date(2026, 8, 1))
    assert r.basis == "model"
