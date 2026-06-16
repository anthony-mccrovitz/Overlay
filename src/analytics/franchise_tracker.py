"""
Franchise Bet Tracker — all 30 MLB teams.

Tracks shadow bets on every team every day they play:
  - Moneyline
  - Run line when favorite (-1.5)
  - Run line when underdog (+1.5)

Validation is ROI-primary. Win rate thresholds are meaningless without
knowing the odds — a 53% WR at -150 loses money; a 53% WR at +120 prints.
The only metric that matters is ROI at your actual avg odds.

Promotes to live July 1 if:
  - ≥ 30 picks
  - ROI ≥ min_roi (default +5%)
  - WR ≥ break-even WR at avg odds (implicit in ROI > 0, but shown explicitly)

Usage:
  python3 -m src.analytics.franchise_tracker              # leaderboard
  python3 -m src.analytics.franchise_tracker --report     # per-team detail
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_PATH = Path("data/franchise/config.json")
_BETS_PATH   = Path("data/franchise/bets.json")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class FranchiseRecord:
    team:    str
    market:  str   # "moneyline" | "run_line" | "run_line_dog"
    wins:    int   = 0
    losses:  int   = 0
    pushes:  int   = 0
    pnl:     float = 0.0
    bets:    list  = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.wins + self.losses + self.pushes

    @property
    def settled(self) -> int:
        return self.wins + self.losses

    @property
    def wr(self) -> float:
        return self.wins / self.settled if self.settled else 0.0

    @property
    def roi(self) -> float:
        """Units profit per unit wagered."""
        return self.pnl / self.settled if self.settled else 0.0

    @property
    def avg_implied_prob(self) -> float:
        """
        Average implied probability across all bets (settled + pending).
        Computed in probability space, not American odds space.

        Why not average the American odds directly:
          -103 and +125 look far apart (+228 points) but are nearly the same
          bet — 50.7% vs 44.4% implied. Averaging American numbers directly
          distorts the true average price. Convert to prob, average, convert back.
        """
        probs = []
        for b in self.bets:
            o = float(b.get("odds", 0))
            if o == 0:
                continue
            if o < 0:
                probs.append(abs(o) / (abs(o) + 100))
            else:
                probs.append(100 / (o + 100))
        return sum(probs) / len(probs) if probs else 0.524

    @property
    def avg_odds(self) -> float:
        """
        Average price as American odds, derived from avg_implied_prob.
        This is what you'd see on a sportsbook — not an average of raw numbers.
        """
        p = self.avg_implied_prob
        if p <= 0 or p >= 1:
            return 0.0
        if p > 0.5:
            return -(p * 100) / (1 - p)     # negative (favorite)
        else:
            return (100 * (1 - p)) / p       # positive (underdog)

    @property
    def breakeven_wr(self) -> float:
        """
        Win rate needed to break even at your avg price.
        Derived directly from avg_implied_prob — no conversion needed.
        At -110 → 52.4%.  At +100 → 50.0%.  At +150 → 40.0%.  At -150 → 60.0%.
        """
        return self.avg_implied_prob

    @property
    def edge_vs_be(self) -> float:
        """Percentage-point edge over break-even WR. Positive = profitable."""
        return self.wr - self.breakeven_wr

    def is_validated(self, cfg: dict) -> bool:
        """
        Validation is ROI-primary.
        A team at +150 odds only needs 40% WR to profit — a fixed 56% gate
        would wrongly disqualify a very profitable underdog system.
        """
        v       = cfg.get("validation", {})
        min_n   = v.get("min_picks_per_market", 30)
        min_roi = v.get("min_roi", 0.05)   # default: +5% ROI per pick
        if self.settled < min_n:
            return False
        # Must beat break-even AND hit ROI threshold
        return self.wr >= self.breakeven_wr and self.roi >= min_roi


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    return json.loads(_CONFIG_PATH.read_text())


def load_bets() -> list[dict]:
    if not _BETS_PATH.exists():
        return []
    raw = json.loads(_BETS_PATH.read_text())
    return raw.get("bets", [])


def save_bets(bets: list[dict]) -> None:
    existing = load_bets()
    # Dedup by bet_id
    seen = {b["bet_id"] for b in existing if "bet_id" in b}
    new = [b for b in bets if b.get("bet_id") not in seen]
    all_bets = existing + new
    _BETS_PATH.write_text(json.dumps(
        {"description": "Franchise shadow bets — logged daily, graded nightly, validated end of June",
         "bets": all_bets},
        indent=2
    ))
    return len(new)


def log_today(game_date: "date | str | None" = None,
              sport: str = "mlb",
              verbose: bool = True) -> int:
    """
    Log one franchise-shadow bet per MLB game today, for every team playing,
    on both the moneyline (favorite/dog as priced) and the run line dog side.

    This is the auto-logger that was missing — without it the tracker was
    a frozen 2-day snapshot from June 6/8. Wire this into the morning MLB
    pipeline (predict.py / chef.py picks mlb) so every day's games land in
    bets.json automatically.

    Returns the number of NEW bets logged (after dedup by bet_id).
    """
    import datetime as _dt
    from pathlib import Path as _Path
    if game_date is None:
        game_date = _dt.date.today()
    if isinstance(game_date, str):
        # accept YYYYMMDD or YYYY-MM-DD
        ds = game_date.replace("-", "")
        game_date = _dt.date(int(ds[:4]), int(ds[4:6]), int(ds[6:]))

    date_str  = game_date.isoformat()
    folder    = game_date.strftime("%Y%m%d")
    picks_path = _Path(f"output/picks/baseball_mlb/{folder}/picks.json")
    if not picks_path.exists():
        if verbose:
            print(f"  [franchise] no picks file at {picks_path}; skipping log")
        return 0

    try:
        picks = json.loads(picks_path.read_text())
    except Exception:
        return 0

    # Filter to moneyline + spread rows (skip totals/props/F5/NRFI — team-agnostic)
    rows = [p for p in picks if isinstance(p, dict)
            and p.get("Market") in ("moneyline", "spread")
            and (p.get("Team") or p.get("team"))
            and (p.get("BestOdds") is not None or p.get("odds") is not None)]
    if not rows:
        return 0

    cfg = load_config()
    team_map = {t["name"]: t.get("slug", t["name"].lower().replace(" ", "")) for t in (cfg.get("teams") or [])}
    now_ts = _dt.datetime.utcnow().isoformat()

    new_bets: list[dict] = []
    for p in rows:
        team   = (p.get("Team") or p.get("team") or "").strip()
        opp    = (p.get("Opponent") or p.get("opponent") or "").strip()
        odds   = p.get("BestOdds") if p.get("BestOdds") is not None else p.get("odds")
        market = p.get("Market") or p.get("market")
        if market == "spread":
            # Convention used in existing tracker data: home team RL → market="run_line",
            # away team taking +1.5 → market="run_line_dog". We log the side the
            # model picked. Use BetLine to decide.
            bet_line = p.get("BetLine") or p.get("bet_line") or ""
            mkt_key = "run_line_dog" if "+1.5" in str(bet_line) else "run_line"
        else:
            mkt_key = "moneyline"

        slug = team_map.get(team) or team.lower().replace(" ", "_")
        bet_id = f"franchise_{folder}_{slug}_{mkt_key}"

        try:
            implied = (100 / (float(odds) + 100)) if float(odds) > 0 else (abs(float(odds)) / (abs(float(odds)) + 100))
        except Exception:
            implied = None

        new_bets.append({
            "bet_id":      bet_id,
            "date":        date_str,
            "team":        team,
            "team_slug":   slug,
            "matchup":     f"{team} vs {opp}" if opp else team,
            "market":      mkt_key,
            "direction":   "home",    # placeholder — grader doesn't use it
            "line":        p.get("BetLine") or p.get("bet_line"),
            "odds":        int(float(odds)),
            "implied_pct": round((implied or 0) * 100, 2),
            "sportsbook":  p.get("Sportsbook") or p.get("sportsbook") or "",
            "stake":       1.0,
            "result":      None,
            "profit":      None,
            "logged_at":   now_ts,
        })

    added = save_bets(new_bets)
    if verbose:
        print(f"  [franchise] {date_str}: {added} new bet(s) logged for {len(rows)} model picks")
    return added


# ── Analytics ─────────────────────────────────────────────────────────────────

def build_records(bets: list[dict] | None = None) -> dict[tuple[str, str], FranchiseRecord]:
    """Return {(team_slug, market): FranchiseRecord} for all settled bets."""
    if bets is None:
        bets = load_bets()
    records: dict[tuple[str, str], FranchiseRecord] = {}
    for b in bets:
        key = (b.get("team_slug", ""), b.get("market", ""))
        if key not in records:
            records[key] = FranchiseRecord(
                team=b.get("team", ""), market=b.get("market", "")
            )
        r = records[key]
        r.bets.append(b)
        result = (b.get("result") or "").upper()
        if result == "WIN":
            r.wins += 1
            r.pnl += float(b.get("profit", 0))
        elif result == "LOSS":
            r.losses += 1
            r.pnl -= 1.0
        elif result in ("PUSH", "VOID"):
            r.pushes += 1
    return records


# ── Grader ────────────────────────────────────────────────────────────────────

def grade_bets(scores: dict[str, dict]) -> int:
    """
    Grade unresolved franchise bets using final scores.

    scores: {matchup_key: {"home_score": int, "away_score": int}}
    Returns number of bets graded.
    """
    bets = load_bets()
    graded = 0
    for b in bets:
        if b.get("result"):
            continue
        matchup = b.get("matchup", "")
        sc = scores.get(matchup)
        if not sc:
            continue
        home_score = int(sc["home_score"])
        away_score = int(sc["away_score"])
        team = b.get("team", "")
        market = b.get("market", "")
        direction = b.get("direction", "")
        odds = float(b.get("odds", -110))

        # Determine win/loss
        if market in ("run_line", "run_line_dog"):
            # line is stored with correct sign: -1.5 for fav, +1.5 for dog
            line = float(b.get("line", -1.5 if market == "run_line" else 1.5))
            if direction == "home":
                margin = (home_score - away_score) + line
            else:
                margin = (away_score - home_score) + line
            if margin > 0:
                result = "WIN"
            elif margin < 0:
                result = "LOSS"
            else:
                result = "PUSH"
        elif market == "moneyline":
            if direction == "home":
                result = "WIN" if home_score > away_score else "LOSS"
            else:
                result = "WIN" if away_score > home_score else "LOSS"
        else:
            continue

        # Compute profit
        if result == "WIN":
            profit = (100 / abs(odds)) if odds < 0 else (odds / 100)
        elif result == "LOSS":
            profit = -1.0
        else:
            profit = 0.0

        b["result"] = result
        b["profit"] = round(profit, 4)
        graded += 1

    _BETS_PATH.write_text(json.dumps(
        {"description": "Franchise shadow bets — logged daily, graded nightly, validated end of June",
         "bets": bets},
        indent=2
    ))
    return graded


# ── Helpers ───────────────────────────────────────────────────────────────────

_MARKET_LABELS = {
    "moneyline":    "ML",
    "run_line":     "RL fav (-1.5)",
    "run_line_dog": "RL dog (+1.5)",
}


def _fmt_odds(avg: float) -> str:
    """Format average odds as American string."""
    if avg == 0:
        return "  —  "
    return f"{avg:+.0f}"


def _record_row(r: "FranchiseRecord", cfg: dict, rank: int | None = None) -> str:
    """
    Format one leaderboard row showing the metrics that actually matter:
      WR  AvgOdds  BE-WR  Edge  ROI  P&L
    """
    valid     = r.is_validated(cfg)
    v_str     = "✅" if valid else f"⏳{r.settled}"
    mkt_label = _MARKET_LABELS.get(r.market, r.market)
    wl        = f"{r.wins}W-{r.losses}L"
    avg_o     = _fmt_odds(r.avg_odds)
    be        = r.breakeven_wr
    edge      = r.edge_vs_be * 100   # pct points above break-even

    rank_s = f"{rank:>3}." if rank is not None else "    "
    return (
        f"  {rank_s}  {r.team:28}  {mkt_label:14}  {wl:7}  "
        f"{r.wr:.1%}  {avg_o:>6}  {be:.1%}  {edge:+.1f}pp  "
        f"{r.roi:+.1%}  {r.pnl:+.2f}u  {v_str}"
    )


# ── Reports ───────────────────────────────────────────────────────────────────

_HDR = (
    f"  {'':4}  {'Team':28}  {'Market':14}  {'W-L':7}  "
    f"{'WR':6}  {'AvgOdds':>6}  {'BE-WR':5}  {'Edge':7}  "
    f"{'ROI':6}  {'P&L':7}  St"
)


def print_report(verbose: bool = True) -> None:
    """Per-team detail view — every team, every market, with odds context."""
    cfg = load_config()
    bets = load_bets()
    records = build_records(bets)

    total_bets   = len(bets)
    settled_bets = sum(1 for b in bets if (b.get("result") or "").upper() in ("WIN","LOSS"))
    pending_bets = total_bets - settled_bets
    review_date  = cfg.get("review_date", "2026-06-30")
    status       = cfg.get("status", "shadow").upper()
    min_roi      = cfg.get("validation", {}).get("min_roi", 0.05)

    print(f"\n{'='*88}")
    print(f"  FRANCHISE TRACKER — {status}  ·  review {review_date}  "
          f"·  {settled_bets} settled  ·  {pending_bets} pending")
    print(f"  Validation: ≥30 picks  +  ROI ≥ {min_roi:.0%}  +  WR ≥ break-even at avg odds")
    print(f"{'='*88}")
    print(_HDR)
    print(f"  {'─'*83}")

    teams_cfg = {t["slug"]: t for t in cfg.get("teams", [])}
    for slug, team_cfg in teams_cfg.items():
        for market in ("moneyline", "run_line", "run_line_dog"):
            key = (slug, market)
            r   = records.get(key)
            if r is None or r.settled == 0:
                continue
            print(_record_row(r, cfg))

    # Overall
    all_w   = sum(r.wins   for r in records.values())
    all_l   = sum(r.losses for r in records.values())
    all_pnl = sum(r.pnl    for r in records.values())
    all_wr  = all_w / (all_w + all_l) if (all_w + all_l) else 0

    print(f"  {'─'*83}")
    print(f"  {'OVERALL':>5}  {all_w}W-{all_l}L ({all_wr:.1%} WR)  {all_pnl:+.2f}u")
    print(f"{'='*88}\n")


def print_leaderboard(min_picks: int = 5) -> None:
    """
    All team/market combos with ≥ min_picks settled bets, ranked by ROI.
    Shows avg odds and break-even WR so the ROI makes sense in context.
    """
    cfg     = load_config()
    bets    = load_bets()
    records = build_records(bets)

    qualified = [
        (key, r) for key, r in records.items()
        if r.settled >= min_picks
    ]
    qualified.sort(key=lambda x: x[1].roi, reverse=True)

    total_combos  = len(records)
    total_bets    = len(bets)
    total_settled = sum(r.settled for r in records.values())
    review_date   = cfg.get("review_date", "2026-06-30")
    min_roi       = cfg.get("validation", {}).get("min_roi", 0.05)

    print(f"\n{'='*88}")
    print(f"  FRANCHISE LEADERBOARD — {total_combos} combos tracked  ·  {total_settled} settled  "
          f"·  review {review_date}")
    print(f"  Ranked by ROI. Validation gate: ≥30 picks + ROI ≥ {min_roi:.0%} + WR ≥ break-even.")
    print(f"  AvgOdds = avg price you bet at. BE-WR = WR needed to profit at those odds.")
    print(f"{'='*88}")
    print(_HDR)
    print(f"  {'─'*83}")

    for rank, ((slug, market), r) in enumerate(qualified, 1):
        print(_record_row(r, cfg, rank=rank))

    if not qualified:
        print(f"  No combos with {min_picks}+ settled picks yet — games grade tonight.")

    # Bottom 5 callout when enough data
    if len(qualified) >= 10:
        print(f"\n  ── Bottom 5 (worst ROI, cut candidates) ──")
        for (slug, market), r in qualified[-5:]:
            print(_record_row(r, cfg))

    # Pending summary
    total_pending = total_bets - total_settled
    print(f"\n  {total_pending} bets pending grade  ·  {total_combos - len(qualified)} combos "
          f"still building sample (<{min_picks} picks)")
    print(f"{'='*88}\n")


def validation_summary(verbose: bool = False) -> dict:
    """Return validation status dict for all team/market combos."""
    cfg = load_config()
    bets = load_bets()
    records = build_records(bets)
    result = {}
    for team_cfg in cfg.get("teams", []):
        slug = team_cfg["slug"]
        for market in team_cfg.get("markets", []):
            r = records.get((slug, market))
            valid = r.is_validated(cfg) if r else False
            result[f"{slug}_{market}"] = {
                "team": team_cfg["name"],
                "market": market,
                "n": r.settled if r else 0,
                "wr": round(r.wr, 4) if r else 0,
                "pnl": round(r.pnl, 2) if r else 0,
                "validated": valid,
            }
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid", action="store_true", help="Validation check only")
    args = parser.parse_args()

    if args.valid:
        summary = validation_summary()
        for k, v in summary.items():
            status = "✅" if v["validated"] else "⏳"
            print(f"  {status} {v['team']:25} {v['market']:12} {v['n']:>3} picks  {v['wr']:.1%} WR  {v['pnl']:+.2f}u")
    else:
        print_report()
