# TODOS

## Completed

### KenPom Integration (was: Barttorvik Historical Backfill)
**Status:** DONE — KenPom dataset (2002-2026) integrated via `src/data/kenpom.py`, replacing the need for Barttorvik scraping. Historical backtesting now uses KenPom advanced stats.

## Future Improvements

### Add Unit Tests
**What:** Add tests for team name normalization, feature engineering, and model training pipeline.
**Why:** No tests exist yet. The team name matching is the most fragile part — a missing alias silently drops a team from predictions.
**Effort:** S
**Priority:** P2

### Kaggle Submission Automation
**What:** Add `--kaggle` flag to `predict.py` that generates and optionally submits the Kaggle Stage 2 CSV.
**Why:** Currently requires a separate script run. Would be cleaner as part of the main CLI.
**Effort:** S
**Priority:** P3
