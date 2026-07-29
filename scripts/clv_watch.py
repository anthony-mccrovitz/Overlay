#!/usr/bin/env python3
"""
scripts/clv_watch.py — Weekly CLV edge watcher.

`chef.py edge` answers "does this market beat the close RIGHT NOW?" (t-test +
Bonferroni + sample floor). This adds the missing dimension: TIME. It snapshots
that gate every week, so you can see:

  - which markets are accruing bets and how fast (velocity),
  - how many weeks until each promising market reaches the sample floor (ETA),
  - the MOMENT a market crosses into (or falls out of) EDGE-CANDIDATE status,
  - whether a "positive" market is a real edge or a best-price mirage (loses to
    Pinnacle's close).

It reuses chef._clv_gate for the statistics — the verdict math never diverges
from `chef.py edge`. This layer only adds history + ETA + crossing alerts.

Run weekly (cron) or ad hoc:
    python3 scripts/clv_watch.py                 # report + record this week's point
    python3 scripts/clv_watch.py --no-record     # report only, don't append history
    python3 scripts/clv_watch.py --min-n 200     # sample floor (default 200)

History: data/clv/clv_watch_history.jsonl (one line per run)
Latest:  data/clv/clv_watch_latest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HISTORY = ROOT / "data" / "clv" / "clv_watch_history.jsonl"
LATEST = ROOT / "data" / "clv" / "clv_watch_latest.json"
SNAPSHOTS = ROOT / "data" / "clv" / "snapshots.json"

# Sport label — delegated to src.config.models._key, the single definition.
# This was a hand-copied mirror that answered "mma" where the registry says
# "ufc", so watch rows could never be joined back to a promotable lane.
def _sport_label(sp: str) -> str:
    try:
        from src.config.models import _key
        return _key(str(sp or "?"), "")[0]
    except Exception:
        return str(sp or "?")


def _has_clv(s: dict) -> bool:
    return any(s.get(k) is not None for k in
               ("clv_novig_pct", "clv_raw_pct", "clv_pct", "line_clv"))


def _velocity() -> dict[str, dict]:
    """Scored picks per (sport·market) in the last 7 / 30 days → weekly accrual."""
    try:
        raw = json.loads(SNAPSHOTS.read_text())
        snaps = raw.get("snapshots", raw) if isinstance(raw, dict) else raw
    except (OSError, ValueError):
        return {}
    cut7 = (date.today() - timedelta(days=7)).isoformat()
    cut30 = (date.today() - timedelta(days=30)).isoformat()
    out: dict[str, dict] = {}
    for s in snaps:
        if not isinstance(s, dict) or not _has_clv(s):
            continue
        key = f"{_sport_label(s.get('sport', '?'))}·{s.get('market') or '(unset)'}"
        d = str(s.get("date") or "")
        v = out.setdefault(key, {"d7": 0, "d30": 0})
        if d >= cut7:
            v["d7"] += 1
        if d >= cut30:
            v["d30"] += 1
    for v in out.values():
        # Prefer the 30d rate (steadier); fall back to 7d×1.
        v["per_week"] = round(max(v["d30"] / 30 * 7, v["d7"]), 1)
    return out


def _rows(min_n: int) -> tuple[list[dict], dict]:
    from chef import _clv_gate
    res = _clv_gate(min_n)
    if res is None:
        raise RuntimeError("snapshots.json unreadable — cannot compute gate")
    return res


def _last_history() -> dict | None:
    if not HISTORY.exists():
        return None
    last = None
    for line in HISTORY.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                last = json.loads(line)
            except ValueError:
                pass
    return last


def _eta_weeks(n: int, min_n: int, per_week: float) -> float | None:
    if n >= min_n:
        return 0.0
    if per_week <= 0:
        return None
    return round((min_n - n) / per_week, 1)


def build(min_n: int) -> dict:
    rows, meta = _rows(min_n)
    vel = _velocity()
    prev = _last_history()
    prev_map = {m["key"]: m for m in (prev or {}).get("markets", [])} if prev else {}

    markets = []
    for r in rows:
        key = f"{r['sport']}·{r['market']}"
        v = vel.get(key, {})
        per_week = v.get("per_week", 0.0)
        eta = _eta_weeks(r["n"], min_n, per_week)
        p = prev_map.get(key)
        # Mirage: positive vs best price but negative vs the sharp (Pinnacle) close.
        mirage = bool(r.get("sharp_n") and r["mean"] > 0
                      and r.get("sharp_mean") is not None and r["sharp_mean"] < 0)
        # Outlier-driven: t-test passes on the mean, but under half the picks
        # actually beat the close — a few big line moves carry it, not a
        # repeatable edge. Not bettable; demote out of the proven bucket.
        outlier_driven = bool(r["is_candidate"] and r.get("beat_pct") is not None
                              and r["beat_pct"] < 50.0)
        # The honest bettable flag: statistically positive AND beats the sharp
        # close AND a majority of picks actually beat it. This is what "proven"
        # means here — crossing alerts and history track THIS, not the raw t-test.
        real_candidate = bool(r["is_candidate"] and not mirage and not outlier_driven)
        crossed = None
        if p is not None:
            if real_candidate and not p.get("is_candidate"):
                crossed = "up"      # newly a real candidate
            elif not real_candidate and p.get("is_candidate"):
                crossed = "down"    # fell out
        markets.append({
            "key": key, "sport": r["sport"], "market": r["market"],
            "n": r["n"], "mean": round(r["mean"], 3), "unit": r["unit"],
            "beat_pct": r.get("beat_pct"),
            "sharp_mean": (round(r["sharp_mean"], 3)
                           if r.get("sharp_mean") is not None else None),
            "sharp_n": r.get("sharp_n"),
            "p_pos": r.get("p_pos"),
            "is_candidate": r["is_candidate"], "real_candidate": real_candidate,
            "verdict": r["verdict"],
            "per_week": per_week, "eta_weeks": eta,
            "delta_n": (r["n"] - p["n"]) if p else None,
            "crossed": crossed, "mirage": mirage, "outlier_driven": outlier_driven,
        })
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": date.today().isoformat(),
        "min_n": meta["min_n"], "alpha": meta["alpha"], "m_tests": meta["m_tests"],
        "prev_date": (prev or {}).get("date"),
        "markets": markets,
    }


def record(report: dict) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    # Store a slim row per market (no verdict prose) to keep history compact.
    # Store real_candidate under "is_candidate" so next run's crossing detection
    # compares against the honest bettable flag, not the raw t-test.
    slim = {
        "ts": report["ts"], "date": report["date"], "min_n": report["min_n"],
        "markets": [{"key": m["key"], "n": m["n"], "mean": m["mean"],
                     "sharp_mean": m["sharp_mean"], "p_pos": m["p_pos"],
                     "is_candidate": m["real_candidate"]}
                    for m in report["markets"]],
    }
    with HISTORY.open("a") as f:
        f.write(json.dumps(slim) + "\n")
    LATEST.write_text(json.dumps(report, indent=2))


def _fmt_eta(eta: float | None) -> str:
    if eta is None:
        return "no accrual"
    if eta <= 0:
        return "AT FLOOR"
    if eta <= 8:
        return f"~{eta:.0f}wk"
    return f"~{eta/4.3:.1f}mo"


def print_report(report: dict) -> None:
    ms = report["markets"]
    cand = [m for m in ms if m["real_candidate"]]
    outliers = [m for m in ms if m.get("outlier_driven")]
    mirage = [m for m in ms if m["mirage"]]
    # "Watch": a REAL sample (kills n<50 flukes), positive lean, actively accruing,
    # and either still building toward the floor within a plausible horizon or at
    # the floor and trending significant. Excludes outlier/mirage markets.
    _WATCH_MIN_N = 50
    _WATCH_ETA_CAP = 26      # weeks (~6 months) — beyond this it's not "soon"
    def _is_watch(m: dict) -> bool:
        if m["real_candidate"] or m.get("outlier_driven") or m["mirage"]:
            return False
        if m["n"] < _WATCH_MIN_N or m["mean"] <= 0 or m["per_week"] <= 0:
            return False
        if m["n"] < report["min_n"]:
            return m["eta_weeks"] is not None and m["eta_weeks"] <= _WATCH_ETA_CAP
        # At/over the floor but not yet a candidate: keep only if trending positive.
        return m.get("p_pos") is not None and m["p_pos"] < 0.20
    watch = [m for m in ms if _is_watch(m)]
    watch.sort(key=lambda m: (m["eta_weeks"] if m["eta_weeks"] is not None else 1e9))
    crossed_up = [m for m in ms if m["crossed"] == "up"]
    crossed_dn = [m for m in ms if m["crossed"] == "down"]

    print(f"\n  ══════════════════════════════════════════════════════════")
    print(f"  CLV EDGE WATCH — {report['date']}"
          + (f"  (prev {report['prev_date']})" if report.get("prev_date") else "  (first run)"))
    print(f"  sample floor n={report['min_n']} · Bonferroni α={report['alpha']:.4f} "
          f"(÷{report['m_tests']})")
    print(f"  ══════════════════════════════════════════════════════════")

    if crossed_up:
        print("\n  🎯 CROSSED INTO EDGE-CANDIDATE THIS PERIOD:")
        for m in crossed_up:
            print(f"     • {m['key']} — mean {m['mean']:+.2f}{m['unit']}, n={m['n']}")
    if crossed_dn:
        print("\n  ⚠  FELL OUT OF EDGE-CANDIDATE THIS PERIOD:")
        for m in crossed_dn:
            print(f"     • {m['key']} — mean {m['mean']:+.2f}{m['unit']}, n={m['n']}")

    print("\n  ── PROVEN EDGE CANDIDATES (cleared t-test + floor + sharp) ──")
    if cand:
        for m in cand:
            sh = (f", sharp {m['sharp_mean']:+.2f}{m['unit']}"
                  if m.get("sharp_mean") is not None else "")
            print(f"     ✅ {m['key']:22} n={m['n']:>4}  mean {m['mean']:+.2f}{m['unit']}"
                  f"  beat {m.get('beat_pct','—')}%{sh}")
        print("     → bet-watch: must ALSO hold positive CLV on NEW picks before real money.")
    else:
        print("     none yet — this is the honest state. More data, not more bets.")

    if outliers:
        print("\n  ⚠  OUTLIER-DRIVEN (t-test positive but <50% beat the close — NOT bettable):")
        for m in outliers:
            print(f"     {m['key']:22} mean {m['mean']:+.2f}{m['unit']} but only "
                  f"{m['beat_pct']}% beat close — a few big moves carry it, not skill.")

    if mirage:
        print("\n  🚫 BEST-PRICE MIRAGES (positive vs best book, NEGATIVE vs Pinnacle):")
        for m in mirage:
            print(f"     {m['key']:22} best {m['mean']:+.2f}{m['unit']} but "
                  f"sharp {m['sharp_mean']:+.2f}{m['unit']} — book-shopping, not skill.")

    print("\n  ── WATCH LIST (positive lean, building toward a verdict) ──")
    if watch:
        print(f"     {'market':22}{'n':>5}{'mean':>9}{'/wk':>6}  ETA→floor")
        for m in watch[:10]:
            d = f"  (+{m['delta_n']})" if m.get("delta_n") else ""
            print(f"     {m['key']:22}{m['n']:>5}{m['mean']:>+8.2f}{m['unit']}"
                  f"{m['per_week']:>6}  {_fmt_eta(m['eta_weeks'])}{d}")
    else:
        print("     nothing with a positive lean accruing right now.")

    print(f"\n  history: {HISTORY.relative_to(ROOT)}  ·  run weekly to track velocity")
    print(f"  ══════════════════════════════════════════════════════════\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-n", type=int, default=200, help="sample floor (default 200)")
    ap.add_argument("--no-record", action="store_true",
                    help="print report but do NOT append to history")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON only")
    args = ap.parse_args()

    report = build(args.min_n)
    if not args.no_record:
        record(report)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
