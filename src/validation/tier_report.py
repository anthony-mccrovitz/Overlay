"""
Tiered ROI from graded picks — compares "best bets" (high edge) vs full slate.

Moneyline tiers match pick_card confidence (src/output/pick_card.py):
  HIGH ≥ 6%, MED ≥ 4%, LOW ≥ 3% min edge.

Spread/total tiers use edge_runs (model − market); legacy grades without it are
filled from picks_spreads.json / picks_totals.json when possible.
"""
from __future__ import annotations

import json
from pathlib import Path

# Moneyline (probability edge 0–1)
ML_HIGH = 0.06
ML_MED = 0.04
ML_LOW = 0.03

# Run line: |model margin − line| in runs (aligns with min_edge_spread ~0.4 default)
SPREAD_HIGH = 1.5
SPREAD_MED = 1.0

# Totals: |pred − line| in runs
TOTAL_HIGH = 2.0
TOTAL_MED = 1.0


def _load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _index_picks_by_paper_id(picks: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in picks:
        gid = p.get("game_id_paper") or p.get("game_id")
        if gid:
            out[str(gid)] = p
    return out


def collect_graded_details_with_edges(picks_root: Path) -> list[dict]:
    """All settled rows from grades.json, with edge_runs backfilled from pick files if needed."""
    rows: list[dict] = []
    if not picks_root.exists():
        return rows

    for day_dir in sorted(picks_root.iterdir()):
        if not day_dir.is_dir():
            continue
        gpath = day_dir / "grades.json"
        if not gpath.exists():
            continue

        spreads = _index_picks_by_paper_id(_load_json_list(day_dir / "picks_spreads.json"))
        totals = _index_picks_by_paper_id(_load_json_list(day_dir / "picks_totals.json"))

        try:
            with open(gpath, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        for d in data.get("details", []):
            if d.get("status") not in ("win", "loss"):
                continue
            row = {**d, "_slate_date": data.get("date", "")}

            bt = row.get("bet_type") or "moneyline"
            gid = str(row.get("game_id", ""))

            if bt == "spread":
                er = float(row.get("edge_runs") or 0)
                if er <= 0 and gid in spreads:
                    er = float(spreads[gid].get("edge_runs") or 0)
                row["edge_runs"] = er
            elif bt == "total":
                er = float(row.get("edge_runs") or 0)
                if er <= 0 and gid in totals:
                    er = float(totals[gid].get("edge_runs") or 0)
                row["edge_runs"] = er

            rows.append(row)

    return rows


def _tier_ml(edge: float) -> str:
    if edge >= ML_HIGH:
        return "HIGH (≥6%)"
    if edge >= ML_MED:
        return "MED (4–6%)"
    if edge >= ML_LOW:
        return "LOW (3–4%)"
    return "min edge (<3%)"


def _tier_spread(er: float) -> str:
    if er >= SPREAD_HIGH:
        return f"HIGH (≥{SPREAD_HIGH} runs)"
    if er >= SPREAD_MED:
        return f"MED ({SPREAD_MED}–{SPREAD_HIGH} runs)"
    if er > 0:
        return f"LOW (>{0.4}–{SPREAD_MED} runs)"
    return "unknown"


def _tier_total(er: float) -> str:
    if er >= TOTAL_HIGH:
        return f"HIGH (≥{TOTAL_HIGH} runs)"
    if er >= TOTAL_MED:
        return f"MED ({TOTAL_MED}–{TOTAL_HIGH} runs)"
    if er > 0:
        return f"LOW (0.5–{TOTAL_MED} runs)"
    return "unknown"


def _summarize(rows: list[dict]) -> tuple[float, float, int, int, float]:
    """profit, staked, wins, losses, roi_pct"""
    staked = 100.0 * len(rows)
    profit = sum(float(r.get("profit") or 0) for r in rows)
    wins = sum(1 for r in rows if r.get("status") == "win")
    losses = len(rows) - wins
    roi = (profit / staked * 100) if staked > 0 else 0.0
    return profit, staked, wins, losses, roi


def print_tier_report(picks_root: Path | None = None) -> str:
    root = picks_root or Path("output/picks") / "baseball_mlb"
    rows = collect_graded_details_with_edges(root)

    lines: list[str] = []
    lines.append("\n" + "=" * 62)
    lines.append("  TIERED ROI — from grades.json (settled bets only)")
    lines.append("=" * 62)
    lines.append(f"  Source: {root.resolve()}")
    lines.append(f"  Settled rows: {len(rows)}")
    lines.append("")

    ml = [r for r in rows if (r.get("bet_type") or "moneyline") == "moneyline"]
    sp = [r for r in rows if r.get("bet_type") == "spread"]
    tot = [r for r in rows if r.get("bet_type") == "total"]

    def block(title: str, subset: list[dict]):
        lines.append(f"  --- {title} ---")
        if not subset:
            lines.append("  (no settled bets)")
            lines.append("")
            return

        profit, staked, wins, losses, roi = _summarize(subset)
        lines.append(
            f"  ALL:  n={len(subset)}  {wins}W-{losses}L  "
            f"ROI {roi:+.1f}%  profit ${profit:+,.0f} on ${staked:,.0f}"
        )

        tiers: dict[str, list[dict]] = {}
        for r in subset:
            if title.startswith("Moneyline"):
                e = float(r.get("edge") or 0)
                t = _tier_ml(e)
            elif title.startswith("Spreads"):
                e = float(r.get("edge_runs") or 0)
                t = _tier_spread(e)
            else:
                e = float(r.get("edge_runs") or 0)
                t = _tier_total(e)
            tiers.setdefault(t, []).append(r)

        for tname in sorted(tiers.keys(), key=lambda x: (-len(tiers[x]), x)):
            tr = tiers[tname]
            p, s, w, l, roi = _summarize(tr)
            lines.append(
                f"  {tname:28s} n={len(tr):3d}  {w}W-{l}L  "
                f"ROI {roi:+.1f}%  ${p:+,.0f}"
            )
        lines.append("")

    block("Moneyline (edge = model prob − implied)", ml)
    block("Spreads (edge_runs = |model − market RL|)", sp)
    block("Totals (edge_runs = |pred − line|)", tot)

    # Recommended subset: ML HIGH only (matches "would recommend")
    high_ml = [r for r in ml if float(r.get("edge") or 0) >= ML_HIGH]
    if high_ml:
        p, s, w, l, roi = _summarize(high_ml)
        lines.append("  --- Recommended-style subset (ML HIGH only, edge ≥ 6%) ---")
        lines.append(
            f"  n={len(high_ml)}  {w}W-{l}L  ROI {roi:+.1f}%  "
            f"profit ${p:+,.0f} on ${s:,.0f}"
        )
    else:
        lines.append("  --- ML HIGH (≥6%): no settled bets yet ---")

    lines.append("  " + "=" * 58)
    lines.append(
        "  Note: small samples — tiers are descriptive; pick thresholds before\n"
        "        the season to avoid overfitting the same history.\n"
    )
    text = "\n".join(lines)
    print(text)
    return text
