"""
"Show your work" caption generator — Overlay's verification-first content angle.

Unlike the generic capper templates in captions_platform.py ("BEST BET / OVER 7.5 /
edge +2.7% / #MLB"), this module produces captions that lead with Brier scores,
CLV, and trailing record. The premise: most pick accounts can't show these stats
because their records aren't real. We can. That IS the content.

Format goal: looks like a sharp trader's note, not a capper's hype.

Functions:
    receipts_caption(picks, sport, market_key, date) → str
        Daily receipts post — pulls trailing-14 record, Brier, CLV from
        public_stats.json + clv_records.json + picks.json.

    weekly_recap(picks, sport, date) → str
        Sunday long-form recap — full W/L table + CLV trend.
"""
from __future__ import annotations

import json
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
_PUBLIC_STATS = ROOT / "data" / "public_stats.json"
_CLV_RECORDS  = ROOT / "data" / "clv" / "clv_records.json"
_PICKS_FILE   = ROOT / "data" / "pnl" / "picks.json"


# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _trailing_record(picks: list[dict], sport: str, market: str,
                     since: _date) -> tuple[int, int, float, float]:
    """Return (wins, losses, units, roi_pct) for picks of (sport, market) on or
    after `since`. Considers shadow + card picks. Profit defaults to stake-based
    if `profit` field is None."""
    w = l = 0
    units = stake = 0.0
    for p in picks:
        if p.get("sport") != sport or (p.get("market") or "").lower() != market.lower():
            continue
        d = (p.get("date") or "")[:10]
        if not d or d < since.isoformat():
            continue
        result = p.get("result")
        if result not in ("win", "loss"):
            continue
        s = float(p.get("stake") or 1.0)
        prof = p.get("profit")
        if prof is None:
            # Compute from stake + odds
            odds = p.get("odds")
            try:
                odds_i = int(odds)
                prof = s * (odds_i / 100 if odds_i > 0 else 100 / abs(odds_i)) if result == "win" else -s
            except (TypeError, ValueError):
                prof = 0.0
        units += float(prof)
        stake += s
        if result == "win":
            w += 1
        else:
            l += 1
    roi = (units / stake * 100) if stake > 0 else 0.0
    return w, l, units, roi


def _trailing_clv(records: list[dict], sport: str, market: str,
                  since: _date) -> tuple[float, int]:
    """Average CLV (in cents = pp of implied probability) and N for picks on/after `since`."""
    matching = [
        r for r in records
        if r.get("sport") == sport
        and (r.get("market") or "").lower() == market.lower()
        and (r.get("date") or "")[:10] >= since.isoformat()
        and r.get("clv_cents") is not None
    ]
    if not matching:
        return 0.0, 0
    avg = sum(float(r["clv_cents"]) for r in matching) / len(matching)
    return avg, len(matching)


def _brier_for(market: str, sport: str) -> tuple[float, int] | None:
    """Read Brier + N from public_stats calibration. Returns (brier, N) or None."""
    stats = _safe_load(_PUBLIC_STATS, {})
    cal = stats.get("calibration") or []
    sport_label = sport.upper() if sport != "wnba" else "WNBA"
    market_label = {
        "moneyline": "moneyline",
        "spread":    "spread",
        "puck_line": "spread",
        "total":     "total",
        "f5_total":  "total",
        "prop":      "prop",
    }.get((market or "").lower(), market.lower())

    for entry in cal:
        seg = (entry.get("segment") or "").lower()
        if sport.lower() in seg and market_label in seg:
            return float(entry.get("brier", 0)), int(entry.get("n", 0))
    return None


def _short_market(market: str) -> str:
    return {
        "moneyline": "Moneyline",
        "spread":    "Run Line" if False else "Spread",
        "total":     "Totals",
        "f5_total":  "F5 Totals",
        "puck_line": "Puck Line",
        "nrfi":      "NRFI",
        "prop":      "Props",
    }.get((market or "").lower(), (market or "").title())


def _safe_str(value) -> str:
    """Coerce a value (possibly NaN/None) into a clean string."""
    if value is None:
        return ""
    if isinstance(value, float):
        # NaN check without importing math.isnan on every call
        if value != value:
            return ""
        return str(value)
    return str(value)


def _pick_display(pick: dict, market: str) -> str:
    """One-line bet description: 'OVER 219.5 Spurs vs Thunder' or 'Padres ML +145'."""
    market = (market or "").lower()
    team = _safe_str(pick.get("Team") or pick.get("team"))
    matchup = _safe_str(pick.get("Matchup") or pick.get("matchup"))
    direction = _safe_str(pick.get("Direction") or pick.get("direction")).upper()
    line = pick.get("BetLine") or pick.get("bet_line") or pick.get("line")
    odds = pick.get("BestOdds") or pick.get("best_odds") or pick.get("odds")
    # Coerce NaN odds to 0 so f-string formatting doesn't choke
    try:
        if isinstance(odds, float) and odds != odds:
            odds = 0
    except Exception:
        odds = 0
    odds_s = f"{int(odds):+d}" if odds else ""
    book = _safe_str(pick.get("Sportsbook") or pick.get("sportsbook") or pick.get("book"))

    if market in ("total", "f5_total"):
        return f"{direction} {line} ({odds_s}) [{book}]  —  {matchup}".strip()
    if market == "moneyline":
        return f"{team} ML ({odds_s}) [{book}]".strip()
    if market in ("spread", "puck_line"):
        line_s = f" {float(line):+.1f}" if line is not None else ""
        return f"{team}{line_s} ({odds_s}) [{book}]".strip()
    return f"{team} {direction} {line} ({odds_s}) [{book}]".strip()


# ── public api ───────────────────────────────────────────────────────────────

def receipts_caption(
    pick: dict,
    sport: str,
    market: str,
    today: _date | None = None,
    trailing_days: int = 14,
) -> str:
    """Generate the "show your work" daily caption for one live pick.

    Pulls trailing record + Brier + CLV from the data layer and frames them
    front-and-center. Same string works for X, Reddit megathread, IG.
    """
    today = today or _date.today()
    since = today - timedelta(days=trailing_days)

    picks_blob = _safe_load(_PICKS_FILE, {"picks": []})
    all_picks = picks_blob.get("picks", []) if isinstance(picks_blob, dict) else picks_blob

    w, l, units, roi = _trailing_record(all_picks, sport, market, since)
    _clv_blob = _safe_load(_CLV_RECORDS, {"picks": []})
    _clv_list = _clv_blob if isinstance(_clv_blob, list) else _clv_blob.get("picks", [])
    clv_avg, clv_n = _trailing_clv(_clv_list, sport, market, since)
    brier = _brier_for(market, sport)

    model_prob = pick.get("ModelProb") or pick.get("model_prob")
    edge = pick.get("Edge") or pick.get("edge_pct")
    if isinstance(model_prob, (int, float)) and model_prob > 1:
        model_prob = model_prob / 100  # already in pct
    model_prob_s = f"{(model_prob or 0) * 100:.1f}%" if model_prob else "—"
    edge_s = f"+{float(edge) * 100:.1f}%" if isinstance(edge, float) and edge < 1 else (
        f"+{float(edge):.1f}%" if edge else "—"
    )

    lines = []
    lines.append(f"{sport.upper()} {_short_market(market)} model — last {trailing_days} days")
    record_str = f"{w}-{l}" if (w + l) else "0-0"
    units_str = f"{units:+.1f}u" if units else "0u"
    roi_str = f"ROI {roi:+.1f}%" if (w + l) else "ROI —"
    line2 = f"{record_str} · {units_str} · {roi_str}"
    if clv_n >= 5:
        line2 += f" · CLV {clv_avg:+.2f}c (N={clv_n})"
    lines.append(line2)
    if brier:
        b_val, b_n = brier
        baseline = 0.245
        verdict = "predictive" if b_val < baseline else "noisy"
        lines.append(f"Brier {b_val:.3f} (N={b_n}) — {verdict} vs {baseline:.3f} naive")
    lines.append("")
    lines.append(f"Tonight: {_pick_display(pick, market)}")
    if model_prob_s != "—":
        lines.append(f"Model {model_prob_s} · Edge {edge_s}")
    lines.append("")
    lines.append("Every pick logged before tip-off. Full record: overlay-gray.vercel.app")
    return "\n".join(lines)


def weekly_recap(
    sport: str,
    today: _date | None = None,
    days: int = 7,
) -> str:
    """Sunday long-form recap — full W/L breakdown by market for one sport."""
    today = today or _date.today()
    since = today - timedelta(days=days)

    picks_blob = _safe_load(_PICKS_FILE, {"picks": []})
    all_picks = picks_blob.get("picks", []) if isinstance(picks_blob, dict) else picks_blob

    markets = sorted({(p.get("market") or "").lower() for p in all_picks if p.get("sport") == sport})
    markets = [m for m in markets if m]

    lines = [f"**{sport.upper()} — last {days} days**", ""]
    lines.append("| Market | W-L | Units | ROI |")
    lines.append("|---|---|---|---|")
    total_u = total_s = 0.0
    for m in markets:
        w, l, u, roi = _trailing_record(all_picks, sport, m, since)
        if (w + l) == 0:
            continue
        lines.append(f"| {_short_market(m)} | {w}-{l} | {u:+.2f}u | {roi:+.1f}% |")
        total_u += u
        total_s += (w + l)
    lines.append("")
    if total_s:
        lines.append(f"Total: {total_u:+.2f}u over {int(total_s)} settled picks")

    clv_records = _safe_load(_CLV_RECORDS, {"picks": []}).get("picks", [])
    clv_avg, clv_n = _trailing_clv(clv_records, sport, "moneyline", since)
    if clv_n:
        lines.append(f"Moneyline CLV: {clv_avg:+.2f}c over {clv_n} picks")

    return "\n".join(lines)
