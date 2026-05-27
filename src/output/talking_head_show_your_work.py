"""
TikTok / Shorts "show your work" script generator.

Writes a 30-second face-on-camera script per live model per day. Anthony reads
it off the phone — no editing required. Replaces the generic talking_head
rotation in src/output/talking_head.py with a verification-first hook.
"""
from __future__ import annotations

from datetime import date as _date, datetime, timezone
from pathlib import Path


_PROJECT_START = _date(2026, 4, 1)  # day 1 of "building in public" countdown


def _day_n(today: _date | None = None) -> int:
    today = today or _date.today()
    return max(1, (today - _PROJECT_START).days + 1)


def _brier_verdict(brier: float) -> str:
    if brier < 0.235:
        return "actually predictive"
    if brier < 0.245:
        return "edges the market"
    return "borderline"


def build_script(
    sport: str,
    market: str,
    pick_line: str,            # e.g. "OVER 219.5 Spurs vs Thunder -105"
    model_prob_pct: float,     # 62.7
    edge_pct: float,           # 11.6
    record_str: str,           # "8-3 ATS · +6.4u"
    brier: float | None,
    clv_avg_cents: float | None,
    today: _date | None = None,
) -> str:
    """Return a markdown script with 5 beats, total 30s.

    Format is plain enough to read in one take. Headings tell Anthony when to
    pause or change posture. No emoji, no music cues — keep it sharp.
    """
    today = today or _date.today()
    day = _day_n(today)
    sport_label = sport.upper()
    market_label = market.replace("_", " ").title()
    brier_str = f"{brier:.3f}" if brier is not None else "—"
    brier_verdict = _brier_verdict(brier) if brier is not None else ""
    clv_str = f"{clv_avg_cents:+.2f} cents" if clv_avg_cents is not None else "—"

    lines = []
    lines.append(f"# {sport_label} {market_label} — Day {day}")
    lines.append("")
    lines.append(f"**Date:** {today.isoformat()}")
    lines.append(f"**Total runtime target:** 30 seconds")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Beat 1 — Hook (0-3s)")
    lines.append("")
    lines.append("> Most sports betting accounts can't show their Brier score.")
    lines.append(f"> Mine for {sport_label} {market_label} is **{brier_str}**.")
    lines.append("")
    lines.append("## Beat 2 — Why that matters (3-10s)")
    lines.append("")
    lines.append("> Brier under 0.245 means the model actually predicts.")
    lines.append("> Above 0.245 is a coin flip. Most cappers can't show this number")
    if brier_verdict:
        lines.append(f"> because they don't actually have one. Mine is {brier_verdict}.")
    else:
        lines.append("> because they don't actually have one.")
    lines.append("")
    lines.append("## Beat 3 — Tonight's call (10-22s)")
    lines.append("")
    lines.append(f"> Tonight my model says **{pick_line}**.")
    lines.append(f"> Model gives it {model_prob_pct:.1f}%. Book has it at {model_prob_pct - edge_pct:.1f}%.")
    lines.append(f"> Edge is **+{edge_pct:.1f}%**.")
    lines.append("")
    lines.append("## Beat 4 — Receipts (22-28s)")
    lines.append("")
    lines.append(f"> Last 14 days on this model: **{record_str}**.")
    if clv_avg_cents is not None:
        lines.append(f"> CLV {clv_str} — model is {'beating' if clv_avg_cents > 0 else 'lagging'} the closing line.")
    lines.append("> Every pick logged before tip-off. Full record in bio.")
    lines.append("")
    lines.append("## Beat 5 — CTA (28-30s)")
    lines.append("")
    lines.append(f"> Day {day} of building a sports betting AI in public.")
    lines.append("> Follow if you want to see how this ends.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Posture notes")
    lines.append("- Beat 1: look directly at camera. Don't smile.")
    lines.append("- Beat 2: brief eye-roll on 'coin flip' line. Earn the credibility.")
    lines.append("- Beat 3: pull up the card / phone with the actual pick.")
    lines.append("- Beat 4: hold up record. Voice drops slightly — confident, not hype.")
    lines.append("- Beat 5: end on neutral. Don't beg for follows.")
    lines.append("")
    lines.append(f"_Generated {datetime.now(timezone.utc).isoformat()}_")
    return "\n".join(lines)


def write_script(
    out_dir: Path,
    sport: str,
    market: str,
    pick_line: str,
    model_prob_pct: float,
    edge_pct: float,
    record_str: str,
    brier: float | None,
    clv_avg_cents: float | None,
    today: _date | None = None,
    filename: str = "show_your_work.md",
) -> Path:
    """Write the script to `out_dir/talking_head/<filename>` and return path."""
    target = out_dir / "talking_head"
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    path.write_text(
        build_script(sport, market, pick_line, model_prob_pct, edge_pct,
                     record_str, brier, clv_avg_cents, today=today),
        encoding="utf-8",
    )
    return path
