"""
Generate a nightly graded results card for Instagram Stories (1080×1920).

Covers all markets: moneylines, totals, run lines, props, NRFI, NBA picks.

Usage:
    python3 scripts/gen_results_card.py                # today
    python3 scripts/gen_results_card.py 20260415       # specific date
    python3 scripts/gen_results_card.py 20260415 --challenge  # challenge bets only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output" / "picks"
BANKROLL   = ROOT / "data" / "challenge" / "bankroll.json"

MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
ESPN_NBA     = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"


# ── Score fetching ─────────────────────────────────────────────────────────────

def fetch_mlb_scores(date_str: str) -> dict[str, dict]:
    """
    Returns {team_name_lower: {runs, opponent, opp_runs, linescore_1st_inn}}
    Keyed by BOTH teams in each game.
    """
    d = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    try:
        r = requests.get(
            MLB_SCHEDULE,
            params={"sportId": 1, "date": d, "hydrate": "linescore,boxscore"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [scores] MLB fetch failed: {e}")
        return {}

    scores: dict[str, dict] = {}
    for game_date in data.get("dates", []):
        for game in game_date.get("games", []):
            status = game.get("status", {}).get("abstractGameState", "")
            if status not in ("Final", "Game Over"):
                continue

            teams = game.get("teams", {})
            away  = teams.get("away", {})
            home  = teams.get("home", {})
            away_name  = away.get("team", {}).get("name", "")
            home_name  = home.get("team", {}).get("name", "")
            away_runs  = int(away.get("score", 0) or 0)
            home_runs  = int(home.get("score", 0) or 0)
            total_runs = away_runs + home_runs

            # First inning linescore
            linescore = game.get("linescore", {})
            innings   = linescore.get("innings", [])
            away_1st  = home_1st = 0
            if innings:
                i1 = innings[0]
                away_1st = int(i1.get("away", {}).get("runs", 0) or 0)
                home_1st = int(i1.get("home", {}).get("runs", 0) or 0)
            nrfi = (away_1st == 0 and home_1st == 0)

            away_key = away_name.lower()
            home_key = home_name.lower()
            game_rec = {
                "away": away_name,
                "home": home_name,
                "away_runs": away_runs,
                "home_runs": home_runs,
                "total": total_runs,
                "away_1st": away_1st,
                "home_1st": home_1st,
                "nrfi": nrfi,
                "winner": home_name if home_runs > away_runs else away_name,
            }
            scores[away_key] = game_rec
            scores[home_key] = game_rec

    return scores


def fetch_nba_scores(date_str: str) -> dict[str, dict]:
    """Returns {team_name_lower: {pts, opp, opp_pts, total, winner}}"""
    try:
        r = requests.get(ESPN_NBA, params={"dates": date_str}, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [scores] NBA fetch failed: {e}")
        return {}

    scores: dict[str, dict] = {}
    for ev in data.get("events", []):
        comps = ev.get("competitions", [])
        if not comps:
            continue
        comp = comps[0]
        if comp.get("status", {}).get("type", {}).get("state") != "post":
            continue

        teams = comp.get("competitors", [])
        if len(teams) < 2:
            continue

        t1 = teams[0]
        t2 = teams[1]
        t1_name = t1.get("team", {}).get("displayName", "")
        t2_name = t2.get("team", {}).get("displayName", "")
        t1_pts  = int(t1.get("score", 0) or 0)
        t2_pts  = int(t2.get("score", 0) or 0)
        total   = t1_pts + t2_pts
        winner  = t1_name if t1.get("winner") else t2_name

        for name, pts, opp_name, opp_pts in [
            (t1_name, t1_pts, t2_name, t2_pts),
            (t2_name, t2_pts, t1_name, t1_pts),
        ]:
            scores[name.lower()] = {
                "name": name,
                "pts": pts,
                "opp": opp_name,
                "opp_pts": opp_pts,
                "total": total,
                "winner": winner,
            }

    return scores


# ── Grading ────────────────────────────────────────────────────────────────────

def _fuzzy_find(name: str, scores: dict) -> dict | None:
    k = name.lower().strip()
    if k in scores:
        return scores[k]
    for key in scores:
        if k in key or key in k:
            return scores[key]
    # word-level match
    words = [w for w in k.split() if len(w) > 3]
    for key in scores:
        if any(w in key for w in words):
            return scores[key]
    return None


def grade_total(pick: dict, mlb_scores: dict) -> dict:
    """Grade UNDER/OVER total pick."""
    team     = str(pick.get("Team", "") or pick.get("team", ""))
    opponent = str(pick.get("Opponent", "") or pick.get("matchup", ""))
    parts    = team.upper().split()
    if len(parts) < 2:
        return {"status": "pending", "score": ""}

    direction = parts[0]
    try:
        line = float(parts[1])
    except ValueError:
        return {"status": "pending", "score": ""}

    # Find the game via opponent string
    game = None
    for seg in re.split(r"\s*[@,]\s*", opponent):
        g = _fuzzy_find(seg.strip(), mlb_scores)
        if g:
            game = g
            break

    if not game:
        return {"status": "pending", "score": ""}

    actual = game["total"]
    score_str = f"{game['away']} {game['away_runs']}, {game['home']} {game['home_runs']}"

    if actual == line:
        return {"status": "push", "score": score_str, "actual": actual}
    hit = (direction == "UNDER" and actual < line) or \
          (direction == "OVER"  and actual > line)
    return {"status": "win" if hit else "loss", "score": score_str, "actual": actual}


def grade_moneyline(pick: dict, mlb_scores: dict) -> dict:
    """Grade moneyline pick (MLB)."""
    team = str(pick.get("Team", "") or pick.get("team", ""))
    game = _fuzzy_find(team, mlb_scores)
    if not game:
        return {"status": "pending", "score": ""}
    score_str = f"{game['away']} {game['away_runs']}, {game['home']} {game['home_runs']}"
    won = game["winner"].lower() == team.lower() or team.lower() in game["winner"].lower()
    return {"status": "win" if won else "loss", "score": score_str}


def grade_runline(pick: dict, mlb_scores: dict) -> dict:
    """Grade run-line spread pick."""
    team_raw = str(pick.get("Team", "") or pick.get("team", ""))
    # "Arizona Diamondbacks +1.5" → team + line
    m = re.match(r"^(.+?)\s+([+-]\d+\.?\d*)$", team_raw.strip())
    if not m:
        return {"status": "pending", "score": ""}
    team_name = m.group(1).strip()
    spread    = float(m.group(2))

    game = _fuzzy_find(team_name, mlb_scores)
    if not game:
        return {"status": "pending", "score": ""}

    score_str = f"{game['away']} {game['away_runs']}, {game['home']} {game['home_runs']}"
    is_away   = game["away"].lower() == team_name.lower() or \
                team_name.lower() in game["away"].lower()
    team_runs = game["away_runs"] if is_away else game["home_runs"]
    opp_runs  = game["home_runs"] if is_away else game["away_runs"]
    margin    = team_runs - opp_runs  # positive = team won

    covered = margin + spread > 0
    pushed  = margin + spread == 0
    return {"status": "push" if pushed else ("win" if covered else "loss"), "score": score_str}


def grade_nrfi(pick: dict, mlb_scores: dict) -> dict:
    """Grade NRFI/YRFI pick."""
    home = str(pick.get("home_team", ""))
    away = str(pick.get("away_team", ""))
    direction = str(pick.get("direction", "NRFI")).upper()

    game = _fuzzy_find(home, mlb_scores) or _fuzzy_find(away, mlb_scores)
    if not game:
        return {"status": "pending", "score": ""}

    nrfi = game["nrfi"]
    score_str = f"1st inn: {game['away']} {game['away_1st']}, {game['home']} {game['home_1st']}"

    if direction == "NRFI":
        return {"status": "win" if nrfi else "loss", "score": score_str}
    else:  # YRFI
        return {"status": "win" if not nrfi else "loss", "score": score_str}


def grade_nba(pick: dict, nba_scores: dict) -> dict:
    """Grade NBA moneyline, spread, or total."""
    market    = str(pick.get("market", "")).lower()
    team_raw  = str(pick.get("team", "") or pick.get("Team", ""))
    matchup   = str(pick.get("matchup", "") or pick.get("Matchup", ""))

    if market in ("total", "nba_total") or team_raw.upper().startswith(("OVER ", "UNDER ")):
        parts = team_raw.upper().split()
        if len(parts) < 2:
            return {"status": "pending", "score": ""}
        direction = parts[0]
        try:
            line = float(parts[1])
        except ValueError:
            return {"status": "pending", "score": ""}

        game = None
        for seg in re.split(r"\s*[@,]\s*", matchup):
            g = _fuzzy_find(seg.strip(), nba_scores)
            if g:
                game = g
                break

        if not game:
            return {"status": "pending", "score": ""}

        actual    = game["total"]
        score_str = f"{game['opp']} {game['opp_pts']}, {game['name']} {game['pts']}"
        if actual == line:
            return {"status": "push", "score": score_str, "actual": actual}
        hit = (direction == "UNDER" and actual < line) or \
              (direction == "OVER"  and actual > line)
        return {"status": "win" if hit else "loss", "score": score_str, "actual": actual}

    elif market in ("spread", "nba_spread"):
        m = re.match(r"^(.+?)\s+([+-]\d+\.?\d*)$", team_raw.strip())
        if not m:
            return {"status": "pending", "score": ""}
        team_name = m.group(1).strip()
        spread    = float(m.group(2))

        game = _fuzzy_find(team_name, nba_scores)
        if not game:
            return {"status": "pending", "score": ""}

        margin    = game["pts"] - game["opp_pts"]
        score_str = f"{game['name']} {game['pts']}, {game['opp']} {game['opp_pts']}"
        covered   = margin + spread > 0
        pushed    = margin + spread == 0
        return {"status": "push" if pushed else ("win" if covered else "loss"), "score": score_str}

    else:  # moneyline
        team_name = team_raw
        game      = _fuzzy_find(team_name, nba_scores)
        if not game:
            return {"status": "pending", "score": ""}
        score_str = f"{game['name']} {game['pts']}, {game['opp']} {game['opp_pts']}"
        won = game["winner"].lower() == team_name.lower() or \
              team_name.lower() in game["winner"].lower()
        return {"status": "win" if won else "loss", "score": score_str}


# ── Load picks ─────────────────────────────────────────────────────────────────

def load_picks_for_date(date_str: str) -> list[dict]:
    """
    Load and merge all pick sources for a date into a unified list.
    Each pick has: source, label, market, odds, book, direction, line, matchup
    """
    all_picks = []
    mlb_dir   = OUTPUT_DIR / "baseball_mlb" / date_str
    nba_dir   = OUTPUT_DIR / "basketball_nba" / date_str

    # ── Challenge bets (always first — these are real money) ──────────────────
    if BANKROLL.exists():
        bk = json.loads(BANKROLL.read_text())
        for bet in bk.get("bets", []):
            if bet.get("date", "").replace("-", "") == date_str:
                all_picks.append({
                    "source": "challenge",
                    "label":  bet.get("game", bet.get("team", "")),
                    "team":   bet.get("team", ""),
                    "market": bet.get("market", "moneyline"),
                    "odds":   bet.get("odds", 0),
                    "book":   bet.get("sportsbook", ""),
                    "result": bet.get("result"),      # pre-populated from bankroll
                    "profit": bet.get("profit"),
                    "score":  bet.get("final_score", ""),
                    "notes":  bet.get("notes", ""),
                    "bet_amount": bet.get("bet_amount", 0),
                })

    if all_picks:
        return all_picks   # challenge bets are the ground truth for the card

    # ── Fallback: top model picks ─────────────────────────────────────────────
    # MLB totals
    picks_file = mlb_dir / "picks_card.json"
    if picks_file.exists():
        data = json.loads(picks_file.read_text())
        for p in (data if isinstance(data, list) else [])[:6]:
            if str(p.get("Market", "")).lower() == "total":
                all_picks.append({
                    "source": "model_total",
                    "label":  f"{p.get('Team','')}  {p.get('Opponent','')}",
                    "team":   p.get("Team", ""),
                    "market": "total",
                    "odds":   p.get("BestOdds", 0),
                    "book":   p.get("Sportsbook", ""),
                    "matchup": p.get("Opponent", ""),
                    "edge":   p.get("Edge", 0),
                })
            else:
                all_picks.append({
                    "source": "model_ml",
                    "label":  f"{p.get('Team','')}  vs  {p.get('Opponent','')}",
                    "team":   p.get("Team", ""),
                    "market": "moneyline",
                    "odds":   p.get("BestOdds", 0),
                    "book":   p.get("Sportsbook", ""),
                    "matchup": p.get("Opponent", ""),
                    "edge":   p.get("Edge", 0),
                })

    # Top 3 props
    props_file = mlb_dir / "props.json"
    if props_file.exists():
        props = json.loads(props_file.read_text())
        for p in props[:3]:
            all_picks.append({
                "source": "prop",
                "label":  p.get("label", ""),
                "team":   p.get("player", ""),
                "market": "prop",
                "odds":   p.get("odds", 0),
                "book":   p.get("book", ""),
                "matchup": f"{p.get('opp','')}",
                "edge":   p.get("edge_pct", 0),
                "prop_direction": p.get("direction", ""),
                "prop_line": p.get("line", 0),
                "projected": p.get("projected", 0),
            })

    # Top 2 NRFI
    nrfi_file = mlb_dir / "nrfi.json"
    if nrfi_file.exists():
        nrfi = json.loads(nrfi_file.read_text())
        for p in nrfi[:2]:
            all_picks.append({
                "source": "nrfi",
                "label":  p.get("label", ""),
                "team":   "NRFI",
                "market": "nrfi",
                "odds":   p.get("odds"),
                "book":   p.get("book", ""),
                "home_team": p.get("home_team", ""),
                "away_team": p.get("away_team", ""),
                "direction": p.get("direction", "NRFI"),
            })

    # NBA picks
    nba_file = nba_dir / "picks.json"
    if nba_file.exists():
        nba = json.loads(nba_file.read_text())
        # Only picks with commence_time on this date
        yyyy, mm, dd = date_str[:4], date_str[4:6], date_str[6:]
        date_prefix  = f"{yyyy}-{mm}-{dd}"
        for p in (nba if isinstance(nba, list) else [])[:4]:
            ct = str(p.get("commence_time", ""))
            if date_prefix in ct:
                all_picks.append({
                    "source": "nba",
                    "label":  f"{p.get('team','')}  ({p.get('matchup','')})",
                    "team":   p.get("team", ""),
                    "market": f"nba_{p.get('market','moneyline')}",
                    "odds":   p.get("best_odds", 0),
                    "book":   p.get("sportsbook", ""),
                    "matchup": p.get("matchup", ""),
                    "edge":   p.get("edge_pct", 0),
                })

    return all_picks


# ── HTML card builder ──────────────────────────────────────────────────────────

_MARKET_LABELS = {
    "moneyline":     "ML",
    "total":         "O/U",
    "spread":        "RL",
    "nrfi":          "NRFI",
    "prop":          "PROP",
    "nba_moneyline": "NBA ML",
    "nba_total":     "NBA O/U",
    "nba_spread":    "NBA SPD",
    "prop_pitcher_strikeouts": "K PROP",
}

_STATUS_COLORS = {
    "win":     ("#00C963", "#0A3D1A"),
    "loss":    ("#FF3B3B", "#3D0A0A"),
    "push":    ("#FFBE00", "#3D2E00"),
    "pending": ("#555870", "#12131E"),
}


def _fmt_odds(odds) -> str:
    try:
        v = int(float(odds))
        return f"+{v}" if v > 0 else str(v)
    except (TypeError, ValueError):
        return "—"


def _row_html(pick: dict, grade: dict) -> str:
    status = grade.get("status", "pending")
    score  = grade.get("score", "")
    profit = pick.get("profit")
    result = pick.get("result") or status

    # Use bankroll result if pre-populated
    if pick.get("result") in ("win", "loss", "push"):
        result = pick["result"]
        score  = pick.get("score") or score

    fg, bg = _STATUS_COLORS.get(result, _STATUS_COLORS["pending"])

    label  = pick.get("label", pick.get("team", ""))[:52]
    mkt    = _MARKET_LABELS.get(pick.get("market", ""), pick.get("market", "ML").upper())
    odds   = _fmt_odds(pick.get("odds", ""))
    book   = str(pick.get("book", ""))[:14]
    amt    = pick.get("bet_amount")
    edge   = pick.get("edge")

    # Result badge
    badge_text  = result.upper()
    badge_emoji = "✓" if result == "win" else ("✗" if result == "loss" else ("↔" if result == "push" else "…"))

    profit_str = ""
    if profit is not None:
        profit_str = f"<span class='profit {'pos' if float(profit)>=0 else 'neg'}'>{'+' if float(profit)>=0 else ''}{profit:.2f}u</span>"

    score_str = f"<span class='score-tag'>{score}</span>" if score else ""
    amt_str   = f"<span class='bet-amt'>${amt:.2f}</span>" if amt else ""
    edge_str  = f"<span class='edge-tag'>+{edge:.1f}%</span>" if edge else ""

    return f"""
  <div class="pick-row" style="--row-bg:{bg}; --row-fg:{fg};">
    <div class="pick-left">
      <span class="mkt-pill">{mkt}</span>
      <span class="pick-label">{label}</span>
      <div class="pick-meta">
        <span class="odds-tag">{odds}</span>
        {f'<span class="book-tag">{book}</span>' if book else ''}
        {amt_str}
        {edge_str}
      </div>
      {score_str}
    </div>
    <div class="pick-right" style="background:{bg}; color:{fg};">
      <span class="badge-icon">{badge_emoji}</span>
      <span class="badge-word">{badge_text}</span>
      {profit_str}
    </div>
  </div>"""


def build_html(date_str: str, picks: list[dict], grades: list[dict]) -> str:
    d    = datetime.strptime(date_str, "%Y%m%d")
    dt   = d.strftime("%b %d, %Y").upper()

    wins    = sum(1 for g in grades if g.get("status") == "win"   or g.get("result") == "win")
    losses  = sum(1 for g in grades if g.get("status") == "loss"  or g.get("result") == "loss")
    pushes  = sum(1 for g in grades if g.get("status") == "push"  or g.get("result") == "push")
    profit  = sum(float(p.get("profit", 0) or 0) for p in picks if p.get("result"))
    record  = f"{wins}-{losses}" + (f"-{pushes}P" if pushes else "")
    rec_col = "#00C963" if wins >= losses else "#FF3B3B"
    pnl_col = "#00C963" if profit >= 0 else "#FF3B3B"
    pnl_str = f"{'+' if profit >= 0 else ''}{profit:.2f}u"

    rows = "".join(_row_html(p, g) for p, g in zip(picks, grades))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}

body {{
  width: 1080px;
  min-height: 1920px;
  background: #07080F;
  font-family: 'Inter', -apple-system, sans-serif;
  overflow: hidden;
  color: #F0F0F8;
}}

.wrap {{
  width: 1080px;
  min-height: 1920px;
  background:
    radial-gradient(ellipse 80% 35% at 50% 0%, rgba(255,190,0,0.07) 0%, transparent 65%),
    radial-gradient(ellipse 60% 50% at 90% 100%, rgba(0,201,99,0.04) 0%, transparent 60%),
    linear-gradient(180deg, #0A0C1A 0%, #06080F 100%);
  display: flex;
  flex-direction: column;
  padding-bottom: 40px;
}}

/* ── Header ── */
.header {{
  padding: 36px 48px 28px;
  border-bottom: 1px solid rgba(255,190,0,0.25);
  background: linear-gradient(180deg, rgba(255,190,0,0.06) 0%, transparent 100%);
}}

.brand-row {{
  display: flex;
  align-items: baseline;
  gap: 0;
  line-height: 1;
}}

.brand-chef {{ font-size: 80px; font-weight: 900; color: #F8F8FC; letter-spacing: -3px; }}
.brand-bets {{ font-size: 62px; font-weight: 900; color: #FFBE00; letter-spacing: -1px; margin-left: 4px; }}
.brand-ai {{
  font-size: 38px; font-weight: 800; margin-left: 12px; margin-bottom: 4px;
  background: linear-gradient(135deg, #00D4E0, #7B61FF);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  filter: drop-shadow(0 0 10px rgba(0,210,220,0.4));
}}

.brand-sub {{ font-size: 17px; color: #444860; font-weight: 400; margin-top: 10px; letter-spacing: 0.03em; }}

.header-meta {{
  margin-top: 22px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}}

.date-tag {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  color: #888AA8;
  font-weight: 700;
  letter-spacing: 0.05em;
}}

.handle {{ font-size: 22px; color: #FFBE00; font-weight: 700; }}

/* ── Record banner ── */
.record-bar {{
  margin: 0 0 4px;
  padding: 20px 48px;
  background: linear-gradient(90deg, rgba(0,0,0,0.4) 0%, rgba(10,12,28,0.6) 100%);
  border-bottom: 2px solid rgba(255,190,0,0.15);
  display: flex;
  align-items: center;
  gap: 32px;
}}

.record-big {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 86px;
  font-weight: 800;
  color: {rec_col};
  letter-spacing: -3px;
  line-height: 1;
  filter: drop-shadow(0 0 16px {rec_col}60);
}}

.record-meta {{
  display: flex;
  flex-direction: column;
  gap: 6px;
}}

.record-label {{ font-size: 18px; color: #444860; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; }}
.pnl-tag {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 32px;
  font-weight: 700;
  color: {pnl_col};
  letter-spacing: -0.5px;
}}

.sport-badge {{
  margin-left: auto;
  background: rgba(255,190,0,0.12);
  border: 1px solid rgba(255,190,0,0.3);
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 20px;
  font-weight: 700;
  color: #FFBE00;
  letter-spacing: 0.08em;
}}

/* ── Section label ── */
.section-label {{
  padding: 16px 48px 8px;
  font-size: 13px;
  font-weight: 700;
  color: #333550;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-family: 'JetBrains Mono', monospace;
}}

/* ── Pick rows ── */
.picks-list {{
  padding: 0 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}}

.pick-row {{
  display: flex;
  border-radius: 14px;
  overflow: hidden;
  background: #0E1020;
  border: 1px solid rgba(255,255,255,0.05);
  min-height: 110px;
}}

.pick-left {{
  flex: 1;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-right: 1px solid rgba(255,255,255,0.06);
}}

.mkt-pill {{
  display: inline-block;
  background: rgba(255,190,0,0.12);
  border: 1px solid rgba(255,190,0,0.25);
  border-radius: 5px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 700;
  color: #FFBE00;
  letter-spacing: 0.08em;
  font-family: 'JetBrains Mono', monospace;
  width: fit-content;
}}

.pick-label {{
  font-size: 22px;
  font-weight: 700;
  color: #E8E8F2;
  line-height: 1.2;
}}

.pick-meta {{
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}}

.odds-tag {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  font-weight: 700;
  color: #FFBE00;
}}

.book-tag {{
  font-size: 14px;
  color: #444860;
  font-weight: 600;
}}

.bet-amt {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  color: #888AA8;
}}

.edge-tag {{
  font-size: 13px;
  color: #2A7F4A;
  font-weight: 700;
  background: rgba(0,201,99,0.1);
  border-radius: 4px;
  padding: 1px 7px;
}}

.score-tag {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: #555870;
  margin-top: 2px;
}}

/* ── Result badge ── */
.pick-right {{
  width: 168px;
  min-width: 168px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 12px;
}}

.badge-icon {{
  font-size: 40px;
  font-weight: 900;
  line-height: 1;
}}

.badge-word {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.05em;
}}

.profit {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 700;
}}
.profit.pos {{ color: #00C963; }}
.profit.neg {{ color: #FF3B3B; }}

/* ── Footer ── */
.footer {{
  margin-top: auto;
  padding: 28px 48px 20px;
  border-top: 1px solid rgba(255,190,0,0.15);
  display: flex;
  justify-content: space-between;
  align-items: center;
}}

.footer-left {{ font-size: 17px; color: #444860; font-weight: 600; }}
.footer-right {{ font-size: 17px; color: #444860; font-weight: 600; text-align: right; }}

.footer-cta {{
  text-align: center;
  font-size: 20px;
  font-weight: 700;
  color: #FFBE00;
  letter-spacing: 0.03em;
}}

/* ── Gold accent line ── */
.gold-line {{ height: 4px; background: linear-gradient(90deg, #FFBE00, #FF8C00 50%, #FFBE00); }}
</style>
</head>
<body>
<div class="wrap">

<div class="gold-line"></div>

<div class="header">
  <div class="brand-row">
    <span class="brand-chef">ChefTony</span>
    <span class="brand-bets">Bets</span>
    <span class="brand-ai">AI</span>
  </div>
  <div class="brand-sub">RESULTS  ·  A.I. Sports Picks  ·  All Markets</div>
  <div class="header-meta">
    <span class="date-tag">{dt}</span>
    <span class="handle">@ChefTonyBets</span>
  </div>
</div>

<div class="record-bar">
  <span class="record-big">{record}</span>
  <div class="record-meta">
    <span class="record-label">Today's Record</span>
    <span class="pnl-tag">{pnl_str}</span>
  </div>
  <span class="sport-badge">GRADED PICKS</span>
</div>

<div class="section-label">— Today's Picks</div>

<div class="picks-list">
{rows}
</div>

<div class="footer">
  <div class="footer-left">AI-powered edge detection<br>Kelly criterion sizing</div>
  <div class="footer-cta">Follow for free daily picks<br>@ChefTonyBets</div>
  <div class="footer-right">Results verified<br>by model output</div>
</div>

</div>
</body>
</html>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def run(date_str: str) -> Path | None:
    print(f"  Generating results card for {date_str}...")

    picks = load_picks_for_date(date_str)
    if not picks:
        print(f"  No picks found for {date_str}")
        return None

    print(f"  Loaded {len(picks)} picks")

    # Fetch scores
    mlb_scores = fetch_mlb_scores(date_str)
    nba_scores = fetch_nba_scores(date_str)
    print(f"  Fetched {len(mlb_scores)//2} MLB games, {len(nba_scores)//2} NBA games")

    # Grade picks
    grades = []
    for pick in picks:
        market = pick.get("market", "moneyline").lower()
        result = pick.get("result")

        # If bankroll.json already has result, use it
        if result in ("win", "loss", "push"):
            score = pick.get("score", "") or pick.get("final_score", "")
            grades.append({"status": result, "score": score})
            continue

        if market in ("total",):
            g = grade_total(pick, mlb_scores)
        elif market in ("moneyline",):
            g = grade_moneyline(pick, mlb_scores)
        elif market in ("spread", "run_line"):
            g = grade_runline(pick, mlb_scores)
        elif market in ("nrfi", "yrfi"):
            g = grade_nrfi(pick, mlb_scores)
        elif market in ("nba_total", "nba_moneyline", "nba_spread"):
            g = grade_nba(pick, nba_scores)
        elif market.startswith("prop"):
            g = {"status": "pending", "score": ""}
        else:
            g = grade_moneyline(pick, mlb_scores)

        grades.append(g)

    wins   = sum(1 for g in grades if g["status"] == "win")
    losses = sum(1 for g in grades if g["status"] == "loss")
    print(f"  Graded: {wins}W {losses}L")

    # Build HTML
    html = build_html(date_str, picks, grades)

    # Save HTML
    out_dir  = OUTPUT_DIR / "baseball_mlb" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "results_card.html"
    html_path.write_text(html)
    print(f"  HTML saved: {html_path}")

    # Screenshot via Playwright
    png_path = out_dir / "results_card.png"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page    = browser.new_page(viewport={"width": 1080, "height": 1920})
            page.goto(f"file://{html_path.resolve()}", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(png_path), full_page=True)
            browser.close()
        print(f"  PNG saved:  {png_path}  ({wins}W-{losses}L)")
        return png_path
    except Exception as e:
        print(f"  Playwright failed ({e}) — open {html_path} in browser manually")
        return html_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=date.today().strftime("%Y%m%d"),
                        help="Date YYYYMMDD (default: today)")
    args = parser.parse_args()
    result = run(args.date)
    if result:
        print(f"\n  Done: {result}")
