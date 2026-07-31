"""The train/test split guard, and the specific leak it was written for."""
from __future__ import annotations

import pytest

from src.analytics.backtest_guard import (
    LeakySplitError,
    check_split,
    describe,
    is_clean,
)


# ── the rule ─────────────────────────────────────────────────────────────────
def test_a_disjoint_ordered_split_passes():
    check_split([2020, 2021, 2022], [2023])
    assert is_clean([2020, 2021, 2022], [2023])


def test_overlap_is_rejected():
    with pytest.raises(LeakySplitError, match="BOTH train and test"):
        check_split([2020, 2021, 2022, 2023], [2023])


def test_full_containment_is_rejected():
    """The exact shape of the shipped bug: test set entirely inside train."""
    with pytest.raises(LeakySplitError):
        check_split(list(range(2008, 2026)), [2025])


def test_training_after_the_test_period_is_rejected():
    """Disjoint is not sufficient. Training on 2025 to predict 2019 leaks the
    future through roster construction and rule changes."""
    with pytest.raises(LeakySplitError, match="leaks the future"):
        check_split([2024, 2025], [2019])


def test_order_check_can_be_waived_explicitly():
    assert is_clean([2024, 2025], [2019], require_order=False)


def test_an_empty_holdout_is_rejected():
    """A metric over zero rows is not a measurement. Silently reporting one is
    'couldn't check' rendering as 'all clear'."""
    with pytest.raises(LeakySplitError, match="test set is empty"):
        check_split([2020, 2021], [])


def test_an_empty_training_set_is_rejected():
    with pytest.raises(LeakySplitError, match="training set is empty"):
        check_split([], [2025])


def test_unsorted_input_is_handled():
    check_split([2022, 2020, 2021], [2024, 2023])


def test_duplicates_do_not_create_false_overlap():
    check_split([2020, 2020, 2021], [2022, 2022])


# ── describe() is what gets printed next to a metric ─────────────────────────
def test_describe_names_the_periods_on_a_clean_split():
    d = describe([2020, 2021, 2022], [2023])
    assert "held out" in d and "2020" in d and "2023" in d


def test_describe_leads_with_LEAKY_when_it_is():
    d = describe([2020, 2021, 2022, 2023], [2023])
    assert d.startswith("LEAKY:")


# ── the regression this was written for ──────────────────────────────────────
def test_mlb_totals_defaults_are_not_leaky():
    """The live lane. Its trainer defaulted to ALL_SEASONS (which contains the
    test season) instead of the TRAIN_SEASONS constant sitting next to it, and
    reported the resulting in-sample score as held-out for months."""
    from src.models.mlb_xgboost import ALL_SEASONS, TEST_SEASONS, TRAIN_SEASONS

    assert is_clean(TRAIN_SEASONS, TEST_SEASONS), \
        "TRAIN_SEASONS/TEST_SEASONS must be a clean split"
    assert not is_clean(ALL_SEASONS, TEST_SEASONS), \
        "ALL_SEASONS still contains the test season — the trap is still live, " \
        "so the guard below must stay"


def test_mlb_totals_trainer_refuses_a_leaky_split():
    """Calling the trainer with the old leaky defaults must now raise rather
    than quietly produce an optimistic number."""
    from src.models.mlb_totals import train_totals_model
    from src.models.mlb_xgboost import ALL_SEASONS, TEST_SEASONS

    with pytest.raises(LeakySplitError):
        train_totals_model(train_seasons=ALL_SEASONS,
                           test_seasons=TEST_SEASONS, verbose=False)


def test_mlb_totals_trainer_binds_the_clean_default():
    """Guards the actual defect: the default must be TRAIN_SEASONS.

    Checked by reading the bound default rather than by training, so this stays
    a fast unit test and needs no season data on disk.
    """
    import inspect

    from src.models.mlb_totals import train_totals_model
    from src.models.mlb_xgboost import TEST_SEASONS, TRAIN_SEASONS

    # Strip comments before matching. The first version of this test failed on
    # the comment explaining the bug, which names ALL_SEASONS — a test that
    # reads prose instead of code is testing the wrong thing.
    code = "\n".join(ln.split("#", 1)[0]
                     for ln in inspect.getsource(train_totals_model).splitlines())

    assert "train_seasons = TRAIN_SEASONS" in code, \
        "the trainer no longer defaults to the clean training seasons"
    assert "ALL_SEASONS" not in code, \
        "ALL_SEASONS contains the test season and must not be used here"
    assert "check_split" in code, "the split guard was removed from the trainer"
    assert is_clean(TRAIN_SEASONS, TEST_SEASONS)
