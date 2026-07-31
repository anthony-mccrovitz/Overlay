"""Refuse to report a held-out score that isn't held out.

WHY THIS EXISTS. `train_totals_model` defaulted its training set to
`ALL_SEASONS` (2008–2025) while testing on `TEST_SEASONS` ([2025]). The test
season was inside the training set, so every 2025 game was scored by a model
that had already seen its result. The reported numbers said so plainly —
test MAE 3.155 BELOW train MAE 3.267, and a headline O/U accuracy of 61.9%
against 52.2% from the same file's clean walk-forward CV — and nobody read them
that way for months, because a number labelled "test" is trusted on sight.

A correct `TRAIN_SEASONS` constant (2008–2024) already existed one file over.
The bug was a single wrong name, which is exactly why this needs a machine
check rather than care.

THE RULE. A split is honest when the training set and the test set share no
period, AND every training period precedes every test period. Ordering matters
independently of overlap: training on 2025 to predict 2019 leaks the future
through team quality, roster construction and rule changes even though the two
sets are disjoint.

This module raises rather than warns. A quiet warning next to a confident
number is how the original bug survived — the loudest thing in the output was
the wrong number.
"""
from __future__ import annotations

from collections.abc import Iterable


class LeakySplitError(AssertionError):
    """Raised when a train/test split cannot support a held-out claim."""


def check_split(train: Iterable, test: Iterable, *, label: str = "split",
                require_order: bool = True) -> None:
    """Validate a period-based train/test split. Raises LeakySplitError.

    `train` and `test` are period identifiers that sort meaningfully — seasons,
    years, dates. They are compared as sets and by order, never by index, so
    passing them in any order is safe.
    """
    tr, te = sorted(set(train)), sorted(set(test))

    if not tr:
        raise LeakySplitError(f"{label}: training set is empty — nothing was learned")
    if not te:
        raise LeakySplitError(
            f"{label}: test set is empty. An empty holdout scores nothing, and a "
            f"metric computed over it is not a measurement.")

    overlap = sorted(set(tr) & set(te))
    if overlap:
        raise LeakySplitError(
            f"{label}: {len(overlap)} period(s) appear in BOTH train and test "
            f"({overlap}). Every one of those rows was scored by a model that "
            f"had already seen its answer, so the resulting metric is in-sample "
            f"and must not be reported as held-out.")

    if require_order and max(tr) > min(te):
        raise LeakySplitError(
            f"{label}: training data runs to {max(tr)} but testing starts at "
            f"{min(te)}. Training on periods after the test period leaks the "
            f"future even though the sets are disjoint.")


def is_clean(train: Iterable, test: Iterable, *, require_order: bool = True) -> bool:
    """Boolean form, for reporting rather than enforcing."""
    try:
        check_split(train, test, require_order=require_order)
    except LeakySplitError:
        return False
    return True


def describe(train: Iterable, test: Iterable, *, require_order: bool = True) -> str:
    """One line fit for printing above a metric."""
    tr, te = sorted(set(train)), sorted(set(test))
    if not tr or not te:
        return "split is degenerate — no honest metric available"
    try:
        check_split(tr, te, require_order=require_order)
    except LeakySplitError as e:
        return f"LEAKY: {e}"
    return (f"held out: trained {min(tr)}–{max(tr)} ({len(tr)} periods), "
            f"tested {min(te)}–{max(te)} ({len(te)} periods), no overlap")
