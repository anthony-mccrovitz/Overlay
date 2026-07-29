"""Tests for the degenerate-calibrator guard.

The guard exists because a collapsed calibrator is worse than none: it maps every
game on the slate to one constant, and the board still looks normal. But it was
rejecting GOOD calibrators too, and that failure is subtler than the one it was
built to catch.

It probed fixed points — f(0.65) - f(0.35) — on the stated assumption that "model
probs live almost entirely in [0.35, 0.65]". True for moneyline models; false for
totals models. mlb/f5_total emits in [0.51, 0.99] with exactly one pick below
0.51, so f(0.35) was flat extrapolation below the data. Its healthy isotonic fit
(spread 0.335 across the range it actually operates in) was rejected for a
"mid-band collapse" of 0.009 measured where the model never operates — and the
lane then ran uncalibrated for months, claiming 17.4pp of edge and delivering 1.4.
"""
import pytest

from src.analytics import calibration as cal


class _Curve:
    """Minimal stand-in for a fitted isotonic model."""

    def __init__(self, fn):
        self._fn = fn

    def predict(self, xs):
        return [self._fn(float(x)) for x in xs]


def _piecewise(lo_val, hi_val, knee):
    """Flat below the knee, rising above it — the shape isotonic produces for a
    model that only ever emits high probabilities."""
    def f(x):
        if x <= knee:
            return lo_val
        return lo_val + (hi_val - lo_val) * min(1.0, (x - knee) / (1.0 - knee))
    return f


class TestSupportAwareSpread:
    def test_one_sided_model_with_real_signal_is_accepted(self):
        """The f5_total case: all output above ~0.51, healthy spread up there."""
        curve = _Curve(_piecewise(0.47, 0.80, knee=0.55))
        X = [0.52 + 0.004 * i for i in range(120)]      # support ≈ [0.52, 0.99]
        ok, why = cal.validate_calibrator("isotonic", curve, X)
        assert ok, f"rejected a healthy one-sided calibrator: {why}"
        assert "support" in why

    def test_same_calibrator_is_rejected_without_training_data(self):
        """Documents exactly what the old behaviour was: with no X, the fixed
        grid probes below the model's support and sees a false collapse."""
        curve = _Curve(_piecewise(0.47, 0.80, knee=0.55))
        ok, why = cal.validate_calibrator("isotonic", curve)
        assert not ok
        assert "mid-band collapse" in why

    def test_genuinely_flat_calibrator_is_still_rejected(self):
        """The quarantined mlb_total mapped every game to 0.5833. Passing X must
        NOT turn the guard off — that would trade one silent failure for another."""
        curve = _Curve(lambda x: 0.5833)
        X = [0.40 + 0.004 * i for i in range(120)]
        ok, why = cal.validate_calibrator("isotonic", curve, X)
        assert not ok
        assert "collapse across model support" in why

    def test_near_flat_over_support_is_rejected(self):
        curve = _Curve(_piecewise(0.50, 0.54, knee=0.55))
        X = [0.52 + 0.004 * i for i in range(120)]
        ok, why = cal.validate_calibrator("isotonic", curve, X)
        assert not ok

    def test_degenerate_model_support_is_named_as_a_model_defect(self):
        """If the model itself emits a nearly constant probability, no calibrator
        can help — say so, rather than blaming the calibrator."""
        curve = _Curve(_piecewise(0.40, 0.90, knee=0.55))
        X = [0.580 + 0.0001 * i for i in range(120)]    # support width ≈ 0.012
        ok, why = cal.validate_calibrator("isotonic", curve, X)
        assert not ok
        assert "model support is degenerate" in why

    def test_outlier_cannot_stretch_the_band_to_hide_a_collapse(self):
        """Band is measured at the 10th/90th percentile, so a single stray pick
        at 0.05 can't widen the window and smuggle a flat curve through."""
        curve = _Curve(_piecewise(0.50, 0.90, knee=0.90))
        X = [0.05] + [0.60 + 0.0005 * i for i in range(200)]
        ok, why = cal.validate_calibrator("isotonic", curve, X)
        assert not ok


class TestInvariantsPreserved:
    def test_non_monotone_still_rejected_with_training_data(self):
        """Higher raw prob must never map to a lower calibrated prob. This check
        runs before any spread logic and is unaffected by support."""
        curve = _Curve(lambda x: 1.0 - x)
        X = [0.40 + 0.004 * i for i in range(120)]
        ok, why = cal.validate_calibrator("isotonic", curve, X)
        assert not ok
        assert "non-monotone" in why

    def test_broken_model_object_fails_closed(self):
        class Exploding:
            def predict(self, xs):
                raise RuntimeError("unpicklable")

        ok, why = cal.validate_calibrator("isotonic", Exploding(), [0.5, 0.6])
        assert not ok
        assert "probe failed" in why

    def test_legacy_callers_without_X_keep_working(self):
        curve = _Curve(lambda x: 0.1 + 0.8 * x)
        ok, _ = cal.validate_calibrator("isotonic", curve)
        assert ok


class TestSupportBand:
    def test_band_uses_documented_quantiles(self):
        X = list([i / 100 for i in range(101)])
        lo, hi = cal._support_band(X)
        assert lo == pytest.approx(0.10, abs=0.02)
        assert hi == pytest.approx(0.90, abs=0.02)

    def test_band_handles_tiny_sample(self):
        lo, hi = cal._support_band([0.6, 0.7])
        assert lo <= hi
