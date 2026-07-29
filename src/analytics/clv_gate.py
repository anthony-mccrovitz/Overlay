"""
clv_gate — the statistical CLV promotion gate (extracted from chef.py).

Shared by `chef.py edge` (display), `chef.py promote` (enforcement), and the
auto-promoter, so all three use one gate and can never diverge. For each
(sport, market): a t-test of mean CLV vs 0, a minimum-sample floor, and a
Bonferroni correction for the number of markets tested.

Returns (rows, meta) or None if snapshots are unreadable. Each row includes
`is_candidate` (cleared the gate), `sharp_mean`/`sharp_beat_pct` (scored vs
Pinnacle's close — the honest benchmark), and `beat_pct`.
"""
from __future__ import annotations

import json
from pathlib import Path


_TAINT_CACHE: set | None = None


def _taint_index() -> set:
    """Keys of every TAINTED pick, for filtering snapshots.

    Snapshots carry no taint flag of their own, so they are matched back to the
    ledger on the fields both records share: canonical sport, market, date and
    bet side. Cached because clv_gate is called repeatedly by the audit.
    """
    global _TAINT_CACHE
    if _TAINT_CACHE is not None:
        return _TAINT_CACHE
    try:
        raw = json.loads(Path("data/pnl/picks.json").read_text())
        picks = raw.get("picks", raw) if isinstance(raw, dict) else raw
    except (json.JSONDecodeError, ValueError, OSError):
        _TAINT_CACHE = set()
        return _TAINT_CACHE
    from src.config.models import _key
    out = set()
    for p in picks:
        if not isinstance(p, dict) or not p.get("tainted"):
            continue
        try:
            sport = _key(str(p.get("sport") or ""), "")[0]
        except Exception:
            sport = str(p.get("sport") or "")
        out.add((sport, str(p.get("market") or "").lower(),
                 str(p.get("date")), str(p.get("team") or "").lower().strip()))
    _TAINT_CACHE = out
    return out


def _is_tainted_snapshot(s: dict) -> bool:
    if not isinstance(s, dict):
        return False
    from src.config.models import _key
    try:
        sport = _key(str(s.get("sport") or ""), "")[0]
    except Exception:
        sport = str(s.get("sport") or "")
    key = (sport, str(s.get("market") or "").lower(),
           str(s.get("date")), str(s.get("team") or "").lower().strip())
    return key in _taint_index()


def clv_gate(min_n: int = 200):
    """Compute the CLV promotion gate for every (sport, market).

    Shared by `chef.py edge` (display) and `chef.py promote` (enforcement) so the
    two can never diverge. Returns (rows, meta) or None if snapshots unreadable.

    Each row: {sport, market, label, n, mean, unit, rmean, p_pos, verdict,
               is_candidate}. `sport` is the short label (mlb/nba/wc/...), which
               matches src.config.models._key so promotion targets line up.
    meta: {min_n, alpha, m_tests}.
    """
    import math, statistics
    from datetime import date as _date, timedelta
    from collections import defaultdict

    try:
        snaps = json.loads(Path("data/clv/snapshots.json").read_text())
        snaps = snaps.get("snapshots", snaps) if isinstance(snaps, dict) else snaps
    except (json.JSONDecodeError, ValueError, OSError):
        return None

    # Drop snapshots belonging to TAINTED picks.
    #
    # The taint flag lives on the pick, never on the snapshot, so the CLV
    # pipeline was the one place it was never applied — calibration,
    # market_stats and the confidence signal all filter it. That let picks from
    # a known-broken mechanism (a degenerate calibrator that flattened every game
    # to one probability, team-blind WNBA ratings) set the beat-close rate for
    # their own lane. Contamination was concentrated exactly where the verdicts
    # were shakiest: wnba/spread 89%, wnba/total 87%, wnba/moneyline 55%,
    # mlb/f5_total 47%, mlb/moneyline 42%. A model cannot be allowed to grade
    # itself on output it produced while broken.
    snaps = [s for s in snaps if not _is_tainted_snapshot(s)]

    def clv_val(s):
        # natural per-market metric: prob markets in %, line markets in points.
        # Prob markets prefer the vig-CONSISTENT variants: novig (fair close vs
        # fair entry) → raw (raw close vs raw entry, vig cancels) → legacy
        # clv_pct (fair close vs VIGGED entry — biased ~-2%, kept as last
        # resort for snapshots that predate the fix).
        for k in ("clv_novig_pct", "clv_raw_pct", "clv_pct"):
            if s.get(k) is not None:
                return float(s[k]), "%"
        if s.get("line_clv") is not None:
            return float(s["line_clv"]), "pt"
        return None, None

    try:
        from src.analytics.clv_tracker import _normalize_sport
    except Exception:
        def _normalize_sport(x): return x

    # Short sport label. This MUST be src.config.models._key itself, not a
    # re-implementation of it: the label is the join key between a CLV row and a
    # promotable registry entry, and the two drifted badly.
    #
    # The old local copy produced tournament-scoped labels truncated to 14 chars
    # ('atp-french_ope', 'wta-bad_hombur', 'golf-the_open_'), which broke the
    # join two ways. Tennis fragmented across six tournament rows that each
    # stayed under the n=30 floor, so a sport with 246 snapshots reported ZERO
    # measurable CLV; and 'mma'/'golf-*' never matched the registry's 'ufc'/'pga'
    # at all. Those lanes looked un-instrumented when they were merely mislabelled.
    from src.config.models import _key as _registry_key

    def _sport_label(sp: str) -> str:
        return _registry_key(_normalize_sport(str(sp or "?")), "")[0]

    recent_cut = (_date.today() - timedelta(days=30)).isoformat()
    # Key on (sport, market) — NOT market alone. Pooling sports is Simpson's
    # paradox: a real tennis-ML edge gets washed out by MLB ML, a soccer outlier
    # drags the blend. An edge is model+sport specific, so each gets its own row.
    by_mkt: dict = defaultdict(list)
    for s in snaps:
        if not isinstance(s, dict):
            continue
        v, unit = clv_val(s)
        if v is None:
            continue
        mkt = s.get("market") or "(unset)"
        key = (_sport_label(s.get("sport", "?")), mkt)
        # sharp = same pick scored vs PINNACLE's close (the honest benchmark);
        # None when Pinnacle didn't price the game or the snapshot predates sharp
        # capture. Unit-matched to the best-price metric: prob markets use the
        # prob-CLV (%), line markets (spread/total/prop) use the line-CLV (pts).
        # Same vig-consistency ladder as clv_val: novig → raw → legacy.
        if unit == "%":
            sharp = next((s[k] for k in ("clv_novig_sharp_pct", "clv_raw_sharp_pct",
                                         "clv_sharp_pct") if s.get(k) is not None), None)
        else:
            sharp = s.get("line_clv_sharp")
        by_mkt[key].append((v, unit, s.get("date", ""), sharp))

    testable = [k for k, vals in by_mkt.items() if len(vals) >= min_n]
    m_tests = max(1, len(testable))
    alpha = 0.05 / m_tests  # Bonferroni-corrected for the number of markets tested

    def p_gt0(mean, sd, n):
        """One-sided p-value that the true mean > 0."""
        if n < 2 or sd == 0:
            return 1.0
        t = mean / (sd / math.sqrt(n))
        try:
            from scipy import stats
            return float(stats.t.sf(t, n - 1))
        except Exception:
            return 0.5 * math.erfc(t / math.sqrt(2))  # normal approx

    rows = []
    for key in sorted(by_mkt, key=lambda k: -len(by_mkt[k])):
        sport, mkt = key
        vals = by_mkt[key]
        n = len(vals)
        unit = vals[0][1]
        xs = [v for v, _, _, _ in vals]
        mean = statistics.fmean(xs)
        recent = [v for v, _, d, _ in vals if d and d >= recent_cut]
        rmean = statistics.fmean(recent) if recent else None
        # Beat-rate: share of picks that beat the (best-price) close. 50% is the
        # coin-flip line; a real edge sits meaningfully above it. Reported next to
        # the mean because a high mean dragged by a few outliers ≠ a repeatable edge.
        # FLATS (line didn't move / exact-same price) are EXCLUDED: a stuck line is
        # neutral, not a loss. Counting it as a loss unfairly punishes sticky
        # markets — MLB totals sit flat ~46% of the time vs ~4% for moneyline, so
        # including flats made totals look like 32% beat when the real directional
        # rate (among lines that moved) is 59%. Beat-rate = accuracy when it moved.
        moved = [x for x in xs if abs(x) > 1e-9]
        beat_pct = round(sum(1 for x in moved if x > 0) / len(moved) * 100, 1) if moved else None
        flat_pct = round((n - len(moved)) / n * 100, 1) if n else None
        # Sharp side: same picks scored vs Pinnacle's close. This is the honest test.
        sharps = [sp for _, _, _, sp in vals if sp is not None]
        sharp_n = len(sharps)
        sharp_mean = statistics.fmean(sharps) if sharps else None
        sharp_moved = [x for x in sharps if abs(x) > 1e-9]
        sharp_beat_pct = (round(sum(1 for x in sharp_moved if x > 0) / len(sharp_moved) * 100, 1)
                          if sharp_moved else None)
        p_pos = None
        is_candidate = False
        if n < min_n:
            verdict = f"insufficient (need {min_n})"
        else:
            sd = statistics.pstdev(xs)
            p_pos = p_gt0(mean, sd, n)
            p_neg = p_gt0(-mean, sd, n)
            if mean > 0 and p_pos < alpha and (rmean is None or rmean > 0):
                verdict = "✅ EDGE CANDIDATE → out-of-sample watch"
                is_candidate = True
            elif mean < 0 and p_neg < alpha:
                verdict = "❌ negative — fade or stop modeling"
            else:
                verdict = "noise (no edge)"
        rows.append({
            "sport": sport, "market": mkt, "label": f"{sport} · {mkt}",
            "n": n, "mean": mean, "unit": unit, "rmean": rmean,
            "p_pos": p_pos, "verdict": verdict, "is_candidate": is_candidate,
            "beat_pct": beat_pct, "flat_pct": flat_pct,
            "sharp_n": sharp_n, "sharp_mean": sharp_mean,
            "sharp_beat_pct": sharp_beat_pct,
            # non-flat sharp sample: the REAL denominator behind sharp_beat_pct.
            # A high beat on a tiny moved-sample (props sit ~99% flat) is noise.
            "sharp_moved_n": len(sharp_moved),
        })
    return rows, {"min_n": min_n, "alpha": alpha, "m_tests": m_tests}
