#!/bin/bash
# ChefTonyBets — automated daily pipeline
#
# Schedule (all times Eastern):
#   9:00 AM  — fetch odds + generate picks + snapshot opening lines
#   9:05 AM  — generate social captions (copy-paste ready)
#   6:45 PM  — closing line snapshot for CLV (before first evening game)
#  11:45 PM  — grade results + update public stats + write web mirror
#
# HOW TO INSTALL:
#   chmod +x scripts/setup_cron.sh
#   ./scripts/setup_cron.sh
#
# HOW TO REMOVE:
#   crontab -l | grep -v 'march-madness' | crontab -
#
# HOW TO VIEW LOGS:
#   tail -f logs/picks.log
#   tail -f logs/close.log
#   tail -f logs/grade.log
#
# NOTE: cron runs in UTC. During EDT (Mar-Nov) UTC-4:
#   9:00 AM ET  = 13:00 UTC
#   6:45 PM ET  = 22:45 UTC
#  11:45 PM ET  = 03:45 UTC (next day)

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── 9:00 AM ET (13:00 UTC) — MLB morning picks run ───────────────────────────
PICKS_MLB="0 13 * * * cd $PROJECT_DIR && $PYTHON chef.py picks mlb >> $LOG_DIR/picks.log 2>&1"

# ── 9:10 AM ET (13:10 UTC) — NBA morning picks run ───────────────────────────
PICKS_NBA="10 13 * * * cd $PROJECT_DIR && $PYTHON chef.py picks nba >> $LOG_DIR/picks.log 2>&1"

# ── 9:05 AM ET (13:05 UTC) — generate captions ───────────────────────────────
# Prints X + IG copy-paste captions to captions.log — check it, copy, post
CAPTION="5 13 * * * cd $PROJECT_DIR && $PYTHON scripts/gen_caption.py >> $LOG_DIR/captions.log 2>&1"

# ── Every 2 min — per-game closing-line capture ──────────────────────────────
# Captures any event starting in the next 2.5-7.5 min window, regardless of
# whether we have a pick on it. Builds the closing-line archive needed for
# CLV. See scripts/capture_closing.py.
CAPTURE_CLOSING="*/2 * * * * cd $PROJECT_DIR && $PYTHON scripts/capture_closing.py --sport all --window 5 >> $LOG_DIR/capture_closing.log 2>&1"

# ── Every 15 min from 4 PM to 3 AM ET — post-game grader ─────────────────────
# Grades any completed game throughout the night. Idempotent — already-graded
# picks are skipped. See scripts/grade_completed.py.
GRADE_LIVE="*/15 20-23,0-7 * * * cd $PROJECT_DIR && $PYTHON scripts/grade_completed.py >> $LOG_DIR/grade_completed.log 2>&1"

# ── 11:45 PM ET (03:45 UTC next day) — final pass: grade + refresh stats ─────
# Catches anything the live grader missed and refreshes public_stats.json.
GRADE="45 3 * * * cd $PROJECT_DIR && $PYTHON chef.py grade >> $LOG_DIR/grade.log 2>&1"

# ── 4:00 AM ET (08:00 UTC) — backfill CLV from captured closing snapshots ────
# Joins yesterday's settled card picks against data/clv/closing/ and writes
# CLV records. Idempotent — only fills gaps. See scripts/backfill_clv.py.
BACKFILL_CLV="0 8 * * * cd $PROJECT_DIR && $PYTHON scripts/backfill_clv.py >> $LOG_DIR/backfill_clv.log 2>&1"

echo "Installing ChefTonyBets cron jobs..."
echo "  Project: $PROJECT_DIR"
echo "  Python:  $PYTHON"
echo ""

(crontab -l 2>/dev/null | grep -v 'march-madness'; \
 echo "# ChefTonyBets daily pipeline"; \
 echo "$PICKS_MLB"; \
 echo "$PICKS_NBA"; \
 echo "$CAPTION"; \
 echo "$CAPTURE_CLOSING"; \
 echo "$GRADE_LIVE"; \
 echo "$GRADE"; \
 echo "$BACKFILL_CLV") | crontab -

echo "Installed:"
echo ""
crontab -l | grep -A1 'ChefTonyBets\|march-madness'
echo ""
echo "Logs directory: $LOG_DIR"
echo ""
echo "To see today's captions:"
echo "  cat $LOG_DIR/captions.log"
echo ""
echo "To manually generate captions now:"
echo "  python scripts/gen_caption.py"
echo ""
echo "To run the full pipeline right now:"
echo "  python predict.py --sport mlb --daily && python scripts/gen_caption.py"
