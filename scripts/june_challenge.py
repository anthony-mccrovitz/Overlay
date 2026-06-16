#!/usr/bin/env python3
"""June 2026 Bankroll Challenge — personal P/L ledger + daily progress card.

Ledger lives at data/june_challenge.json. Bet results auto-sync from picks.json
when the underlying card pick grades. Each settled bet generates a result card;
the daily card refreshes every morning.

CLI:
  add <pick_id> [--stake-units N]   Log a personal bet (defaults to 1u)
  grade                              Sync pending bets with picks.json results
  card                               Generate daily progress card
  recap                              Final June 30 recap card
  status                             Text-only summary
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
LEDGER     = ROOT / "data" / "june_challenge.json"
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"
OUT_DIR    = ROOT / "output" / "june_challenge"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_ledger() -> dict:
    return json.loads(LEDGER.read_text())


def save_ledger(d: dict) -> None:
    LEDGER.write_text(json.dumps(d, indent=2))


def load_picks() -> list[dict]:
    raw = json.loads(PICKS_FILE.read_text())
    picks = raw if isinstance(raw, list) else raw.get("picks", [])
    return [p for p in picks if isinstance(p, dict)]


def find_pick(pick_id: str) -> dict | None:
    for p in load_picks():
        if p.get("pick_id") == pick_id:
            return p
    return None


def profit_dollars(odds: float, stake_dollars: float, result: str) -> float:
    """Return $ profit (negative for loss, 0 for push)."""
    if result == "push":  return 0.0
    if result == "loss":  return -stake_dollars
    o = float(odds)
    if o > 0:  return stake_dollars * (o / 100.0)
    else:      return stake_dollars * (100.0 / abs(o))


def _fmt_odds(odds) -> str:
    try:
        o = int(float(odds))
        return f"+{o}" if o > 0 else str(o)
    except Exception:
        return "N/A"


def _sport_label(sport: str) -> str:
    s = (sport or "").lower()
    if "mlb" in s or "baseball" in s: return "MLB"
    if "wnba" in s:                    return "WNBA"
    if "nba" in s or "basketball" in s: return "NBA"
    if "nhl" in s or "icehockey" in s:  return "NHL"
    return s.upper() or "?"


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_add(args) -> int:
    pick = find_pick(args.pick_id)
    if not pick:
        print(f"[challenge] pick_id not found: {args.pick_id}")
        return 1

    ledger = load_ledger()
    if any(b["pick_id"] == args.pick_id for b in ledger["bets"]):
        print(f"[challenge] already logged: {args.pick_id}")
        return 0

    stake_dollars = round(args.stake_units * ledger["unit_size"], 2)
    bet = {
        "pick_id":        args.pick_id,
        "date":           pick.get("date"),
        "sport":          pick.get("sport"),
        "market":         pick.get("market"),
        "team":           pick.get("team"),
        "matchup":        pick.get("matchup"),
        "odds":           pick.get("odds"),
        "stake_units":    args.stake_units,
        "stake_dollars":  stake_dollars,
        "result":         pick.get("result"),
        "profit_dollars": None,
        "bankroll_after": None,
        "logged_at":      datetime.now().isoformat(timespec="seconds"),
    }
    if pick.get("result") in ("win", "loss", "push"):
        bet["profit_dollars"] = round(
            profit_dollars(pick["odds"], stake_dollars, pick["result"]), 2)

    ledger["bets"].append(bet)
    _recompute_bankroll(ledger)
    save_ledger(ledger)

    print(f"[challenge] logged {pick['team']} ({_fmt_odds(pick['odds'])}) "
          f"@ ${stake_dollars} — bankroll ${ledger['current_bankroll']:.2f}")
    return 0


def cmd_grade(args) -> int:
    ledger = load_ledger()
    picks_by_id = {p["pick_id"]: p for p in load_picks() if p.get("pick_id")}

    newly_graded = []
    for bet in ledger["bets"]:
        if bet["result"] in ("win", "loss", "push"):
            continue
        live = picks_by_id.get(bet["pick_id"])
        if not live:
            continue
        if live.get("result") not in ("win", "loss", "push"):
            continue
        bet["result"]         = live["result"]
        bet["profit_dollars"] = round(
            profit_dollars(bet["odds"], bet["stake_dollars"], live["result"]), 2)
        newly_graded.append(bet)

    _recompute_bankroll(ledger)
    save_ledger(ledger)

    print(f"[challenge] graded {len(newly_graded)} bet(s). "
          f"bankroll now ${ledger['current_bankroll']:.2f}")
    for b in newly_graded:
        # Render per-bet result card
        out = render_bet_result_card(b, ledger)
        if out:
            print(f"  result card → {out.name}")
    return 0


def cmd_card(args) -> int:
    ledger = load_ledger()
    out = render_daily_card(ledger)
    if out:
        print(f"[challenge] daily card → {out}")
    return 0


def cmd_recap(args) -> int:
    ledger = load_ledger()
    out = render_recap_card(ledger)
    if out:
        print(f"[challenge] recap card → {out}")
    return 0


def cmd_status(args) -> int:
    ledger = load_ledger()
    settled = [b for b in ledger["bets"] if b["result"] in ("win","loss","push")]
    w = sum(1 for b in settled if b["result"] == "win")
    l = sum(1 for b in settled if b["result"] == "loss")
    p = sum(1 for b in settled if b["result"] == "push")
    pnl = ledger["current_bankroll"] - ledger["starting_bankroll"]
    print(f"June Challenge — bankroll ${ledger['current_bankroll']:.2f} "
          f"(start ${ledger['starting_bankroll']:.2f}, P/L {pnl:+.2f})")
    print(f"  Bets: {len(ledger['bets'])} total, {len(settled)} settled, "
          f"{len(ledger['bets']) - len(settled)} pending")
    print(f"  Record: {w}W - {l}L - {p}P "
          f"({w/(w+l)*100:.1f}% WR)" if (w+l) else f"  Record: {w}W - {l}L - {p}P")
    print(f"  Main target $750: "
          f"{'HIT' if ledger['current_bankroll'] >= 750 else 'WORKING'}")
    print(f"  Stretch $1500: "
          f"{'HIT' if ledger['current_bankroll'] >= 1500 else 'WORKING'}")
    return 0


def _recompute_bankroll(ledger: dict) -> None:
    bank = ledger["starting_bankroll"]
    # Sort by logged_at so bankroll-after fields are chronological
    for b in sorted(ledger["bets"], key=lambda x: x.get("logged_at","")):
        if b["result"] in ("win","loss","push") and b["profit_dollars"] is not None:
            bank = round(bank + b["profit_dollars"], 2)
            b["bankroll_after"] = bank
    ledger["current_bankroll"] = bank


# ── Card rendering ───────────────────────────────────────────────────────────

def _render_html(html: str, out_path: Path, width: int = 1080, height: int = 1350) -> Path | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [challenge] playwright not installed; pip install playwright")
        return None
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html, wait_until="networkidle")
            page.screenshot(path=str(out_path),
                            clip={"x": 0, "y": 0, "width": width, "height": height})
            browser.close()
        return out_path
    except Exception as e:
        print(f"  [challenge] render error: {e}")
        return None


def render_daily_card(ledger: dict) -> Path | None:
    bank   = ledger["current_bankroll"]
    start  = ledger["starting_bankroll"]
    main   = ledger["main_target"]
    stretch = ledger["stretch_target"]
    pnl    = bank - start

    settled = [b for b in ledger["bets"] if b["result"] in ("win","loss","push")]
    w = sum(1 for b in settled if b["result"] == "win")
    l = sum(1 for b in settled if b["result"] == "loss")
    wr_str = f"{w/(w+l)*100:.1f}%" if (w+l) else "—"

    # Progress: 0% at $500, 100% at $750 main, 200% at $1500 stretch (visual cap at 100%+)
    pct_to_main    = min(max((bank - start) / (main    - start), 0.0), 2.0)
    pct_to_stretch = min(max((bank - start) / (stretch - start), 0.0), 2.0)
    main_pct_w     = min(pct_to_main * 100, 100)
    stretch_pct_w  = min(pct_to_stretch * 100, 100)

    pnl_col = "#00e87a" if pnl >= 0 else "#ff4444"
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"

    # Days remaining
    today = date.today()
    end   = date.fromisoformat(ledger["end_date"])
    days_left = max(0, (end - today).days)

    main_status    = "HIT" if bank >= main    else "ON TRACK" if pct_to_main    >= ((today - date.fromisoformat(ledger["start_date"])).days / 30) else "BEHIND"
    stretch_status = "HIT" if bank >= stretch else ("PUSHING" if bank > main else "WORKING")

    # Recent bet rows (last 5 settled)
    recent_html = ""
    recent = sorted(
        [b for b in settled if b.get("logged_at")],
        key=lambda x: x["logged_at"],
        reverse=True,
    )[:5]
    for b in recent:
        team   = (b.get("team") or "")[:24]
        sport  = _sport_label(b.get("sport") or "")
        result = b["result"]
        profit = b.get("profit_dollars") or 0
        icon   = "W" if result == "win" else ("L" if result == "loss" else "P")
        icon_color = "#00e87a" if result == "win" else ("#ff4444" if result == "loss" else "#888")
        profit_col = "#00e87a" if profit > 0 else ("#ff4444" if profit < 0 else "#888")
        profit_str = f"+${profit:.2f}" if profit > 0 else (f"-${abs(profit):.2f}" if profit < 0 else "$0.00")
        recent_html += f"""
      <div class="bet-row">
        <div class="bet-icon" style="background:{icon_color}">{icon}</div>
        <div class="bet-detail">
          <div class="bet-meta">{sport} · {_fmt_odds(b.get('odds'))}</div>
          <div class="bet-team">{team}</div>
        </div>
        <div class="bet-profit" style="color:{profit_col}">{profit_str}</div>
      </div>"""

    if not recent_html:
        recent_html = '<div class="bet-empty">No settled bets yet — challenge starts June 1</div>'

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  width:1080px; height:1350px; overflow:hidden;
  background:#080c10;
  font-family:'Inter', sans-serif;
  position:relative;
}}
body::before {{
  content:''; position:absolute; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size:60px 60px;
}}
.accent-bar {{ height:3px; background:#00e87a; }}
.content {{
  position:relative; z-index:10;
  padding:52px 64px 48px;
  display:flex; flex-direction:column;
  height:calc(1350px - 3px);
}}
.brand   {{ font-size:13px; font-weight:700; letter-spacing:0.25em; color:#c0d4e8; text-transform:uppercase; }}
.title   {{ font-family:'Bebas Neue', sans-serif; font-size:78px; color:#fff; letter-spacing:0.04em; line-height:1; margin-top:6px; }}
.subtitle{{ font-size:18px; color:#8aaac0; margin-top:4px; letter-spacing:0.05em; }}

.bankroll-hero {{
  background:#0e1419; border:1px solid #243040;
  border-radius:20px; padding:38px 32px;
  margin-top:34px;
  display:flex; flex-direction:column; align-items:center;
}}
.bankroll-label {{ font-size:13px; font-weight:700; letter-spacing:0.22em; color:#b0c8e0; text-transform:uppercase; }}
.bankroll-val   {{ font-family:'Bebas Neue', sans-serif; font-size:124px; color:#fff; line-height:0.95; margin-top:6px; }}
.bankroll-pnl   {{ font-size:24px; font-weight:900; margin-top:10px; color:{pnl_col}; }}

.targets {{
  display:flex; flex-direction:column; gap:14px;
  margin-top:32px;
}}
.target-row {{
  background:#0e1419; border:1px solid #243040;
  border-radius:14px; padding:18px 22px;
}}
.target-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }}
.target-name {{ font-size:14px; font-weight:800; color:#fff; letter-spacing:0.08em; text-transform:uppercase; }}
.target-amount {{ font-size:18px; font-weight:900; color:#fff; }}
.target-status {{ font-size:11px; font-weight:800; letter-spacing:0.15em; padding:4px 10px; border-radius:6px; text-transform:uppercase; }}
.s-hit       {{ background:#00e87a; color:#000; }}
.s-on-track  {{ background:#3a86ff; color:#fff; }}
.s-behind    {{ background:#ff8c00; color:#000; }}
.s-working   {{ background:#243040; color:#c8ddf0; }}
.s-pushing   {{ background:#a855f7; color:#fff; }}

.progress-bar {{
  height:10px; background:#1a2230; border-radius:5px; overflow:hidden;
}}
.progress-fill {{ height:100%; border-radius:5px; }}
.fill-main    {{ background:linear-gradient(90deg, #00e87a, #00b35a); }}
.fill-stretch {{ background:linear-gradient(90deg, #a855f7, #6b21a8); }}

.section-label {{ font-size:12px; font-weight:700; letter-spacing:0.2em; color:#b0c8e0; text-transform:uppercase; margin-top:30px; margin-bottom:14px; }}

.bet-row {{
  background:#0e1419; border:1px solid #243040; border-radius:12px;
  padding:14px 18px; margin-bottom:8px;
  display:flex; align-items:center; gap:16px;
}}
.bet-icon  {{ width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:900; color:#000; font-size:16px; flex-shrink:0; }}
.bet-detail {{ flex:1; }}
.bet-meta  {{ font-size:11px; font-weight:700; color:#8aaac0; letter-spacing:0.1em; text-transform:uppercase; }}
.bet-team  {{ font-size:18px; font-weight:800; color:#fff; margin-top:2px; }}
.bet-profit{{ font-size:18px; font-weight:900; }}
.bet-empty {{ font-size:15px; color:#8aaac0; text-align:center; padding:24px; font-style:italic; }}

.footer {{
  margin-top:auto; padding-top:20px; border-top:1px solid #1a2230;
  display:flex; justify-content:space-between; align-items:flex-end;
}}
.f-stat  {{ display:flex; flex-direction:column; }}
.f-label {{ font-size:11px; font-weight:700; letter-spacing:0.18em; color:#b0c8e0; text-transform:uppercase; }}
.f-val   {{ font-size:22px; font-weight:900; color:#fff; margin-top:3px; }}
.f-brand {{ font-size:11px; font-weight:800; color:#a0bcd4; letter-spacing:0.15em; }}
</style>
</head><body>
<div class="accent-bar"></div>
<div class="content">
  <div class="brand">Overlay &nbsp;·&nbsp; June Challenge</div>
  <div class="title">Bankroll Challenge</div>
  <div class="subtitle">{ledger['start_date']} – {ledger['end_date']} &nbsp;·&nbsp; {days_left} days remaining</div>

  <div class="bankroll-hero">
    <div class="bankroll-label">Current Bankroll</div>
    <div class="bankroll-val">${bank:.2f}</div>
    <div class="bankroll-pnl">{pnl_str}</div>
  </div>

  <div class="targets">
    <div class="target-row">
      <div class="target-header">
        <div class="target-name">Main Target</div>
        <div style="display:flex; align-items:center; gap:14px;">
          <div class="target-amount">${main:.0f}</div>
          <div class="target-status s-{main_status.lower().replace(' ','-')}">{main_status}</div>
        </div>
      </div>
      <div class="progress-bar"><div class="progress-fill fill-main" style="width:{main_pct_w:.1f}%"></div></div>
    </div>
    <div class="target-row">
      <div class="target-header">
        <div class="target-name">Stretch Target</div>
        <div style="display:flex; align-items:center; gap:14px;">
          <div class="target-amount">${stretch:.0f}</div>
          <div class="target-status s-{stretch_status.lower().replace(' ','-')}">{stretch_status}</div>
        </div>
      </div>
      <div class="progress-bar"><div class="progress-fill fill-stretch" style="width:{stretch_pct_w:.1f}%"></div></div>
    </div>
  </div>

  <div class="section-label">Recent Bets</div>
  <div>{recent_html}</div>

  <div class="footer">
    <div class="f-stat">
      <div class="f-label">Record</div>
      <div class="f-val">{w}W – {l}L</div>
    </div>
    <div class="f-stat">
      <div class="f-label">Win Rate</div>
      <div class="f-val">{wr_str}</div>
    </div>
    <div class="f-stat">
      <div class="f-label">Unit Size</div>
      <div class="f-val">${ledger['unit_size']:.0f}</div>
    </div>
    <div class="f-brand">OVERLAY-GRAY.VERCEL.APP</div>
  </div>
</div></body></html>"""

    today_str = date.today().strftime("%Y%m%d")
    out = OUT_DIR / today_str / "challenge_daily.png"
    return _render_html(html, out)


def render_bet_result_card(bet: dict, ledger: dict) -> Path | None:
    result    = bet["result"]
    profit    = bet.get("profit_dollars") or 0
    team      = (bet.get("team") or "")[:30]
    sport     = _sport_label(bet.get("sport") or "")
    odds      = _fmt_odds(bet.get("odds"))
    bank      = bet.get("bankroll_after") or ledger["current_bankroll"]
    matchup   = bet.get("matchup") or ""

    result_label = result.upper()
    result_color = "#00e87a" if result == "win" else ("#ff4444" if result == "loss" else "#8aaac0")
    profit_str   = (f"+${profit:.2f}" if profit > 0
                    else (f"-${abs(profit):.2f}" if profit < 0 else "$0.00"))

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:1080px; height:1080px; overflow:hidden; background:#080c10; font-family:'Inter', sans-serif; position:relative; }}
body::before {{
  content:''; position:absolute; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size:60px 60px;
}}
.accent-bar {{ height:3px; background:{result_color}; }}
.content {{ position:relative; z-index:10; padding:60px 70px; display:flex; flex-direction:column; height:calc(1080px - 3px); }}
.brand {{ font-size:14px; font-weight:700; letter-spacing:0.25em; color:#c0d4e8; text-transform:uppercase; }}
.title {{ font-family:'Bebas Neue', sans-serif; font-size:90px; color:{result_color}; letter-spacing:0.04em; line-height:1; margin-top:12px; }}
.subtitle {{ font-size:18px; color:#8aaac0; margin-top:6px; letter-spacing:0.05em; }}

.bet-card {{
  background:#0e1419; border:1px solid #243040;
  border-radius:24px; padding:48px 40px;
  margin-top:60px;
  display:flex; flex-direction:column; align-items:center;
}}
.bet-meta {{ font-size:14px; font-weight:700; letter-spacing:0.18em; color:{result_color}; text-transform:uppercase; }}
.bet-team {{ font-family:'Bebas Neue', sans-serif; font-size:72px; color:#fff; line-height:1; margin-top:10px; text-align:center; }}
.bet-matchup {{ font-size:18px; color:#8aaac0; margin-top:8px; }}
.bet-odds  {{ font-size:24px; font-weight:900; color:#fff; margin-top:18px; }}

.profit-row {{
  margin-top:80px;
  display:flex; flex-direction:column; align-items:center;
}}
.profit-label {{ font-size:14px; font-weight:700; letter-spacing:0.2em; color:#b0c8e0; text-transform:uppercase; }}
.profit-val   {{ font-family:'Bebas Neue', sans-serif; font-size:140px; color:{result_color}; line-height:0.95; margin-top:8px; }}

.bankroll-bar {{
  margin-top:auto; padding:24px 30px;
  background:#0e1419; border:1px solid #243040; border-radius:16px;
  display:flex; justify-content:space-between; align-items:center;
}}
.b-label {{ font-size:12px; font-weight:700; letter-spacing:0.2em; color:#b0c8e0; text-transform:uppercase; }}
.b-val   {{ font-family:'Bebas Neue', sans-serif; font-size:48px; color:#fff; line-height:1; margin-top:4px; }}
</style>
</head><body>
<div class="accent-bar"></div>
<div class="content">
  <div class="brand">Overlay &nbsp;·&nbsp; June Challenge</div>
  <div class="title">{result_label}</div>
  <div class="subtitle">Bet settled · {bet.get('date','')}</div>

  <div class="bet-card">
    <div class="bet-meta">{sport} · {bet.get('market','').upper()}</div>
    <div class="bet-team">{team}</div>
    <div class="bet-matchup">{matchup}</div>
    <div class="bet-odds">{odds} &nbsp;·&nbsp; ${bet.get('stake_dollars',0):.2f} risked</div>
  </div>

  <div class="profit-row">
    <div class="profit-label">Profit / Loss</div>
    <div class="profit-val">{profit_str}</div>
  </div>

  <div class="bankroll-bar">
    <div>
      <div class="b-label">Bankroll Now</div>
      <div class="b-val">${bank:.2f}</div>
    </div>
    <div>
      <div class="b-label">Main Target</div>
      <div class="b-val">${ledger['main_target']:.0f}</div>
    </div>
    <div>
      <div class="b-label">Stretch</div>
      <div class="b-val">${ledger['stretch_target']:.0f}</div>
    </div>
  </div>
</div></body></html>"""

    today_str = date.today().strftime("%Y%m%d")
    safe_pid = bet["pick_id"].replace("/","_")[:60]
    out = OUT_DIR / today_str / "result_cards" / f"{safe_pid}.png"
    return _render_html(html, out, width=1080, height=1080)


def render_recap_card(ledger: dict) -> Path | None:
    bank   = ledger["current_bankroll"]
    start  = ledger["starting_bankroll"]
    main   = ledger["main_target"]
    stretch = ledger["stretch_target"]
    pnl    = bank - start
    pct    = (bank / start - 1) * 100

    settled = [b for b in ledger["bets"] if b["result"] in ("win","loss","push")]
    w = sum(1 for b in settled if b["result"] == "win")
    l = sum(1 for b in settled if b["result"] == "loss")
    wr = w/(w+l)*100 if (w+l) else 0
    avg_stake = sum(b["stake_dollars"] for b in settled)/len(settled) if settled else 0
    roi = pnl / sum(b["stake_dollars"] for b in settled) * 100 if settled else 0

    if bank >= stretch: headline = "STRETCH HIT"; hcol = "#a855f7"
    elif bank >= main:  headline = "TARGET HIT";  hcol = "#00e87a"
    elif bank > start:  headline = "PROFITABLE";  hcol = "#00e87a"
    else:                headline = "TOUGH MONTH"; hcol = "#ff8c00"

    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    pct_str = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"

    best = max(settled, key=lambda b: b.get("profit_dollars") or 0, default=None)
    best_html = ""
    if best and (best.get("profit_dollars") or 0) > 0:
        bt = (best.get("team") or "")[:28]
        bp = best["profit_dollars"]
        best_html = f"""
    <div class="section-label">Best Bet of June</div>
    <div class="best-pick">
      <div>
        <div class="best-meta">{_sport_label(best.get('sport',''))} · {_fmt_odds(best.get('odds'))}</div>
        <div class="best-team">{bt}</div>
      </div>
      <div class="best-profit">+${bp:.2f}</div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:1080px; height:1350px; overflow:hidden; background:#080c10; font-family:'Inter', sans-serif; position:relative; }}
body::before {{
  content:''; position:absolute; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size:60px 60px;
}}
.accent-bar {{ height:3px; background:{hcol}; }}
.content {{ position:relative; z-index:10; padding:52px 64px 48px; display:flex; flex-direction:column; height:calc(1350px - 3px); }}
.brand {{ font-size:13px; font-weight:700; letter-spacing:0.25em; color:#c0d4e8; text-transform:uppercase; }}
.title {{ font-family:'Bebas Neue', sans-serif; font-size:84px; color:{hcol}; letter-spacing:0.04em; line-height:1; margin-top:6px; }}
.subtitle {{ font-size:18px; color:#8aaac0; margin-top:4px; letter-spacing:0.05em; }}

.hero {{
  background:#0e1419; border:1px solid #243040;
  border-radius:24px; padding:38px;
  margin-top:30px;
  display:flex; flex-direction:column; align-items:center;
}}
.hero-label {{ font-size:14px; font-weight:700; letter-spacing:0.22em; color:#b0c8e0; text-transform:uppercase; }}
.hero-val   {{ font-family:'Bebas Neue', sans-serif; font-size:140px; color:#fff; line-height:0.95; margin-top:6px; }}
.hero-delta {{ font-size:28px; font-weight:900; margin-top:8px; color:{hcol}; }}

.big-stats {{ display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:14px; margin-top:30px; }}
.big-stat  {{ background:#0e1419; border:1px solid #243040; border-radius:16px; padding:20px 16px; display:flex; flex-direction:column; align-items:center; }}
.big-stat-label {{ font-size:11px; font-weight:700; letter-spacing:0.18em; color:#b0c8e0; text-transform:uppercase; margin-bottom:8px; }}
.big-stat-val   {{ font-family:'Bebas Neue', sans-serif; font-size:48px; color:#fff; line-height:1; }}

.section-label {{ font-size:12px; font-weight:700; letter-spacing:0.2em; color:#b0c8e0; text-transform:uppercase; margin-top:28px; margin-bottom:14px; }}

.best-pick {{
  background:#0e1419; border:1px solid #1e3a2a; border-radius:18px;
  padding:24px 28px; display:flex; justify-content:space-between; align-items:center;
}}
.best-meta {{ font-size:13px; font-weight:700; letter-spacing:0.12em; color:#00e87a; text-transform:uppercase; }}
.best-team {{ font-family:'Bebas Neue', sans-serif; font-size:42px; color:#fff; line-height:1; margin-top:4px; }}
.best-profit {{ font-size:30px; font-weight:900; color:#00e87a; }}

.targets-row {{ display:flex; gap:14px; margin-top:24px; }}
.target-card {{ flex:1; background:#0e1419; border:1px solid #243040; border-radius:16px; padding:18px 22px; display:flex; justify-content:space-between; align-items:center; }}
.t-label {{ font-size:11px; font-weight:800; letter-spacing:0.18em; color:#b0c8e0; text-transform:uppercase; }}
.t-amount {{ font-size:20px; font-weight:900; color:#fff; margin-top:3px; }}
.t-pill {{ font-size:11px; font-weight:800; letter-spacing:0.15em; padding:4px 10px; border-radius:6px; text-transform:uppercase; }}
.t-hit {{ background:#00e87a; color:#000; }}
.t-miss{{ background:#243040; color:#c8ddf0; }}

.footer {{ margin-top:auto; padding-top:20px; border-top:1px solid #1a2230; display:flex; justify-content:space-between; align-items:flex-end; }}
.f-stat  {{ display:flex; flex-direction:column; }}
.f-label {{ font-size:11px; font-weight:700; letter-spacing:0.18em; color:#b0c8e0; text-transform:uppercase; }}
.f-val   {{ font-size:22px; font-weight:900; color:#fff; margin-top:3px; }}
.f-brand {{ font-size:11px; font-weight:800; color:#a0bcd4; letter-spacing:0.15em; }}
</style>
</head><body>
<div class="accent-bar"></div>
<div class="content">
  <div class="brand">Overlay &nbsp;·&nbsp; June Challenge</div>
  <div class="title">{headline}</div>
  <div class="subtitle">June 1 – June 30, 2026 · Final Recap</div>

  <div class="hero">
    <div class="hero-label">Final Bankroll</div>
    <div class="hero-val">${bank:.2f}</div>
    <div class="hero-delta">{pnl_str} &nbsp;({pct_str})</div>
  </div>

  <div class="big-stats">
    <div class="big-stat"><div class="big-stat-label">Record</div><div class="big-stat-val">{w}–{l}</div></div>
    <div class="big-stat"><div class="big-stat-label">Win Rate</div><div class="big-stat-val">{wr:.1f}%</div></div>
    <div class="big-stat"><div class="big-stat-label">ROI</div><div class="big-stat-val">{roi:+.1f}%</div></div>
    <div class="big-stat"><div class="big-stat-label">Bets</div><div class="big-stat-val">{len(settled)}</div></div>
  </div>

  <div class="section-label">Targets</div>
  <div class="targets-row">
    <div class="target-card">
      <div><div class="t-label">Main</div><div class="t-amount">${main:.0f}</div></div>
      <div class="t-pill {'t-hit' if bank >= main else 't-miss'}">{'HIT' if bank >= main else 'MISSED'}</div>
    </div>
    <div class="target-card">
      <div><div class="t-label">Stretch</div><div class="t-amount">${stretch:.0f}</div></div>
      <div class="t-pill {'t-hit' if bank >= stretch else 't-miss'}">{'HIT' if bank >= stretch else 'MISSED'}</div>
    </div>
  </div>

  {best_html}

  <div class="footer">
    <div class="f-stat"><div class="f-label">Start</div><div class="f-val">${start:.0f}</div></div>
    <div class="f-stat"><div class="f-label">Unit</div><div class="f-val">${ledger['unit_size']:.0f}</div></div>
    <div class="f-stat"><div class="f-label">Avg Stake</div><div class="f-val">${avg_stake:.2f}</div></div>
    <div class="f-brand">OVERLAY-GRAY.VERCEL.APP</div>
  </div>
</div></body></html>"""

    out = OUT_DIR / "20260630" / "june_challenge_recap.png"
    return _render_html(html, out)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="June 2026 Bankroll Challenge")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Log a personal bet from a card pick")
    p_add.add_argument("pick_id")
    p_add.add_argument("--stake-units", type=float, default=1.0,
                        help="Stake in units (default 1.0)")
    p_add.set_defaults(fn=cmd_add)

    sub.add_parser("grade", help="Sync pending bets with picks.json").set_defaults(fn=cmd_grade)
    sub.add_parser("card",  help="Generate daily progress card").set_defaults(fn=cmd_card)
    sub.add_parser("recap", help="Generate final June 30 recap card").set_defaults(fn=cmd_recap)
    sub.add_parser("status",help="Text-only status").set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
