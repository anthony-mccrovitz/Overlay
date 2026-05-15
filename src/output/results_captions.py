"""
Multi-platform captions for yesterday's graded results.

Reads from data/pnl/picks.json (canonical record), filters by date + card_pick,
and emits ready-to-post text for Instagram, X/Twitter, and per-subreddit Reddit.

For talking-head video scripts (TikTok / YouTube Shorts), see talking_head.py.

Usage:
    from src.output.results_captions import write_all
    write_all("20260511")              # writes captions to output/picks/.../captions/
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"
OUTPUT_DIR = ROOT / "output" / "picks"

HANDLE         = "@ChefTonyBets"
BIO_LINK_HINT  = "Free daily picks → link in bio"

# ── Loaders ──────────────────────────────────────────────────────────────────

def _yyyymmdd_to_iso(date_str: str) -> str:
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"


def _load_settled_card_picks(date_str: str) -> list[dict]:
    """Yesterday's card_pick=True picks that have a settled result."""
    if not PICKS_FILE.exists():
        return []
    try:
        all_picks = json.loads(PICKS_FILE.read_text()).get("picks", [])
    except (json.JSONDecodeError, OSError):
        return []

    iso = _yyyymmdd_to_iso(date_str)
    out = []
    for p in all_picks:
        if not p.get("card_pick"):
            continue
        if (p.get("date") or "")[:10] != iso:
            continue
        if p.get("result") not in ("win", "loss", "push"):
            continue
        out.append(p)
    return out


# ── Stats ────────────────────────────────────────────────────────────────────

def _summarize(picks: list[dict]) -> dict:
    wins   = sum(1 for p in picks if p["result"] == "win")
    losses = sum(1 for p in picks if p["result"] == "loss")
    pushes = sum(1 for p in picks if p["result"] == "push")
    profit = sum(float(p.get("profit") or 0) for p in picks)
    stake  = sum(float(p.get("stake") or 1) for p in picks if p["result"] != "push") or 1.0
    roi    = profit / stake

    record = f"{wins}-{losses}"
    if pushes:
        record += f"-{pushes}"

    by_sport: Counter = Counter()
    for p in picks:
        by_sport[(p.get("sport") or "?").upper()] += 1

    return {
        "wins":   wins,
        "losses": losses,
        "pushes": pushes,
        "profit": round(profit, 2),
        "roi":    round(roi * 100, 1),  # pct
        "record": record,
        "by_sport": dict(by_sport),
        "n":       len(picks),
    }


def _profit_str(profit: float) -> str:
    sign = "+" if profit >= 0 else ""
    return f"{sign}{profit:.2f}u"


def _pick_line(p: dict, *, terse: bool = False) -> str:
    """Single-line pick recap. e.g. 'WIN  NYY ML -135  (+0.74u)'"""
    res     = p["result"].upper()
    icon    = {"WIN": "✅", "LOSS": "❌", "PUSH": "➖"}.get(res, "•")
    team    = p.get("team") or p.get("matchup") or ""
    mkt     = (p.get("market") or "").upper()
    odds    = p.get("odds")
    odds_s  = ""
    if odds is not None:
        odds_i = int(odds)
        odds_s = f" {'+' if odds_i > 0 else ''}{odds_i}"
    profit  = float(p.get("profit") or 0)

    if terse:
        return f"{icon} {team[:32]} ({_profit_str(profit)})"
    return f"{icon} {team[:40]:<40} {mkt:<8}{odds_s:<6} {_profit_str(profit)}"


def _streak_from_stats() -> int:
    """Pull current streak from public_stats.json if available."""
    stats_path = ROOT / "data" / "public_stats.json"
    if not stats_path.exists():
        return 0
    try:
        return int(json.loads(stats_path.read_text())["summary"]["streak"])
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return 0


# ── Platform: Instagram ──────────────────────────────────────────────────────

def caption_instagram(picks: list[dict], date_str: str) -> str:
    """
    Carousel-friendly recap. Designed to pair with results_card.png.
    Long-form OK, emoji-friendly, hashtag-rich at end.
    """
    s         = _summarize(picks)
    pretty_dt = datetime.strptime(date_str, "%Y%m%d").strftime("%a %b %-d")
    rec_emoji = "🟢" if s["profit"] >= 0 else "🔴"
    streak    = _streak_from_stats()
    streak_s  = ""
    if streak >= 3:
        streak_s = f"\n🔥 {streak}-pick win streak"
    elif streak <= -3:
        streak_s = f"\n🧊 Cold streak — bouncing back today"

    # Highlight top 3 wins by profit
    wins_sorted = sorted(
        (p for p in picks if p["result"] == "win"),
        key=lambda x: float(x.get("profit") or 0),
        reverse=True,
    )
    highlights = "\n".join(_pick_line(p, terse=True) for p in wins_sorted[:3])
    if not highlights:
        highlights = "Rough night — back to the lab. Today's slate is loaded. 📊"

    lines = [
        f"{rec_emoji} {pretty_dt} Results: {s['record']} • {_profit_str(s['profit'])} • {s['roi']:+.1f}% ROI",
        "",
        "Top hits:",
        highlights,
        streak_s.strip() if streak_s else "",
        "",
        f"Every pick is run through an XGBoost+LightGBM ensemble vs sharp Pinnacle lines.",
        f"No noise. No squares. Just edge.",
        "",
        f"📈 Today's picks dropping at 11 AM ET",
        f"🔗 {BIO_LINK_HINT}",
        f"📲 {HANDLE}",
        "",
        "#sportsbetting #mlbpicks #nbapicks #sportsbettingpicks #freepicks "
        "#sportsbettor #dailypicks #betting #gamblingtwitter #mlbbets #nbabets "
        "#cheftonybets #aibetting #sportsai #pickoftheday #bettingedge",
    ]
    return "\n".join(l for l in lines if l != "").replace("\n\n\n", "\n\n")


# ── Platform: X / Twitter ────────────────────────────────────────────────────

def caption_x(picks: list[dict], date_str: str) -> str:
    """
    280-char hard limit. Lead with record, one hot take, CTA.
    """
    s         = _summarize(picks)
    rec_emoji = "🟢" if s["profit"] >= 0 else "🔴"
    streak    = _streak_from_stats()

    # Top single hit
    top = max(
        (p for p in picks if p["result"] == "win"),
        key=lambda x: float(x.get("profit") or 0),
        default=None,
    )

    hot_take = ""
    if top:
        team_short = (top.get("team") or "")[:24]
        hot_take = f"\n✅ Top hit: {team_short}"
    elif s["profit"] < 0:
        hot_take = "\n📊 Closing line still positive — process > results"

    streak_s = ""
    if streak >= 3:
        streak_s = f" • {streak}-win streak 🔥"
    elif streak <= -3:
        streak_s = f" • due for a bounce"

    head = f"{rec_emoji} Yesterday: {s['record']} • {_profit_str(s['profit'])}{streak_s}"
    cta  = f"\nToday's picks → 11am ET\n{HANDLE}"

    body = f"{head}{hot_take}{cta}"

    # Auto-trim if over 280 — drop hot_take first, then streak
    if len(body) > 280:
        body = f"{head}{cta}"
    if len(body) > 280:
        body = body.replace(streak_s, "")
    if len(body) > 280:
        body = body[:277] + "..."
    return body


# ── Platform: Reddit ─────────────────────────────────────────────────────────

def _reddit_body_table(picks: list[dict]) -> str:
    """Markdown table of every pick + result."""
    rows = ["| Pick | Market | Odds | Result | Profit |",
            "|------|--------|------|--------|--------|"]
    for p in picks:
        team   = (p.get("team") or "")[:36]
        mkt    = (p.get("market") or "").upper()
        odds   = p.get("odds")
        odds_s = f"{'+' if (odds or 0) > 0 else ''}{int(odds)}" if odds is not None else "—"
        res    = p["result"].upper()
        prof   = _profit_str(float(p.get("profit") or 0))
        rows.append(f"| {team} | {mkt} | {odds_s} | {res} | {prof} |")
    return "\n".join(rows)


def caption_reddit_sportsbook(picks: list[dict], date_str: str) -> str:
    """
    For r/sportsbook 'How Did We Do?' daily thread.
    Strict rules: no self-promo, no links, no Discord pitch.
    Just record + picks + lessons.
    """
    s         = _summarize(picks)
    iso       = _yyyymmdd_to_iso(date_str)

    lines = [
        f"**{iso} — {s['record']} ({_profit_str(s['profit'])}, {s['roi']:+.1f}% ROI)**",
        "",
        "Model: XGBoost + LightGBM ensemble vs Pinnacle no-vig lines. Flat 1u stakes on +EV plays.",
        "",
        _reddit_body_table(picks),
        "",
    ]

    # Honest lesson — sportsbook crowd respects it
    if s["profit"] < 0:
        wrst = min(picks, key=lambda x: float(x.get("profit") or 0))
        lines.append(
            f"Worst beat: {wrst.get('team','')}. "
            "Always going to happen. Closing line was still on our side, so the process holds."
        )
    else:
        lines.append("Process > results. Edge is real, variance is variance.")
    return "\n".join(lines)


def caption_reddit_sportsbetting(picks: list[dict], date_str: str) -> str:
    """
    For r/sportsbetting — slightly more permissive than r/sportsbook.
    Can mention model/approach but still no direct paid pitch.
    """
    s = _summarize(picks)
    lines = [
        f"My AI model went {s['record']} yesterday ({_profit_str(s['profit'])}, {s['roi']:+.1f}% ROI)",
        "",
        "Approach: XGBoost + LightGBM ensemble, calibrated probabilities, edge measured against "
        "Pinnacle no-vig lines. Flat 1u stakes. No martingale, no parlays.",
        "",
        _reddit_body_table(picks),
        "",
        "Posting daily for accountability. Happy to discuss methodology in comments.",
    ]
    return "\n".join(lines)


def caption_reddit_sport(picks: list[dict], date_str: str, sport: str) -> str:
    """
    For r/mlbbetting or r/nbabetting (sport-specific, more relaxed self-promo).
    """
    sport_u = sport.upper()
    sport_picks = [p for p in picks if (p.get("sport") or "").lower() == sport.lower()]
    if not sport_picks:
        return ""

    s = _summarize(sport_picks)
    lines = [
        f"{sport_u} model results — {_yyyymmdd_to_iso(date_str)}",
        "",
        f"**{s['record']} • {_profit_str(s['profit'])} • {s['roi']:+.1f}% ROI**",
        "",
        _reddit_body_table(sport_picks),
        "",
        f"Today's {sport_u} card drops at 11am ET. All free. DM if curious about the model.",
    ]
    return "\n".join(lines)


# ── Writer ───────────────────────────────────────────────────────────────────

def write_all(date_str: str, *, verbose: bool = True) -> dict[str, Path]:
    """
    Generate all platform captions for yesterday's results.
    Returns {platform: path_written}.
    """
    picks = _load_settled_card_picks(date_str)
    if not picks:
        if verbose:
            print(f"  [captions] No settled card picks for {date_str}")
        return {}

    # Output co-located with mlb dir by convention (matches gen_results_card.py)
    out_dir = OUTPUT_DIR / "baseball_mlb" / date_str / "captions"
    out_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    files = {
        "results_instagram.txt":            caption_instagram(picks, date_str),
        "results_x.txt":                    caption_x(picks, date_str),
        "results_reddit_sportsbook.txt":    caption_reddit_sportsbook(picks, date_str),
        "results_reddit_sportsbetting.txt": caption_reddit_sportsbetting(picks, date_str),
        "results_reddit_mlb.txt":           caption_reddit_sport(picks, date_str, "mlb"),
        "results_reddit_nba.txt":           caption_reddit_sport(picks, date_str, "nba"),
    }

    for fname, body in files.items():
        if not body:
            continue
        path = out_dir / fname
        path.write_text(body)
        written[fname.replace("results_", "").replace(".txt", "")] = path
        if verbose:
            print(f"  [captions]  wrote {path.relative_to(ROOT)}")

    return written


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else (
        (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    )
    write_all(target)
