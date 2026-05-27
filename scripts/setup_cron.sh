#!/bin/bash
# ChefTonyBets — timing-aware automated daily pipeline
#
# RESEARCH-BACKED SCHEDULE (all times Eastern / EDT = UTC-4):
#
#  NIGHT BEFORE (capture opening lines):
#   9:30 PM  — MLB picks + open line snapshot    (lines open ~9-10 PM)
#   9:35 PM  — NBA picks + open line snapshot    (lines open night before)
#   9:40 PM  — NHL picks + open line snapshot    (lines open night before)
#   9:45 PM  — WNBA picks + open line snapshot   (lines open night before)
#
#  MORNING (morning-of sports + captions):
#   7:30 AM  — Tennis picks  (lines open morning of; bet right at open)
#   8:00 AM  — Soccer picks  (morning of is fine for daily leagues)
#   8:00 AM  — PGA picks     (Monday only — lines drop Sunday night)
#   9:00 AM  — NASCAR picks  (Monday only — race week lines open)
#   9:05 AM  — UFC picks     (Tuesday only — card lines post ~5 days out)
#   9:10 AM  — Captions generated from overnight picks
#
#  GATE CHECKS (triggers before placing bets):
#   5:00 PM  — Gates check: NBA inactives + NHL goalies + MLB lineups
#   6:00 PM  — Gates check: refresh (catches late roster decisions)
#   7:00 PM  — Gates check: final pre-game sweep
#
#  NIGHT (grading):
#  Every 15min 4PM-3AM — live grader (grades completed games)
#  11:45 PM  — Final grade pass + stats refresh
#   4:00 AM  — CLV backfill from closing snapshots
#
# HOW TO INSTALL:
#   chmod +x scripts/setup_cron.sh && ./scripts/setup_cron.sh
#
# HOW TO REMOVE:
#   crontab -l | grep -v 'march-madness' | crontab -
#
# HOW TO VIEW LOGS:
#   tail -f logs/night.log      # overnight picks pipeline
#   tail -f logs/picks.log      # morning picks
#   tail -f logs/gates.log      # trigger checks
#   tail -f logs/grade.log      # grading
#
# NOTE: cron runs in UTC. During EDT (Mar-Nov) UTC-4:
#   7:30 AM ET  = 11:30 UTC
#   8:00 AM ET  = 12:00 UTC
#   9:00 AM ET  = 13:00 UTC
#   9:30 PM ET  = 01:30 UTC (next day)
#   9:40 PM ET  = 01:40 UTC (next day)
#  11:45 PM ET  = 03:45 UTC (next day)

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# ══════════════════════════════════════════════════════════════════
# NIGHT BEFORE — capture opening lines (9:30–9:50 PM ET = 01:30–01:50 UTC)
# ══════════════════════════════════════════════════════════════════

# ── 9:30 PM ET (01:30 UTC) — MLB night picks + open line snapshot ────────────
# MLB lines open ~9-10 PM ET. Bet ML/spread at open. Totals: wait for T-60min lineup.
NIGHT_MLB="30 1 * * * cd $PROJECT_DIR && $PYTHON chef.py night --sport mlb >> $LOG_DIR/night.log 2>&1"

# ── 9:35 PM ET (01:35 UTC) — NBA night picks + open line snapshot ────────────
# NBA lines open night before. HOLD all picks until inactives posted (~T-90min).
NIGHT_NBA="35 1 * * * cd $PROJECT_DIR && $PYTHON chef.py night --sport nba >> $LOG_DIR/night.log 2>&1"

# ── 9:40 PM ET (01:40 UTC) — NHL night picks + open line snapshot ────────────
# NHL lines open night before. ML: bet at open. Totals: wait for goalie confirm.
NIGHT_NHL="40 1 * * * cd $PROJECT_DIR && $PYTHON chef.py night --sport nhl >> $LOG_DIR/night.log 2>&1"

# ── 9:45 PM ET (01:45 UTC) — WNBA night picks + open line snapshot ───────────
# Same as NBA: hold until inactives confirmed (~T-90min before tip).
NIGHT_WNBA="45 1 * * * cd $PROJECT_DIR && $PYTHON chef.py night --sport wnba >> $LOG_DIR/night.log 2>&1"

# ══════════════════════════════════════════════════════════════════
# MORNING — morning-of sports
# ══════════════════════════════════════════════════════════════════

# ── 7:30 AM ET (11:30 UTC) — Tennis picks ────────────────────────────────────
# Tennis lines open morning of. Bet right at open (soft early, limits low).
PICKS_TENNIS="30 11 * * * cd $PROJECT_DIR && $PYTHON run_tennis.py >> $LOG_DIR/picks.log 2>&1"

# ── 8:00 AM ET (12:00 UTC) — Soccer picks ────────────────────────────────────
# Morning of is fine. Lineup news drops ~60min before kickoff.
PICKS_SOCCER="0 12 * * * cd $PROJECT_DIR && $PYTHON run_soccer.py >> $LOG_DIR/picks.log 2>&1"

# ── 8:00 AM ET (12:00 UTC) — PGA picks (Monday only) ────────────────────────
# Lines drop Sunday night. Monday AM is the prime sharp window.
# Run Mon only (1 = Monday in cron). Skips if no active tournament.
PICKS_PGA="0 12 * * 1 cd $PROJECT_DIR && $PYTHON run_pga.py >> $LOG_DIR/picks.log 2>&1"

# ── 9:00 AM ET (13:00 UTC) — NASCAR picks (Monday race week) ─────────────────
# Race-week lines open Sunday/Monday. Bet early, qualifying moves lines by Fri.
PICKS_NASCAR="0 13 * * 1 cd $PROJECT_DIR && $PYTHON run_nascar.py >> $LOG_DIR/picks.log 2>&1"

# ── 9:05 AM ET (13:05 UTC) — UFC picks (Tuesday of fight week) ───────────────
# Card lines post ~5-6 days out. Bet immediately. Watch Thu weigh-ins.
# Runs every Tuesday — script skips if no card posted within 7 days.
PICKS_UFC="5 13 * * 2 cd $PROJECT_DIR && $PYTHON run_ufc.py >> $LOG_DIR/picks.log 2>&1"

# ── 9:10 AM ET (13:10 UTC) — generate captions from overnight picks ──────────
CAPTION="10 13 * * * cd $PROJECT_DIR && $PYTHON scripts/gen_caption.py >> $LOG_DIR/captions.log 2>&1"

# ── 9:15 AM ET (13:15 UTC) — deploy morning picks to Vercel ─────────────────
# Pushes all overnight + morning picks to GitHub → triggers Vercel redeploy
# Subscribers will see today's picks live within ~60s of this firing.
DEPLOY_MORNING="15 13 * * * cd $PROJECT_DIR && $PYTHON scripts/deploy_picks.py >> $LOG_DIR/deploy.log 2>&1"

# ── 9:36 PM ET (01:36 UTC) — deploy MLB night picks to Vercel immediately ────
# Pushes right after MLB night pipeline so subs see opening lines asap
DEPLOY_NIGHT_MLB="36 1 * * * cd $PROJECT_DIR && $PYTHON scripts/deploy_picks.py --sport mlb >> $LOG_DIR/deploy.log 2>&1"

# ── 9:46 PM ET (01:46 UTC) — deploy NBA/NHL/WNBA night picks ─────────────────
DEPLOY_NIGHT_NBA="46 1 * * * cd $PROJECT_DIR && $PYTHON scripts/deploy_picks.py --sport nba >> $LOG_DIR/deploy.log 2>&1"

# ══════════════════════════════════════════════════════════════════
# GATE CHECKS — run before placing bets (5–7 PM ET)
# Checks: NBA/WNBA inactives, NHL goalies, MLB lineups
# Prints BET NOW or HOLD for each pending pick
# ══════════════════════════════════════════════════════════════════

# ── 5:00 PM ET (21:00 UTC) — first gate sweep ────────────────────────────────
GATES_1="0 21 * * * cd $PROJECT_DIR && $PYTHON chef.py gates >> $LOG_DIR/gates.log 2>&1"

# ── 6:00 PM ET (22:00 UTC) — second gate sweep ───────────────────────────────
GATES_2="0 22 * * * cd $PROJECT_DIR && $PYTHON chef.py gates >> $LOG_DIR/gates.log 2>&1"

# ── 7:00 PM ET (23:00 UTC) — final pre-game gate sweep ───────────────────────
GATES_3="0 23 * * * cd $PROJECT_DIR && $PYTHON chef.py gates >> $LOG_DIR/gates.log 2>&1"

# ══════════════════════════════════════════════════════════════════
# CLOSING LINE CAPTURE (for CLV tracking)
# ══════════════════════════════════════════════════════════════════

# ── Every 2 min — per-game closing-line capture ──────────────────────────────
CAPTURE_CLOSING="*/2 * * * * cd $PROJECT_DIR && $PYTHON scripts/capture_closing.py --sport all --window 5 >> $LOG_DIR/capture_closing.log 2>&1"

# ══════════════════════════════════════════════════════════════════
# GRADING
# ══════════════════════════════════════════════════════════════════

# ── Every 15 min from 4 PM to 3 AM ET — live grader ─────────────────────────
GRADE_LIVE="*/15 20-23,0-7 * * * cd $PROJECT_DIR && $PYTHON scripts/grade_completed.py >> $LOG_DIR/grade_completed.log 2>&1"

# ── 11:45 PM ET (03:45 UTC next day) — final grade + stats refresh ───────────
GRADE="45 3 * * * cd $PROJECT_DIR && $PYTHON chef.py grade >> $LOG_DIR/grade.log 2>&1"

# ── 11:50 PM ET (03:50 UTC) — nightly recap card + deploy ────────────────────
# Generates the nightly recap card (all sports, POTD hero, W-L, P/L)
# Then pushes grades + recap to Vercel so subs see final results.
NIGHTLY_RECAP="50 3 * * * cd $PROJECT_DIR && $PYTHON scripts/nightly_recap.py --deploy >> $LOG_DIR/recap.log 2>&1"

# ── 4:00 AM ET (08:00 UTC) — CLV backfill ────────────────────────────────────
BACKFILL_CLV="0 8 * * * cd $PROJECT_DIR && $PYTHON scripts/backfill_clv.py >> $LOG_DIR/backfill_clv.log 2>&1"

echo "Installing ChefTonyBets cron jobs..."
echo "  Project: $PROJECT_DIR"
echo "  Python:  $PYTHON"
echo ""

(crontab -l 2>/dev/null | grep -v 'march-madness'; \
 echo "# ChefTonyBets timing-aware pipeline"; \
 echo "# ── NIGHT BEFORE (opening lines) ──"; \
 echo "$NIGHT_MLB"; \
 echo "$NIGHT_NBA"; \
 echo "$NIGHT_NHL"; \
 echo "$NIGHT_WNBA"; \
 echo "# ── DEPLOY (night picks → Vercel) ──"; \
 echo "$DEPLOY_NIGHT_MLB"; \
 echo "$DEPLOY_NIGHT_NBA"; \
 echo "# ── MORNING (morning-of sports) ──"; \
 echo "$PICKS_TENNIS"; \
 echo "$PICKS_SOCCER"; \
 echo "$PICKS_PGA"; \
 echo "$PICKS_NASCAR"; \
 echo "$PICKS_UFC"; \
 echo "$CAPTION"; \
 echo "$DEPLOY_MORNING"; \
 echo "# ── GATE CHECKS (BET NOW vs HOLD) ──"; \
 echo "$GATES_1"; \
 echo "$GATES_2"; \
 echo "$GATES_3"; \
 echo "# ── CLOSING LINES + GRADING ──"; \
 echo "$CAPTURE_CLOSING"; \
 echo "$GRADE_LIVE"; \
 echo "$GRADE"; \
 echo "$NIGHTLY_RECAP"; \
 echo "$BACKFILL_CLV") | crontab -

echo "Installed ChefTonyBets timing-aware cron jobs:"
echo ""
crontab -l | grep -v '^#' | grep 'march-madness' | head -20
echo ""
echo "Logs:"
echo "  tail -f $LOG_DIR/night.log     # overnight picks"
echo "  tail -f $LOG_DIR/picks.log     # morning picks"
echo "  tail -f $LOG_DIR/gates.log     # trigger checks"
echo "  tail -f $LOG_DIR/grade.log     # grading"
echo ""
echo "Manual commands:"
echo "  python3 chef.py night          # run night pipeline now (tomorrow's picks)"
echo "  python3 chef.py gates          # check BET NOW / HOLD status"
echo "  python3 chef.py timing         # print sport timing cheat sheet"
