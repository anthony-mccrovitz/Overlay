#!/usr/bin/env python3
"""
gen_morning_brief.py — Your one-page daily content briefing.

Covers all active sports: MLB, NBA, Tennis, Soccer, PGA.

Sections:
  1. Yesterday's results (W-L by sport + overall)
  2. Model Heat — rolling L10 record per model with HOT/WARM/COLD status
  3. Today's slate (picks from all sports)
  4. Ready-to-post captions (Instagram, X/Twitter, Reddit, TikTok) by sport
  5. Daily posting checklist

Output: output/briefs/<TODAY>.md

Usage:
  python3 scripts/gen_morning_brief.py                 # today
  python3 scripts/gen_morning_brief.py 20260519        # specific date
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT        = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PICKS_FILE  = ROOT / "data" / "pnl" / "picks.json"
STATS_FILE  = ROOT / "data" / "public_stats.json"
OUTPUT_DIR  = ROOT / "output" / "picks"
BRIEFS_DIR  = ROOT / "output" / "briefs"


# ─────────────────────────── Data loaders ────────────────────────────────────

def _iso(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _yesterday(today: str) -> str:
    d = datetime.strptime(today, "%Y%m%d") - timedelta(days=1)
    return d.strftime("%Y%m%d")


def _load_picks() -> list[dict]:
    if not PICKS_FILE.exists():
        return []
    try:
        raw = json.loads(PICKS_FILE.read_text())
        return raw if isinstance(raw, list) else raw.get("picks", [])
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


def _today_from_output_dirs(today: str) -> list[dict]:
    """Scan all sport output dirs for today's picks.json files."""
    picks: list[dict] = []
    if not OUTPUT_DIR.exists():
        return picks
    for sport_dir in OUTPUT_DIR.iterdir():
        if not sport_dir.is_dir():
            continue
        date_dir = sport_dir / today
        picks_path = date_dir / "picks.json"
        if picks_path.exists():
            try:
                data = json.loads(picks_path.read_text())
                if isinstance(data, list):
                    for p in data:
                        p.setdefault("sport", sport_dir.name)
                    picks.extend(data)
                elif isinstance(data, dict):
                    rows = data.get("picks", [])
                    for p in rows:
                        p.setdefault("sport", sport_dir.name)
                    picks.extend(rows)
            except (json.JSONDecodeError, OSError):
                pass
    return picks


def _read_if_exists(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


# ─────────────────────────── Results helpers ─────────────────────────────────

_ACTIVE_SPORTS = [
    ("mlb",    "MLB"),
    ("nba",    "NBA"),
    ("tennis", "Tennis"),
    ("soccer", "Soccer"),
    ("golf",   "PGA / Golf"),
]


def _sport_prefix_match(sport_val: str, prefix: str) -> bool:
    return (sport_val or "").lower().startswith(prefix)


def _results_block(picks: list[dict]) -> str:
    if not picks:
        return "_No settled card picks._"

    wins   = sum(1 for p in picks if p.get("result") == "win")
    losses = sum(1 for p in picks if p.get("result") == "loss")
    pushes = sum(1 for p in picks if p.get("result") == "push")
    profit = sum(float(p.get("profit") or 0) for p in picks)
    staked = sum(float(p.get("stake") or 1) for p in picks if p.get("result") != "push") or 1.0
    roi    = profit / staked * 100
    rec    = f"{wins}-{losses}" + (f"-{pushes}P" if pushes else "")
    icon   = "🟢" if profit >= 0 else "🔴"

    streak = ""
    if STATS_FILE.exists():
        try:
            s = int(json.loads(STATS_FILE.read_text())["summary"]["streak"])
            if s >= 3:
                streak = f"  •  🔥 {s}-pick win streak"
            elif s <= -3:
                streak = f"  •  🧊 {abs(s)}-pick cold streak"
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            pass

    lines = [f"{icon} **OVERALL: {rec}** — {profit:+.2f}u — ROI {roi:+.1f}%{streak}", ""]

    # Per-sport breakdown
    lines.append("| Sport | W-L | Profit | ROI |")
    lines.append("|-------|-----|--------|-----|")
    for prefix, label in _ACTIVE_SPORTS:
        sp = [p for p in picks if _sport_prefix_match(p.get("sport", ""), prefix)]
        if not sp:
            continue
        sp_np  = [p for p in sp if p.get("result") in ("win", "loss")]
        sp_w   = sum(1 for p in sp_np if p.get("result") == "win")
        sp_l   = len(sp_np) - sp_w
        sp_prf = sum(float(p.get("profit") or 0) for p in sp_np)
        sp_stk = sum(float(p.get("stake") or 1) for p in sp_np) or 1.0
        sp_roi = sp_prf / sp_stk * 100
        lines.append(f"| {label} | {sp_w}-{sp_l} | {sp_prf:+.2f}u | {sp_roi:+.1f}% |")

    return "\n".join(lines)


# ─────────────────────────── Model heat ──────────────────────────────────────

_MODEL_DEFS = [
    # (display_name, sport_prefix, market)
    ("MLB Totals",       "mlb",    "total"),
    ("MLB Moneyline",    "mlb",    "moneyline"),
    ("NBA Totals",       "nba",    "total"),
    ("Tennis",           "tennis", None),
    ("Soccer",           "soccer", None),
    ("PGA / Golf",       "golf",   None),
]


def _model_heat_block(all_picks: list[dict], n: int = 10) -> str:
    """Build the Model Heat section."""
    try:
        from src.analytics.public_stats import model_heat
        use_func = True
    except ImportError:
        use_func = False

    card = [p for p in all_picks if p.get("card_pick")]

    lines: list[str] = []
    lines.append("| Model | L10 Record | ROI | Status | Avg CLV | Note |")
    lines.append("|-------|-----------|-----|--------|---------|------|")

    for display_name, sport_prefix, market in _MODEL_DEFS:
        # Filter card picks for this model
        mp = [
            p for p in card
            if _sport_prefix_match(p.get("sport", ""), sport_prefix)
            and (market is None or p.get("market") == market)
        ]
        settled_np = [p for p in mp if p.get("result") in ("win", "loss")]
        if len(settled_np) < 5:
            lines.append(f"| {display_name} | — | — | — | — | < 5 picks |")
            continue

        last_n = settled_np[-n:]
        wins  = sum(1 for p in last_n if p.get("result") == "win")
        total = len(last_n)
        profit = sum(float(p.get("profit") or 0) for p in last_n)
        staked = sum(float(p.get("stake") or 1) for p in last_n) or 1.0
        wr    = wins / total
        roi   = profit / staked

        # CLV average
        clv_vals = [float(p["clv_pct"]) for p in last_n if p.get("clv_pct") is not None]
        avg_clv  = f"{sum(clv_vals)/len(clv_vals):+.1f}%" if clv_vals else "—"

        # Status
        if wr >= 0.60:
            status = "🔥 HOT"
            note   = "Consider bumping stake to 1.5u"
        elif wr >= 0.50:
            status = "✅ WARM"
            note   = "Maintain current stake"
        else:
            status = "🧊 COLD"
            if len(settled_np) >= 15 and wr < 0.50:
                note = "Consider shadow-only until it recovers"
            else:
                note = "Monitor — need more sample"

        rec_str = f"{wins}-{total-wins} ({wr:.0%})"
        roi_str = f"{roi:+.1%}"
        lines.append(f"| {display_name} | {rec_str} | {roi_str} | {status} | {avg_clv} | {note} |")

    return "\n".join(lines)


# ─────────────────────────── Slate block ─────────────────────────────────────

def _slate_block(picks: list[dict]) -> str:
    if not picks:
        return (
            "_No picks generated yet — run `python3 chef.py picks mlb`, "
            "`chef.py picks nba`, `chef.py picks tennis`, etc._"
        )
    rows = [
        "| Sport | Pick | Market | Odds | Edge | Confidence |",
        "|-------|------|--------|------|------|------------|",
    ]
    for p in picks:
        sport  = (p.get("sport") or "").upper()
        team   = (p.get("team") or "")[:36]
        mkt    = (p.get("market") or "").upper()
        odds   = p.get("odds")
        odds_s = f"{'+' if (odds or 0) > 0 else ''}{int(odds)}" if odds is not None else "—"
        edge   = float(p.get("edge_pct") or 0)
        prob   = float(p.get("model_prob") or 0) * 100
        rows.append(f"| {sport} | {team} | {mkt} | {odds_s} | {edge:+.1f}% | {prob:.0f}% |")
    return "\n".join(rows)


# ─────────────────────────── Caption helpers ─────────────────────────────────

# Sport dirs in priority display order
_SPORT_DIRS_ORDER = [
    ("baseball_mlb",   "MLB"),
    ("basketball_nba", "NBA"),
    ("tennis_atp_french_open",    "Tennis — Roland-Garros (ATP)"),
    ("tennis_wta_french_open",    "Tennis — Roland-Garros (WTA)"),
    ("tennis_atp_wimbledon",      "Tennis — Wimbledon (ATP)"),
    ("tennis_wta_wimbledon",      "Tennis — Wimbledon (WTA)"),
    ("tennis_atp_us_open",        "Tennis — US Open (ATP)"),
    ("tennis_atp_australian_open","Tennis — Australian Open (ATP)"),
    ("soccer",                    "Soccer (All Leagues)"),
    ("soccer_epl",                "Soccer — EPL"),
    ("soccer_spain_la_liga",      "Soccer — La Liga"),
    ("soccer_italy_serie_a",      "Soccer — Serie A"),
    ("soccer_germany_bundesliga", "Soccer — Bundesliga"),
    ("soccer_france_ligue_1",     "Soccer — Ligue 1"),
    ("golf_pga",                  "PGA Tour"),
]

_PLATFORM_LABELS = {
    "instagram":     "Instagram",
    "x_twitter":     "X / Twitter",
    "twitter":       "X / Twitter",
    "reddit":        "Reddit",
    "tiktok_script": "TikTok Script",
    "tiktok":        "TikTok Script",
}
_PLATFORM_ORDER = ["instagram", "x_twitter", "twitter", "reddit", "tiktok_script", "tiktok"]


def _collect_captions(date_str: str) -> dict[str, dict[str, str]]:
    """Return {sport_label: {platform: text}} for all sports with captions."""
    result: dict[str, dict[str, str]] = {}
    if not OUTPUT_DIR.exists():
        return result

    seen_labels: set[str] = set()
    ordered_sport_dirs = {sd: label for sd, label in _SPORT_DIRS_ORDER}

    all_sport_dirs = []
    for sd, label in _SPORT_DIRS_ORDER:
        p = OUTPUT_DIR / sd / date_str
        if p.exists():
            all_sport_dirs.append((sd, label, p))

    # Also pick up any sport dirs not in the predefined order
    for sport_dir in sorted(OUTPUT_DIR.iterdir()):
        if not sport_dir.is_dir() or sport_dir.name in ordered_sport_dirs:
            continue
        date_dir = sport_dir / date_str
        if date_dir.exists():
            label = sport_dir.name.replace("_", " ").title()
            all_sport_dirs.append((sport_dir.name, label, date_dir))

    for _sd, label, date_dir in all_sport_dirs:
        if label in seen_labels:
            continue
        caps: dict[str, str] = {}
        cap_dir = date_dir / "captions"
        if cap_dir.exists():
            for txt in sorted(cap_dir.glob("*.txt")):
                content = txt.read_text(encoding="utf-8").strip()
                if content:
                    caps[txt.stem] = content
        if caps:
            result[label] = caps
            seen_labels.add(label)

    return result


def _captions_block(date_str: str, today: bool) -> str:
    """Build caption section markdown."""
    captions = _collect_captions(date_str)
    if not captions:
        sport_type = "today's picks" if today else "yesterday's results"
        return f"_No captions found for {date_str}. Run chef.py picks <sport> to generate {sport_type}._"

    sections: list[str] = []
    for sport_label, platform_caps in captions.items():
        sections.append(f"### {sport_label}")
        ordered = [k for k in _PLATFORM_ORDER if k in platform_caps]
        rest    = [k for k in platform_caps if k not in _PLATFORM_ORDER]
        for key in ordered + rest:
            plabel  = _PLATFORM_LABELS.get(key, key.replace("_", " ").title())
            content = platform_caps[key]
            sections += [f"#### {plabel}", "```", content.rstrip(), "```", ""]

    return "\n".join(sections)


# ─────────────────────────── Build brief ─────────────────────────────────────

def build_brief(today: str) -> str:
    yesterday  = _yesterday(today)
    y_picks    = _settled_yesterday(yesterday)
    t_picks    = _today_card(today)
    all_picks  = _load_picks()

    # Supplement today_card with any picks found in output dirs (not yet in PnL)
    if not t_picks:
        t_picks = _today_from_output_dirs(today)

    pretty_today = datetime.strptime(today, "%Y%m%d").strftime("%A, %B %-d, %Y")
    pretty_y     = datetime.strptime(yesterday, "%Y%m%d").strftime("%A %b %-d")

    sections = [
        "# Overlay — Daily Brief",
        f"**{pretty_today}**",
        "",
        "---",
        "",
        f"## Yesterday's Results ({pretty_y})",
        "",
        _results_block(y_picks),
        "",
        "---",
        "",
        "## Model Heat (Last 10 Picks)",
        "",
        _model_heat_block(all_picks),
        "",
        "_HOT = L10 win rate ≥ 60% | WARM = 50-59% | COLD < 50%_",
        "",
        "---",
        "",
        "## Today's Slate",
        "",
        _slate_block(t_picks),
        "",
        "---",
        "",
        "## Today's Pick Captions",
        "",
        _captions_block(today, today=True),
        "",
        "---",
        "",
        "## Yesterday's Result Captions",
        "",
        _captions_block(yesterday, today=False),
        "",
        "---",
        "",
        "## Daily Posting Checklist",
        "",
        f"**9:30 AM ET — Post yesterday's results (all sports) to X/Twitter + IG**",
        "- [ ] Post results card + IG caption to Instagram",
        "- [ ] Post results card + X caption to X/Twitter",
        "- [ ] Record + post RECAP talking-head to TikTok & YouTube Shorts",
        "",
        f"**10:00 AM ET — Post today's MLB picks (IG carousel + X thread)**",
        "- [ ] Post MLB pick card to Instagram (carousel: cover → top picks → CTA)",
        "- [ ] Post MLB pick card thread to X/Twitter",
        "",
        f"**10:15 AM ET — Post today's NBA picks (IG + X)**",
        "- [ ] Post NBA pick card to Instagram",
        "- [ ] Post NBA pick card to X/Twitter",
        "",
        f"**10:30 AM ET — Post Tennis / Soccer / PGA if active (IG + X)**",
        "- [ ] Check if Tennis picks generated today — post if yes",
        "- [ ] Check if Soccer picks generated today — post if yes",
        "- [ ] Check if PGA picks generated today — post if yes",
        "",
        f"**11:00 AM ET — Reddit megathread posts**",
        "- [ ] Post to r/sportsbook daily thread",
        "- [ ] Post to r/sportsbetting and sport-specific subreddits",
        "- [ ] Post tennis to r/tennis / r/tennisbetting if active",
        "- [ ] Post soccer to r/soccerbetting if active",
        "- [ ] Post golf to r/sportsbook golf thread if active",
        "",
        f"**Throughout the day — TikTok talking-head scripts**",
        "- [ ] Record picks talking-head (scripts in output dir)",
        "- [ ] Record education talking-head (concept of the day)",
        "- [ ] Post both to TikTok + YouTube Shorts",
        "",
        "**Always:**",
        "- [ ] Reply to every comment within 2 hours",
        "- [ ] DM anyone asking about the model",
        "- [ ] Track engagement (which hooks land?)",
        "",
        "---",
        "",
        f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M ET')}_",
    ]

    return "\n".join(sections)


# ─────────────────────────── Main ────────────────────────────────────────────

def main() -> int:
    today = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEFS_DIR / f"{today}.md"

    body = build_brief(today)
    out_path.write_text(body, encoding="utf-8")

    print(f"Wrote brief: {out_path.relative_to(ROOT)}")
    print(f"   Open with:  open {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
