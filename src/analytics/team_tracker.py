"""
Team-level accuracy tracker.

For each team × market, computes actual win rate, model calibration error,
P&L, and whether the model has demonstrated reliable edge on that team.

Used by:
  - predict.py  : gate card_pick for ML/RL based on team track record
  - chef.py record --teams : per-team breakdown report
  - src/models   : calibrated_edge() to shrink overclaimed model probs
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_PICKS_PATH = Path("data/pnl/picks.json")

# Minimum settled picks before we trust a team record
MIN_N_TRUST    = 15
# Minimum actual WR to consider betting (above break-even ~52%)
MIN_WR_TRUST   = 0.53
# Minimum calibrated edge % to post publicly
MIN_CARD_EDGE  = 8.0


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TeamRecord:
    team:         str
    sport:        str
    market:       str
    wins:         int  = 0
    losses:       int  = 0
    pushes:       int  = 0
    pnl:          float = 0.0
    model_probs:  list  = field(default_factory=list)   # claimed model_prob per pick
    edges_claimed:list  = field(default_factory=list)   # edge_pct per pick

    @property
    def n(self) -> int:
        return self.wins + self.losses + self.pushes

    @property
    def wr(self) -> float:
        denom = self.wins + self.losses
        return self.wins / denom if denom else 0.0

    @property
    def roi(self) -> float:
        staked = self.wins + self.losses  # 1u per pick
        return self.pnl / staked if staked else 0.0

    @property
    def avg_model_prob(self) -> float:
        return sum(self.model_probs) / len(self.model_probs) if self.model_probs else 0.0

    @property
    def avg_edge_claimed(self) -> float:
        return sum(self.edges_claimed) / len(self.edges_claimed) if self.edges_claimed else 0.0

    @property
    def calibration_error(self) -> float:
        """How much the model over/understates win probability.
        Positive = model overclaims (shows 60%, actually wins 50%).
        """
        return self.avg_model_prob - self.wr

    @property
    def is_reliable(self) -> bool:
        """Has ≥MIN_N_TRUST picks AND actual WR ≥ MIN_WR_TRUST."""
        return self.n >= MIN_N_TRUST and self.wr >= MIN_WR_TRUST

    def as_dict(self) -> dict:
        return {
            "team": self.team, "sport": self.sport, "market": self.market,
            "n": self.n, "w": self.wins, "l": self.losses,
            "wr": round(self.wr, 4), "pnl": round(self.pnl, 2),
            "roi": round(self.roi, 4),
            "avg_model_prob": round(self.avg_model_prob, 4),
            "avg_edge_claimed": round(self.avg_edge_claimed, 2),
            "calibration_error": round(self.calibration_error, 4),
            "reliable": self.is_reliable,
        }


# ── Core loader ───────────────────────────────────────────────────────────────

def _load_picks(sport: str | None = None, market: str | None = None,
                card_only: bool = False) -> list[dict]:
    """Load settled picks from pnl/picks.json, optionally filtered."""
    raw = json.loads(_PICKS_PATH.read_text())
    picks = raw["picks"] if isinstance(raw, dict) else raw
    picks = [p for p in picks if isinstance(p, dict)]

    if sport:
        s = sport.lower().replace("baseball_","").replace("basketball_","") \
                         .replace("icehockey_","")
        picks = [p for p in picks if s in (p.get("sport") or "").lower()]
    if market:
        picks = [p for p in picks if (p.get("market") or "").lower() == market.lower()]
    if card_only:
        picks = [p for p in picks if p.get("card_pick") is True]

    return [p for p in picks if p.get("result") in ("win","loss","push")]


# ── Team record builder ───────────────────────────────────────────────────────

def _normalise_team(name: str) -> str:
    """Strip city prefix noise for matching (e.g. 'Los Angeles Dodgers' → same)."""
    return (name or "").strip().lower()


def all_team_records(sport: str, market: str,
                     min_n: int = 1,
                     card_only: bool = False) -> list[TeamRecord]:
    """Return TeamRecord for every team that appears in the pick history."""
    picks = _load_picks(sport=sport, market=market, card_only=card_only)

    index: dict[str, TeamRecord] = {}
    for p in picks:
        team = (p.get("team") or p.get("Team") or "").strip()
        if not team:
            continue
        key = _normalise_team(team)
        if key not in index:
            index[key] = TeamRecord(team=team, sport=sport, market=market)
        r = index[key]

        result = p.get("result","").lower()
        if result == "win":
            r.wins += 1
        elif result == "loss":
            r.losses += 1
        else:
            r.pushes += 1

        r.pnl += float(p.get("profit") or 0)

        mp = float(p.get("model_prob") or p.get("ModelProb") or 0)
        if mp > 1.5:
            mp /= 100
        if mp > 0:
            r.model_probs.append(mp)

        ep = float(p.get("edge_pct") or p.get("Edge") or 0)
        if ep > 0:
            r.edges_claimed.append(ep)

    records = [r for r in index.values() if r.n >= min_n]
    records.sort(key=lambda r: r.wr, reverse=True)
    return records


def team_record(team: str, sport: str, market: str,
                card_only: bool = False) -> TeamRecord | None:
    """Return the TeamRecord for a single team, or None if not enough data."""
    all_recs = all_team_records(sport, market, min_n=1, card_only=card_only)
    key = _normalise_team(team)
    for r in all_recs:
        if _normalise_team(r.team) == key:
            return r
    return None


# ── Calibration ───────────────────────────────────────────────────────────────

def calibration_factor(sport: str, market: str,
                        card_only: bool = False) -> float:
    """
    Ratio of actual WR to average claimed model probability.
    Used to shrink overclaimed edges back to reality.

    e.g. if model claims avg 0.58 but actual WR is 0.47:
         calibration_factor = 0.47 / 0.58 = 0.81
         calibrated_prob    = raw_prob * 0.81

    Capped at [0.60, 1.10] to avoid overcorrecting on small samples.
    """
    picks = _load_picks(sport=sport, market=market, card_only=card_only)
    settled = [p for p in picks if p.get("result") in ("win","loss")]
    if len(settled) < 20:
        return 1.0   # not enough data — trust the model as-is

    actual_wr = sum(1 for p in settled if p["result"]=="win") / len(settled)
    probs = []
    for p in settled:
        mp = float(p.get("model_prob") or p.get("ModelProb") or 0)
        if mp > 1.5:
            mp /= 100
        if mp > 0:
            probs.append(mp)
    if not probs:
        return 1.0
    avg_claimed = sum(probs) / len(probs)
    if avg_claimed < 0.01:
        return 1.0
    factor = actual_wr / avg_claimed
    return max(0.60, min(1.10, factor))


def calibrated_edge(model_prob: float, market_implied: float,
                    sport: str, market: str,
                    card_only: bool = False) -> float:
    """
    Return edge % after applying historical calibration.

    model_prob and market_implied should be in [0,1] or [0,100] — normalised internally.
    Returns edge in percentage points (e.g. 8.4 means 8.4%).
    """
    if model_prob > 1.5:
        model_prob /= 100
    if market_implied > 1.5:
        market_implied /= 100
    factor = calibration_factor(sport, market, card_only=card_only)
    cal_prob = model_prob * factor
    edge = (cal_prob - market_implied) * 100
    return round(edge, 2)


# ── Bet gate ──────────────────────────────────────────────────────────────────

def should_bet(team: str, sport: str, market: str,
               model_prob: float, market_implied: float,
               min_n: int = MIN_N_TRUST,
               min_wr: float = MIN_WR_TRUST,
               min_edge: float = MIN_CARD_EDGE,
               card_only: bool = False) -> tuple[bool, str]:
    """
    Full gate for whether a pick should be card_pick=True.

    Returns (bool, reason_string).

    Gate passes if ALL of:
      1. calibrated edge ≥ min_edge %
      2. team has ≥ min_n historical picks with WR ≥ min_wr   (OR team is new — <5 picks)

    New teams (< 5 picks) pass through with a note — we need data to build a record.
    Teams with 5–min_n picks are held back until sample is large enough.
    """
    cal_edge = calibrated_edge(model_prob, market_implied, sport, market, card_only)
    if cal_edge < min_edge:
        return False, f"calibrated edge {cal_edge:.1f}% < {min_edge}% threshold"

    rec = team_record(team, sport, market, card_only=card_only)
    if rec is None or rec.n < 5:
        return True, f"new team ({0 if rec is None else rec.n} picks) — collecting data"
    if rec.n < min_n:
        return False, f"insufficient history ({rec.n} picks, need {min_n})"
    if rec.wr < min_wr:
        return False, f"team WR {rec.wr:.1%} below {min_wr:.1%} threshold"

    return True, f"team {rec.n} picks, {rec.wr:.1%} WR, edge {cal_edge:.1f}%"


# ── Reports ───────────────────────────────────────────────────────────────────

def print_report(sport: str, market: str,
                 min_n: int = 5, card_only: bool = False) -> None:
    """Print a full team accuracy table for a sport × market."""
    records = all_team_records(sport, market, min_n=min_n, card_only=card_only)
    if not records:
        print(f"No settled {sport} {market} picks found (min_n={min_n}).")
        return

    total_w = sum(r.wins for r in records)
    total_l = sum(r.losses for r in records)
    total_pnl = sum(r.pnl for r in records)
    overall_wr = total_w / (total_w + total_l) if total_w + total_l else 0
    factor = calibration_factor(sport, market, card_only)

    print(f"\n{'='*72}")
    print(f"  {sport.upper()} {market.upper()} — Team Accuracy Report")
    print(f"  Overall: {total_w}W-{total_l}L ({overall_wr:.1%} WR)  P&L: {total_pnl:+.2f}u")
    print(f"  Calibration factor: {factor:.3f}  "
          f"({'model overclaims — shrinking' if factor < 0.95 else 'model ok'})")
    print(f"{'='*72}")
    print(f"  {'TEAM':<30} {'N':>4}  {'W-L':>9}  {'WR':>6}  {'P&L':>7}  {'CAL_ERR':>8}  {'OK':>4}")
    print(f"  {'-'*68}")

    reliable = [r for r in records if r.is_reliable]
    borderline = [r for r in records if not r.is_reliable and r.n >= 5]

    for section, recs, label in [
        (reliable,   reliable,   "✅ RELIABLE (≥15 picks, ≥53% WR)"),
        (borderline, borderline, "⏳ BUILDING SAMPLE (5-14 picks)"),
    ]:
        if not recs:
            continue
        print(f"\n  {label}")
        for r in recs:
            ok = "✅" if r.is_reliable else "  "
            cal = f"{r.calibration_error:+.1%}"
            print(f"  {r.team:<30} {r.n:>4}  "
                  f"{r.wins:>3}W-{r.losses:<3}L  {r.wr:>5.1%}  "
                  f"{r.pnl:>+6.2f}u  {cal:>8}  {ok:>4}")

    print(f"\n  Teams with <5 picks: "
          f"{sum(1 for r in records if r.n < 5)} (too new to judge)")
    print(f"{'='*72}\n")


def calibration_report() -> None:
    """Print calibration summary across all tracked markets."""
    print(f"\n{'='*60}")
    print("  MODEL CALIBRATION REPORT")
    print(f"{'='*60}")
    for sport_market in [
        ("mlb",  "moneyline"),
        ("mlb",  "spread"),
        ("mlb",  "total"),
        ("nba",  "total"),
        ("nhl",  "total"),
    ]:
        s, m = sport_market
        picks = _load_picks(sport=s, market=m)
        settled = [p for p in picks if p.get("result") in ("win","loss")]
        if not settled:
            continue
        actual_wr = sum(1 for p in settled if p["result"]=="win") / len(settled)
        factor    = calibration_factor(s, m)
        probs = []
        for p in settled:
            mp = float(p.get("model_prob") or 0)
            if mp > 1.5: mp /= 100
            if mp > 0: probs.append(mp)
        avg_claimed = sum(probs)/len(probs) if probs else 0
        print(f"  {s:6} {m:12}  n={len(settled):>4}  "
              f"claimed={avg_claimed:.1%}  actual={actual_wr:.1%}  "
              f"factor={factor:.3f}  "
              f"{'⚠️  OVERCLAIMS' if factor < 0.90 else '✅ OK'}")
    print(f"{'='*60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Team accuracy tracker")
    parser.add_argument("sport",  nargs="?", default="mlb")
    parser.add_argument("market", nargs="?", default="moneyline")
    parser.add_argument("--min-n", type=int, default=5)
    parser.add_argument("--card-only", action="store_true")
    parser.add_argument("--calibration", action="store_true",
                        help="Print calibration report across all markets")
    args = parser.parse_args()

    if args.calibration:
        calibration_report()
    else:
        print_report(args.sport, args.market, min_n=args.min_n,
                     card_only=args.card_only)
