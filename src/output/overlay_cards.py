"""
Overlay-branded pick card renderer.

Clean, professional design for daily MLB / NBA pick cards.
Replaces the legacy Overlay template:
  - ◈ Overlay wordmark + indigo/violet brand mark
  - Team color accent bar on every pick
  - Sportsbook brand colors for book pills
  - Edge color tiers: green >= 10%, amber >= 5%, indigo < 5%
  - Tabular numbers, Inter font, no text gradients, no neon glow
  - Card height fits content (no forced 1080-square)

Public entry points:
  - render_overlay_card(picks, sport, d, ...) -> writes .html + .png
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from src.output.card_html import (
    _logo_url, _nba_logo_url,
    _team_abbr, _nba_team_abbr,
    _MLB_HEX, _NBA_HEX,
    _clean_book, _odds_int,
    _playwright_render,
    OUTPUT_DIR,
)


# ── Tiny helpers ─────────────────────────────────────────────────────────────

def _is_nan(v) -> bool:
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return str(v).strip().lower() in ("nan", "none", "")


def _safe(v) -> str:
    return "" if _is_nan(v) else str(v)


def _edge_color(edge_pct: float) -> str:
    if edge_pct >= 10:  return "#4ADE80"   # green
    if edge_pct >= 5:   return "#FBBF24"   # amber
    return "#818CF8"                        # indigo


# ── Sportsbook brand badges ──────────────────────────────────────────────────

_BOOK_BRANDS: dict[str, tuple[str, str, str]] = {
    # key                  bg          fg          display label
    "draftkings":         ("#185D2F", "#FFFFFF", "DraftKings"),
    "fanduel":            ("#1493FF", "#FFFFFF", "FanDuel"),
    "betmgm":             ("#C9A24D", "#0B0B0B", "BetMGM"),
    "betrivers":          ("#003087", "#FFFFFF", "BetRivers"),
    "hard rock bet":      ("#C8102E", "#FFFFFF", "Hard Rock"),
    "hardrockbet":        ("#C8102E", "#FFFFFF", "Hard Rock"),
    "hard rock":          ("#C8102E", "#FFFFFF", "Hard Rock"),
    "caesars":            ("#002D72", "#D4AF37", "Caesars"),
    "fanatics":           ("#E4002B", "#FFFFFF", "Fanatics"),
    "espnbet":            ("#D00000", "#FFFFFF", "ESPN BET"),
    "espn bet":           ("#D00000", "#FFFFFF", "ESPN BET"),
    "bet365":             ("#0D8C40", "#FFFFFF", "bet365"),
    "fliff":              ("#6C2BD9", "#FFFFFF", "Fliff"),
    "pinnacle":           ("#161616", "#FFFFFF", "Pinnacle"),
    "betfair":            ("#FFB80C", "#0B0B0B", "Betfair"),
    "betparx":            ("#000044", "#FFFFFF", "betPARX"),
    "thescore bet":       ("#E4002B", "#FFFFFF", "theScore"),
    "thescorebet":        ("#E4002B", "#FFFFFF", "theScore"),
    "bovada":             ("#F44336", "#FFFFFF", "Bovada"),
    "lowvig":             ("#0F172A", "#FFFFFF", "LowVig"),
    "lowvig.ag":          ("#0F172A", "#FFFFFF", "LowVig"),
    "mybookieag":         ("#1A3A6E", "#FFFFFF", "MyBookie"),
    "mybookie.ag":        ("#1A3A6E", "#FFFFFF", "MyBookie"),
    "betonlineag":        ("#000",    "#FFFFFF", "BetOnline"),
}


def _book_pill(book: str) -> str:
    if not book:
        return ""
    key = book.lower().strip()
    if key in _BOOK_BRANDS:
        bg, fg, lbl = _BOOK_BRANDS[key]
    else:
        bg, fg, lbl = "#1E293B", "#F1F5F9", _clean_book(book)
    return (
        f'<span style="display:inline-flex;align-items:center;'
        f'background:{bg};color:{fg};font-size:10px;font-weight:800;'
        f'padding:3px 9px;border-radius:5px;letter-spacing:0.04em;'
        f'white-space:nowrap;line-height:1.4">{lbl}</span>'
    )


# ── Visual primitives ────────────────────────────────────────────────────────

def _logo_html(url: str, abbr: str, color: str, size: int = 64) -> str:
    if url:
        return (
            f'<img src="{url}" style="width:{size}px;height:{size}px;'
            f'object-fit:contain;flex-shrink:0" alt="{abbr}">'
        )
    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
        f'background:{color};display:flex;align-items:center;justify-content:center;'
        f'font-size:{max(size//3, 14)}px;font-weight:900;color:#fff;'
        f'flex-shrink:0;letter-spacing:0.04em">{abbr}</div>'
    )


# Static stylesheet — shared across every card type
_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body {
  width:1080px;
  background:#06080F;
  font-family:'Inter',-apple-system,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;
  text-rendering:geometricPrecision;
  font-feature-settings:'tnum' 1, 'cv11' 1;
  color:#F1F5F9;
}
.card-wrap {
  width:1080px;
  background:
    radial-gradient(ellipse 90% 60% at 50% -10%, rgba(99,102,241,0.10) 0%, transparent 60%),
    #06080F;
  padding:36px 40px 28px;
}
/* Header */
.header {
  display:flex; align-items:center; justify-content:space-between;
  padding-bottom:22px;
  border-bottom:1px solid rgba(255,255,255,0.07);
  margin-bottom:22px;
}
.brand { display:flex; align-items:center; gap:14px; }
.brand-mark {
  width:48px; height:48px; border-radius:12px;
  background:linear-gradient(135deg,#6366f1,#8b5cf6);
  display:flex; align-items:center; justify-content:center;
  font-size:22px; color:#fff; font-weight:900; line-height:1;
  box-shadow:0 4px 24px rgba(99,102,241,0.28);
}
.brand-text { display:flex; flex-direction:column; gap:3px; line-height:1; }
.brand-name {
  font-size:30px; font-weight:900; color:#F1F5F9;
  letter-spacing:-0.5px;
}
.brand-sub {
  font-size:11px; color:rgba(255,255,255,0.4);
  letter-spacing:0.06em; font-weight:600;
}
.header-right { text-align:right; line-height:1; }
.header-date {
  font-size:15px; font-weight:700; color:#F1F5F9;
  letter-spacing:0.08em;
}
.header-meta {
  font-size:10px; font-weight:800; color:rgba(255,255,255,0.4);
  letter-spacing:0.14em; margin-top:6px;
}
/* Stat strip */
.summary {
  display:flex; gap:0;
  background:rgba(255,255,255,0.02);
  border:1px solid rgba(255,255,255,0.06);
  border-radius:12px;
  padding:14px 4px;
  margin-bottom:16px;
}
.summary-cell {
  flex:1; text-align:center;
  border-right:1px solid rgba(255,255,255,0.06);
}
.summary-cell:last-child { border-right:none; }
.summary-label {
  font-size:9px; font-weight:800; letter-spacing:0.14em;
  color:rgba(255,255,255,0.4); text-transform:uppercase;
  margin-bottom:6px;
}
.summary-val {
  font-size:22px; font-weight:900; color:#F1F5F9;
  letter-spacing:-0.5px; line-height:1;
  font-variant-numeric:tabular-nums;
}
.summary-val.pos { color:#4ADE80; }
/* Pick rows */
.picks { display:flex; flex-direction:column; gap:10px; }
.pick {
  display:flex; align-items:stretch;
  background:rgba(255,255,255,0.025);
  border:1px solid rgba(255,255,255,0.07);
  border-radius:14px; overflow:hidden;
}
.pick.best {
  background:linear-gradient(135deg,rgba(99,102,241,0.08) 0%,rgba(255,255,255,0.025) 60%);
  border:1px solid rgba(99,102,241,0.32);
}
.pick-accent { width:4px; align-self:stretch; flex-shrink:0; }
.pick-body {
  flex:1; min-width:0;
  display:flex; align-items:center; gap:18px;
  padding:16px 20px 16px 18px;
}
.pick-logo-wrap {
  display:flex; align-items:center; justify-content:center;
  width:64px; height:64px; flex-shrink:0;
}
.pick-vs-logos {
  display:flex; align-items:center; gap:6px; flex-shrink:0;
}
.pick-vs-sep {
  font-size:10px; font-weight:700; color:rgba(255,255,255,0.3);
  letter-spacing:0.06em;
}
.pick-info { flex:1; min-width:0; }
.pick-row1 {
  display:flex; align-items:center; gap:8px;
  margin-bottom:6px;
}
.mkt-tag {
  font-size:9px; font-weight:800; letter-spacing:0.14em;
  color:rgba(255,255,255,0.5); text-transform:uppercase;
  background:rgba(255,255,255,0.04);
  border:1px solid rgba(255,255,255,0.08);
  padding:2px 7px; border-radius:4px; line-height:1.4;
}
.best-tag {
  font-size:9px; font-weight:900; letter-spacing:0.14em;
  color:#A5B4FC;
  background:rgba(99,102,241,0.14);
  border:1px solid rgba(99,102,241,0.35);
  padding:2px 8px; border-radius:4px; line-height:1.4;
}
.pick-name {
  font-size:26px; font-weight:900; color:#F1F5F9;
  letter-spacing:-0.5px; line-height:1.15;
  margin-bottom:6px;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.pick-meta {
  display:flex; align-items:center; gap:10px;
  font-size:12px; color:rgba(255,255,255,0.55);
  font-weight:500;
}
.pick-meta .dot { color:rgba(255,255,255,0.2); }
.pick-stats {
  text-align:right; flex-shrink:0; padding-left:8px;
  min-width:130px;
}
.pick-odds {
  font-size:46px; font-weight:900; color:#F1F5F9;
  letter-spacing:-1.5px; line-height:1;
  font-variant-numeric:tabular-nums;
}
.pick-edge {
  font-size:12px; font-weight:800;
  letter-spacing:0.05em;
  margin-top:6px;
  font-variant-numeric:tabular-nums;
}
.pick-edge .pct { font-size:13px; }
/* NBA totals — direction + line as primary headline */
.pick-name .arrow {
  display:inline-block; transform:translateY(-1px); margin-right:2px;
}
/* Footer */
.footer {
  margin-top:22px; padding-top:18px;
  border-top:1px solid rgba(255,255,255,0.07);
  display:flex; align-items:center; justify-content:space-between;
}
.footer-record {
  display:flex; align-items:center; gap:10px;
  font-size:12px; color:rgba(255,255,255,0.5);
  font-variant-numeric:tabular-nums;
}
.footer-record .seg-label {
  font-size:9px; font-weight:800; letter-spacing:0.14em;
  color:rgba(255,255,255,0.3); text-transform:uppercase;
}
.footer-record .seg-val {
  font-weight:700; color:#F1F5F9;
}
.footer-record .pos { color:#4ADE80; }
.footer-record .neg { color:#F87171; }
.footer-record .div {
  width:1px; height:14px; background:rgba(255,255,255,0.1);
}
.footer-right {
  font-size:11px; color:rgba(255,255,255,0.4);
  letter-spacing:0.04em; font-weight:600;
  text-align:right;
}
.footer-right .handle { color:#818CF8; font-weight:700; }
.footer-right .url { color:#F1F5F9; font-weight:700; }
"""


# ── Building blocks ──────────────────────────────────────────────────────────

def _header_html(date_str: str, meta: str) -> str:
    return f'''
<div class="header">
  <div class="brand">
    <div class="brand-mark">&#9672;</div>
    <div class="brand-text">
      <div class="brand-name">Overlay</div>
      <div class="brand-sub">ML Picks Model</div>
    </div>
  </div>
  <div class="header-right">
    <div class="header-date">{date_str}</div>
    <div class="header-meta">{meta}</div>
  </div>
</div>'''


def _summary_html(n_picks: int, avg_edge: float, top_edge: float, top_pick: str) -> str:
    return f'''
<div class="summary">
  <div class="summary-cell">
    <div class="summary-label">Picks</div>
    <div class="summary-val">{n_picks}</div>
  </div>
  <div class="summary-cell">
    <div class="summary-label">Avg Edge</div>
    <div class="summary-val pos">+{avg_edge:.1f}%</div>
  </div>
  <div class="summary-cell">
    <div class="summary-label">Top Edge</div>
    <div class="summary-val pos">+{top_edge:.1f}%</div>
  </div>
  <div class="summary-cell">
    <div class="summary-label">Best Bet</div>
    <div class="summary-val" style="font-size:15px">{top_pick}</div>
  </div>
</div>'''


def _footer_html(record_str: str, handle: str = "getoverlay") -> str:
    rec_inner = ""
    if record_str:
        rec_inner = (
            f'<span class="seg-label">Season</span>'
            f'<span class="seg-val">{record_str}</span>'
        )
    return f'''
<div class="footer">
  <div class="footer-record">{rec_inner}</div>
  <div class="footer-right">
    <span class="handle">@{handle}</span>
    &nbsp;·&nbsp;
    <span class="url">overlay-gray.vercel.app</span>
  </div>
</div>'''


# ── Pick row rendering ───────────────────────────────────────────────────────

def _parse_matchup_mlb(matchup: str) -> tuple[str, str]:
    """Parse 'Away Team @ Home Team' → (away, home)."""
    if not matchup or _is_nan(matchup):
        return "", ""
    s = str(matchup).strip()
    if " @ " in s:
        parts = s.split(" @ ", 1)
        return parts[0].strip(), parts[1].strip()
    if " vs " in s:
        parts = s.split(" vs ", 1)
        return parts[1].strip(), parts[0].strip()
    return "", ""


def _mlb_pick_row(pick: dict, is_best: bool) -> str:
    market = str(pick.get("Market", "moneyline") or "moneyline").lower()
    team = _safe(pick.get("Team"))
    opponent = _safe(pick.get("Opponent"))
    matchup = _safe(pick.get("Matchup"))
    raw_edge = float(pick.get("Edge", 0) or 0)
    odds_val = _odds_int(pick.get("BestOdds", 0))
    book = _safe(pick.get("Sportsbook"))
    model_prob = float(pick.get("ModelProb", 0) or 0)
    bet_line = pick.get("BetLine")
    odds_str = f"{odds_val:+d}" if odds_val else "—"
    prob_pct = round(model_prob * 100, 1)

    # Edge is decimal for moneyline, pct for others
    edge_pct = round(raw_edge * 100, 1) if market == "moneyline" else round(raw_edge, 1)

    # Parse away/home from matchup or use team/opponent
    away_team, home_team = _parse_matchup_mlb(matchup)
    if not away_team and not home_team:
        # Fall back to team + opponent (opponent is "Opponent" field)
        away_team, home_team = opponent, team

    away_hex = _MLB_HEX.get(away_team, "#4080FF")
    home_hex = _MLB_HEX.get(home_team, "#4080FF")
    away_abbr = _team_abbr(away_team) if away_team else ""
    home_abbr = _team_abbr(home_team) if home_team else ""
    away_logo = _logo_url(away_team) if away_team else ""
    home_logo = _logo_url(home_team) if home_team else ""

    # Bet label and accent color depend on market
    if market == "spread":
        mkt_label = "RUN LINE"
        line = ""
        if bet_line is not None and not _is_nan(bet_line):
            line = f" {float(bet_line):+.1f}"
        pick_name = f"{team}{line}".strip()
        accent_hex = _MLB_HEX.get(team, "#4080FF")
    elif market == "total":
        direction = _safe(pick.get("Direction") or "OVER").upper()
        line_val = pick.get("MarketLine") or bet_line
        mkt_label = "GAME TOTAL"
        line_str = f"{line_val}" if not _is_nan(line_val) else ""
        pick_name = f"{direction} {line_str}".strip()
        accent_hex = "#22D3EE" if direction == "OVER" else "#F87171"
    else:
        mkt_label = "MONEYLINE"
        pick_name = team
        accent_hex = _MLB_HEX.get(team, "#4080FF")

    # Always show both teams (matches NBA card style — consistent layout across markets)
    logo_section = f'''
      <div class="pick-vs-logos">
        {_logo_html(away_logo, away_abbr, away_hex, 52)}
        <span class="pick-vs-sep">@</span>
        {_logo_html(home_logo, home_abbr, home_hex, 52)}
      </div>'''

    e_color = _edge_color(edge_pct)
    best_tag = '<span class="best-tag">BEST BET</span>' if is_best else ""

    # Meta line: matchup + model + book
    meta_parts = []
    if market == "moneyline" and opponent:
        meta_parts.append(f'vs {_team_abbr(opponent)}')
    elif away_abbr and home_abbr:
        meta_parts.append(f'{away_abbr} @ {home_abbr}')
    if prob_pct > 0:
        meta_parts.append(f'{prob_pct:.1f}% model')
    if book:
        meta_parts.append(_book_pill(book))
    meta_html = ' <span class="dot">·</span> '.join(meta_parts)

    cls = "pick best" if is_best else "pick"

    return f'''
<div class="{cls}">
  <div class="pick-accent" style="background:{accent_hex}"></div>
  <div class="pick-body">
    {logo_section}
    <div class="pick-info">
      <div class="pick-row1">
        <span class="mkt-tag">{mkt_label}</span>
        {best_tag}
      </div>
      <div class="pick-name">{pick_name}</div>
      <div class="pick-meta">{meta_html}</div>
    </div>
    <div class="pick-stats">
      <div class="pick-odds">{odds_str}</div>
      <div class="pick-edge" style="color:{e_color}">+{edge_pct:.1f}% <span style="color:rgba(255,255,255,0.35);font-weight:700;margin-left:2px">EDGE</span></div>
    </div>
  </div>
</div>'''


def _nba_pick_row(pick: dict, is_best: bool) -> str:
    market = str(pick.get("market", "spread") or "spread").lower()
    team_str = _safe(pick.get("team"))
    matchup = _safe(pick.get("matchup"))
    direction = _safe(pick.get("direction") or "").upper()
    bet_line = pick.get("bet_line")
    odds_val = _odds_int(pick.get("best_odds", 0))
    book = _safe(pick.get("sportsbook"))
    edge_pct = float(pick.get("edge_pct", 0) or 0)
    model_prob = float(pick.get("model_prob", 0) or 0)
    odds_str = f"{odds_val:+d}" if odds_val else "—"
    prob_pct = round(model_prob * 100, 1)

    # Parse away/home from matchup
    if " @ " in matchup:
        away_team, home_team = [p.strip() for p in matchup.split(" @ ", 1)]
    else:
        away_team, home_team = "", ""

    away_logo = _nba_logo_url(away_team) if away_team else ""
    home_logo = _nba_logo_url(home_team) if home_team else ""
    away_hex = _NBA_HEX.get(away_team, "#4080FF")
    home_hex = _NBA_HEX.get(home_team, "#4080FF")
    away_abbr = _nba_team_abbr(away_team) if away_team else ""
    home_abbr = _nba_team_abbr(home_team) if home_team else ""

    if market in ("moneyline", "h2h"):
        mkt_label = "MONEYLINE"
        bet_team = team_str
        accent_hex = _NBA_HEX.get(bet_team, "#4080FF")
        pick_name = bet_team
    elif market == "spread":
        mkt_label = "SPREAD"
        bet_team = team_str.rsplit(" ", 1)[0] if " " in team_str else team_str
        accent_hex = _NBA_HEX.get(bet_team, "#4080FF")
        line_disp = f"{float(bet_line):+.1f}" if bet_line is not None and not _is_nan(bet_line) else ""
        pick_name = f"{bet_team} {line_disp}".strip()
    else:  # total
        mkt_label = "GAME TOTAL"
        accent_hex = "#22D3EE" if direction == "OVER" else "#F87171"
        line_disp = f"{bet_line}" if bet_line is not None and not _is_nan(bet_line) else ""
        pick_name = f"{direction} {line_disp}".strip()

    e_color = _edge_color(edge_pct)
    best_tag = '<span class="best-tag">BEST BET</span>' if is_best else ""

    # Show both team logos for NBA (visual context)
    logo_section = f'''
      <div class="pick-vs-logos">
        {_logo_html(away_logo, away_abbr, away_hex, 52)}
        <span class="pick-vs-sep">@</span>
        {_logo_html(home_logo, home_abbr, home_hex, 52)}
      </div>'''

    meta_parts = []
    if matchup:
        meta_parts.append(f'{away_abbr} @ {home_abbr}' if away_abbr and home_abbr else matchup)
    if prob_pct > 0:
        meta_parts.append(f'{prob_pct:.1f}% model')
    if book:
        meta_parts.append(_book_pill(book))
    meta_html = ' <span class="dot">·</span> '.join(meta_parts)

    cls = "pick best" if is_best else "pick"

    return f'''
<div class="{cls}">
  <div class="pick-accent" style="background:{accent_hex}"></div>
  <div class="pick-body">
    {logo_section}
    <div class="pick-info">
      <div class="pick-row1">
        <span class="mkt-tag">{mkt_label}</span>
        {best_tag}
      </div>
      <div class="pick-name">{pick_name}</div>
      <div class="pick-meta">{meta_html}</div>
    </div>
    <div class="pick-stats">
      <div class="pick-odds">{odds_str}</div>
      <div class="pick-edge" style="color:{e_color}">+{edge_pct:.1f}% <span style="color:rgba(255,255,255,0.35);font-weight:700;margin-left:2px">EDGE</span></div>
    </div>
  </div>
</div>'''


# ── Card builders ────────────────────────────────────────────────────────────

def _build_mlb_card(picks: list[dict], d: date, record_str: str = "",
                    card_type: str = "moneyline") -> str:
    date_str = d.strftime("%b %-d, %Y").upper() if hasattr(d, "strftime") else "—"
    picks = picks[:5]
    n = len(picks)

    # Summary edges
    edges: list[float] = []
    for p in picks:
        m = str(p.get("Market", "moneyline") or "moneyline").lower()
        e = float(p.get("Edge", 0) or 0)
        edges.append(round(e * 100, 1) if m == "moneyline" else round(e, 1))

    top_edge = max(edges) if edges else 0.0
    avg_edge = sum(edges) / len(edges) if edges else 0.0

    # Best pick name (short)
    top_pick = ""
    if picks:
        top_team = _safe(picks[0].get("Team"))
        top_pick = _team_abbr(top_team) if top_team else "—"

    rows = "\n".join(_mlb_pick_row(p, idx == 0) for idx, p in enumerate(picks))

    meta = f"MLB · {n} pick{'s' if n != 1 else ''}"
    if card_type == "spread":
        meta = f"MLB Run Line · {n} pick{'s' if n != 1 else ''}"
    elif card_type == "total":
        meta = f"MLB Totals · {n} pick{'s' if n != 1 else ''}"

    summary = _summary_html(n, avg_edge, top_edge, top_pick) if n >= 2 else ""

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head><body>
<div class="card-wrap">
  {_header_html(date_str, meta)}
  {summary}
  <div class="picks">{rows}</div>
  {_footer_html(record_str)}
</div>
</body></html>"""


def _build_nba_card(picks: list[dict], d: date, context_label: str = "NBA",
                    record_str: str = "") -> str:
    date_str = d.strftime("%b %-d, %Y").upper() if hasattr(d, "strftime") else "—"
    picks = picks[:6]
    n = len(picks)

    edges = [float(p.get("edge_pct", 0) or 0) for p in picks]
    top_edge = max(edges) if edges else 0.0
    avg_edge = sum(edges) / len(edges) if edges else 0.0

    # "Best bet" label for summary
    if picks:
        bp = picks[0]
        m = str(bp.get("market", "") or "").lower()
        if m == "total":
            dirn = _safe(bp.get("direction") or "").upper()
            top_pick = f"{dirn} {_safe(bp.get('bet_line'))}" if dirn else "—"
        else:
            t = _safe(bp.get("team"))
            top_pick = _nba_team_abbr(t.rsplit(" ", 1)[0] if " " in t else t)
    else:
        top_pick = "—"

    rows = "\n".join(_nba_pick_row(p, idx == 0) for idx, p in enumerate(picks))

    meta = f"{context_label} · {n} pick{'s' if n != 1 else ''}"
    summary = _summary_html(n, avg_edge, top_edge, top_pick) if n >= 2 else ""

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head><body>
<div class="card-wrap">
  {_header_html(date_str, meta)}
  {summary}
  <div class="picks">{rows}</div>
  {_footer_html(record_str)}
</div>
</body></html>"""


# ── Pick of the Day (single hero card, 1080×1080) ────────────────────────────

_POD_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body {
  width:1080px;
  background:#06080F;
  font-family:'Inter',-apple-system,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;
  text-rendering:geometricPrecision;
  font-feature-settings:'tnum' 1;
  color:#F1F5F9;
}
.pod-wrap {
  width:1080px; height:1080px;
  background:
    radial-gradient(ellipse 70% 50% at 50% 0%, var(--accent-glow) 0%, transparent 55%),
    radial-gradient(ellipse 70% 50% at 50% 100%, rgba(99,102,241,0.06) 0%, transparent 55%),
    #06080F;
  padding:44px 56px 36px;
  display:flex; flex-direction:column;
  position:relative;
}
.pod-header {
  display:flex; align-items:center; justify-content:space-between;
  padding-bottom:24px;
  border-bottom:1px solid rgba(255,255,255,0.07);
}
.pod-brand { display:flex; align-items:center; gap:14px; }
.pod-mark {
  width:52px; height:52px; border-radius:13px;
  background:linear-gradient(135deg,#6366f1,#8b5cf6);
  display:flex; align-items:center; justify-content:center;
  font-size:24px; color:#fff; font-weight:900; line-height:1;
  box-shadow:0 4px 24px rgba(99,102,241,0.3);
}
.pod-name {
  font-size:34px; font-weight:900; color:#F1F5F9;
  letter-spacing:-0.5px; line-height:1;
}
.pod-sub {
  font-size:12px; color:rgba(255,255,255,0.4);
  letter-spacing:0.06em; font-weight:600;
  margin-top:4px;
}
.pod-pill {
  background:rgba(99,102,241,0.14);
  border:1px solid rgba(99,102,241,0.4);
  color:#A5B4FC;
  font-size:11px; font-weight:900; letter-spacing:0.2em;
  padding:6px 14px; border-radius:999px;
  text-transform:uppercase;
}
.pod-date {
  font-size:14px; font-weight:700; color:#F1F5F9;
  letter-spacing:0.08em; text-align:right;
}
.pod-meta {
  font-size:10px; font-weight:800; color:rgba(255,255,255,0.4);
  letter-spacing:0.14em; margin-top:6px; text-align:right;
}

/* Center column */
.pod-body {
  flex:1; display:flex; flex-direction:column;
  align-items:center; justify-content:center;
  padding:8px 0;
}
.pod-mkt {
  font-size:11px; font-weight:800; letter-spacing:0.22em;
  color:rgba(255,255,255,0.4); text-transform:uppercase;
  background:rgba(255,255,255,0.04);
  border:1px solid rgba(255,255,255,0.08);
  padding:5px 14px; border-radius:6px;
  margin-bottom:30px;
}
.pod-logos {
  display:flex; align-items:center; gap:18px;
  margin-bottom:26px;
}
.pod-logo-single {
  width:200px; height:200px;
  display:flex; align-items:center; justify-content:center;
  filter:drop-shadow(0 12px 36px var(--accent-glow));
}
.pod-logo-pair {
  width:140px; height:140px;
  display:flex; align-items:center; justify-content:center;
}
.pod-logo-pair img { width:140px; height:140px; object-fit:contain; }
.pod-logo-single img { width:200px; height:200px; object-fit:contain; }
.pod-sep {
  font-size:24px; font-weight:700; color:rgba(255,255,255,0.25);
}

.pod-team {
  font-size:46px; font-weight:900; color:#F1F5F9;
  letter-spacing:-1px; line-height:1.05; text-align:center;
  margin-bottom:8px;
}
.pod-matchup {
  font-size:15px; font-weight:600; color:rgba(255,255,255,0.45);
  letter-spacing:0.04em;
  margin-bottom:34px;
}

.pod-odds-wrap {
  display:flex; flex-direction:column; align-items:center;
  margin-bottom:24px;
}
.pod-odds {
  font-size:104px; font-weight:900; color:#F1F5F9;
  letter-spacing:-4px; line-height:1;
  font-variant-numeric:tabular-nums;
}

.pod-tags {
  display:flex; gap:10px; align-items:center;
}
.pod-edge {
  display:inline-flex; align-items:center;
  font-size:14px; font-weight:900;
  padding:7px 16px; border-radius:999px;
  letter-spacing:0.03em;
  font-variant-numeric:tabular-nums;
}

.pod-why {
  margin-top:24px; max-width:720px; text-align:center;
  font-size:14px; color:rgba(255,255,255,0.55);
  line-height:1.55; font-style:italic;
}

/* Footer */
.pod-footer {
  display:flex; align-items:center; justify-content:space-between;
  padding-top:20px;
  border-top:1px solid rgba(255,255,255,0.07);
}
.pod-record {
  font-size:13px; color:rgba(255,255,255,0.55);
  font-variant-numeric:tabular-nums;
}
.pod-record .seg-label {
  font-size:9px; font-weight:800; letter-spacing:0.14em;
  color:rgba(255,255,255,0.3); text-transform:uppercase;
  margin-right:8px;
}
.pod-record .seg-val { font-weight:700; color:#F1F5F9; }
.pod-handle {
  font-size:12px; color:rgba(255,255,255,0.45);
  letter-spacing:0.04em; font-weight:600;
  text-align:right;
}
.pod-handle .at { color:#818CF8; font-weight:700; }
.pod-handle .url { color:#F1F5F9; font-weight:700; }
"""


def _build_pick_of_day(pick: dict, sport: str, d: date, record_str: str = "") -> str:
    """Build a 1080×1080 hero pick-of-the-day card."""
    is_nba = sport.lower() in ("nba", "basketball_nba")
    date_str = d.strftime("%b %-d, %Y").upper() if hasattr(d, "strftime") else "—"
    sport_lbl = "NBA" if is_nba else "MLB"

    # Pull fields with both MLB-shape (Team, Market, BestOdds) and NBA-shape (team, market, best_odds)
    market = str(pick.get("Market") or pick.get("market") or "moneyline").lower()
    team_str = _safe(pick.get("Team") or pick.get("team"))
    opponent = _safe(pick.get("Opponent"))
    matchup = _safe(pick.get("Matchup") or pick.get("matchup"))
    bet_line = pick.get("BetLine") if pick.get("BetLine") is not None else pick.get("bet_line")
    odds_val = _odds_int(pick.get("BestOdds") or pick.get("best_odds") or 0)
    book = _safe(pick.get("Sportsbook") or pick.get("sportsbook"))
    raw_edge = float(pick.get("Edge") or pick.get("edge_pct") or 0)
    direction = _safe(pick.get("Direction") or pick.get("direction") or "").upper()
    why = _safe(pick.get("Why") or pick.get("notes") or "")

    # Edge normalization (MLB ML stores as decimal)
    if "edge_pct" in pick:
        edge_pct = round(raw_edge, 1)
    elif market == "moneyline":
        edge_pct = round(raw_edge * 100, 1)
    else:
        edge_pct = round(raw_edge, 1)

    odds_str = f"{odds_val:+d}" if odds_val else "—"

    # Parse matchup
    if " @ " in matchup:
        away_team, home_team = [p.strip() for p in matchup.split(" @ ", 1)]
    elif " vs " in matchup:
        a, b = [p.strip() for p in matchup.split(" vs ", 1)]
        away_team, home_team = b, a
    else:
        away_team, home_team = "", ""

    # Build market label, pick name, and logo section
    if market == "total" or market == "f5_total":
        mkt_label = "GAME TOTAL"
        line_val = bet_line if bet_line is not None else (pick.get("MarketLine") or "")
        line_str = "" if _is_nan(line_val) else str(line_val)
        pick_name = f"{direction} {line_str}".strip()
        if is_nba:
            away_logo = _nba_logo_url(away_team) if away_team else ""
            home_logo = _nba_logo_url(home_team) if home_team else ""
            away_color = _NBA_HEX.get(away_team, "#4080FF")
            home_color = _NBA_HEX.get(home_team, "#4080FF")
            away_abbr = _nba_team_abbr(away_team) if away_team else ""
            home_abbr = _nba_team_abbr(home_team) if home_team else ""
        else:
            away_logo = _logo_url(away_team) if away_team else ""
            home_logo = _logo_url(home_team) if home_team else ""
            away_color = _MLB_HEX.get(away_team, "#4080FF")
            home_color = _MLB_HEX.get(home_team, "#4080FF")
            away_abbr = _team_abbr(away_team) if away_team else ""
            home_abbr = _team_abbr(home_team) if home_team else ""

        # Both team logos
        logo_html = f'''
<div class="pod-logos">
  <div class="pod-logo-pair">{_logo_html(away_logo, away_abbr, away_color, 140)}</div>
  <span class="pod-sep">@</span>
  <div class="pod-logo-pair">{_logo_html(home_logo, home_abbr, home_color, 140)}</div>
</div>'''
        matchup_disp = f"{away_team} @ {home_team}" if away_team and home_team else matchup
        accent = "#22D3EE" if direction == "OVER" else "#F87171"

    elif market == "spread":
        mkt_label = "SPREAD" if is_nba else "RUN LINE"
        line = ""
        if bet_line is not None and not _is_nan(bet_line):
            line = f" {float(bet_line):+.1f}"
        # Team string may already include line
        team_only = team_str
        if " " in team_only and any(c in team_only for c in "+-"):
            # try strip line
            team_only = team_only.rsplit(" ", 1)[0]
        pick_name = f"{team_only}{line}".strip()
        accent = (_NBA_HEX if is_nba else _MLB_HEX).get(team_only, "#4080FF")
        team_logo = (_nba_logo_url if is_nba else _logo_url)(team_only)
        team_abbr_str = (_nba_team_abbr if is_nba else _team_abbr)(team_only)
        logo_html = f'''
<div class="pod-logos">
  <div class="pod-logo-single">{_logo_html(team_logo, team_abbr_str, accent, 200)}</div>
</div>'''
        if not matchup and opponent:
            matchup_disp = f"vs {opponent}"
        elif away_team and home_team:
            matchup_disp = f"{away_team} @ {home_team}"
        else:
            matchup_disp = matchup

    else:  # moneyline / h2h
        mkt_label = "MONEYLINE"
        pick_name = team_str
        accent = (_NBA_HEX if is_nba else _MLB_HEX).get(team_str, "#4080FF")
        team_logo = (_nba_logo_url if is_nba else _logo_url)(team_str)
        team_abbr_str = (_nba_team_abbr if is_nba else _team_abbr)(team_str)
        logo_html = f'''
<div class="pod-logos">
  <div class="pod-logo-single">{_logo_html(team_logo, team_abbr_str, accent, 200)}</div>
</div>'''
        # Build matchup display, handling NaN opponent
        opp_clean = "" if _is_nan(opponent) else opponent
        if opp_clean:
            matchup_disp = f"vs {opp_clean}"
        elif away_team and home_team:
            matchup_disp = f"{away_team} @ {home_team}"
        else:
            matchup_disp = ""

    e_color = _edge_color(edge_pct)
    # accent_glow: convert hex to rgba with low alpha
    try:
        ah = accent.lstrip("#")
        r, g, b = int(ah[0:2], 16), int(ah[2:4], 16), int(ah[4:6], 16)
        accent_glow = f"rgba({r},{g},{b},0.18)"
    except Exception:
        accent_glow = "rgba(99,102,241,0.18)"

    # Book pill
    book_html = _book_pill(book) if book else ""

    # Edge pill (using tier color)
    edge_pill = (
        f'<span class="pod-edge" style="color:{e_color};'
        f'background:{e_color}1A;border:1px solid {e_color}66">+{edge_pct:.1f}% EDGE</span>'
    )

    # Why excerpt (max ~120 chars)
    why_html = ""
    if why and len(why) > 4 and "lower confidence" not in why.lower():
        snippet = why if len(why) <= 140 else why[:137].rsplit(" ", 1)[0] + "…"
        why_html = f'<div class="pod-why">"{snippet}"</div>'

    matchup_html = (
        f'<div class="pod-matchup">{matchup_disp}</div>' if matchup_disp else ""
    )

    record_inner = ""
    if record_str:
        record_inner = (
            f'<span class="seg-label">Season</span><span class="seg-val">{record_str}</span>'
        )

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>{_POD_CSS}</style>
</head><body>
<div class="pod-wrap" style="--accent-glow:{accent_glow}">
  <div class="pod-header">
    <div class="pod-brand">
      <div class="pod-mark">&#9672;</div>
      <div>
        <div class="pod-name">Overlay</div>
        <div class="pod-sub">ML Picks Model</div>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:10px">
      <span class="pod-pill">Pick of the Day</span>
      <div>
        <div class="pod-date">{date_str}</div>
        <div class="pod-meta">{sport_lbl}</div>
      </div>
    </div>
  </div>

  <div class="pod-body">
    <div class="pod-mkt">{mkt_label}</div>
    {logo_html}
    <div class="pod-team">{pick_name}</div>
    {matchup_html}
    <div class="pod-odds-wrap">
      <div class="pod-odds">{odds_str}</div>
    </div>
    <div class="pod-tags">
      {book_html}
      {edge_pill}
    </div>
    {why_html}
  </div>

  <div class="pod-footer">
    <div class="pod-record">{record_inner}</div>
    <div class="pod-handle">
      <span class="at">@getoverlay</span>
      &nbsp;·&nbsp;
      <span class="url">overlay-gray.vercel.app</span>
    </div>
  </div>
</div>
</body></html>"""


def render_overlay_pick_of_day(
    pick: dict,
    sport: str = "mlb",
    card_date: date | None = None,
    record_str: str = "",
    filename: str = "pick_of_day_card",
) -> Path | None:
    """Render hero 1080×1080 pick-of-the-day card for MLB or NBA."""
    d = card_date or date.today()
    is_nba = sport.lower() in ("nba", "basketball_nba")
    save_dir = OUTPUT_DIR / ("basketball_nba" if is_nba else "baseball_mlb") / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    html = _build_pick_of_day(pick, sport, d, record_str=record_str)
    return _playwright_render(
        html,
        save_dir / f"{filename}.html",
        save_dir / f"{filename}.png",
        target_height=1080,
    )


# ── Public render entry points ───────────────────────────────────────────────

def render_overlay_mlb_card(
    picks: list[dict],
    card_date: date | None = None,
    record_str: str = "",
    card_type: str = "moneyline",
    filename: str = "pick_card",
) -> Path | None:
    d = card_date or date.today()
    html = _build_mlb_card(picks, d, record_str=record_str, card_type=card_type)
    save_dir = OUTPUT_DIR / "baseball_mlb" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(
        html,
        save_dir / f"{filename}.html",
        save_dir / f"{filename}.png",
        target_height=1400,
    )


def render_overlay_nba_card(
    picks: list[dict],
    card_date: date | None = None,
    context_label: str = "NBA",
    record_str: str = "",
    filename: str = "nba_pick_card",
) -> Path | None:
    d = card_date or date.today()
    html = _build_nba_card(picks, d, context_label=context_label, record_str=record_str)
    save_dir = OUTPUT_DIR / "basketball_nba" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(
        html,
        save_dir / f"{filename}.html",
        save_dir / f"{filename}.png",
        target_height=1400,
    )
