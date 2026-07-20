"""Dynamic picks scanner — checks all sports for upcoming events and triggers
picks generation if events are found but picks haven't been generated yet.

Runs every 2 hours via cron. Prevents missed events for tennis, soccer,
WNBA, NHL, and any other sport with irregular schedules.

Cron: 0 */2 * * * cd /path && python3 scripts/dynamic_picks_scanner.py >> logs/scanner.log 2>&1
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG = ROOT / "logs" / "scanner.log"

# Sports to scan dynamically — these have irregular or unpredictable schedules.
# MLB/NBA are handled by the fixed 9:30 PM night pipeline.
DYNAMIC_SPORTS = [
    # Tennis trigger keys span the active grass/hard warm-ups + Slams. run_tennis
    # auto-detects ALL active tournaments anyway (and tennis.yml runs it daily),
    # so this list just needs to overlap whatever is in season as a backstop.
    ("tennis",       "run_tennis.py",   ["tennis_atp_wimbledon", "tennis_wta_wimbledon",
                                          "tennis_atp_us_open", "tennis_wta_us_open",
                                          "tennis_atp_halle_open", "tennis_atp_queens_club_champ",
                                          "tennis_wta_german_open", "tennis_atp_french_open"]),
    # These keys are only the event-detection trigger; run_soccer.py scans ALL of
    # SOCCER_LEAGUES once fired. Liga MX is listed so a Liga-MX-only match day
    # (no MLS/Euro game in the window) still triggers the scan — else its shadow
    # CLV feed would have holes on non-overlapping match days.
    ("soccer",       "run_soccer.py",   ["soccer_spain_la_liga", "soccer_germany_bundesliga",
                                          "soccer_italy_serie_a", "soccer_usa_mls",
                                          "soccer_mexico_ligamx",
                                          "soccer_fifa_world_cup", "soccer_france_ligue_one"]),
    ("wnba",         "run_wnba.py",     ["basketball_wnba"]),
    ("nhl",          "run_nhl.py",      ["icehockey_nhl"]),
    ("nhl_props",    "run_nhl_props.py",["icehockey_nhl"]),
]

# Only trigger picks if game starts within this many hours
LOOKAHEAD_HOURS = 10

# Don't re-generate if picks were already logged within this many hours
REGENERATE_COOLDOWN_HOURS = 6


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _has_events_soon(sport_keys: list[str], within_hours: int = LOOKAHEAD_HOURS) -> bool:
    """Return True if any of the sport keys have events starting within N hours."""
    try:
        from src.data.odds_api import fetch_odds
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=within_hours)
        for key in sport_keys:
            try:
                df = fetch_odds(markets="h2h", sport=key, refresh=True)
                if df.empty:
                    continue
                for _, row in df.iterrows():
                    ct = row.get("CommenceTime")
                    if ct is None:
                        continue
                    if isinstance(ct, str):
                        try:
                            ct = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                        except Exception:
                            continue
                    if hasattr(ct, "tzinfo") and ct.tzinfo is None:
                        ct = ct.replace(tzinfo=timezone.utc)
                    if now <= ct <= cutoff:
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _picks_already_generated(sport_label: str, today: str) -> bool:
    """Return True if picks for this sport were logged to pnl within the cooldown window."""
    try:
        f = ROOT / "data" / "pnl" / "picks.json"
        raw = json.loads(f.read_text())
        picks = raw if isinstance(raw, list) else raw.get("picks", [])
        cutoff = datetime.now(timezone.utc) - timedelta(hours=REGENERATE_COOLDOWN_HOURS)
        for p in picks:
            if not isinstance(p, dict):
                continue
            if p.get("date") != today:
                continue
            sport = (p.get("sport") or "").lower()
            if sport_label.lower() not in sport and not sport.startswith(sport_label.lower()):
                continue
            rec = p.get("recorded_at")
            if not rec:
                continue
            try:
                rec_dt = datetime.fromisoformat(rec.replace("Z", "+00:00"))
                if rec_dt >= cutoff:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def run() -> None:
    today = date.today().strftime("%Y-%m-%d")
    _log(f"Dynamic scanner running — checking {len(DYNAMIC_SPORTS)} sports for {today}")

    triggered = []
    skipped   = []

    for sport_label, script, keys in DYNAMIC_SPORTS:
        has_events = _has_events_soon(keys)
        already_done = _picks_already_generated(sport_label, today)

        if not has_events:
            skipped.append(f"{sport_label}: no events in next {LOOKAHEAD_HOURS}h")
            continue

        if already_done:
            skipped.append(f"{sport_label}: picks already generated (cooldown)")
            continue

        # Trigger picks generation
        _log(f"  → Triggering {script} (events found, picks not yet generated)")
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / script)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode == 0:
                triggered.append(sport_label)
                _log(f"  ✓ {sport_label} picks generated")
            else:
                _log(f"  ✗ {sport_label} failed: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            _log(f"  ✗ {sport_label} timed out after 180s")
        except Exception as e:
            _log(f"  ✗ {sport_label} error: {e}")

    if triggered:
        _log(f"  Triggered: {', '.join(triggered)}")
        # Redeploy so new picks go live
        try:
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "deploy_picks.py")],
                cwd=str(ROOT), capture_output=True, text=True, timeout=120,
            )
            _log("  ✓ Deployed updated picks to Vercel")
        except Exception as e:
            _log(f"  ✗ Deploy failed: {e}")
    else:
        _log(f"  Nothing triggered. Skipped: {len(skipped)} sports")


if __name__ == "__main__":
    run()
