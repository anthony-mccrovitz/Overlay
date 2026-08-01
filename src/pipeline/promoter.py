"""
promoter — the auto-validation engine (the factory's quality control).

Runs nightly. Scores every registry lane on realized ROI (the ledger) AND
closing-line value vs the SHARP market (Pinnacle), then:

  • PROMOTES a shadow lane to live only if `model_standard.clears_promotion_gate`
    says so. That function is the ONLY promote decision in the system; this
    module asks it and reports the answer. It does not carry its own copy of the
    criterion — it used to, and the copy went stale when the gate moved from
    beat-close to EV on 2026-07-30 (see _decide).
  • DEMOTES a live lane back to shadow the moment it goes cold (negative settled
    ROI or negative sharp CLV on a real sample). Demotion only removes risk, so
    it fires more readily than promotion.

Default is a DRY-RUN report — it recommends, it doesn't bless. `--apply` writes
the decisions to promotions.json (which the registry already reads). This keeps
the "flags them, doesn't auto-bet them" discipline unless you opt in.

CLI:
    python3 -m src.pipeline.promoter            # report
    python3 -m src.pipeline.promoter --apply    # enact promotions/demotions
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from src.config.models import (
    MODELS, _key, model_status, model_label,
    set_promotion, is_clv_validated,
)
from src.analytics.clv_gate import clv_gate
from src.analytics.market_stats import market_stats

# DEMOTION thresholds only. Promotion has no thresholds here by design — they
# live in model_standard, the single source. Demotion keeps its own because it
# only ever REMOVES risk, so a lane going cold should fall out faster than the
# promote gate would re-admit it.
DEMOTE_MIN_N = 30           # sample for a single-signal demotion (ROI or CLV alone)
DEMOTE_CONFLUENCE_N = 10    # lower bar when ROI AND sharp CLV agree it's cold


@dataclass
class PromotionAction:
    sport: str
    market: str
    current: str            # live / incubating
    recommended: str        # live / incubating
    reason: str
    evidence: dict = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.current != self.recommended

    @property
    def kind(self) -> str:
        if not self.changed:
            return "hold"
        return "promote" if self.recommended == "live" else "demote"


def _gate_lookup(min_n: int) -> dict[tuple[str, str], dict]:
    """CLV-gate rows keyed by canonical (sport, market) so they join the registry.
    Harmonizes gate sport labels (e.g. 'mma' → 'ufc') through _key."""
    res = clv_gate(min_n)
    if res is None:
        return {}
    rows, _meta = res
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        out[_key(r["sport"], r["market"])] = r
    return out


def _decide(status: str, row: dict | None, st,
            sport: str = "", market: str = "") -> tuple[str, str]:
    """Return (recommended_status, reason) for one lane."""
    roi = st.roi if st else None
    roi_n = st.n if st else 0

    if status == "live":
        sharp = row.get("sharp_mean") if row else None
        sharp_n = row.get("sharp_n", 0) if row else 0
        roi_cold = roi is not None and roi < 0
        clv_cold = sharp is not None and sharp < 0
        # Confluence: BOTH realized ROI and the sharp close say cold, on a modest
        # sample. The agreement is strong evidence even below the single-signal
        # floor — and demotion only removes risk, so it fires readily.
        if roi_cold and clv_cold and roi_n >= DEMOTE_CONFLUENCE_N and sharp_n >= DEMOTE_CONFLUENCE_N:
            return "incubating", f"cold both ways: {roi:+.1f}% ROI, {sharp:+.2f} sharp CLV"
        # Either signal alone, but only on a full sample.
        if roi_cold and roi_n >= DEMOTE_MIN_N:
            return "incubating", f"cold: {roi:+.1f}% ROI over {roi_n}"
        if clv_cold and sharp_n >= DEMOTE_MIN_N:
            return "incubating", f"−CLV vs sharp close ({sharp:+.2f})"
        return "live", "holding — still positive"

    # Shadow → live is NOT this module's decision to make. It delegates to
    # model_standard.clears_promotion_gate, the single source, for the reason
    # the invariant exists: this function used to carry its own copy of the
    # PRE-2026-07-30 criterion (beat-close >= 55%, positive sharp mean, ROI on
    # n>=30). That copy had no EV floor and no independence check, so with
    # --apply it could write `status=live` for exactly the lanes the real gate
    # refuses — mlb/moneyline (+0.09% EV over 1,132 bets, the lane that MOTIVATED
    # the EV floor) and any lane whose sample is 4 clustered days. A promoted
    # lane's picks become card_pick=True, so the divergence spends real money.
    from src.config.model_standard import clears_promotion_gate
    ok, why = clears_promotion_gate(sport, market)
    return ("live" if ok else status), ("clears gate: " + why if ok
                                        else "holding — " + why)


def evaluate(min_n: int = 200) -> list[PromotionAction]:
    """Score every non-retired registry lane. Pure — writes nothing."""
    gate = _gate_lookup(min_n)
    stats = market_stats()
    actions: list[PromotionAction] = []
    for (sport, market) in MODELS:
        status = model_status(sport, market)
        if status == "retired":
            continue
        row = gate.get((sport, market))
        st = stats.get((sport, market))
        rec, reason = _decide(status, row, st, sport, market)
        ev = {}
        if st:
            ev.update({"roi": round(st.roi, 2) if st.roi is not None else None,
                       "roi_n": st.n})
        if row:
            ev.update({"clv_mean": round(row["mean"], 3), "clv_n": row["n"],
                       "sharp_mean": row.get("sharp_mean"),
                       "sharp_beat_pct": row.get("sharp_beat_pct")})
        actions.append(PromotionAction(sport, market, status, rec, reason, ev))
    return actions


def apply(actions: list[PromotionAction]) -> int:
    """Enact changed actions via set_promotion. Returns count applied."""
    n = 0
    for a in actions:
        if not a.changed:
            continue
        if a.recommended == "live":
            set_promotion(a.sport, a.market, "live", "t2", evidence=a.evidence)
        else:
            set_promotion(a.sport, a.market, "incubating", "shadow", evidence=a.evidence)
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Auto promote/demote lanes on ROI + CLV.")
    ap.add_argument("--apply", action="store_true",
                    help="Write decisions to promotions.json (default: report only).")
    ap.add_argument("--min-n", type=int, default=200, dest="min_n",
                    help="Minimum scored picks for the CLV gate (default 200).")
    args = ap.parse_args(argv)

    actions = evaluate(args.min_n)
    promos = [a for a in actions if a.kind == "promote"]
    demos = [a for a in actions if a.kind == "demote"]

    print(f"\n  ─ Auto-Promoter {'(APPLYING)' if args.apply else '(dry-run)'} ─ "
          f"{len(promos)} promote, {len(demos)} demote ─")
    for a in promos:
        print(f"   🟢↑ {model_label(a.sport, a.market)[:40]:40} {a.reason}")
    for a in demos:
        print(f"   🔵↓ {model_label(a.sport, a.market)[:40]:40} {a.reason}")
    if not promos and not demos:
        print("   nothing to change — the board is stable.")

    if args.apply:
        applied = apply(actions)
        print(f"\n  ✓ applied {applied} change(s) to promotions.json")
    else:
        print("\n  (dry-run — re-run with --apply to enact)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
