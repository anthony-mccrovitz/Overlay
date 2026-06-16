"""
June Challenge card generator.

Two cards per day:
  1. Bet-of-Day card  (morning)  — shows the pick before game time
  2. Result card      (evening)  — WIN / LOSS after grading

State is persisted in data/june_challenge/state.json so bankroll
and record carry forward across days automatically.

Public entry points
-------------------
  generate_morning_card(bet: dict) -> Path | None
  generate_result_card(bet: dict)  -> Path | None
  load_state()                     -> dict
  save_state(state: dict)
  get_todays_bet(state: dict, today: str) -> dict | None
  register_bet(state, bet_dict)    -> dict   (adds to state, returns updated state)
  mark_result(state, date, result, profit, bankroll_after) -> dict
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

STATE_PATH = Path("data/june_challenge/state.json")
OUTPUT_DIR = Path("output/picks")


# ── State helpers ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"bankroll": 200.0, "unit": 20.0, "record": {"w": 0, "l": 0}, "bets": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


def get_todays_bet(state: dict, today: str | None = None) -> dict | None:
    today = today or date.today().strftime("%Y-%m-%d")
    for b in state.get("bets", []):
        if b.get("date") == today:
            return b
    return None


def register_bet(state: dict, bet: dict) -> dict:
    """Add a new bet to state (morning). Does not overwrite if date already exists."""
    today = bet.get("date") or date.today().strftime("%Y-%m-%d")
    if not get_todays_bet(state, today):
        state["bets"].append(bet)
    return state


def mark_result(state: dict, bet_date: str, result: str,
                profit: float, bankroll_after: float) -> dict:
    """Update an existing bet with its result and new bankroll."""
    for b in state["bets"]:
        if b.get("date") == bet_date:
            b["result"]         = result
            b["profit"]         = profit
            b["bankroll_after"] = bankroll_after
            break
    state["bankroll"] = bankroll_after
    if result == "WIN":
        state["record"]["w"] = state["record"].get("w", 0) + 1
    else:
        state["record"]["l"] = state["record"].get("l", 0) + 1
    return state


# ── Shared visual constants ───────────────────────────────────────────────────

_GOOGLE_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:'
    'wght@400;500;600;700;800;900&display=swap" rel="stylesheet">'
)

_BASE_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body {
  width:1080px; background:#06080F;
  font-family:'Inter',-apple-system,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased; color:#F1F5F9;
}
.wrap {
  width:1080px;
  background:
    radial-gradient(ellipse 80% 50% at 50% -5%, rgba(99,102,241,0.10) 0%, transparent 55%),
    #06080F;
  padding:36px 44px 32px;
}
.header {
  display:flex; align-items:center; justify-content:space-between;
  padding-bottom:22px; border-bottom:1px solid rgba(255,255,255,0.07); margin-bottom:22px;
}
.brand { display:flex; align-items:center; gap:14px; }
.brand-mark {
  width:50px; height:50px; border-radius:12px;
  background:linear-gradient(135deg,#6366f1,#8b5cf6);
  display:flex; align-items:center; justify-content:center;
  font-size:22px; color:#fff; font-weight:900; box-shadow:0 4px 20px rgba(99,102,241,0.30);
}
.brand-name { font-size:30px; font-weight:900; color:#F1F5F9; letter-spacing:-0.5px; }
.brand-sub  { font-size:12px; color:rgba(255,255,255,0.45); letter-spacing:0.06em; font-weight:600; margin-top:3px; }
.header-right { text-align:right; }
.header-date  { font-size:15px; font-weight:800; color:#F1F5F9; letter-spacing:0.08em; }
.header-pill  {
  display:inline-block; margin-top:7px;
  font-size:11px; font-weight:800; color:#A5B4FC; letter-spacing:0.18em;
  background:rgba(99,102,241,0.14); border:1px solid rgba(99,102,241,0.32);
  padding:3px 14px; border-radius:20px;
}
.strip {
  display:flex; background:rgba(255,255,255,0.025);
  border:1px solid rgba(255,255,255,0.07); border-radius:13px;
  padding:16px 0; margin-bottom:20px;
}
.strip-cell { flex:1; text-align:center; border-right:1px solid rgba(255,255,255,0.07); }
.strip-cell:last-child { border-right:none; }
.sc-label { font-size:11px; font-weight:800; letter-spacing:0.16em; color:rgba(255,255,255,0.45); text-transform:uppercase; margin-bottom:7px; }
.sc-val   { font-size:25px; font-weight:900; color:#F1F5F9; letter-spacing:-0.3px; line-height:1; font-variant-numeric:tabular-nums; }
.sc-val.grn { color:#4ADE80; }
.sc-val.red { color:#F87171; }
.sc-val.ind { color:#A5B4FC; }
.t-row {
  display:flex; align-items:center; gap:16px;
  background:rgba(26,58,110,0.25); border:1px solid rgba(200,75,0,0.22);
  border-radius:12px; padding:14px 20px; margin-bottom:20px;
}
.t-name { font-size:18px; font-weight:900; color:#F1F5F9; letter-spacing:-0.2px; }
.t-sub  { font-size:12px; font-weight:700; color:rgba(255,255,255,0.50); margin-top:3px; }
.clay-pill { background:#C84B00; color:#fff; font-size:11px; font-weight:800; letter-spacing:0.14em; padding:5px 14px; border-radius:20px; }
.tag { font-size:10px; font-weight:800; letter-spacing:0.14em; text-transform:uppercase; padding:3px 10px; border-radius:5px; }
.tag-mkt  { background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.11); color:rgba(255,255,255,0.55); }
.tag-potd { background:rgba(99,102,241,0.17); border:1px solid rgba(99,102,241,0.42); color:#A5B4FC; }
.book-tag { background:#E4002B; color:#fff; font-size:11px; font-weight:800; letter-spacing:0.10em; padding:4px 12px; border-radius:5px; }
.footer {
  padding-top:18px; border-top:1px solid rgba(255,255,255,0.07);
  display:flex; align-items:center; justify-content:space-between; margin-top:22px;
}
.footer-disc   { font-size:12px; color:rgba(255,255,255,0.38); font-weight:600; }
.footer-right  { font-size:13px; font-weight:700; }
.footer-handle { color:#818CF8; }
.footer-sep    { color:rgba(255,255,255,0.20); margin:0 8px; }
.footer-url    { color:rgba(255,255,255,0.70); }
"""


def _rg_badge_svg(size: int = 56) -> str:
    return f"""<svg width="{size}" height="{size}" viewBox="0 0 56 56" xmlns="http://www.w3.org/2000/svg">
  <rect width="56" height="56" rx="11" fill="#1A3A6E"/>
  <text x="28" y="24" text-anchor="middle" font-family="Arial Black,Arial,sans-serif"
        font-weight="900" font-size="16" fill="#C84B00">RG</text>
  <text x="28" y="36" text-anchor="middle" font-family="Arial,sans-serif"
        font-weight="700" font-size="6.5" fill="rgba(255,255,255,0.85)" letter-spacing="0.8">ROLAND</text>
  <text x="28" y="46" text-anchor="middle" font-family="Arial,sans-serif"
        font-weight="700" font-size="6.5" fill="rgba(255,255,255,0.85)" letter-spacing="0.8">GARROS</text>
</svg>"""


def _sport_badge(sport: str, tournament: str) -> str:
    """Return the right event badge SVG for the given sport."""
    s = sport.lower()
    if "french_open" in s or "roland" in tournament.lower():
        return _rg_badge_svg()
    # Generic fallback: sport initial in indigo
    initial = tournament[0].upper() if tournament else "?"
    return (
        f'<div style="width:56px;height:56px;border-radius:11px;'
        f'background:linear-gradient(135deg,#6366f1,#8b5cf6);'
        f'display:flex;align-items:center;justify-content:center;'
        f'font-size:26px;font-weight:900;color:#fff">{initial}</div>'
    )


def _fmt_odds(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)


def _unit_profit(odds: int, unit: float) -> float:
    if odds < 0:
        return round(unit * (100 / abs(odds)), 2)
    return round(unit * (odds / 100), 2)


def _render(html: str, html_path: Path, png_path: Path, height: int = 940) -> Path | None:
    try:
        from src.output.card_html import _playwright_render
        return _playwright_render(html, html_path, png_path, target_height=height)
    except Exception as e:
        print(f"  [june_challenge] render error: {e}")
        return None


# ── Morning card — "Bet of the Day" ──────────────────────────────────────────

def generate_morning_card(bet: dict, card_date: date | None = None) -> Path | None:
    """
    Render the pre-game June Challenge pick card.

    bet keys: player, opponent, tournament, surface, sport, odds, edge,
              model_prob, market_prob, book, unit, day (int)
    """
    d       = card_date or date.today()
    day     = bet.get("day", 1)
    odds    = int(bet.get("odds", -110))
    edge    = float(bet.get("edge", 0))
    unit    = float(bet.get("unit", 20))
    profit  = _unit_profit(odds, unit)   # potential payout on this single bet

    # Normalize probabilities: stored as decimal (0.62) or percentage (62.0) — handle both
    def _pct(v: float) -> float:
        return v * 100 if v <= 1.5 else v
    _mprob = _pct(float(bet.get("model_prob", 0)))
    _iprob = _pct(float(bet.get("market_prob", 0)))
    gap    = round(_mprob - _iprob, 1)

    # Load challenge record + P&L from state (exclude today's pending bet)
    try:
        _st = load_state()
        _settled = [b for b in _st.get("bets", []) if b.get("result") in ("WIN", "LOSS")]
        _rec_w = sum(1 for b in _settled if b["result"] == "WIN")
        _rec_l = sum(1 for b in _settled if b["result"] == "LOSS")
        _pnl   = sum(float(b.get("profit", 0)) for b in _settled)
    except Exception:
        _rec_w, _rec_l, _pnl = 0, 0, 0.0
    _rec_str  = f"{_rec_w}-{_rec_l}"
    _pnl_str  = f"+${_pnl:.2f}" if _pnl >= 0 else f"-${abs(_pnl):.2f}"
    sport   = bet.get("sport", "")
    tour    = bet.get("tournament", "")
    surface = bet.get("surface", "")
    player  = bet.get("player", "")
    opp     = bet.get("opponent", "")
    book    = bet.get("book", "")

    badge   = _sport_badge(sport, tour)
    date_s  = d.strftime("%b %d, %Y").upper()

    # Surface pill color
    surf_color = "#C84B00" if "clay" in surface.lower() else \
                 "#4ADE80" if "hard" in surface.lower() else \
                 "#818CF8" if "nhl" in sport.lower() else "#94a3b8"

    # Sport-aware labels
    market_type = bet.get("market", "moneyline").replace("_", " ").title()
    if "total" in market_type.lower():
        market_label = "Game Total"
    elif "spread" in market_type.lower() or "puck" in market_type.lower():
        market_label = "Puck Line"
    else:
        market_label = "Moneyline"

    if "nhl" in sport.lower():
        sport_sub = "Stanley Cup Playoffs &nbsp;&middot;&nbsp; NHL"
        model_label = "NHL totals model"
        court_label = "NHL TOTAL"
    elif "nba" in sport.lower():
        sport_sub = "NBA"
        model_label = "NBA model"
        court_label = surface.upper() or "NBA"
    elif "mlb" in sport.lower():
        sport_sub = "MLB"
        model_label = "MLB model"
        court_label = surface.upper() or "MLB"
    elif "tennis" in sport.lower():
        sport_sub = "French Open &nbsp;&middot;&nbsp; ATP Tour"
        model_label = "Clay Elo model"
        court_label = surface.upper() + " COURT"
    else:
        sport_sub = tour
        model_label = "ML model"
        court_label = surface.upper() or "PICK"

    CARD_CSS = _BASE_CSS + """
.pick {
  display:flex; align-items:stretch;
  background:linear-gradient(135deg,rgba(99,102,241,0.09) 0%,rgba(255,255,255,0.018) 60%);
  border:1px solid rgba(99,102,241,0.38); border-radius:16px; overflow:hidden; margin-bottom:18px;
}
.pick-bar   { width:5px; background:#4ADE80; flex-shrink:0; }
.pick-body  { flex:1; display:flex; align-items:center; gap:24px; padding:26px 26px 26px 22px; }
.pick-info  { flex:1; min-width:0; }
.tag-row    { display:flex; align-items:center; gap:9px; margin-bottom:11px; }
.player-name { font-size:42px; font-weight:900; color:#F1F5F9; letter-spacing:-0.8px; line-height:1.05; margin-bottom:10px; }
.vs-row     { font-size:15px; font-weight:600; color:rgba(255,255,255,0.55); display:flex; align-items:center; gap:10px; }
.pick-nums  { text-align:right; flex-shrink:0; }
.p-odds     { font-size:68px; font-weight:900; color:#F1F5F9; letter-spacing:-2px; line-height:1; font-variant-numeric:tabular-nums; }
.p-edge     { font-size:19px; font-weight:900; color:#4ADE80; margin-top:8px; }
.p-win      { font-size:13px; font-weight:700; color:rgba(255,255,255,0.45); margin-top:5px; }
.mvs        { background:rgba(255,255,255,0.022); border:1px solid rgba(255,255,255,0.07); border-radius:13px; padding:22px 28px; margin-bottom:22px; }
.mvs-title  { font-size:11px; font-weight:800; letter-spacing:0.18em; color:rgba(255,255,255,0.40); text-transform:uppercase; text-align:center; margin-bottom:18px; }
.mvs-row    { display:flex; align-items:center; justify-content:center; }
.mvs-col    { flex:1; text-align:center; }
.mvs-label  { font-size:12px; font-weight:800; letter-spacing:0.14em; text-transform:uppercase; margin-bottom:8px; }
.mvs-val    { font-size:54px; font-weight:900; line-height:1; letter-spacing:-1px; font-variant-numeric:tabular-nums; }
.mvs-sub    { font-size:11px; font-weight:700; margin-top:5px; color:rgba(255,255,255,0.38); letter-spacing:0.06em; }
.mvs-div    { font-size:22px; font-weight:300; color:rgba(255,255,255,0.18); padding:0 20px; flex-shrink:0; }
.edge-box   { background:rgba(74,222,128,0.10); border:1px solid rgba(74,222,128,0.28); border-radius:10px; padding:14px 22px; text-align:center; flex-shrink:0; min-width:138px; }
.eb-label   { font-size:10px; font-weight:800; letter-spacing:0.16em; color:rgba(74,222,128,0.60); text-transform:uppercase; margin-bottom:6px; }
.eb-val     { font-size:30px; font-weight:900; color:#4ADE80; letter-spacing:-0.5px; line-height:1; }
.eb-sub     { font-size:11px; font-weight:700; color:rgba(74,222,128,0.50); margin-top:5px; }
"""

    html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=1080">
{_GOOGLE_FONTS}<style>{CARD_CSS}</style></head>
<body><div class="wrap">
  <div class="header">
    <div class="brand">
      <div class="brand-mark">&#9672;</div>
      <div><div class="brand-name">Overlay</div><div class="brand-sub">ML PICKS MODEL</div></div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_s}</div>
      <div class="header-pill">JUNE CHALLENGE &nbsp;&middot;&nbsp; DAY {day}</div>
    </div>
  </div>

  <div class="strip">
    <div class="strip-cell"><div class="sc-label">Bankroll</div><div class="sc-val">${bet.get("bankroll_before", 200):.2f}</div></div>
    <div class="strip-cell"><div class="sc-label">Unit Size</div><div class="sc-val">${unit:.0f}</div></div>
    <div class="strip-cell"><div class="sc-label">Record</div><div class="sc-val">{_rec_str}</div></div>
    <div class="strip-cell"><div class="sc-label">P&amp;L</div><div class="sc-val {'grn' if _pnl >= 0 else 'red'}">{_pnl_str}</div></div>
  </div>

  <div class="t-row">
    {badge}
    <div style="flex:1">
      <div class="t-name">{tour}</div>
      <div class="t-sub">{sport_sub}</div>
    </div>
    <div class="clay-pill" style="background:{surf_color}">{court_label}</div>
  </div>

  <div class="pick">
    <div class="pick-bar"></div>
    <div class="pick-body">
      <div class="pick-info">
        <div class="tag-row">
          <span class="tag tag-mkt">{market_label}</span>
          <span class="tag tag-potd">Bet of the Day</span>
        </div>
        <div class="player-name">{player}</div>
        <div class="vs-row">
          <span>vs {opp}</span>
          <span style="color:rgba(255,255,255,0.20)">&middot;</span>
          <span class="book-tag">{book}</span>
        </div>
      </div>
      <div class="pick-nums">
        <div class="p-odds">{_fmt_odds(odds)}</div>
        <div class="p-edge">+{edge:.1f}% EDGE</div>
        <div class="p-win">${unit:.0f} unit &rarr; wins +${profit:.2f}</div>
      </div>
    </div>
  </div>

  <div class="mvs">
    <div class="mvs-title">Model Probability vs Market Implied</div>
    <div class="mvs-row">
      <div class="mvs-col">
        <div class="mvs-label" style="color:#4ADE80">Model</div>
        <div class="mvs-val" style="color:#4ADE80">{_mprob:.1f}%</div>
        <div class="mvs-sub">{model_label}</div>
      </div>
      <div class="mvs-div">vs</div>
      <div class="mvs-col">
        <div class="mvs-label" style="color:#818CF8">Market</div>
        <div class="mvs-val" style="color:#818CF8">{_iprob:.1f}%</div>
        <div class="mvs-sub">No-vig implied</div>
      </div>
      <div class="mvs-div" style="color:rgba(255,255,255,0.08)">|</div>
      <div class="edge-box">
        <div class="eb-label">Edge</div>
        <div class="eb-val">+{gap:.1f}pp</div>
        <div class="eb-sub">prob gap</div>
      </div>
    </div>
  </div>

  <div class="footer">
    <div class="footer-disc">Not financial advice &nbsp;&middot;&nbsp; Bet responsibly &nbsp;&middot;&nbsp; 21+</div>
    <div class="footer-right">
      <span class="footer-handle">@getoverlay</span>
      <span class="footer-sep">&middot;</span>
      <span class="footer-url">overlay-gray.vercel.app</span>
    </div>
  </div>
</div></body></html>"""

    ts      = d.strftime("%Y%m%d")
    sport_slug = sport.replace("tennis_atp_", "tennis_atp_").replace(" ", "_").lower()
    out_dir = OUTPUT_DIR / sport_slug / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    fn      = f"june_challenge_day{day}_card"
    return _render(html, out_dir / f"{fn}.html", out_dir / f"{fn}.png", height=940)


# ── Result card — WIN / LOSS ──────────────────────────────────────────────────

def generate_result_card(bet: dict, card_date: date | None = None,
                         record_w: int = 0, record_l: int = 0) -> Path | None:
    """
    Render the post-game result card (WIN or LOSS).

    bet keys: player, opponent, tournament, surface, sport, odds, edge,
              unit, day, result, profit, bankroll_before, bankroll_after, book
    """
    d       = card_date or date.today()
    day     = bet.get("day", 1)
    odds    = int(bet.get("odds", -110))
    edge    = float(bet.get("edge", 0))
    unit    = float(bet.get("unit", 20))
    result  = (bet.get("result") or "LOSS").upper()
    profit  = float(bet.get("profit", 0))
    br_bef  = float(bet.get("bankroll_before", 200))
    br_aft  = float(bet.get("bankroll_after", br_bef))
    sport   = bet.get("sport", "")
    tour    = bet.get("tournament", "")
    surface = bet.get("surface", "")
    player  = bet.get("player", "")
    opp     = bet.get("opponent", "")

    is_win     = result == "WIN"
    res_color  = "#4ADE80" if is_win else "#F87171"
    res_bg     = "rgba(74,222,128,0.08)" if is_win else "rgba(248,113,113,0.08)"
    res_border = "rgba(74,222,128,0.30)" if is_win else "rgba(248,113,113,0.30)"
    pnl_str    = f"+${profit:.2f}" if is_win else f"-${unit:.2f}"
    br_color   = "#4ADE80" if br_aft >= br_bef else "#F87171"
    rec_color  = "#4ADE80" if record_w > record_l else "#F87171" if record_l > record_w else "#F1F5F9"

    badge  = _sport_badge(sport, tour)
    date_s = d.strftime("%b %d, %Y").upper()

    CARD_CSS = _BASE_CSS + f"""
.result-hero {{
  display:flex; align-items:center; justify-content:space-between;
  background:{res_bg}; border:1px solid {res_border};
  border-radius:16px; padding:28px 36px; margin-bottom:20px;
}}
.result-left   {{ display:flex; align-items:center; gap:28px; }}
.result-badge  {{ font-size:52px; font-weight:900; color:{res_color}; letter-spacing:-1px; line-height:1; }}
.result-name   {{ font-size:28px; font-weight:900; color:#F1F5F9; letter-spacing:-0.3px; margin-bottom:6px; }}
.result-meta   {{ font-size:14px; font-weight:700; color:rgba(255,255,255,0.55); }}
.result-right  {{ text-align:right; }}
.result-pnl    {{ font-size:48px; font-weight:900; color:{res_color}; letter-spacing:-1px; line-height:1; font-variant-numeric:tabular-nums; }}
.result-sub    {{ font-size:13px; font-weight:700; color:rgba(255,255,255,0.45); margin-top:6px; }}
.pick-detail {{
  display:flex; align-items:center; gap:16px;
  background:rgba(255,255,255,0.018); border:1px solid rgba(255,255,255,0.07);
  border-radius:12px; padding:18px 24px; margin-bottom:20px;
}}
.pd-name  {{ font-size:16px; font-weight:900; color:#F1F5F9; }}
.pd-sub   {{ font-size:12px; font-weight:700; color:rgba(255,255,255,0.45); margin-top:3px; }}
.pd-odds  {{ font-size:36px; font-weight:900; color:#F1F5F9; letter-spacing:-0.5px; font-variant-numeric:tabular-nums; }}
.pd-edge  {{ font-size:13px; font-weight:800; color:#4ADE80; margin-top:4px; }}
"""

    html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=1080">
{_GOOGLE_FONTS}<style>{CARD_CSS}</style></head>
<body><div class="wrap">
  <div class="header">
    <div class="brand">
      <div class="brand-mark">&#9672;</div>
      <div><div class="brand-name">Overlay</div><div class="brand-sub">ML PICKS MODEL</div></div>
    </div>
    <div class="header-right">
      <div class="header-date">{date_s}</div>
      <div class="header-pill">JUNE CHALLENGE &nbsp;&middot;&nbsp; DAY {day}</div>
    </div>
  </div>

  <div class="result-hero">
    <div class="result-left">
      <div class="result-badge">{result}</div>
      <div>
        <div class="result-name">{player}</div>
        <div class="result-meta">{tour} &nbsp;&middot;&nbsp; {surface} &nbsp;&middot;&nbsp; {_fmt_odds(odds)} odds</div>
      </div>
    </div>
    <div class="result-right">
      <div class="result-pnl">{pnl_str}</div>
      <div class="result-sub">${unit:.0f} unit &nbsp;&middot;&nbsp; Bet of the Day</div>
    </div>
  </div>

  <div class="strip">
    <div class="strip-cell"><div class="sc-label">Bankroll Before</div><div class="sc-val">${br_bef:.2f}</div></div>
    <div class="strip-cell"><div class="sc-label">Bankroll After</div><div class="sc-val" style="color:{br_color}">${br_aft:.2f}</div></div>
    <div class="strip-cell"><div class="sc-label">June Record</div><div class="sc-val" style="color:{rec_color}">{record_w}-{record_l}</div></div>
    <div class="strip-cell"><div class="sc-label">P&amp;L</div><div class="sc-val {'grn' if is_win else 'red'}">{pnl_str}</div></div>
  </div>

  <div class="pick-detail">
    <div style="flex:1;display:flex;align-items:center;gap:14px">
      {badge}
      <div>
        <div class="pd-name">{player} vs {opp}</div>
        <div class="pd-sub">{tour} &nbsp;&middot;&nbsp; Moneyline &nbsp;&middot;&nbsp; {bet.get("book","")}</div>
      </div>
    </div>
    <div style="text-align:right">
      <div class="pd-odds">{_fmt_odds(odds)}</div>
      <div class="pd-edge">+{edge:.1f}% model edge</div>
    </div>
  </div>

  <div class="footer">
    <div class="footer-disc">Not financial advice &nbsp;&middot;&nbsp; Bet responsibly &nbsp;&middot;&nbsp; 21+</div>
    <div class="footer-right">
      <span class="footer-handle">@getoverlay</span>
      <span class="footer-sep">&middot;</span>
      <span class="footer-url">overlay-gray.vercel.app</span>
    </div>
  </div>
</div></body></html>"""

    ts         = d.strftime("%Y%m%d")
    sport_slug = sport.lower().replace(" ", "_")
    out_dir    = OUTPUT_DIR / sport_slug / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    fn         = f"june_challenge_day{day}_{result.lower()}_card"
    return _render(html, out_dir / f"{fn}.html", out_dir / f"{fn}.png", height=780)


# ── Grading hook — called from chef.py after grade runs ──────────────────────

def grade_challenge_bets(grade_date: str | None = None) -> None:
    """
    After grading, check state.json for any unresolved challenge bets on
    grade_date and generate result cards for them.
    """
    from datetime import datetime
    import json as _json

    gd = grade_date or (datetime.now().strftime("%Y-%m-%d"))
    # Normalise YYYYMMDD → YYYY-MM-DD
    if len(gd) == 8 and "-" not in gd:
        gd = f"{gd[:4]}-{gd[4:6]}-{gd[6:]}"

    state = load_state()
    picks_path = Path("data/pnl/picks.json")
    if not picks_path.exists():
        return
    all_picks = _json.loads(picks_path.read_text())

    changed = False
    for bet in state["bets"]:
        if bet.get("date") != gd:
            continue
        if bet.get("result"):          # already resolved
            if not bet.get("card_generated"):
                _emit_result_card(bet, state)
                bet["card_generated"] = True
                changed = True
            continue

        # Try to find a matching graded pick
        player = (bet.get("player") or "").lower()
        matched = next(
            (p for p in all_picks
             if p.get("date", "").startswith(gd.replace("-", ""))
             and player in (p.get("team") or p.get("matchup") or "").lower()
             and p.get("result") in ("win", "loss")),
            None,
        )
        if not matched:
            print(f"  [june_challenge] no graded result found for {bet.get('player')} on {gd}")
            continue

        result  = matched["result"].upper()
        profit  = float(matched.get("profit") or 0)
        br_aft  = round(float(bet.get("bankroll_before", 200)) + profit, 2)

        bet["result"]         = result
        bet["profit"]         = profit
        bet["bankroll_after"] = br_aft
        state["bankroll"]     = br_aft
        state["record"]["w" if result == "WIN" else "l"] = \
            state["record"].get("w" if result == "WIN" else "l", 0) + 1

        _emit_result_card(bet, state)
        bet["card_generated"] = True
        changed = True
        print(f"  [june_challenge] Day {bet['day']} {result}  P&L {profit:+.2f}u  "
              f"Bankroll ${br_aft:.2f}  Record {state['record']['w']}-{state['record']['l']}")

    if changed:
        save_state(state)


def _emit_result_card(bet: dict, state: dict) -> None:
    from datetime import datetime
    d = datetime.strptime(bet["date"], "%Y-%m-%d").date()
    path = generate_result_card(
        bet,
        card_date=d,
        record_w=state["record"].get("w", 0),
        record_l=state["record"].get("l", 0),
    )
    if path:
        print(f"  [june_challenge] Result card → {path}")
