"""
src/analytics/calibration_gate.py — Edge honesty gate (plan item X1).

THE PROBLEM this fixes: models emit `edge_pct = model_prob − implied_prob` and we
trust it at face value. A systematically overconfident model then manufactures
edges that don't exist — the record showed tennis totals claiming +43% while
winning 38%, WNBA spreads claiming +27% while winning 43%. Across the whole book,
*claimed edge was inversely correlated with realized performance.*

THE FIX: shrink every model's claimed edge by how much of it has HISTORICALLY
materialized, out-of-sample, on that (sport, market).

  realized = mean(win_indicator − implied_prob)   ← how much we actually beat the price
  claimed  = mean(model_prob   − implied_prob)     ← how much the model SAID we would
  k = clamp(realized / claimed, 0, 1)              ← fraction of the claim that came true

- TRUSTED segment (n ≥ MIN_TRUST): stored edge = raw_edge × k. A model that has
  realized none of its claimed edge gets k≈0 and stops producing phantom picks.
- UNPROVEN segment (n < MIN_TRUST): we have no right to trust a large edge, so the
  magnitude is hard-capped at HARD_CAP; if there's partial evidence of
  overconfidence (n ≥ PARTIAL_N and k < 1) that shrink is applied on top.

The table is computed from graded history and cached to disk (compute_table());
normalize_pick() reads the cache and calibrates *pending* picks only, so historical
graded edges are never rewritten and the public record is untouched.

Refresh the table after grading:  python3 -m src.analytics.calibration_gate
"""
from __future__ import annotations

import json
from pathlib import Path

PICKS_FILE = Path("data/pnl/picks.json")
TABLE_FILE = Path("data/models/calibration.json")

# A segment is TRUSTED once it has this many settled picks; below it we cap
# magnitude instead of trusting the model's number.
MIN_TRUST = 100
# Some evidence of overconfidence is actionable even below MIN_TRUST.
PARTIAL_N = 20
# Hard ceiling (percentage points) on an unproven market's stored edge.
HARD_CAP = 8.0
# Claimed edges smaller than this (pp) are noise — nothing to calibrate.
_MIN_CLAIM_PP = 0.5

_table_cache: dict | None = None


# ── canonical (sport, market) key ────────────────────────────────────────────
def _key(sport: str, market: str) -> str:
    """Canonical "sport::market" key, delegated to src.config.models._key.

    This was a hand-copied mirror of that function whose own comment claimed it
    mirrored it — and it had drifted. It collapsed every club league to a single
    "soccer" bucket while the registry keys them per league, so the edge-shrink
    record for MLS was written to `soccer::moneyline` and every lookup for
    `usa_mls::moneyline` came back empty. The lane reported "no edge-shrink
    record" while its record existed under a name nothing asked for.

    Sixth module found re-deriving this mapping today. Delegate; never re-copy.
    """
    try:
        from src.config.models import _key as _registry_key
        s, _ = _registry_key(sport or "", "")
    except Exception:                                   # keep the gate usable
        s = (sport or "").lower()
    return f"{s}::{(market or '').lower()}"


def _implied(odds: float) -> float | None:
    """American odds → implied probability (with vig)."""
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    if o == 0:
        return None
    return 100.0 / (o + 100.0) if o > 0 else abs(o) / (abs(o) + 100.0)


# ── table construction ───────────────────────────────────────────────────────
def compute_table(picks_path: Path | str = PICKS_FILE,
                  out_path: Path | str = TABLE_FILE) -> dict:
    """Recompute the per-segment calibration table from graded history and cache it."""
    picks_path = Path(picks_path)
    try:
        raw = json.loads(picks_path.read_text())
    except (OSError, ValueError):
        return {}
    picks = raw.get("picks", raw) if isinstance(raw, dict) else raw

    agg: dict[str, dict[str, float]] = {}
    for p in picks:
        if p.get("result") not in ("win", "loss"):   # skip pending + pushes
            continue
        if p.get("tainted"):
            # Produced by a known-broken mechanism (degenerate calibrator,
            # team-blind ratings…) — the gate must not learn a segment's k
            # from picks the segment's own bug generated.
            continue
        mp = p.get("model_prob")
        imp = _implied(p.get("odds"))
        if mp is None or imp is None:
            continue
        try:
            mp = float(mp)
        except (TypeError, ValueError):
            continue
        k = _key(p.get("sport", ""), p.get("market", ""))
        a = agg.setdefault(k, {"n": 0.0, "claimed": 0.0, "realized": 0.0})
        a["n"] += 1
        a["claimed"] += (mp - imp) * 100.0                       # pp
        a["realized"] += ((1.0 if p["result"] == "win" else 0.0) - imp) * 100.0

    table: dict[str, dict] = {}
    for k, a in agg.items():
        n = int(a["n"])
        claimed = a["claimed"] / n
        realized = a["realized"] / n
        table[k] = {
            "n": n,
            "claimed_pp": round(claimed, 3),
            "realized_pp": round(realized, 3),
            "k": round(_k_from(n, claimed, realized), 4),
        }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(table, indent=2, sort_keys=True))
    global _table_cache
    _table_cache = table
    return table


def _k_from(n: int, claimed: float, realized: float) -> float:
    """Shrink factor from segment stats. See module docstring."""
    if claimed < _MIN_CLAIM_PP:      # model claims ~no edge → nothing to shrink
        return 1.0
    return max(0.0, min(realized / claimed, 1.0))


def _load_table() -> dict:
    global _table_cache
    if _table_cache is None:
        try:
            _table_cache = json.loads(TABLE_FILE.read_text())
        except (OSError, ValueError):
            _table_cache = {}
    return _table_cache



# ── the gate ─────────────────────────────────────────────────────────────────

def is_retired_market(sport: str, market: str) -> bool:
    """True when a segment's own history has ruled it dead: with a trusted
    sample (n ≥ MIN_TRUST) the realized fraction of claimed edge is k = 0 —
    the model has NO signal here. Used to stop LOGGING new picks in flood
    markets (700 batter props/day echoing the book line at r≈0.98); markets
    that come back to life in a future table refresh un-retire automatically.
    """
    row = _load_table().get(_key(sport, market))
    if not row:
        return False
    return int(row.get("n", 0)) >= MIN_TRUST and float(row.get("k", 1.0)) == 0.0


def calibrate_edge(sport: str, market: str, raw_edge_pct: float | None) -> float | None:
    """Map a model's claimed edge (pp) to its calibration-honest value.

    TRUSTED segment → raw × realization factor k.
    UNPROVEN segment → magnitude capped at HARD_CAP, times partial-evidence k.
    """
    if raw_edge_pct is None:
        return None
    try:
        raw = float(raw_edge_pct)
    except (TypeError, ValueError):
        return None

    row = _load_table().get(_key(sport, market))
    n = int(row.get("n", 0)) if row else 0

    if n >= MIN_TRUST:
        return round(raw * float(row.get("k", 1.0)), 2)

    # Unproven: cap the magnitude first (sign preserved).
    capped = max(-HARD_CAP, min(raw, HARD_CAP))
    if row and n >= PARTIAL_N:
        k = _k_from(n, row.get("claimed_pp", 0.0), row.get("realized_pp", 0.0))
        capped *= k
    return round(capped, 2)


if __name__ == "__main__":   # refresh the cached table
    t = compute_table()
    trusted = {k: v for k, v in t.items() if v["n"] >= MIN_TRUST}
    print(f"[calibration_gate] wrote {len(t)} segments → {TABLE_FILE} "
          f"({len(trusted)} trusted, n≥{MIN_TRUST})")
    for k in sorted(t, key=lambda x: -t[x]["n"])[:20]:
        r = t[k]
        print(f"  {k:38s} n={r['n']:4d}  claim={r['claimed_pp']:+6.1f}pp  "
              f"real={r['realized_pp']:+6.1f}pp  k={r['k']:.2f}")
