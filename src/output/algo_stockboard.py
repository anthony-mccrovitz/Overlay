"""Algo Stockboard — stock-style breakdown of every (sport, market) algorithm.

Two outputs:
  1. Summary table card — one row per algo with lifetime / 30d / 7d / trend
  2. Drilldown card per algo — full stats, calibration, recent picks

Used by scripts/weekly_audit.py and runnable standalone:
  python3 -m src.output.algo_stockboard
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT       = Path(__file__).resolve().parent.parent.parent
PICKS_FILE = ROOT / "data" / "pnl" / "picks.json"
OUT_DIR    = ROOT / "output" / "stockboard"

SPORT_CLEAN = {
    "baseball_mlb": "mlb", "basketball_nba": "nba", "basketball_wnba": "wnba",
    "icehockey_nhl": "nhl", "soccer_germany_bundesliga": "soccer",
    "soccer_italy_serie_a": "soccer", "soccer_spain_la_liga": "soccer",
    "soccer_usa_mls": "soccer", "soccer_conmebol_copa_libertadores": "soccer",
    "tennis_atp_french_open": "tennis", "tennis_atp_italian_open": "tennis",
    "mma_mixed_martial_arts": "ufc",
}


# ── Data layer ───────────────────────────────────────────────────────────────

def _load_picks() -> list[dict]:
    raw = json.loads(PICKS_FILE.read_text())
    picks = raw if isinstance(raw, list) else raw.get("picks", [])
    return [p for p in picks if isinstance(p, dict)]


def _canon_sport(p: dict) -> str:
    s = (p.get("sport") or "").lower()
    return SPORT_CLEAN.get(s, s)


def _stats(picks: list[dict]) -> dict:
    settled = [p for p in picks if p.get("result") in ("win", "loss", "push")]
    w = sum(1 for p in settled if p["result"] == "win")
    l = sum(1 for p in settled if p["result"] == "loss")
    pu = sum(1 for p in settled if p["result"] == "push")
    profit = sum(p.get("profit") or 0 for p in settled)
    wl = w + l
    return {
        "w": w, "l": l, "push": pu, "n": len(settled), "profit": profit,
        "wr":  w / wl if wl else 0,
        "roi": profit / wl if wl else 0,
    }


def _model_status(sport: str, market: str) -> tuple[str, str]:
    """Return (status, tier) using model registry, with a safe fallback."""
    try:
        from src.config.models import model_status, model_tier
        return model_status(sport, market), model_tier(sport, market)
    except Exception:
        return "incubating", "shadow"


def compute_algo_grid() -> list[dict]:
    """Build a sorted list of algo stats, one per (sport, market) pair.

    Sort order: LIVE first (by lifetime ROI desc), then SHADOW (by volume desc).
    """
    today = date.today()
    cutoff_30d = today - timedelta(days=30)
    cutoff_7d  = today - timedelta(days=7)

    picks = _load_picks()
    grid: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in picks:
        sp = _canon_sport(p)
        mk = (p.get("market") or "?").lower()
        if not sp or sp == "?":
            continue
        grid[(sp, mk)].append(p)

    rows = []
    for (sport, market), bucket in grid.items():
        card_only = [p for p in bucket if p.get("card_pick")]
        # Use ALL picks for shadow stats; card_pick only when live
        status, tier = _model_status(sport, market)
        pool = card_only if status == "live" else bucket

        if len(pool) < 5:
            continue  # too small to surface

        recent_30 = [p for p in pool if (p.get("date") or "") >= str(cutoff_30d)]
        recent_7  = [p for p in pool if (p.get("date") or "") >= str(cutoff_7d)]

        s_life = _stats(pool)
        s_30   = _stats(recent_30)
        s_7    = _stats(recent_7)

        # Trend: 30d ROI vs lifetime ROI
        if s_30["n"] < 5:
            trend = "flat"
        elif s_30["roi"] > s_life["roi"] + 0.02:
            trend = "up"
        elif s_30["roi"] < s_life["roi"] - 0.02:
            trend = "down"
        else:
            trend = "flat"

        rows.append({
            "sport": sport, "market": market,
            "status": status, "tier": tier,
            "lifetime": s_life, "d30": s_30, "d7": s_7,
            "trend": trend,
        })

    def _sort_key(r):
        # LIVE rows first (by lifetime ROI desc), then SHADOW (by volume desc)
        live_rank = 0 if r["status"] == "live" else (1 if r["status"] == "incubating" else 2)
        if r["status"] == "live":
            return (live_rank, -r["lifetime"]["roi"])
        return (live_rank, -r["lifetime"]["n"])

    return sorted(rows, key=_sort_key)


# ── Render helpers ───────────────────────────────────────────────────────────

def _render_html(html: str, out_path: Path, width: int = 1080, height: int = 1500) -> Optional[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [stockboard] playwright not installed")
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
        print(f"  [stockboard] render error: {e}")
        return None


def _sport_label(s: str) -> str:
    return {"mlb":"MLB","nba":"NBA","nhl":"NHL","wnba":"WNBA","ufc":"UFC",
            "pga":"PGA","soccer":"SOCCER","tennis":"TENNIS",
            "nascar":"NASCAR","indycar":"INDYCAR","f1":"F1"}.get(s, s.upper())


def _market_label(m: str) -> str:
    return {"moneyline":"Moneyline","ml":"Moneyline","total":"Total","totals":"Total",
            "spread":"Spread","run_line":"Run Line","puck_line":"Puck Line",
            "f5_total":"F5 Total","nrfi":"NRFI","outright":"Outright",
            "pitcher_strikeouts":"Pitcher Ks","prop":"Prop",
            "batter_home_runs":"Batter HR","batter_hits":"Batter Hits",
            "batter_total_bases":"Batter TB","batter_rbis":"Batter RBI",
            "player_points":"Player Pts","player_rebounds":"Player Reb",
            "player_assists":"Player Ast","player_goals":"Player Goals",
            "player_shots_on_goal":"Player SOG","player_blocked_shots":"Player Blocks",
            "player_blocks":"Player Blocks","player_steals":"Player Stl",
            "player_threes":"Player 3PM","player_pra":"Player PRA",
            }.get(m, m.replace("_"," ").title())


def _fmt_record(s: dict) -> str:
    if s["n"] == 0: return "—"
    return f"{s['w']}-{s['l']}"


def _fmt_roi(s: dict) -> str:
    if s["n"] == 0: return "—"
    return f"{s['roi']*100:+.1f}%"


def _fmt_profit(s: dict) -> str:
    if s["n"] == 0: return "—"
    return f"{s['profit']:+.2f}u"


# ── Summary table card ───────────────────────────────────────────────────────

def render_stockboard_card(rows: list[dict] | None = None,
                           out_path: Path | None = None) -> Optional[Path]:
    if rows is None:
        rows = compute_algo_grid()

    today = date.today()

    # Build rows HTML
    row_html_parts = []
    last_status = None
    for r in rows:
        # Section header when status group changes
        if r["status"] != last_status:
            label = {"live":"LIVE","incubating":"SHADOW","retired":"RETIRED"}.get(r["status"], r["status"].upper())
            row_html_parts.append(f'<div class="section-label">{label}</div>')
            last_status = r["status"]

        status_class = {"live":"s-live","incubating":"s-shadow","retired":"s-retired"}.get(r["status"], "s-shadow")
        tier_pill   = {"t1":"T1","t2":"T2","shadow":"SH","paused":"PSE"}.get(r["tier"], "—")

        algo_name = f"{_sport_label(r['sport'])} {_market_label(r['market'])}"

        # Trend arrow
        trend_icon = {"up":"↑","down":"↓","flat":"·"}[r["trend"]]
        trend_class = {"up":"t-up","down":"t-down","flat":"t-flat"}[r["trend"]]

        # ROI color per cell
        def _roi_class(s):
            if s["n"] == 0: return "v-empty"
            if s["roi"] > 0.02: return "v-pos"
            if s["roi"] < -0.02: return "v-neg"
            return "v-flat"

        # Sample-size class: muted when below threshold
        def _vol_class(s, min_n):
            return "" if s["n"] >= min_n else " low-n"

        row_html_parts.append(f"""
        <div class="row">
          <div class="cell algo">
            <div class="algo-name">{algo_name}</div>
            <div class="algo-meta">
              <span class="pill {status_class}">{r['status'].upper()}</span>
              <span class="pill p-tier">{tier_pill}</span>
            </div>
          </div>
          <div class="cell tf{_vol_class(r['lifetime'], 20)}">
            <div class="rec">{_fmt_record(r['lifetime'])}</div>
            <div class="roi {_roi_class(r['lifetime'])}">{_fmt_roi(r['lifetime'])}</div>
            <div class="prof">{_fmt_profit(r['lifetime'])}</div>
          </div>
          <div class="cell tf{_vol_class(r['d30'], 10)}">
            <div class="rec">{_fmt_record(r['d30'])}</div>
            <div class="roi {_roi_class(r['d30'])}">{_fmt_roi(r['d30'])}</div>
            <div class="prof">{_fmt_profit(r['d30'])}</div>
          </div>
          <div class="cell tf{_vol_class(r['d7'], 3)}">
            <div class="rec">{_fmt_record(r['d7'])}</div>
            <div class="roi {_roi_class(r['d7'])}">{_fmt_roi(r['d7'])}</div>
          </div>
          <div class="cell trend"><span class="trend-arrow {trend_class}">{trend_icon}</span></div>
        </div>""")

    rows_html = "".join(row_html_parts)
    height    = max(1500, 280 + 88 * len(rows) + 60 * 3)

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700;800;900&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:1080px; height:{height}px; background:#080c10; font-family:'Inter', sans-serif; position:relative; }}
body::before {{
  content:''; position:absolute; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size:60px 60px;
}}
.accent-bar {{ height:3px; background:#00e87a; }}
.content {{ position:relative; z-index:10; padding:46px 48px 40px; }}
.brand {{ font-size:13px; font-weight:700; letter-spacing:0.25em; color:#c0d4e8; text-transform:uppercase; }}
.title {{ font-family:'Bebas Neue', sans-serif; font-size:72px; color:#fff; letter-spacing:0.04em; line-height:1; margin-top:6px; }}
.subtitle {{ font-size:16px; color:#8aaac0; margin-top:4px; letter-spacing:0.05em; }}

.headers {{
  display:grid; grid-template-columns: 280px 180px 180px 140px 80px;
  gap:14px; padding:14px 18px; margin-top:32px;
  border-bottom:2px solid #243040;
}}
.h-cell {{ font-size:11px; font-weight:800; letter-spacing:0.18em; color:#8aaac0; text-transform:uppercase; }}
.h-cell.right {{ text-align:right; }}

.section-label {{
  font-size:11px; font-weight:900; letter-spacing:0.25em;
  color:#8aaac0; text-transform:uppercase;
  margin-top:22px; margin-bottom:10px;
  padding-left:18px;
}}

.row {{
  display:grid; grid-template-columns: 280px 180px 180px 140px 80px;
  gap:14px; padding:14px 18px; margin-bottom:8px;
  background:#0e1419; border:1px solid #243040; border-radius:14px;
  align-items:center;
}}
.cell.algo {{ display:flex; flex-direction:column; gap:5px; }}
.algo-name {{ font-size:16px; font-weight:800; color:#fff; }}
.algo-meta {{ display:flex; gap:6px; }}
.pill {{ font-size:9px; font-weight:900; letter-spacing:0.12em; padding:2px 7px; border-radius:4px; text-transform:uppercase; }}
.s-live {{ background:#00e87a; color:#000; }}
.s-shadow {{ background:#243040; color:#c8ddf0; }}
.s-retired{{ background:#3a2030; color:#c8a0b0; }}
.p-tier {{ background:#1a2230; color:#8aaac0; font-family:'JetBrains Mono', monospace; }}

.cell.tf {{ display:flex; flex-direction:column; align-items:flex-end; }}
.cell.tf.low-n {{ opacity:0.45; }}
.rec  {{ font-family:'JetBrains Mono', monospace; font-size:18px; font-weight:700; color:#fff; }}
.roi  {{ font-family:'JetBrains Mono', monospace; font-size:13px; font-weight:700; margin-top:2px; }}
.prof {{ font-family:'JetBrains Mono', monospace; font-size:11px; color:#8aaac0; margin-top:2px; }}
.v-pos {{ color:#00e87a; }}
.v-neg {{ color:#ff4444; }}
.v-flat{{ color:#c8ddf0; }}
.v-empty{{ color:#4a5868; }}

.cell.trend {{ display:flex; justify-content:center; align-items:center; }}
.trend-arrow {{ font-size:28px; font-weight:900; }}
.t-up   {{ color:#00e87a; }}
.t-down {{ color:#ff4444; }}
.t-flat {{ color:#4a5868; }}

.footer {{ margin-top:32px; padding-top:18px; border-top:1px solid #1a2230; display:flex; justify-content:space-between; align-items:center; }}
.f-legend {{ font-size:11px; color:#8aaac0; letter-spacing:0.06em; }}
.f-brand  {{ font-size:11px; font-weight:800; color:#a0bcd4; letter-spacing:0.15em; }}
</style>
</head><body>
<div class="accent-bar"></div>
<div class="content">
  <div class="brand">Overlay &nbsp;·&nbsp; Algo Stockboard</div>
  <div class="title">Algorithm Health</div>
  <div class="subtitle">{today.strftime('%B %d, %Y')} &nbsp;·&nbsp; {len(rows)} models tracked</div>

  <div class="headers">
    <div class="h-cell">Algorithm</div>
    <div class="h-cell right">Lifetime</div>
    <div class="h-cell right">Last 30d</div>
    <div class="h-cell right">Last 7d</div>
    <div class="h-cell" style="text-align:center;">Trend</div>
  </div>

  {rows_html}

  <div class="footer">
    <div class="f-legend">Trend compares 30d ROI vs lifetime · Greyed rows have low sample size</div>
    <div class="f-brand">OVERLAY-GRAY.VERCEL.APP</div>
  </div>
</div></body></html>"""

    out = out_path or (OUT_DIR / today.strftime("%Y%m%d") / "stockboard.png")
    return _render_html(html, out, width=1080, height=height)


# ── Per-algo drilldown ───────────────────────────────────────────────────────

def render_algo_detail_card(row: dict, out_path: Path | None = None) -> Optional[Path]:
    today = date.today()
    algo_name = f"{_sport_label(row['sport'])} {_market_label(row['market'])}"
    status_label = {"live":"LIVE","incubating":"SHADOW","retired":"RETIRED"}.get(row["status"], row["status"].upper())
    status_class = {"live":"s-live","incubating":"s-shadow","retired":"s-retired"}.get(row["status"], "s-shadow")

    life = row["lifetime"]
    d30  = row["d30"]
    d7   = row["d7"]

    # Hero color: green if profitable lifetime, red if not, blue if zero-volume
    if life["n"] == 0:    hero_col = "#8aaac0"
    elif life["roi"] > 0: hero_col = "#00e87a"
    else:                  hero_col = "#ff4444"

    def _block(title: str, s: dict, min_n: int):
        muted = "muted" if s["n"] < min_n else ""
        wr = f"{s['wr']*100:.1f}%" if s["n"] else "—"
        roi = _fmt_roi(s)
        roi_col = "#00e87a" if s["roi"] > 0.02 else ("#ff4444" if s["roi"] < -0.02 else "#c8ddf0")
        return f"""
        <div class="stat-block {muted}">
          <div class="b-label">{title}</div>
          <div class="b-record">{_fmt_record(s)}</div>
          <div class="b-row">
            <div><span class="b-key">WR</span> <span class="b-val">{wr}</span></div>
            <div><span class="b-key">ROI</span> <span class="b-val" style="color:{roi_col}">{roi}</span></div>
            <div><span class="b-key">P/L</span> <span class="b-val">{_fmt_profit(s)}</span></div>
            <div><span class="b-key">N</span> <span class="b-val">{s['n']}</span></div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700;800;900&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:1080px; height:1080px; background:#080c10; font-family:'Inter', sans-serif; position:relative; }}
body::before {{
  content:''; position:absolute; inset:0;
  background-image:
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size:60px 60px;
}}
.accent-bar {{ height:3px; background:{hero_col}; }}
.content {{ position:relative; z-index:10; padding:50px 60px; height:calc(1080px - 3px); display:flex; flex-direction:column; }}
.brand {{ font-size:13px; font-weight:700; letter-spacing:0.25em; color:#c0d4e8; text-transform:uppercase; }}
.title-row {{ display:flex; align-items:center; gap:18px; margin-top:8px; }}
.title {{ font-family:'Bebas Neue', sans-serif; font-size:84px; color:#fff; letter-spacing:0.04em; line-height:1; }}
.status-pill {{ font-size:13px; font-weight:900; letter-spacing:0.18em; padding:6px 14px; border-radius:6px; text-transform:uppercase; }}
.s-live {{ background:#00e87a; color:#000; }}
.s-shadow {{ background:#243040; color:#c8ddf0; }}
.s-retired {{ background:#3a2030; color:#c8a0b0; }}
.subtitle {{ font-size:16px; color:#8aaac0; margin-top:6px; letter-spacing:0.05em; }}

.hero {{
  background:#0e1419; border:1px solid #243040; border-radius:20px;
  padding:32px; margin-top:32px;
  display:flex; flex-direction:column; align-items:center;
}}
.hero-label {{ font-size:13px; font-weight:800; letter-spacing:0.2em; color:#b0c8e0; text-transform:uppercase; }}
.hero-val   {{ font-family:'Bebas Neue', sans-serif; font-size:108px; color:{hero_col}; line-height:1; margin-top:6px; }}
.hero-sub   {{ font-size:16px; color:#8aaac0; margin-top:6px; }}

.stat-grid {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; margin-top:30px; }}
.stat-block {{ background:#0e1419; border:1px solid #243040; border-radius:14px; padding:20px; }}
.stat-block.muted {{ opacity:0.45; }}
.b-label {{ font-size:11px; font-weight:800; letter-spacing:0.18em; color:#8aaac0; text-transform:uppercase; }}
.b-record {{ font-family:'Bebas Neue', sans-serif; font-size:54px; color:#fff; line-height:1; margin-top:6px; }}
.b-row {{ display:grid; grid-template-columns:1fr 1fr; gap:10px 16px; margin-top:14px; }}
.b-key {{ font-size:11px; font-weight:700; letter-spacing:0.12em; color:#8aaac0; text-transform:uppercase; margin-right:4px; }}
.b-val {{ font-family:'JetBrains Mono', monospace; font-size:14px; font-weight:700; color:#fff; }}

.footer {{ margin-top:auto; padding-top:20px; border-top:1px solid #1a2230; display:flex; justify-content:space-between; align-items:center; }}
.f-stat {{ display:flex; flex-direction:column; }}
.f-label {{ font-size:11px; font-weight:700; letter-spacing:0.18em; color:#b0c8e0; text-transform:uppercase; }}
.f-val {{ font-size:18px; font-weight:900; color:#fff; margin-top:3px; }}
.f-brand {{ font-size:11px; font-weight:800; color:#a0bcd4; letter-spacing:0.15em; }}
</style>
</head><body>
<div class="accent-bar"></div>
<div class="content">
  <div class="brand">Overlay &nbsp;·&nbsp; Algorithm Detail</div>
  <div class="title-row">
    <div class="title">{algo_name}</div>
    <div class="status-pill {status_class}">{status_label}</div>
  </div>
  <div class="subtitle">Tier {row['tier'].upper()} &nbsp;·&nbsp; {today.strftime('%B %d, %Y')}</div>

  <div class="hero">
    <div class="hero-label">Lifetime ROI</div>
    <div class="hero-val">{_fmt_roi(life)}</div>
    <div class="hero-sub">{life['w']}W – {life['l']}L &nbsp;·&nbsp; {life['profit']:+.2f}u &nbsp;·&nbsp; {life['n']} settled</div>
  </div>

  <div class="stat-grid">
    {_block("Lifetime", life, 20)}
    {_block("Last 30d", d30, 10)}
    {_block("Last 7d", d7, 3)}
  </div>

  <div class="footer">
    <div class="f-stat">
      <div class="f-label">Trend</div>
      <div class="f-val">{row['trend'].upper()}</div>
    </div>
    <div class="f-stat">
      <div class="f-label">Last 30d Volume</div>
      <div class="f-val">{d30['n']} bets</div>
    </div>
    <div class="f-brand">OVERLAY-GRAY.VERCEL.APP</div>
  </div>
</div></body></html>"""

    safe = f"{row['sport']}_{row['market']}".replace("/", "_")
    out = out_path or (OUT_DIR / today.strftime("%Y%m%d") / "detail" / f"{safe}.png")
    return _render_html(html, out, width=1080, height=1080)


def render_all_detail_cards(rows: list[dict] | None = None) -> list[Path]:
    if rows is None:
        rows = compute_algo_grid()
    out_paths = []
    for r in rows:
        # Skip algos with too little data for a meaningful detail card
        if r["lifetime"]["n"] < 5:
            continue
        path = render_algo_detail_card(r)
        if path:
            out_paths.append(path)
    return out_paths


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    rows = compute_algo_grid()
    print(f"Computed {len(rows)} algo rows")
    p = render_stockboard_card(rows)
    if p: print(f"Stockboard → {p}")
    details = render_all_detail_cards(rows)
    print(f"Generated {len(details)} drilldown cards")
