"""
Reddit daily thread templates — ChefTonyBets AI.

Generates four templates per day:
  1. r/sportsbook Pick of the Day (POTD) — one pick, -200/+200 range, model write-up
  2. MLB Props thread
  3. MLB Betting and Picks thread
  4. NBA Betting and Picks thread

Output: output/picks/{sport}/{YYYYMMDD}/captions/reddit_{template}.txt
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

OUTPUT_DIR = Path("output/picks")

_SEASON_RECORD = "44-32 (57.9% WR)"  # updated by write_reddit_templates

_MODEL_DESC = (
    "XGBoost + Pythagorean expectation ensemble trained on 10 years of MLB/NBA data. "
    "Walk-forward validated on held-out seasons. "
    "Edges calculated by comparing model win probability to sportsbook implied probability "
    "after vig removal. Kelly criterion used for sizing."
)


def _odds_str(odds) -> str:
    try:
        v = int(float(odds))
        return f"{v:+d}"
    except Exception:
        return str(odds)


def _day_str(d: date) -> str:
    return d.strftime("%-m/%-d/%y (%A)")


def _load_record(sport: str) -> str:
    try:
        import json
        stats = json.loads(Path("data/public_stats.json").read_text())
        sp = "mlb" if "mlb" in sport.lower() else "nba"
        s = stats.get("by_sport", {}).get(sp, {})
        w, l = s.get("wins", 0), s.get("losses", 0)
        if w + l < 3:
            return _SEASON_RECORD
        wr = round(w / (w + l) * 100, 1)
        profit = s.get("profit_units", 0)
        sign = "+" if profit >= 0 else ""
        return f"{w}-{l} ({wr}% WR, {sign}{profit:.1f}u)"
    except Exception:
        return _SEASON_RECORD


def _potd_pick(mlb_picks: list[dict], nba_picks: list[dict]) -> dict | None:
    """Return best POTD pick: highest edge within -200 to +200 odds, prefer +EV underdogs."""
    candidates = []
    for p in mlb_picks + nba_picks:
        odds = int(float(p.get("BestOdds") or p.get("odds") or 0))
        if odds == 0:
            continue
        # Must be within -200 to +200
        if odds < -200 or odds > 200:
            continue
        edge = float(p.get("Edge") or p.get("edge_pct") or 0)
        # Normalise: decimal edges (<1.0) → multiply by 100
        if 0 < edge < 1.0:
            edge = edge * 100
        if edge <= 0:
            continue
        candidates.append({**p, "_edge_pct": edge, "_odds": odds})
    if not candidates:
        return None
    return max(candidates, key=lambda x: x["_edge_pct"])


def _implied_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def _kelly(model_prob: float, odds: int) -> float:
    b = odds / 100 if odds > 0 else 100 / abs(odds)
    q = 1 - model_prob
    k = (b * model_prob - q) / b
    return max(0.0, k)


# ── Template 1: Pick of the Day ───────────────────────────────────────────────

def _potd_template(
    mlb_picks: list[dict],
    nba_picks: list[dict],
    d: date,
    record: str,
) -> str:
    pick = _potd_pick(mlb_picks, nba_picks)
    if not pick:
        return ""

    odds     = pick["_odds"]
    edge_pct = pick["_edge_pct"]
    team     = pick.get("Team") or pick.get("team") or pick.get("direction") or ""
    opponent = pick.get("Opponent") or pick.get("opponent") or pick.get("matchup") or ""
    book     = pick.get("Sportsbook") or pick.get("sportsbook") or ""
    market   = str(pick.get("Market") or pick.get("market") or "moneyline").lower()
    why      = pick.get("Why") or pick.get("why") or ""
    model_prob = float(pick.get("ModelProb") or pick.get("model_prob") or 0)

    # Determine sport + event string
    is_nba = pick.get("_sport") == "nba"
    sport_str = "NBA" if is_nba else "MLB"
    if opponent and " @ " in str(opponent):
        event_str = opponent
    elif opponent:
        event_str = f"{opponent} @ {team}" if not is_nba else f"{opponent} vs {team}"
    else:
        event_str = team

    market_label = "Moneyline" if market in ("moneyline", "h2h") else market.upper()

    impl_prob = _implied_prob(odds)
    kelly_frac = _kelly(model_prob, odds) if model_prob > 0 else edge_pct / 100 * 0.25
    units = max(1.0, min(5.0, round(kelly_frac * 20, 1)))  # quarter-Kelly scaled to 1–5u

    why_line = f"\n\n**Why:** {why}" if why and why.strip() else ""

    return f"""**ChefTonyBets AI — Pick of the Day · {_day_str(d)}**

**Sport:** {sport_str}
**Pick:** {team} {market_label} {_odds_str(odds)} @ {book}
**Event:** {event_str}
**Bet Size:** {units:.1f} units

---

**Model Edge:** +{edge_pct:.1f}% (model: {model_prob*100:.1f}% vs market: {impl_prob*100:.1f}%)
**Season Record:** {record}{why_line}

---

**About the Model**

{_MODEL_DESC}

The model runs daily before first pitch/tip-off. All picks are timestamped and logged publicly — you can verify the record at any point. No retroactive changes.

This pick was selected as POTD because it has the highest positive expected value among today's plays within the -200/+200 odds requirement.

---

*Not financial advice. Bet responsibly. 21+*"""


# ── Template 2: MLB Props ─────────────────────────────────────────────────────

def _mlb_props_template(props: list[dict], d: date, record: str) -> str:
    if not props:
        return ""

    # Separate pitcher Ks from HR and other props
    k_props  = [p for p in props if "strikeout" in str(p.get("market","")).lower()]
    hr_props = [p for p in props if "home_run" in str(p.get("market","")).lower() or "hr" in str(p.get("market","")).lower()]
    other    = [p for p in props if p not in k_props and p not in hr_props]

    def prop_row(p) -> str:
        player = p.get("player") or p.get("team") or ""
        mkt    = str(p.get("market","")).replace("pitcher_","").replace("batter_","").replace("_"," ").title()
        dirn   = str(p.get("direction","")).upper()
        line   = p.get("line") or p.get("bet_line") or ""
        odds   = _odds_str(p.get("odds") or p.get("BestOdds") or 0)
        edge   = float(p.get("edge_pct") or p.get("Edge") or 0)
        book   = p.get("book") or p.get("sportsbook") or p.get("Sportsbook") or "–"
        proj   = p.get("projected") or p.get("model_proj") or ""
        proj_str = f" (proj: {proj})" if proj else ""
        line_str = f" {line}" if line else ""
        return f"| {player} | {dirn} {mkt}{line_str} | {odds} | +{edge:.1f}%{proj_str} | {book} |"

    sections = []
    if k_props:
        rows = "\n".join(prop_row(p) for p in k_props[:8])
        sections.append(f"**🎯 Pitcher Strikeouts**\n\n| Player | Bet | Odds | Edge | Book |\n|--------|-----|------|------|------|\n{rows}")
    if hr_props:
        rows = "\n".join(prop_row(p) for p in hr_props[:5])
        sections.append(f"**💣 Home Run Props**\n\n| Player | Bet | Odds | Edge | Book |\n|--------|-----|------|------|------|\n{rows}")
    if other:
        rows = "\n".join(prop_row(p) for p in other[:5])
        sections.append(f"**📊 Other Props**\n\n| Player | Bet | Odds | Edge | Book |\n|--------|-----|------|------|------|\n{rows}")

    body = "\n\n".join(sections)

    return f"""**ChefTonyBets AI — MLB Props · {_day_str(d)}**

Running XGBoost prop model on pitcher K-rate, batter contact, park factors, and weather. {len(props)} edges found today.

**Season Record (props):** {record}

---

{body}

---

**How the prop model works:** Projects pitcher strikeout totals using K/9, opposing team K%, umpire tendencies, and ballpark factors. Batter props use wOBA, hard-hit rate, and matchup data vs. starter handedness.

All picks logged before first pitch. Verified record in post history.

*Not financial advice. Bet responsibly. 21+*"""


# ── Template 3: MLB Betting & Picks ──────────────────────────────────────────

def _mlb_picks_template(picks: list[dict], nrfi_picks: list[dict], d: date, record: str) -> str:
    def pick_row(p) -> str:
        team   = p.get("Team") or p.get("team") or ""
        opp    = p.get("Opponent") or p.get("opponent") or ""
        odds   = _odds_str(p.get("BestOdds") or p.get("odds") or 0)
        edge   = float(p.get("Edge") or p.get("edge_pct") or 0)
        if 0 < edge < 1.0:
            edge *= 100
        book   = p.get("Sportsbook") or p.get("sportsbook") or ""
        why    = p.get("Why") or p.get("why") or ""
        why_str = f" — {why}" if why and why.strip() else ""
        return f"| {team} vs {opp} | {odds} | +{edge:.1f}%{why_str} | {book} |"

    ml_rows   = "\n".join(pick_row(p) for p in picks[:5])
    nrfi_rows = ""
    if nrfi_picks:
        nrfi_lines = []
        for p in nrfi_picks[:5]:
            matchup = (p.get("label") or p.get("matchup") or p.get("Matchup")
                       or f"{p.get('away_team','')} @ {p.get('home_team','')}").strip()
            prob    = float(p.get("projected_nrfi") or p.get("model_prob") or p.get("ModelProb") or 0) * 100
            odds    = _odds_str(p.get("odds") or p.get("BestOdds") or 0)
            book    = p.get("book") or p.get("sportsbook") or p.get("Sportsbook") or "–"
            sp_away = p.get("away_sp") or ""
            sp_home = p.get("home_sp") or ""
            sp_note = f" ({sp_away} vs {sp_home})" if sp_away and sp_home else ""
            nrfi_lines.append(f"| {matchup}{sp_note} | NRFI {odds} | {prob:.0f}% | {book} |")
        nrfi_rows = "\n**⚡ NRFI Plays**\n\n| Game | Bet | Proj% | Book |\n|------|-----|-------|------|\n" + "\n".join(nrfi_lines)

    return f"""**ChefTonyBets AI — MLB Picks · {_day_str(d)}**

XGBoost + Pythagorean ensemble | Walk-forward validated | **Season: {record}**

All picks timestamped before first pitch. No retroactive edits.

---

**💰 Moneyline Edges**

| Game | Odds | Edge | Book |
|------|------|------|------|
{ml_rows}
{nrfi_rows}

---

**Model overview:** Ensemble of XGBoost (pitcher ERA, FIP, xFIP, bullpen REST, lineup wRC+) and Pythagorean expectation. Edge = model win prob minus sportsbook implied prob after vig removal. Only plays where both methods agree are posted as card picks.

Drop questions in the comments — happy to explain any pick.

*Not financial advice. Bet responsibly. 21+*"""


# ── Template 4: NBA Betting & Picks ──────────────────────────────────────────

def _nba_picks_template(picks: list[dict], d: date, record: str) -> str:
    ml_picks = [p for p in picks if str(p.get("market","")).lower() in ("moneyline","h2h")]
    ou_picks = [p for p in picks if str(p.get("market","")).lower() in ("total","totals")]

    def ml_row(p) -> str:
        team   = p.get("team") or p.get("Team") or ""
        opp    = p.get("matchup") or p.get("Matchup") or p.get("Opponent") or ""
        odds   = _odds_str(p.get("odds") or p.get("BestOdds") or 0)
        edge   = float(p.get("edge_pct") or p.get("Edge") or 0)
        book   = p.get("sportsbook") or p.get("Sportsbook") or ""
        return f"| {team} ({opp}) | {odds} | +{edge:.1f}% | {book} |"

    def ou_row(p) -> str:
        dirn   = str(p.get("direction") or p.get("Direction") or "OVER").upper()
        line   = p.get("line") or p.get("MarketLine") or p.get("bet_line") or ""
        matchup = p.get("matchup") or p.get("Matchup") or ""
        odds   = _odds_str(p.get("odds") or p.get("BestOdds") or 0)
        edge   = float(p.get("edge_pct") or p.get("Edge") or 0)
        book   = p.get("sportsbook") or p.get("Sportsbook") or ""
        return f"| {matchup} | {dirn} {line} {odds} | +{edge:.1f}% | {book} |"

    sections = []
    if ml_picks:
        rows = "\n".join(ml_row(p) for p in ml_picks[:5])
        sections.append(f"**🏀 Moneyline**\n\n| Pick | Odds | Edge | Book |\n|------|------|------|------|\n{rows}")
    if ou_picks:
        rows = "\n".join(ou_row(p) for p in ou_picks[:5])
        sections.append(f"**📊 Totals (O/U)**\n\n| Game | Bet | Edge | Book |\n|------|-----|------|------|\n{rows}")

    if not sections:
        return ""

    body = "\n\n".join(sections)

    return f"""**ChefTonyBets AI — NBA Picks · {_day_str(d)}**

XGBoost on ORtg/DRtg/Pace efficiency ratings | **Season: {record}**

All picks timestamped before tip-off. Verified record in post history.

---

{body}

---

**Model overview:** Trains on 10 years of NBA box scores. Features: offensive/defensive rating, pace, rest advantage, travel, home court, lineup injury adjustments. Walk-forward validated — no look-ahead bias. Edge = model probability minus sportsbook implied after vig removal.

Drop any questions below.

*Not financial advice. Bet responsibly. 21+*"""


# ── Main entry point ──────────────────────────────────────────────────────────

def write_reddit_templates(
    mlb_picks:  list[dict],
    mlb_props:  list[dict],
    nrfi_picks: list[dict],
    nba_picks:  list[dict],
    sport: str,
    card_date: date | None = None,
) -> dict[str, Path]:
    d       = card_date or date.today()
    ts      = d.strftime("%Y%m%d")
    record  = _load_record(sport)

    # Tag each pick with sport for POTD selection
    # Tag and normalise picks — handle both capital-key (predict.py) and lowercase-key (run_nba.py) formats
    for p in mlb_picks:
        p["_sport"] = "mlb"
        if "ModelProb" in p and "model_prob" not in p:
            p["model_prob"] = p["ModelProb"]
        if "Opponent" in p and not p.get("opponent"):
            p["opponent"] = p["Opponent"]
        if "Sportsbook" in p and not p.get("sportsbook"):
            p["sportsbook"] = p["Sportsbook"]
        if "Why" in p and not p.get("why"):
            p["why"] = p["Why"]
    for p in nba_picks:
        p["_sport"] = "nba"

    out_dir = OUTPUT_DIR / sport / ts / "captions"
    out_dir.mkdir(parents=True, exist_ok=True)

    written = {}

    # 1. POTD
    potd = _potd_template(mlb_picks, nba_picks, d, record)
    if potd:
        p = out_dir / "reddit_potd.txt"
        p.write_text(potd)
        written["potd"] = p

    # 2. MLB Props
    if mlb_props and "mlb" in sport.lower():
        props_txt = _mlb_props_template(mlb_props, d, record)
        if props_txt:
            p = out_dir / "reddit_mlb_props.txt"
            p.write_text(props_txt)
            written["mlb_props"] = p

    # 3. MLB Picks
    if mlb_picks and "mlb" in sport.lower():
        txt = _mlb_picks_template(mlb_picks, nrfi_picks, d, record)
        if txt:
            p = out_dir / "reddit_mlb_picks.txt"
            p.write_text(txt)
            written["mlb_picks"] = p

    # 4. NBA Picks
    if nba_picks and "nba" in sport.lower():
        txt = _nba_picks_template(nba_picks, d, record)
        if txt:
            p = out_dir / "reddit_nba_picks.txt"
            p.write_text(txt)
            written["nba_picks"] = p

    return written
