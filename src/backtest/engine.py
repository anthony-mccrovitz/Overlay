"""
Walk-forward backtesting engine.

Tests the model against every tournament from 2010-2025 (excluding 2020).
For each year: train on all prior years, predict that year's tournament,
measure performance.

Key metrics:
- Log loss (lower = better calibrated probabilities)
- Accuracy (% of games predicted correctly)
- ATS record (if historical odds available)
- Bracket pool percentile simulation
"""
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, accuracy_score

from src.data.store import build_training_data
from src.models.xgboost_model import XGBoostModel


def run_backtest(
    min_train_year: int = 2003,
    min_test_year: int = 2010,
    max_test_year: int = 2025,
    use_barttorvik: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Walk-forward backtest across multiple tournament years.

    For each test year:
    1. Train on all tournaments before that year
    2. Predict that year's tournament matchups
    3. Record accuracy, log loss, upset detection rate

    Returns DataFrame with per-year metrics.
    """
    results = []
    test_years = [y for y in range(min_test_year, max_test_year + 1) if y != 2020]

    for test_year in test_years:
        try:
            # Train on all prior years
            X_train, y_train = build_training_data(
                min_year=min_train_year,
                max_year=test_year - 1,
                use_barttorvik=use_barttorvik,
            )

            if len(X_train) < 50:
                if verbose:
                    print(f"  {test_year}: Skipping — insufficient training data ({len(X_train)} samples)")
                continue

            # Test on this year's tournament
            X_test, y_test = build_training_data(
                min_year=test_year,
                max_year=test_year,
                use_barttorvik=use_barttorvik,
            )

            if len(X_test) == 0:
                if verbose:
                    print(f"  {test_year}: Skipping — no test data")
                continue

            # Train and evaluate
            model = XGBoostModel()
            model.train(X_train, y_train)
            probs = model.predict_proba(X_test)
            preds = (probs >= 0.5).astype(int)

            # Upset detection: how many upsets did we correctly predict?
            # Upset = lower seed (higher number) wins → y_test == 0
            upsets_mask = y_test == 0
            n_upsets = upsets_mask.sum()
            if n_upsets > 0:
                upset_detection_rate = (preds[upsets_mask] == 0).mean()
            else:
                upset_detection_rate = 0.0

            result = {
                "Year": test_year,
                "Accuracy": accuracy_score(y_test, preds),
                "LogLoss": log_loss(y_test, probs),
                "Games": len(y_test),
                "TrainSize": len(X_train),
                "Upsets": int(n_upsets),
                "UpsetDetectionRate": upset_detection_rate,
                "ChalkRate": y_test.mean(),  # How often did the higher seed win?
            }
            results.append(result)

            if verbose:
                print(
                    f"  {test_year}: {result['Accuracy']:.1%} acc | "
                    f"{result['LogLoss']:.4f} log loss | "
                    f"{result['Upsets']} upsets ({result['UpsetDetectionRate']:.0%} detected) | "
                    f"{result['Games']} games"
                )

        except Exception as e:
            if verbose:
                print(f"  {test_year}: FAILED — {e}")

    return pd.DataFrame(results)


def print_backtest_summary(results: pd.DataFrame) -> str:
    """Pretty-print backtest results."""
    if results.empty:
        return "  No backtest results.\n"

    lines = []
    lines.append(f"\n{'='*70}")
    lines.append("  BACKTEST RESULTS — Walk-Forward Validation")
    lines.append(f"{'='*70}")

    lines.append(
        f"\n  {'Year':>6} {'Acc':>7} {'LogLoss':>9} {'Games':>6} "
        f"{'Upsets':>7} {'Detected':>9}"
    )
    lines.append(f"  {'-'*55}")

    for _, r in results.iterrows():
        lines.append(
            f"  {r['Year']:>6.0f} {r['Accuracy']:>6.1%} "
            f"{r['LogLoss']:>9.4f} {r['Games']:>6.0f} "
            f"{r['Upsets']:>7.0f} {r['UpsetDetectionRate']:>8.0%}"
        )

    lines.append(f"\n  {'='*55}")
    lines.append(f"  SUMMARY")
    lines.append(f"  {'='*55}")
    lines.append(f"  Years tested:     {len(results)}")
    lines.append(f"  Total games:      {results['Games'].sum():.0f}")
    lines.append(f"  Avg accuracy:     {results['Accuracy'].mean():.1%}")
    lines.append(f"  Avg log loss:     {results['LogLoss'].mean():.4f}")
    lines.append(f"  Avg upset detect: {results['UpsetDetectionRate'].mean():.0%}")
    lines.append(
        f"  Best year:        {results.loc[results['Accuracy'].idxmax(), 'Year']:.0f} "
        f"({results['Accuracy'].max():.1%})"
    )
    lines.append(
        f"  Worst year:       {results.loc[results['Accuracy'].idxmin(), 'Year']:.0f} "
        f"({results['Accuracy'].min():.1%})"
    )

    # Beat chalk baseline?
    chalk_acc = results["ChalkRate"].mean()
    model_acc = results["Accuracy"].mean()
    if model_acc > chalk_acc:
        lines.append(f"\n  Model beats chalk baseline: {model_acc:.1%} vs {chalk_acc:.1%} (+{(model_acc-chalk_acc)*100:.1f}pp)")
    else:
        lines.append(f"\n  WARNING: Model underperforms chalk: {model_acc:.1%} vs {chalk_acc:.1%}")

    lines.append(f"{'='*70}\n")
    return "\n".join(lines)
