#!/usr/bin/env python3
"""
gen_morning_brief.py — Your one-page daily content briefing.

Stitches together:
  • Yesterday's results (record, profit, ROI, streak)
  • Path to results card PNG (for IG/X)
  • All per-platform captions (ready to copy-paste)
  • Today's slate summary (so you can hype it)
  • Talking-head script outlines (TikTok/YouTube)
  • Daily posting checklist with order-of-operations

Output: output/briefs/<TODAY>.md

Usage:
  python3 scripts/gen_morning_brief.py                 # today (yesterday's results, today's picks)
  python3 scripts/gen_morning_brief.py 20260512        # specific date
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PICKS_FILE  = ROOT / "data" / "pnl" / "picks.json"
STATS_FILE  = ROOT / "data" / "public_stats.json"
OUTPUT_DIR  = ROOT / "output" / "picks"
BRIEFS_DIR  = ROOT / "output" / "briefs"


def _iso(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _yesterday(today: str) -> str:
    d = datetime.strptime(today, "%Y%m%d") - timedelta(days=1)
    return d.strftime("%Y%m%d")


def _load_picks() -> list[dict]:
    if not PICKS_FILE.exists():
        return []
    try:
        return json.loads(PICKS_FILE.read_text()).get("picks", [])
    except (json.JSONDecodeError, OSError):
        return []


def _settled_yesterday(yesterday: str) -> list[dict]:
    iso_y = _iso(yesterday)
    return [
        p for p in _load_picks()
        if p.get("card_pick")
        and (p.get("date") or "")[:10] == iso_y
        and p.get("result") in ("win", "loss", "push")
    ]


def _today_card(today: str) -> list[dict]:
    iso_t = _iso(today)
    return [
        p for p in _load_picks()
        if p.get("card_pick") and (p.get("date") or "")[:10] == iso_t
    ]


def _read_if_exists(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def _find_caption(date_str: str, name: str) -> Path | None:
    """Search both MLB and NBA output dirs for the caption file."""
    for sport_dir in ("baseball_mlb", "basketball_nba"):
        p = OUTPUT_DIR / sport_dir / date_str / "captions" / name
        if p.exists():
            return p
    return None


def _find_card(date_str: str) -> Path | None:
    """Find graded results card PNG."""
    for sport_dir in ("baseball_mlb", "basketball_nba"):
        for name in ("graded_results_card.png", "results_card.png"):
            p = OUTPUT_DIR / sport_dir / date_str / name
            if p.exists():
                return p
    return None


def _summary_block(picks: list[dict]) -> str:
    if not picks:
        return "_No settled picks._"
    wins   = sum(1 for p in picks if p["result"] == "win")
    losses = sum(1 for p in picks if p["result"] == "loss")
    pushes = sum(1 for p in picks if p["result"] == "push")
    profit = sum(float(p.get("profit") or 0) for p in picks)
    stake  = sum(float(p.get("stake") or 1) for p in picks if p["result"] != "push") or 1.0
    roi    = profit / stake * 100
    rec    = f"{wins}-{losses}" + (f"-{pushes}" if pushes else "")
    icon   = "🟢" if profit >= 0 else "🔴"

    streak = ""
    if STATS_FILE.exists():
        try:
            s = int(json.loads(STATS_FILE.read_text())["summary"]["streak"])
            if s >= 3:
                streak = f" • 🔥 {s}-pick win streak"
            elif s <= -3:
                streak = f" • 🧊 {abs(s)}-pick cold streak"
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            pass

    return f"{icon} **{rec}** • {profit:+.2f}u • {roi:+.1f}% ROI{streak}"


def _slate_block(picks: list[dict]) -> str:
    if not picks:
        return "_No picks generated yet — run `python3 chef.py picks mlb` and `python3 chef.py picks nba`._"
    rows = ["| Sport | Pick | Market | Odds | Edge | Confidence |",
            "|-------|------|--------|------|------|------------|"]
    for p in picks:
        sport = (p.get("sport") or "").upper()
        team  = (p.get("team") or "")[:36]
        mkt   = (p.get("market") or "").upper()
        odds  = p.get("odds")
        odds_s = f"{'+' if (odds or 0) > 0 else ''}{int(odds)}" if odds is not None else "—"
        edge  = float(p.get("edge_pct") or 0)
        prob  = float(p.get("model_prob") or 0) * 100
        rows.append(f"| {sport} | {team} | {mkt} | {odds_s} | {edge:+.1f}% | {prob:.0f}% |")
    return "\n".join(rows)


def build_brief(today: str) -> str:
    yesterday = _yesterday(today)
    y_picks   = _settled_yesterday(yesterday)
    t_picks   = _today_card(today)
    card_png  = _find_card(yesterday)

    pretty_today = datetime.strptime(today, "%Y%m%d").strftime("%A, %B %-d, %Y")
    pretty_y     = datetime.strptime(yesterday, "%Y%m%d").strftime("%A %b %-d")

    sections = [
        f"# ChefTonyBets — Daily Brief",
        f"**{pretty_today}**",
        "",
        "---",
        "",
        f"## 📊 Yesterday ({pretty_y})",
        "",
        _summary_block(y_picks),
        "",
    ]

    if card_png:
        rel = card_png.relative_to(ROOT)
        sections.extend([
            f"**Results card PNG:** `{rel}`",
            "→ Upload this to IG/X with the captions below.",
            "",
        ])

    # Today's slate
    sections.extend([
        "## 🎯 Today's Slate",
        "",
        _slate_block(t_picks),
        "",
    ])

    # Captions
    sections.extend([
        "---",
        "",
        "## 📱 Ready-to-Post Captions (yesterday's results)",
        "",
    ])

    platforms = [
        ("Instagram",                     "results_instagram.txt"),
        ("X / Twitter",                   "results_x.txt"),
        ("Reddit — r/sportsbook",         "results_reddit_sportsbook.txt"),
        ("Reddit — r/sportsbetting",      "results_reddit_sportsbetting.txt"),
        ("Reddit — r/mlbbetting",         "results_reddit_mlb.txt"),
        ("Reddit — r/nbabetting",         "results_reddit_nba.txt"),
    ]
    for label, fname in platforms:
        path = _find_caption(yesterday, fname)
        body = _read_if_exists(path) if path else None
        if not body:
            continue
        sections.extend([
            f"### {label}",
            "```",
            body.rstrip(),
            "```",
            "",
        ])

    # Today's picks captions (already generated by chef.py picks)
    sections.extend([
        "---",
        "",
        "## 🎬 Today's Pick Captions (use after slate locks)",
        "",
    ])
    for label, fname in [
        ("Instagram",   "instagram.txt"),
        ("X / Twitter", "twitter.txt"),
        ("Reddit",      "reddit.txt"),
        ("TikTok",      "tiktok.txt"),
    ]:
        path = _find_caption(today, fname)
        body = _read_if_exists(path) if path else None
        if not body:
            continue
        sections.extend([
            f"### {label}",
            "```",
            body.rstrip(),
            "```",
            "",
        ])

    # Talking-head links
    sections.extend([
        "---",
        "",
        "## 🎥 Talking-Head Scripts (TikTok / YouTube Shorts)",
        "",
        "Record yourself reading these. ~30-90 sec each.",
        "",
    ])
    for label, fname in [
        ("Recap (yesterday's results)", f"output/picks/baseball_mlb/{yesterday}/talking_head/recap.md"),
        ("Picks (today's top play)",    f"output/picks/baseball_mlb/{today}/talking_head/picks.md"),
        ("Education (concept of day)",  f"output/picks/baseball_mlb/{today}/talking_head/education.md"),
    ]:
        path = ROOT / fname
        if path.exists():
            sections.append(f"- **{label}:** `{path.relative_to(ROOT)}`")
    sections.append("")

    # Daily checklist
    sections.extend([
        "---",
        "",
        "## ✅ Daily Posting Checklist",
        "",
        "**Morning (7-9 AM ET)** — yesterday's results",
        "- [ ] Post results card + IG caption to Instagram",
        "- [ ] Post results card + X caption to X/Twitter",
        "- [ ] Post Reddit results to r/sportsbook daily thread (if open)",
        "- [ ] Record + post RECAP talking-head to TikTok & YouTube Shorts",
        "",
        "**Late morning (10-11 AM ET)** — today's slate",
        "- [ ] Post pick card to Instagram (carousel: cover → top 3 picks → CTA)",
        "- [ ] Post pick card thread to X/Twitter",
        "- [ ] Cross-post to r/sportsbetting and r/mlbbetting / r/nbabetting",
        "- [ ] Record + post PICKS talking-head to TikTok & YouTube Shorts",
        "",
        "**Afternoon (variable)** — education",
        "- [ ] Record + post EDUCATION talking-head (build trust, not pick-dependent)",
        "",
        "**Always:**",
        "- [ ] Reply to every comment within 2 hours",
        "- [ ] DM anyone asking about the model",
        "- [ ] Track engagement in a spreadsheet (which hooks land?)",
        "",
        "---",
        "",
        f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M ET')}_",
    ])

    return "\n".join(sections)


def main() -> int:
    today = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEFS_DIR / f"{today}.md"

    body = build_brief(today)
    out_path.write_text(body)

    print(f"✅ Wrote brief: {out_path.relative_to(ROOT)}")
    print(f"   Open with:  open {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
