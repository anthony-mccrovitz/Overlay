#!/bin/bash
# EdgeFinder automated schedule
#
# Times are Eastern (ET). If your machine is UTC, adjust hour fields:
#   10am ET = 14:00 UTC (during EDT, UTC-4)
#
# Usage:
#   chmod +x scripts/setup_cron.sh
#   ./scripts/setup_cron.sh
#
# Remove all EdgeFinder cron lines:
#   crontab -l | grep -v 'march-madness' | crontab -

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR" "$PROJECT_DIR/data/ops" "$PROJECT_DIR/data/odds_history"

# ── Daily picks (night before for best CLV) ───────────────────────────────────
# 9:30 PM — generate tomorrow's picks, snapshot opening lines
PICKS="30 21 * * * cd $PROJECT_DIR && $PYTHON predict.py --sport mlb --daily --tomorrow >> $LOG_DIR/picks.log 2>&1"

# ── Closing line snapshot (30 min before first pitch) ─────────────────────────
# 3:30 PM — pre-game closing snapshot (before ~4pm first pitches)
CLOSE_1="30 15 * * * cd $PROJECT_DIR && $PYTHON predict.py --sport mlb --close >> $LOG_DIR/close.log 2>&1"

# ── Odds history — line movement tracker (every 2 hours, 10am–10pm) ──────────
# These build the full line-movement curve for model validation
SNAP_10="0 10 * * * cd $PROJECT_DIR && $PYTHON scripts/odds_snapshot.py >> $LOG_DIR/odds_snapshot.log 2>&1"
SNAP_12="0 12 * * * cd $PROJECT_DIR && $PYTHON scripts/odds_snapshot.py >> $LOG_DIR/odds_snapshot.log 2>&1"
SNAP_14="0 14 * * * cd $PROJECT_DIR && $PYTHON scripts/odds_snapshot.py >> $LOG_DIR/odds_snapshot.log 2>&1"
SNAP_16="0 16 * * * cd $PROJECT_DIR && $PYTHON scripts/odds_snapshot.py >> $LOG_DIR/odds_snapshot.log 2>&1"
SNAP_18="0 18 * * * cd $PROJECT_DIR && $PYTHON scripts/odds_snapshot.py >> $LOG_DIR/odds_snapshot.log 2>&1"
SNAP_20="0 20 * * * cd $PROJECT_DIR && $PYTHON scripts/odds_snapshot.py >> $LOG_DIR/odds_snapshot.log 2>&1"
SNAP_22="0 22 * * * cd $PROJECT_DIR && $PYTHON scripts/odds_snapshot.py >> $LOG_DIR/odds_snapshot.log 2>&1"

# ── Grading (after games finish) ──────────────────────────────────────────────
# 1:00 AM — grade yesterday's picks (west coast games done by ~1am ET)
GRADE="0 1 * * * cd $PROJECT_DIR && $PYTHON predict.py --sport mlb --grade >> $LOG_DIR/grade.log 2>&1"

echo "Installing EdgeFinder cron jobs..."
echo "  Project: $PROJECT_DIR"
echo "  Python:  $PYTHON"
echo ""

(crontab -l 2>/dev/null | grep -v 'march-madness'; \
 echo "$PICKS"; \
 echo "$CLOSE_1"; \
 echo "$SNAP_10"; echo "$SNAP_12"; echo "$SNAP_14"; \
 echo "$SNAP_16"; echo "$SNAP_18"; echo "$SNAP_20"; echo "$SNAP_22"; \
 echo "$GRADE") | crontab -

echo "Cron jobs installed:"
echo ""
crontab -l | grep 'march-madness'
echo ""
echo "Logs:"
echo "  Picks:        $LOG_DIR/picks.log"
echo "  Close:        $LOG_DIR/close.log"
echo "  Odds history: $LOG_DIR/odds_snapshot.log"
echo "  Grade:        $LOG_DIR/grade.log"
echo ""
echo "View line movement:"
echo "  python scripts/odds_snapshot.py --show-movement"
