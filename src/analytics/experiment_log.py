"""
experiment_log — the model-tuning ledger: baseline → change → re-measure → keep/revert.

The discipline for improving an algo without fooling ourselves:

  1. SNAPSHOT the algo's current state as a tagged version (record()).
  2. Change ONE thing, re-fit/regenerate, snapshot again with a new tag.
  3. COMPARE the two — did the honest metric (CLV first, then ROI) improve?
  4. KEEP the new version, or REVERT to the stashed old one.

Every snapshot is appended to data/experiments/{sport}__{market}.json, so the
full history of what we tried and whether it worked is permanent — nothing is
lost, and a change that made things worse is provable, not guessed.

The centerpiece metric is the CONFIDENCE SIGNAL: bucket graded picks by the
model's own stated probability and check whether higher confidence actually
means a higher win rate. If it doesn't, the model's probabilities carry no
signal — no amount of threshold-tuning saves it, and the honest call is rebuild
or cut. (This is exactly what condemned MLB NRFI: WR was flat ~43% across every
confidence tercile.)
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path

from src.config.models import _key
from src.analytics.market_stats import market_stats, _load_picks, _dec

_EXPERIMENTS_DIR = Path("data/experiments")
_PNL_FILE = Path("data/pnl/picks.json")


@dataclass
class ConfidenceSignal:
    """Does higher model confidence mean a higher win rate? The 'is there
    real signal' test — a model whose confidence doesn't predict outcomes is
    unfixable by tuning."""

    n: int = 0
    buckets: list[dict] = field(default_factory=list)  # [{lo,hi,n,wr}]
    monotonic: bool | None = None   # WR rises with confidence across buckets?
    spread: float | None = None     # WR(top bucket) − WR(bottom bucket), pts
    verdict: str = "insufficient-data"


def _confidence_signal(graded: list[dict], n_buckets: int = 3) -> ConfidenceSignal:
    """Does a higher model_prob actually mean a higher win rate?

    TAINTED picks are excluded by the callers, and must be: they came from a
    known-broken mechanism (a degenerate calibrator that flattened every game to
    one probability, team-blind ratings), so their model_prob is the previous
    bug's output. Reading a confidence signal off them measures the bug, not the
    model — WNBA spread read a confident "inverted (-34pts)" from 65 tainted rows
    while holding only 8 clean ones, which would have justified building a fade
    strategy on noise from a model that no longer exists.
    """
    pts = [(p["model_prob"], p["result"]) for p in graded
           if not p.get("tainted")
           if isinstance(p.get("model_prob"), (int, float))
           and p["result"] in ("win", "loss")]
    sig = ConfidenceSignal(n=len(pts))
    if len(pts) < 30:
        return sig  # too few to say anything honest
    pts.sort(key=lambda t: t[0])
    size = len(pts) // n_buckets
    wrs: list[float] = []
    for b in range(n_buckets):
        lo_i = b * size
        hi_i = len(pts) if b == n_buckets - 1 else (b + 1) * size
        chunk = pts[lo_i:hi_i]
        w = sum(1 for _, r in chunk if r == "win")
        wr = w / len(chunk) * 100
        wrs.append(wr)
        sig.buckets.append({
            "lo": round(chunk[0][0], 3), "hi": round(chunk[-1][0], 3),
            "n": len(chunk), "wr": round(wr, 1),
        })
    sig.spread = round(wrs[-1] - wrs[0], 1)
    sig.monotonic = all(wrs[i] <= wrs[i + 1] + 1e-9 for i in range(len(wrs) - 1))
    # Noise-aware verdict. The spread between two ~m-sized bucket win rates has a
    # standard error of ~sqrt(2·0.25/m); a spread only means something if it
    # clears ~2 SE. Otherwise it's sampling noise, not (anti-)signal — calling a
    # −4pt wobble "inverted" would tell us to cut a profitable model.
    import math
    m = min(b["n"] for b in sig.buckets)
    thresh = round(2 * math.sqrt(2 * 0.25 / m) * 100, 1)  # ~2·SE in WR points
    if sig.spread >= thresh:
        sig.verdict = "real-signal" if sig.monotonic else "noisy-but-present"
    elif sig.spread <= -thresh:
        sig.verdict = "inverted"      # confidently worse — the model is backwards
    else:
        sig.verdict = "flat"          # within noise: confidence doesn't discriminate
    return sig


@dataclass
class AlgoSnapshot:
    sport: str
    market: str
    tag: str
    date: str
    note: str = ""
    n: int = 0
    record: str = "0-0"
    wr: float | None = None
    roi: float | None = None
    clv: float | None = None
    clv_n: int = 0
    avg_odds: str = "—"
    confidence: dict = field(default_factory=dict)


def algo_snapshot(sport: str, market: str, tag: str, note: str = "",
                  pnl_file: Path = _PNL_FILE) -> AlgoSnapshot:
    """Compute the current state of one algo — the metrics we tune against."""
    csport, cmarket = _key(sport, market)[0], market.lower()
    st = market_stats(pnl_file).get((csport, cmarket))
    picks = _load_picks(pnl_file)
    graded = [p for p in picks
              if _key(p.get("sport", ""), "")[0] == csport
              and (p.get("market") or "").lower() == cmarket
              and p.get("result") in ("win", "loss")
              and p.get("odds") not in (None, 0)
              and not p.get("tainted")]
    sig = _confidence_signal(graded)
    return AlgoSnapshot(
        sport=csport, market=cmarket, tag=tag, date=date.today().isoformat(),
        note=note,
        n=st.n if st else 0,
        record=st.record if st else "0-0",
        wr=round(st.wr, 1) if st and st.wr is not None else None,
        roi=round(st.roi, 1) if st and st.roi is not None else None,
        clv=round(st.clv, 2) if st and st.clv is not None else None,
        clv_n=st.clv_n if st else 0,
        avg_odds=st.avg_odds if st else "—",
        confidence=asdict(sig),
    )


def _path(sport: str, market: str) -> Path:
    csport = _key(sport, market)[0]
    return _EXPERIMENTS_DIR / f"{csport}__{market.lower()}.json"


def record(sport: str, market: str, tag: str, note: str = "",
           pnl_file: Path = _PNL_FILE) -> AlgoSnapshot:
    """Snapshot the algo now and append it to its experiment history."""
    snap = algo_snapshot(sport, market, tag, note, pnl_file)
    path = _path(sport, market)
    path.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(path.read_text()) if path.exists() else []
    history.append(asdict(snap))
    path.write_text(json.dumps(history, indent=2))
    return snap


def history(sport: str, market: str) -> list[dict]:
    path = _path(sport, market)
    return json.loads(path.read_text()) if path.exists() else []


@dataclass
class FloorRec:
    """A confidence-floor recommendation for one lane, from a backtest sweep."""
    sport: str
    market: str
    n_base: int
    roi_base: float
    floor: float | None = None
    n_kept: int = 0
    wr_kept: float | None = None
    roi_kept: float | None = None
    robust: bool = False
    verdict: str = "REBUILD — no confidence floor helps"


def _roi(subset: list[dict]) -> tuple[int, float, float]:
    if not subset:
        return (0, 0.0, 0.0)
    w = sum(1 for x in subset if x["result"] == "win")
    pnl = sum((_dec(x["odds"]) - 1) if x["result"] == "win" else -1 for x in subset)
    return (len(subset), w / len(subset) * 100, pnl / len(subset) * 100)


def optimize_floor(sport: str, market: str, pnl_file: Path = _PNL_FILE,
                   min_kept: int = 100, min_roi: float = 2.0) -> FloorRec:
    """Sweep model_prob floors for one lane and recommend the best ROBUST one.

    Robust = the chosen floor AND its neighbours (±0.02, ±0.04) are all
    profitable (a plateau, not an overfit spike) and it retains ≥ min_kept
    picks. Anything thinner is flagged, never auto-applied — a floor fit to a
    few dozen picks is just variance."""
    picks = _load_picks(pnl_file)
    lane = [p for p in picks
            if _key(p.get("sport", ""), "")[0] == _key(sport, market)[0]
            and (p.get("market") or "").lower() == market.lower()
            and p.get("result") in ("win", "loss")
            and p.get("odds") not in (None, 0)
            and isinstance(p.get("model_prob"), (int, float))]
    n_base, _, roi_base = _roi(lane)
    rec = FloorRec(sport=_key(sport, market)[0], market=market.lower(),
                   n_base=n_base, roi_base=round(roi_base, 1))
    if n_base < 60:
        rec.verdict = "WAIT — need more graded picks"
        return rec

    grid = [round(0.50 + 0.02 * i, 2) for i in range(16)]  # 0.50 .. 0.80
    roi_at = {f: _roi([x for x in lane if x["model_prob"] >= f]) for f in grid}

    # Best floor: highest ROI among those clearing min_roi and retaining enough.
    candidates = [(f, *roi_at[f]) for f in grid
                  if roi_at[f][2] >= min_roi and roi_at[f][0] >= min_kept]
    best_thin = [(f, *roi_at[f]) for f in grid
                 if roi_at[f][2] >= min_roi and roi_at[f][0] >= 25]
    if candidates:
        f, n, wr, roi = max(candidates, key=lambda t: t[3])
        neigh = [f - 0.04, f - 0.02, f, f + 0.02, f + 0.04]
        robust = all(roi_at.get(round(g, 2), (0, 0, -99))[2] > 0 for g in neigh
                     if round(g, 2) in roi_at)
        rec.floor, rec.n_kept, rec.wr_kept, rec.roi_kept = f, n, round(wr, 1), round(roi, 1)
        rec.robust = robust
        rec.verdict = ("TUNE-APPLY — robust profitable floor" if robust
                       else "TUNE-CHECK — profitable but not a stable plateau")
    elif best_thin:
        f, n, wr, roi = max(best_thin, key=lambda t: t[3])
        rec.floor, rec.n_kept, rec.wr_kept, rec.roi_kept = f, n, round(wr, 1), round(roi, 1)
        rec.verdict = "TUNE-THIN — profitable subset too small; forward-validate"
    return rec


@dataclass
class Triage:
    sport: str
    market: str
    n: int
    roi: float | None
    clv: float | None
    clv_n: int
    signal: str            # confidence verdict
    spread: float | None   # WR(top) − WR(bottom) confidence buckets
    call: str              # what to do about it


def _triage_call(roi, clv, signal, ev=None) -> str:
    """The action a lane's numbers imply — the honest keep/tune/cut recommendation.

    Money comes first: a profitable or +CLV lane is never a 'cut', whatever the
    confidence test says (that test is a supporting diagnostic for LOSING lanes,
    not an override of real results). Only lanes losing on BOTH ROI and CLV, with
    no usable confidence signal, are rebuild/cut candidates.

    EV QUALIFIES 'PROFITABLE' (added 2026-07-30). Realised ROI on a few hundred
    bets is a noisy read on a lane's edge, and this function was calling
    mlb/f5_total "KEEP — profitable" on +1.9% ROI while its mean EV against the
    close was -5.74% (t=-10.4) and the promotion gate blocked it. Two tools
    giving opposite advice about the same lane is how a losing model gets funded
    by whichever screen someone happened to open.

    So a lane that is profitable-but-negative-EV is now flagged rather than
    endorsed: the profit is real and belongs on the record, but it is variance
    sitting on top of a negative edge, and scaling it is the mistake."""
    profitable = roi is not None and roi > 1.0
    beats_close = clv is not None and clv > 0.5
    ev_negative = ev is not None and ev < 0
    if signal == "insufficient-data":
        return "WAIT — need ≥30 graded picks"
    if profitable and ev_negative:
        return (f"⚠ DON'T SCALE — +ROI but EV {ev:+.1f}% vs close "
                f"(profit is variance on a negative edge)")
    if profitable:
        return "KEEP — profitable (verify edge is real, don't scale on variance)"
    if beats_close:
        return "TUNE — beats the close, fix conversion to ROI"
    # Losing on both ROI and CLV from here down.
    if signal in ("real-signal", "noisy-but-present"):
        return "TUNE — has signal but losing; recalibrate / fix side-selection"
    if signal == "inverted":
        return "CUT/REBUILD — confidence is backwards (broken)"
    return "CUT/REBUILD — no signal, losing on ROI + CLV"


def triage(pnl_file: Path = _PNL_FILE, min_n: int = 30) -> list[Triage]:
    """Run the confidence-signal test across every lane with enough data — the
    program-wide map of which algos are worth tuning vs dead on arrival."""
    picks = _load_picks(pnl_file)
    stats = market_stats(pnl_file)
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in picks:
        if p.get("tainted"):
            continue
        key = (_key(p.get("sport", ""), "")[0], (p.get("market") or "").lower())
        if p.get("result") in ("win", "loss") and p.get("odds") not in (None, 0):
            groups.setdefault(key, []).append(p)

    # One EV implementation, shared with the promotion gate and clv_gate, so the
    # triage screen and the gate cannot give opposite advice about a lane.
    try:
        from src.analytics.ev_gate import ev_by_lane
        _ev = ev_by_lane()
    except Exception:
        _ev = {}

    out: list[Triage] = []
    for (sport, market), graded in groups.items():
        if len(graded) < min_n:
            continue
        st = stats.get((sport, market))
        sig = _confidence_signal(graded)
        roi = round(st.roi, 1) if st and st.roi is not None else None
        clv = round(st.clv, 2) if st and st.clv is not None else None
        out.append(Triage(
            sport=sport, market=market, n=len(graded), roi=roi,
            clv=clv, clv_n=st.clv_n if st else 0,
            signal=sig.verdict, spread=sig.spread,
            call=_triage_call(roi, clv, sig.verdict,
                              ev=(_ev.get((sport, market)).mean_ev_pct
                                  if _ev.get((sport, market)) else None)),
        ))
    # Real signal first, then by ROI — the tunable, promising lanes on top.
    _rank = {"real-signal": 0, "noisy-but-present": 1, "flat": 2, "inverted": 3,
             "insufficient-data": 4}
    out.sort(key=lambda t: (_rank.get(t.signal, 9), -(t.roi or -999)))
    return out
