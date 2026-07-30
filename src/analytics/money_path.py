"""The money path: every link between raw odds and a bet you can place.

WHY THIS EXISTS. The repo is ~90,000 lines across 254 files, and 94 of its 95
lanes cannot move money — they log, research, and sit dormant. Understanding all
of it is neither achievable nor useful. What matters is one question: is the
chain that produces a REAL BET intact today?

This walks that chain link by link and checks each one against live data. Each
link states three things:

  DOES      one sentence on what the link contributes
  PROOF     the observable fact that shows it worked
  IF BROKEN what a SILENT failure looks like downstream

That last column is the point. Every expensive defect in this repo's history was
silent: a monitor that couldn't reach the API and reported ALL GREEN, a capture
script that archived nothing and exited 0, a promotion gate keyed on the wrong
sport string that read a full lane as empty. A link is only trustworthy if you
know what its silence would mean.

Deliberately dependency-free and read-only: it spends no API credits, writes
nothing, and reports on the committed record — so it can be run on the day the
Odds API is the thing that's down.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PICKS = Path("data/pnl/picks.json")
SNAPS = Path("data/clv/snapshots.json")
ODDS_CACHE = Path("data/cache/odds")
CLOSING = Path("data/clv/closing")


@dataclass
class Link:
    n: int
    name: str
    ok: bool | None          # None = "can't tell" — never silently a pass
    does: str
    proof: str
    if_broken: str
    exempt: str = ""         # live, dated exemption covering a failing check


def _exemption(sport: str, market: str, check: str) -> str:
    """The documented exemption covering this check, or "".

    A link failing under an exemption the owner ACCEPTED, with a date and a
    retirement condition, is not the same as a link failing unnoticed. Treating
    them alike would make this tool print DO NOT BET every day until the
    exemption retires — and a verdict that never changes is a verdict nobody
    reads, which is the failure mode the whole reliability program exists to
    remove. The exemption is surfaced in full, never hidden; it just doesn't
    veto the verdict on its own.
    """
    try:
        from src.config.model_standard import EXEMPTIONS
        rec = EXEMPTIONS.get((sport, market))
        if rec and check in (rec.get("checks") or []):
            return str(rec.get("why") or "exempt")
    except Exception:
        pass
    return ""


def _load(p: Path, key: str | None = None) -> list:
    try:
        raw = json.loads(p.read_text().replace("NaN", "null"))
    except (OSError, ValueError):
        return []
    rows = raw.get(key, raw) if (key and isinstance(raw, dict)) else raw
    return rows if isinstance(rows, list) else []


def audit(sport: str = "mlb", market: str = "total") -> list[Link]:
    """Walk the chain for the lane that actually takes money."""
    out: list[Link] = []
    today = date.today()
    picks = _load(PICKS, "picks")
    lane = [p for p in picks if isinstance(p, dict)
            and p.get("sport") == sport and p.get("market") == market]

    # 1 ─ odds in
    board = ODDS_CACHE / f"baseball_{sport}_latest.json" if sport == "mlb" else None
    cands = list(ODDS_CACHE.glob(f"*{sport}*_latest.json")) if ODDS_CACHE.exists() else []
    board = cands[0] if cands else board
    age_h = None
    if board and board.exists():
        age_h = (datetime.now().timestamp() - board.stat().st_mtime) / 3600
    out.append(Link(
        1, "Odds ingested", (age_h is not None and age_h < 24),
        "Pulls the live board from the Odds API into a local cache.",
        f"board cached {age_h:.1f}h ago" if age_h is not None else "no cached board found",
        "A stale board prices today's games off yesterday's numbers, so every "
        "edge is measured against a line nobody is offering.",
    ))

    # 2 ─ model probability
    try:
        from src.config.model_standard import has_calibrator
        cal_ok, cal_txt = has_calibrator(sport, market)
    except Exception as e:
        cal_ok, cal_txt = None, f"could not check ({type(e).__name__})"
    out.append(Link(
        2, "Model probability", cal_ok,
        "The ensemble emits a win/over probability, then a calibrator maps it "
        "onto observed frequencies.",
        cal_txt,
        "A degenerate calibrator flattens every game to one number, so the model "
        "stops discriminating while still reporting confident edges.",
        exempt=_exemption(sport, market, "calibrator") if not cal_ok else "",
    ))

    # 3 ─ edge shrink
    try:
        from src.config.model_standard import edge_shrink
        k_ok, k_txt = edge_shrink(sport, market)
    except Exception as e:
        k_ok, k_txt = None, f"could not check ({type(e).__name__})"
    out.append(Link(
        3, "Edge shrunk to reality", k_ok,
        "Scales the claimed edge by how much of it historically materialised "
        "(k = realised / claimed).",
        k_txt,
        "Sizing on an unshrunk edge overbets. Overbetting Kelly loses growth far "
        "faster than underbetting, and past ~1.5x it can go negative.",
    ))

    # 4 ─ pick recorded
    graded = [p for p in lane if p.get("result") in ("win", "loss", "push")]
    out.append(Link(
        4, "Pick written to the ledger", bool(lane),
        "Normalises the pick and appends it under a deterministic pick_id.",
        f"{len(lane)} pick(s) on this lane, {len(graded)} settled",
        "A pick that never lands in the ledger is invisible to grading, CLV and "
        "the gate — it looks like it was never made.",
    ))

    # 5 ─ gate authorises
    try:
        from src.config.model_standard import clears_promotion_gate
        g_ok, g_txt = clears_promotion_gate(sport, market)
    except Exception as e:
        g_ok, g_txt = None, f"could not check ({type(e).__name__})"
    out.append(Link(
        5, "Gate authorises real money", g_ok,
        "Requires positive EV vs the close AND positive ROI over a minimum sample.",
        g_txt,
        "A gate reading the wrong metric funds a losing lane: beat-close "
        "correlated -0.153 with realised ROI, so a hit-rate gate pointed the "
        "wrong way.",
    ))

    # 6 ─ stake sized
    try:
        from src.betting.kelly import shrunk_prob, kelly_fraction, _implied_prob
        odds = -110
        p_raw = _implied_prob(odds) + 0.0617
        f_raw = kelly_fraction(p_raw, odds, fraction=0.25)
        f_adj = kelly_fraction(shrunk_prob(p_raw, odds, sport, market), odds, fraction=0.25)
        k_ok2 = f_adj <= f_raw
        k_txt2 = (f"quarter-Kelly on a 6.2pp claimed edge: "
                  f"{f_raw*100:.2f}% -> {f_adj*100:.2f}% after shrink")
    except Exception as e:
        k_ok2, k_txt2 = None, f"could not check ({type(e).__name__})"
    out.append(Link(
        6, "Stake sized", k_ok2,
        "Fractional Kelly on the SHRUNK edge, capped as a share of bankroll.",
        k_txt2,
        "If the shrink never reaches the stake, the ledger records a conservative "
        "edge while the wallet backs an optimistic one.",
    ))

    # 7 ─ the bet
    card = [p for p in lane if p.get("card_pick")]
    recent = [p for p in card
              if str(p.get("date") or "") >= (today - timedelta(days=7)).isoformat()]
    out.append(Link(
        7, "Bet published", bool(card),
        "Marks the pick card_pick=True — the only picks that count as real bets.",
        f"{len(card)} card pick(s) all-time, {len(recent)} in the last 7d",
        "Shadow picks look identical in the ledger. If card_pick never gets set, "
        "the public record silently stops moving.",
    ))

    # 8 ─ closing line captured
    try:
        from src.analytics.coverage import capture_rate, MIN_CAPTURE_RATE
        n_c, closed, rate = capture_rate(sport, 14, today - timedelta(days=3))
        cap_ok = n_c >= 10 and rate >= MIN_CAPTURE_RATE
        cap_txt = f"{closed}/{n_c} snapshots have a closing line ({rate:.0%})"
    except Exception as e:
        cap_ok, cap_txt = None, f"could not check ({type(e).__name__})"
    out.append(Link(
        8, "Closing line captured", cap_ok,
        "Archives the market's final price — the benchmark every verdict rests on.",
        cap_txt,
        "Closing lines cannot be backfilled. A missed capture destroys that "
        "night's CLV permanently, and the lane simply never becomes provable.",
    ))

    # 9 ─ graded
    stale = [p for p in lane if not p.get("result")
             and str(p.get("date") or "") <= (today - timedelta(days=3)).isoformat()]
    out.append(Link(
        9, "Result graded", not stale,
        "Settles each pick win/loss/push against the final score.",
        f"{len(graded)} settled, {len(stale)} older than 3d still ungraded",
        "Ungraded picks rot the record silently — ~2,850 stale pendings once "
        "accumulated across every sport before a sweep caught them.",
    ))

    # 10 ─ CLV / EV scored
    snaps = _load(SNAPS, "snapshots")
    try:
        from src.analytics.ev_gate import ev_by_lane
        ev = ev_by_lane().get((sport, market))
    except Exception:
        ev = None
    out.append(Link(
        10, "EV scored vs the close", bool(ev and ev.n >= 30),
        "Values each bet against the devigged closing market: "
        "fair_close(bet) / price_paid - 1.",
        (f"n={ev.n}, mean EV {ev.mean_ev_pct:+.2f}%, "
         f"t={ev.t:+.2f} {'SIGNIFICANT' if ev.significant else 'not significant'}")
        if ev else "no EV rows for this lane",
        "Keyed on the wrong sport string, a full lane reads as empty — usa_mls "
        "held 46 rows and the gate saw 0.",
    ))

    # 11 ─ feedback loop
    try:
        from src.config.models import model_status
        st = model_status(sport, market)
        loop_ok = st in ("live", "incubating", "retired")
    except Exception as e:
        st, loop_ok = f"unknown ({type(e).__name__})", None
    out.append(Link(
        11, "Promote / demote loop", loop_ok,
        "Feeds the verdict back into the registry so a lane can be promoted or "
        "pulled.",
        f"registry status: {st}",
        "Without the loop a lane that stops working keeps taking money on last "
        "month's evidence.",
    ))

    # 12 ─ the alarm
    try:
        import chef
        n_ack = len(getattr(chef, "ACKNOWLEDGED_GAPS", {}))
        alarm_ok = hasattr(chef, "_monitor_run")
        alarm_txt = f"monitor wired, {n_ack} acknowledged gap(s) with expiries"
    except Exception as e:
        alarm_ok, alarm_txt = None, f"could not check ({type(e).__name__})"
    out.append(Link(
        12, "Alarm if a link breaks", alarm_ok,
        "Daily integrity monitor plus a heartbeat that arrives green or red.",
        alarm_txt,
        "The worst case in this repo's history: the monitor was RED for 12 "
        "consecutive days and delivered zero alerts, because the alert step "
        "itself was broken and nothing tested it.",
    ))

    return out


def verdict(links: list[Link]) -> tuple[bool, str]:
    """Can this lane be bet today?

    A link failing under a live, dated exemption does not veto the verdict — the
    owner accepted that risk explicitly and it is printed in full. An
    unverifiable link DOES veto: "could not check" is never a pass.
    """
    broken = [l for l in links if l.ok is False and not l.exempt]
    accepted = [l for l in links if l.ok is False and l.exempt]
    unknown = [l for l in links if l.ok is None]
    if broken:
        return False, f"{len(broken)} broken link(s): " + ", ".join(str(l.n) for l in broken)
    if unknown:
        return False, f"{len(unknown)} unverifiable link(s): " + ", ".join(str(l.n) for l in unknown)
    if accepted:
        return True, (f"every link verified, {len(accepted)} on an accepted "
                      f"exemption (link " + ", ".join(str(l.n) for l in accepted) + ")")
    return True, "every link verified"
