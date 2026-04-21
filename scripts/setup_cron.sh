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

# ── 6:45 PM ET (22:45 UTC) — closing line snapshot ───────────────────────────
CLOSE="45 22 * * * cd $PROJECT_DIR && $PYTHON predict.py --sport mlb --close >> $LOG_DIR/close.log 2>&1"

# ── 11:45 PM ET (03:45 UTC next day) — grade + publish stats ─────────────────
# West coast games finish by ~11:30 PM ET. Grade both sports.
GRADE="45 3 * * * cd $PROJECT_DIR && $PYTHON chef.py grade >> $LOG_DIR/grade.log 2>&1"

echo "Installing ChefTonyBets cron jobs..."
echo "  Project: $PROJECT_DIR"
echo "  Python:  $PYTHON"
echo ""

(crontab -l 2>/dev/null | grep -v 'march-madness'; \
 echo "# ChefTonyBets daily pipeline"; \
 echo "$PICKS_MLB"; \
 echo "$PICKS_NBA"; \
 echo "$CAPTION"; \
 echo "$CLOSE"; \
 echo "$GRADE") | crontab -

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
