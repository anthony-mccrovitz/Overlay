"""
bankroll.py — the MONEY ledger, kept deliberately separate from the LAB.

Two ledgers, two questions:

  data/pnl/picks.json           THE LAB — every model/shadow pick ever emitted.
                                Judged on CLV. Units are notional. Never dollars.

  data/pnl/personal_picks.json  THE MONEY — only bets Anthony actually placed.
                                Judged on dollars. No shadow picks, ever.

The money ledger already existed and died on 2026-06-13 for one reason: grading
was manual (`chef.py result <team> win`, once per bet). Nobody sustains that. So
the core of this module is `autograde` — the lab grades itself nightly, and a
real bet that matches a lab pick simply inherits that result. Zero keystrokes.

A bet that has no lab counterpart (a line you took off-card) still needs a manual
`chef.py result`, and `open_bets` surfaces those so they can't rot as `pending`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER = Path("data/pnl/personal_picks.json")
LAB    = Path("data/pnl/picks.json")

# Real starting bankroll, in dollars. This is the number every dollar figure
# downstream is anchored to, so it lives in exactly one place.
#
# 2026-07-29: ledger reset to a clean slate for the line-shop trial. Everything
# before this date is archived at data/pnl/backups/personal_picks_archived_*.json
# — it was the model era and mixes methodologies, so grinding it into the new
# record would blur the one question the trial exists to answer.
# The REAL Polymarket balance at era start, 2026-07-31: cash $298.52 + one
# open position $5.78 = $304.30, matching the app to the cent. This ledger
# tracks the Polymarket era ONLY — the June bets placed at US books (a
# different wallet, before the owner moved to Switzerland) live in
# data/pnl/backups/personal_picks_usbook_era_20260731.json, graded and kept
# as history but outside this balance's arithmetic.
BANKROLL_START = 304.30

SETTLED = ("win", "loss", "push")


# ─────────────────────────── io ──────────────────────────────────────────────

def load_bets(path: str | Path = LEDGER) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("picks", data) if isinstance(data, dict) else data


def save_bets(bets: list[dict], path: str | Path = LEDGER) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"picks": bets}, indent=2))


def _load_lab(path: str | Path = LAB) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("picks", data) if isinstance(data, dict) else data


# ─────────────────────────── money math ──────────────────────────────────────

def payout(stake_dollars: float, odds: int, won: bool) -> float:
    """Profit in dollars (not including the returned stake). Loss returns
    -stake. American odds."""
    if not won:
        return -stake_dollars
    return stake_dollars * (odds / 100 if odds > 0 else 100 / abs(odds))


def _stake(bet: dict) -> float:
    return float(bet.get("stake_dollars") or bet.get("stake") or 0)


# ─────────────────────────── auto-grading ────────────────────────────────────

def _slug(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _matches(bet: dict, lab: dict) -> bool:
    """Is this lab pick the same wager as this real bet?

    Deliberately strict: same day, sport, market, and side. For lined markets
    (totals/spreads) the line must match too — an UNDER 8.5 and an UNDER 9.0 in
    the same game are different bets and must never inherit each other's result.
    Team match is required only when the bet names a team, because totals are
    identified by game + line rather than by side.
    """
    if bet.get("date") != lab.get("date"):
        return False
    if _slug(bet.get("sport")) != _slug(lab.get("sport")):
        return False
    if _slug(bet.get("market")) != _slug(lab.get("market")):
        return False
    if _slug(bet.get("direction")) != _slug(lab.get("direction")):
        return False

    b_line, l_line = _num(bet.get("line")), _num(lab.get("line"))
    if b_line is not None or l_line is not None:
        if b_line is None or l_line is None or abs(b_line - l_line) > 1e-6:
            return False

    b_team = _slug(bet.get("team"))
    if b_team and b_team != _slug(lab.get("team")):
        # Totals often carry a matchup rather than a team; allow a matchup hit.
        if b_team not in _slug(lab.get("matchup")):
            return False
    return True


def autograde(bets: list[dict] | None = None,
              lab_picks: list[dict] | None = None) -> tuple[list[dict], int]:
    """Settle every ungraded real bet that has a settled twin in the lab.

    Returns (bets, n_graded). Pure with respect to disk — the caller saves.
    """
    bets = load_bets() if bets is None else bets
    lab  = _load_lab() if lab_picks is None else lab_picks

    graded_lab = [p for p in lab if p.get("result") in SETTLED]
    now = datetime.now(timezone.utc).isoformat()
    n = 0

    for bet in bets:
        if bet.get("result") in SETTLED:
            continue
        twin = next((p for p in graded_lab if _matches(bet, p)), None)
        if twin is None:
            continue
        result = twin["result"]
        stake  = _stake(bet)
        profit = 0.0 if result == "push" else payout(stake, int(bet.get("odds") or 0),
                                                     result == "win")
        bet["result"]         = result
        bet["profit_dollars"] = round(profit, 2)
        bet["resulted_at"]    = now
        bet["graded_via"]     = f"lab:{twin.get('pick_id', '?')}"
        n += 1

    return bets, n


# ─────────────────────────── reporting ───────────────────────────────────────

def open_bets(bets: list[dict] | None = None) -> list[dict]:
    """Ungraded real bets — money currently at risk, or rotting unsettled."""
    bets = load_bets() if bets is None else bets
    return [b for b in bets if b.get("result") not in SETTLED]


def summary(bets: list[dict] | None = None,
            start: float = BANKROLL_START) -> dict:
    """Dollar truth about the real bankroll. Units never appear here."""
    bets     = load_bets() if bets is None else bets
    settled  = [b for b in bets if b.get("result") in SETTLED]
    decided  = [b for b in settled if b.get("result") != "push"]
    wins     = [b for b in decided if b["result"] == "win"]
    staked   = sum(_stake(b) for b in decided)
    profit   = sum(float(b.get("profit_dollars") or 0) for b in settled)
    at_risk  = sum(_stake(b) for b in open_bets(bets))

    return {
        "start":       start,
        "balance":     round(start + profit, 2),
        "profit":      round(profit, 2),
        "staked":      round(staked, 2),
        "roi_pct":     round(profit / staked * 100, 2) if staked else 0.0,
        "wins":        len(wins),
        "losses":      len(decided) - len(wins),
        "pushes":      len(settled) - len(decided),
        "win_rate":    round(len(wins) / len(decided) * 100, 1) if decided else 0.0,
        "open":        len(open_bets(bets)),
        "at_risk":     round(at_risk, 2),
        "n_settled":   len(settled),
    }


def by_lane(bets: list[dict] | None = None) -> list[dict]:
    """Dollar P&L per sport×market — where the money actually went."""
    bets = load_bets() if bets is None else bets
    lanes: dict[tuple[str, str], dict] = {}
    for b in bets:
        if b.get("result") not in SETTLED:
            continue
        key = (str(b.get("sport") or "?"), str(b.get("market") or "?"))
        lane = lanes.setdefault(key, {"sport": key[0], "market": key[1],
                                      "n": 0, "wins": 0, "losses": 0,
                                      "staked": 0.0, "profit": 0.0})
        lane["n"] += 1
        if b["result"] == "win":
            lane["wins"] += 1
        elif b["result"] == "loss":
            lane["losses"] += 1
        if b["result"] != "push":
            lane["staked"] += _stake(b)
        lane["profit"] += float(b.get("profit_dollars") or 0)

    out = []
    for lane in lanes.values():
        lane["roi_pct"] = round(lane["profit"] / lane["staked"] * 100, 2) if lane["staked"] else 0.0
        lane["profit"]  = round(lane["profit"], 2)
        lane["staked"]  = round(lane["staked"], 2)
        out.append(lane)
    return sorted(out, key=lambda x: -x["profit"])
