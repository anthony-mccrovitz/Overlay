"""
Talking-head video scripts for TikTok / YouTube Shorts.

You record these yourself on camera — this module gives you a structured
script every morning so you never have to stare at a blank page.

Three flavors:
  1. RECAP   — "Yesterday went X-Y, here's what happened"  (30-45s)
  2. PICKS   — "Today's top play and why"                   (45-60s)
  3. EDU     — "Sports betting concept of the day"          (60-90s)

Output: output/picks/baseball_mlb/<DATE>/talking_head/*.md
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"
STATS_FILE = ROOT / "data" / "public_stats.json"
OUTPUT_DIR = ROOT / "output" / "picks"


# Rotating educational topics — one per day, cycles through.
EDU_TOPICS = [
    {
        "title": "What is closing line value (CLV) and why it's the only stat that matters",
        "hook":  "If you're not tracking this one number, you have no idea if you're actually a winning bettor.",
        "beats": [
            "CLV = the difference between the odds you got and the closing line.",
            "If you bet Yankees -110 and it closes -130, you beat the market by 20 cents.",
            "Sharp bettors live in the +1c to +5c CLV range. Squares are negative every time.",
            "Win-loss noise dies after 100 bets. CLV doesn't lie.",
            "Track every bet. If your CLV is positive, the wins will follow. Math.",
        ],
    },
    {
        "title": "Why flat staking beats Kelly for 99% of bettors",
        "hook":  "Everyone tells you to use Kelly criterion. Here's why that's terrible advice for almost everyone.",
        "beats": [
            "Kelly assumes you know your true edge. You don't.",
            "Overestimate your edge by 2% and Kelly bankrupts you twice as fast.",
            "Flat 1u stakes are forgiving. Your variance is bounded.",
            "Pros use fractional Kelly (quarter-Kelly) — never full Kelly.",
            "Start with 1u flat. Track CLV for 200 bets. Then maybe scale.",
        ],
    },
    {
        "title": "What -110 actually means (the vig explained)",
        "hook":  "If you don't understand this, the sportsbook is robbing you and you don't even know.",
        "beats": [
            "-110 on both sides means you bet $110 to win $100.",
            "Implied probability of -110 is 52.4%. Both sides add to 104.8% — that's the vig.",
            "You need to win 52.4% of -110 bets just to break even.",
            "The 'no-vig' fair line is 50/50. The book charges you 2.4% on every play.",
            "Shopping for the best line shaves this. -105 cuts vig nearly in half.",
        ],
    },
    {
        "title": "Why Pinnacle is the sharpest book and how to use it",
        "hook":  "Pinnacle isn't a sportsbook. It's a price-discovery engine. Here's how to weaponize it.",
        "beats": [
            "Pinnacle takes sharp action. They don't limit winners.",
            "Their lines are the closest thing to a 'true' price.",
            "Take Pinnacle's line, remove the vig, that's your fair probability.",
            "Compare to soft books (DK, FD). Anything 3%+ off is potential edge.",
            "If your books won't take your action, you're probably sharp.",
        ],
    },
    {
        "title": "The single biggest mistake new sports bettors make",
        "hook":  "I see this every day in every comment section. Stop doing it.",
        "beats": [
            "Chasing losses by doubling up. Martingale.",
            "Your edge doesn't change because you lost the last bet.",
            "A 5% edge bet at 2u is just two 5% edge bets stacked.",
            "Variance is brutal. 10-bet losing streaks happen even to +EV bettors.",
            "Stake size = your confidence × your edge. Not your emotions.",
        ],
    },
    {
        "title": "How sportsbooks set lines (it's not what you think)",
        "hook":  "Sportsbooks aren't predicting the game. They're predicting YOU.",
        "beats": [
            "Books open with a sharp number from their traders.",
            "Then they shade it 1-2 points based on expected public bias.",
            "Lakers/Cowboys/Yankees get inflated lines because public bets them.",
            "The real game is fading the public on these inflated sides.",
            "If you see a line move AGAINST the public bet %, sharps just hammered the other side.",
        ],
    },
    {
        "title": "The math behind why parlays are the worst bet on the board",
        "hook":  "The book LOVES parlays. Here's the math on why.",
        "beats": [
            "Each leg of a parlay has vig baked in.",
            "A 3-leg parlay at -110 each compounds vig 3 times. House edge ~12%.",
            "Same 3 bets straight, you're paying 2.4% × 3.",
            "Books market parlays hard because they're 5x more profitable for them.",
            "Pros bet straight. Squares bet parlays. There's a reason.",
        ],
    },
]


# ── Loaders (mirror results_captions.py — keep both files standalone) ────────

def _yyyymmdd_to_iso(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _load_yesterday_settled(date_str: str) -> list[dict]:
    if not PICKS_FILE.exists():
        return []
    try:
        all_picks = json.loads(PICKS_FILE.read_text()).get("picks", [])
    except (json.JSONDecodeError, OSError):
        return []
    iso = _yyyymmdd_to_iso(date_str)
    return [
        p for p in all_picks
        if p.get("card_pick")
        and (p.get("date") or "")[:10] == iso
        and p.get("result") in ("win", "loss", "push")
    ]


def _load_today_card(date_str: str) -> list[dict]:
    """Today's card picks (not yet settled)."""
    if not PICKS_FILE.exists():
        return []
    try:
        all_picks = json.loads(PICKS_FILE.read_text()).get("picks", [])
    except (json.JSONDecodeError, OSError):
        return []
    iso = _yyyymmdd_to_iso(date_str)
    return [
        p for p in all_picks
        if p.get("card_pick") and (p.get("date") or "")[:10] == iso
    ]


def _record_str(picks: list[dict]) -> tuple[str, float, float]:
    wins   = sum(1 for p in picks if p["result"] == "win")
    losses = sum(1 for p in picks if p["result"] == "loss")
    profit = sum(float(p.get("profit") or 0) for p in picks)
    stake  = sum(float(p.get("stake") or 1) for p in picks if p["result"] != "push") or 1.0
    return f"{wins}-{losses}", round(profit, 2), round(profit / stake * 100, 1)


# ── Scripts ──────────────────────────────────────────────────────────────────

def script_recap(date_str: str) -> str:
    """
    30-45 second talking-head script recapping yesterday.
    """
    picks = _load_yesterday_settled(date_str)
    if not picks:
        return f"# RECAP SCRIPT — {date_str}\n\nNo settled card picks for this date. Skip recap today.\n"

    rec, profit, roi = _record_str(picks)
    iso = _yyyymmdd_to_iso(date_str)

    wins_sorted = sorted(
        (p for p in picks if p["result"] == "win"),
        key=lambda x: float(x.get("profit") or 0),
        reverse=True,
    )
    top    = wins_sorted[0] if wins_sorted else None
    losses = [p for p in picks if p["result"] == "loss"]
    worst  = min(losses, key=lambda x: float(x.get("profit") or 0)) if losses else None

    won_day = profit > 0
    energy  = "winning" if won_day else "honest"

    sections = [
        f"# RECAP — {iso}",
        "",
        f"**Target length:** 30-45 sec • **Tone:** {energy}, confident, no hype",
        "",
        "---",
        "",
        "## 🎬 HOOK (first 3 seconds — most important)",
    ]

    if won_day:
        hook = random.choice([
            f"Day {rec[0]}: my AI just went {rec} and printed {profit:+.2f} units. Here's how.",
            f"If you tailed me yesterday, you're up {profit:+.2f} units. Quick breakdown.",
            f"Going {rec} yesterday with a {roi:+.1f}% ROI — and I have receipts.",
        ])
    else:
        hook = random.choice([
            f"Went {rec} yesterday — {profit:+.2f} units. Here's why I'm not panicking.",
            f"Rough day at {rec}. Let me show you why the process is still winning.",
            f"Lost {abs(profit):.2f} units yesterday. Three reasons today's slate is loaded.",
        ])
    sections.extend([hook, ""])

    sections.extend([
        "## 📊 BODY (~25 sec)",
        "",
    ])

    if top:
        sections.append(
            f"- **Top hit:** {top.get('team','')}. "
            f"Model had it at {(top.get('model_prob') or 0)*100:.0f}%, "
            f"book had it at {(100/(abs(top.get('odds',-110))+100)*100 if (top.get('odds',-110) < 0) else (100/(top.get('odds',110)+100)*100)):.0f}%. "
            "Free money."
        )

    if worst and won_day:
        sections.append(
            f"- **Worst beat:** {worst.get('team','')}. "
            "Stuff happens. Closing line was still on our side."
        )
    elif worst:
        sections.append(
            f"- **The bad:** {worst.get('team','')} took an L. "
            "Bullpen blew it / late variance / take your pick."
        )

    sections.extend([
        "- Process numbers: model picks beat their closing line on most plays. "
        "That's the only stat that matters long-term.",
        "",
        "## 🎯 CTA (~5 sec)",
        "",
        "- Today's slate drops in a few hours. Free. Link in bio.",
        "- Follow for tomorrow's recap whether we win or lose. I post both.",
        "",
        "---",
        "",
        "## 🎨 B-roll suggestions",
        "- Cut to results card PNG at the 5-second mark",
        "- Score graphic for top hit (use ESPN screenshot)",
        "- Final 5 sec: zoom on link-in-bio CTA",
    ])

    return "\n".join(sections)


def script_picks(date_str: str) -> str:
    """
    45-60 second talking-head script for today's top play.
    """
    picks = _load_today_card(date_str)
    if not picks:
        return f"# PICKS SCRIPT — {date_str}\n\nNo card picks yet. Run morning pipeline first.\n"

    # Pick the highest-edge play
    top = max(picks, key=lambda x: float(x.get("edge_pct") or 0))

    iso     = _yyyymmdd_to_iso(date_str)
    team    = top.get("team", "")
    mkt     = (top.get("market") or "").upper()
    odds    = top.get("odds")
    odds_s  = f"{'+' if (odds or 0) > 0 else ''}{int(odds)}" if odds is not None else "—"
    matchup = top.get("matchup", "")
    edge    = float(top.get("edge_pct") or 0)
    prob    = float(top.get("model_prob") or 0) * 100

    return f"""# PICKS — {iso}

**Target length:** 45-60 sec • **Tone:** confident, technical-but-accessible

---

## 🎬 HOOK
Three options — pick one based on vibe:

- "My single highest-confidence play of the day. Model edge: {edge:.1f}%. Here it is."
- "If I could only bet ONE game tonight, this is it."
- "{team}. {odds_s}. {edge:.1f}% edge. Here's why the book is wrong."

## 📊 THE PICK
- **Game:** {matchup}
- **Bet:** {team} — {mkt} at {odds_s}
- **Model probability:** {prob:.1f}%
- **Implied market probability:** ~{(100/(abs(odds or 110)+100)*100 if (odds or 0) < 0 else 100/((odds or 110)+100)*100):.1f}%
- **Edge:** {edge:.1f}%

## 🧠 THE WHY (this is the meat — 25-30 sec)
*Pick ONE angle to talk through. Don't try to cram all three:*

1. **Pitching matchup angle** (MLB) — starter ERA differential, recent form, BvP history
2. **Pace/efficiency angle** (NBA) — offensive rating, defensive matchup, recent trends
3. **Line movement angle** — where did the sharp money go? Pinnacle vs softer books

## 🎯 CTA
- Full slate (5+ plays) on the site — link in bio. Free.
- Tag me when you cash this. I post results tomorrow either way.

---

## 🎨 B-roll
- Open: pull up the pick card PNG
- Middle: ESPN team page or recent game highlights
- End: scoreboard graphic of expected stat (e.g., team's last 5 totals)

## 🔥 Strong words to use
"sharp money", "edge", "the model", "calibrated", "Pinnacle's number"

## ❌ Words to avoid
"lock", "hammer", "free money", "guaranteed", "easy" — these are tells.
"""


def script_education(date_str: str) -> str:
    """
    60-90 second educational sports betting concept.
    Rotates through EDU_TOPICS using day-of-year for deterministic variety.
    """
    day_idx = datetime.strptime(date_str, "%Y%m%d").timetuple().tm_yday
    topic   = EDU_TOPICS[day_idx % len(EDU_TOPICS)]
    iso     = _yyyymmdd_to_iso(date_str)

    beats = "\n".join(f"{i+1}. {b}" for i, b in enumerate(topic["beats"]))

    return f"""# EDUCATION — {iso}

**Topic:** {topic['title']}
**Target length:** 60-90 sec • **Tone:** teacher, not preacher

---

## 🎬 HOOK (first 3 seconds)
> {topic['hook']}

## 📚 THE 5 BEATS
{beats}

## 🎯 CTA
- "If you want to see this applied to real picks, link in bio. Free daily."
- "Follow for one of these every day. No fluff."

---

## 🎨 B-roll
- Whiteboard or screen-share calculations
- Show real example from your tracking sheet
- End screen: link to your bio

## 💡 Why this works
Educational content gets shared 3x more than picks. People who learn from you
trust you. Trust converts to subs.
"""


# ── Writer ───────────────────────────────────────────────────────────────────

def write_all(date_str: str, *, verbose: bool = True) -> dict[str, Path]:
    """Generate all three scripts. Returns {flavor: path}."""
    out_dir = OUTPUT_DIR / "baseball_mlb" / date_str / "talking_head"
    out_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    files = {
        "recap.md":      script_recap(date_str),
        "picks.md":      script_picks(date_str),
        "education.md":  script_education(date_str),
    }

    for fname, body in files.items():
        path = out_dir / fname
        path.write_text(body)
        written[fname.replace(".md", "")] = path
        if verbose:
            print(f"  [talking-head] wrote {path.relative_to(ROOT)}")

    return written


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else (
        (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    )
    write_all(target)
