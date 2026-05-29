"""
scripts/timing_config.py — Sport-by-sport bet timing config

Research-backed optimal windows for when to generate picks and when to
actually place bets for each sport. Used by night_pipeline.py and bet_gates.py.

Summary:
  MLB     → Generate night before (~9:30 PM ET). Place at open. Recheck at T-60min for lineup.
  NBA     → Generate night before. HOLD until inactives posted (~T-90min before tip).
  NHL     → Generate night before. Place moneylines at open; hold totals until goalie confirmed.
  WNBA    → Same as NBA. Wait for inactives (~T-90min before tip).
  Tennis  → Generate morning of. Place right at open (soft early lines). Watch Pinnacle for moves.
  Soccer  → Generate morning of (or day before for big matches). Place morning of.
  PGA     → Generate Monday morning when weekly lines drop. Place Mon–Tue before sharp tightening.
  UFC     → Generate as soon as card lines post (~5 days out). Place immediately.
  NASCAR  → Generate Sunday night when race-week lines post. Place early in the week.
"""

from __future__ import annotations

SPORT_TIMING: dict[str, dict] = {

    # ── MLB ──────────────────────────────────────────────────────────────────
    # Lines open: night before ~9–10 PM ET on sharp books (Pinnacle first)
    # Bet window: immediately at open for ML/spread; T-60min recheck for totals/props
    # Key trigger: confirmed starting pitchers + batting lineup (~60 min pre-game)
    # Pipeline run: 9:30 PM ET night before
    "mlb": {
        "pipeline_run":    "21:30",           # 9:30 PM ET — night before
        "bet_ready":       "open",            # ML/spread can be placed at open
        "trigger_markets": ["total", "nrfi"], # hold totals/props until lineup confirmed
        "trigger_type":    "lineup",          # MLB lineup confirmation
        "trigger_offset":  -60,               # T-60 min before first pitch
        "notes": "Place ML/spread at night open. Recheck totals at T-60min after SP + lineup confirmed.",
    },

    # ── NBA ──────────────────────────────────────────────────────────────────
    # Lines open: night before
    # Bet window: AFTER inactives posted (~T-90min before tip)
    # Key trigger: NBA inactives list (rest/load management decisions)
    # Pipeline run: 9:30 PM ET night before (generate picks, hold placement)
    "nba": {
        "pipeline_run":    "21:30",           # 9:30 PM ET — night before
        "bet_ready":       "trigger",         # do NOT bet until trigger fires
        "trigger_markets": ["all"],           # hold ALL markets
        "trigger_type":    "inactives",       # NBA inactives list
        "trigger_offset":  -90,               # T-90 min before tip
        "notes": "Never bet at open. Always wait for inactives. Load management can swing totals 4-6pts.",
    },

    # ── NHL ──────────────────────────────────────────────────────────────────
    # Lines open: night before (~Monday night for Tuesday games)
    # Bet window: moneylines at open; totals AFTER starting goalie confirmed
    # Key trigger: starting goalie announcement (can be T-60min or same-day)
    # Pipeline run: 9:30 PM ET night before
    "nhl": {
        "pipeline_run":    "21:30",           # 9:30 PM ET — night before
        "bet_ready":       "split",           # moneylines: open; totals: trigger
        "trigger_markets": ["total"],         # hold totals until goalie confirmed
        "trigger_type":    "goalie",          # NHL starting goalie confirmation
        "trigger_offset":  -120,              # T-120 min before puck drop
        "notes": "Moneylines: bet at open. Totals: wait for starting goalie (changes line 0.5–1.0 goals).",
    },

    # ── WNBA ─────────────────────────────────────────────────────────────────
    # Same pattern as NBA — smaller market, lines stay softer longer
    # Books slower to adjust to sharp action → slight edge in early window too
    # Bet window: after inactives (~T-90min)
    # Pipeline run: 9:30 PM ET night before
    "wnba": {
        "pipeline_run":    "21:30",           # 9:30 PM ET — night before
        "bet_ready":       "trigger",         # hold until inactives
        "trigger_markets": ["all"],
        "trigger_type":    "inactives",
        "trigger_offset":  -90,               # T-90 min before tip
        "notes": "Same as NBA. WNBA market is softer — lines stay mispriced longer, but still wait for inactives.",
    },

    # ── Tennis ───────────────────────────────────────────────────────────────
    # Lines open: morning of match day during tournaments (low limits at first)
    # Bet window: right at open when lines are softest + limits lowest
    # Key signal: watch Pinnacle — if odds jump sharply, sharp money hit → follow fast
    # Pipeline run: morning of (7:30 AM ET to catch early matches)
    "tennis": {
        "pipeline_run":    "07:30",           # 7:30 AM ET day of
        "bet_ready":       "open",            # place right at morning open
        "trigger_markets": [],                # no trigger — just place early
        "trigger_type":    None,
        "trigger_offset":  0,
        "notes": "Bet at open. Limits are low early = book is soft. Watch Pinnacle for sharp steam moves.",
    },

    # ── Soccer ───────────────────────────────────────────────────────────────
    # Lines open: 2–7 days out for major competitions; 1–2 days for league games
    # Bet window: morning of is generally fine; lineup news ~60 min before kickoff
    # Pipeline run: morning of (8:00 AM ET)
    "soccer": {
        "pipeline_run":    "08:00",           # 8:00 AM ET day of
        "bet_ready":       "open",            # morning of is fine
        "trigger_markets": [],
        "trigger_type":    None,
        "trigger_offset":  -60,               # optional: recheck post-lineup
        "notes": "Place morning of. Lineup news drops ~60min before kickoff but less impactful than NBA/NHL.",
    },

    # ── PGA / Golf ───────────────────────────────────────────────────────────
    # Lines open: Sunday night / Monday morning for weekly events
    # Sharp money hits Monday–Tuesday, market tightens by Wednesday
    # Bet window: Monday morning ASAP when lines first post
    # Pipeline run: Monday 8:00 AM ET (currently runs Thu morning — too late!)
    "pga": {
        "pipeline_run":    "08:00_monday",    # Monday 8 AM ET — first thing week of event
        "bet_ready":       "open",            # place Mon–Tue before sharp tightening
        "trigger_markets": [],
        "trigger_type":    None,
        "trigger_offset":  0,
        "notes": "Lines post Sunday night. Monday AM is the prime window. By Wednesday the market is tight.",
    },

    # ── UFC ──────────────────────────────────────────────────────────────────
    # Lines open: ~5–6 days before the fight card
    # Sharp MMA bettors are most active in the first 24–48 hrs after posting
    # Key late trigger: Thursday weigh-ins (weight miss → wild line move)
    # Pipeline run: as soon as card lines appear (~Tuesday for Saturday card)
    "ufc": {
        "pipeline_run":    "on_card_post",    # run as soon as lines appear (~Tue for Sat card)
        "bet_ready":       "open",            # place immediately at open
        "trigger_markets": [],
        "trigger_type":    "weigh_in",        # Thursday weigh-in news
        "trigger_offset":  0,
        "notes": "Bet right at open. Check Thursday weigh-ins for missed weight (can flip moneyline entirely).",
    },

    # ── NASCAR / Racing ──────────────────────────────────────────────────────
    # Lines open: Sunday–Monday of race week
    # Bet window: early week before practice/qualifying narrows the market
    # Pipeline run: Monday 9 AM ET of race week
    "nascar": {
        "pipeline_run":    "09:00_monday",    # Monday 9 AM ET race week
        "bet_ready":       "open",            # bet early in the week
        "trigger_markets": [],
        "trigger_type":    None,
        "trigger_offset":  0,
        "notes": "Place Mon–Wed. Qualifying + practice results move outrights significantly by Friday.",
    },
}


def get_timing(sport: str) -> dict:
    """Return timing config for a sport, normalized to lowercase."""
    sport = sport.lower().replace("baseball_mlb", "mlb") \
                         .replace("basketball_nba", "nba") \
                         .replace("basketball_wnba", "wnba") \
                         .replace("icehockey_nhl", "nhl")
    return SPORT_TIMING.get(sport, {
        "pipeline_run": "09:00",
        "bet_ready":    "open",
        "trigger_markets": [],
        "trigger_type": None,
        "trigger_offset": 0,
        "notes": "No specific timing config. Default: place at morning open.",
    })


def print_timing_guide() -> None:
    """Print a human-readable timing cheat sheet."""
    sep = "─" * 66
    print(f"\n  {'═'*66}")
    print(f"  {'BET TIMING GUIDE':^66}")
    print(f"  {'═'*66}")
    print(f"  {'SPORT':<10} {'PIPELINE RUN':<20} {'BET WHEN':<20} {'TRIGGER'}")
    print(f"  {sep}")
    for sport, cfg in SPORT_TIMING.items():
        run  = cfg["pipeline_run"]
        when = cfg["bet_ready"]
        trig = cfg.get("trigger_type") or "—"
        mkt  = ", ".join(cfg.get("trigger_markets", [])) or "—"
        print(f"  {sport.upper():<10} {run:<20} {when:<20} {trig} ({mkt})")
    print(f"  {sep}")
    print()


if __name__ == "__main__":
    print_timing_guide()
