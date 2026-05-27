#!/usr/bin/env python3
"""
scripts/nightly_recap.py — Nightly recap card generator

Generates end-of-night recap card covering ALL sports:
  - Daily W-L record + P/L
  - Pick of the Day (POTD) hero highlight
  - Row-by-row results for every card pick
  - Suitable for Instagram Stories (1080×1920) or Square (1080×1080)

Output:
    output/recap/{date}/recap_card.png
    output/recap/{date}/recap_card.html
    output/recap/{date}/potd.json      ← pick of the day metadata

Usage:
    python3 scripts/nightly_recap.py                   # tonight
    python3 scripts/nightly_recap.py --date 20260526   # specific date
    python3 scripts/nightly_recap.py --date 20260526 --deploy  # + push to Vercel

Cron (11:50 PM ET = 03:50 UTC):
    50 3 * * * cd /path && python3 scripts/nightly_recap.py --deploy >> logs/recap.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
RECAP_DIR  = ROOT / "output" / "recap"
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_card_picks(date_str: str) -> list[dict]:
    pnl = ROOT / "data" / "pnl" / "picks.json"
    if not pnl.exists():
        return []
    raw = json.loads(pnl.read_text())
    picks = raw if isinstance(raw, list) else raw.get("picks", [])
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return [p for p in picks if p.get("card_pick") and
            str(p.get("date", "")).startswith(date_fmt)]


def identify_potd(picks: list[dict]) -> dict | None:
    """
    Pick of the Day = best graded win by profit.
    If no wins yet, best pending by edge.
    """
    wins = [p for p in picks if str(p.get("result", "")).lower() == "win"]
    if wins:
        return max(wins, key=lambda p: p.get("profit", 0) or 0)
    pending = [p for p in picks if not p.get("result")]
    if pending:
        return max(pending, key=lambda p: p.get("edge_pct", 0) or 0)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# HTML card builder
# ─────────────────────────────────────────────────────────────────────────────

SPORT_EMOJI = {
    "mlb":                         "⚾",
    "baseball_mlb":                "⚾",
    "nba":                         "🏀",
    "basketball_nba":              "🏀",
    "nhl":                         "🏒",
    "icehockey_nhl":               "🏒",
    "wnba":                        "🏀",
    "basketball_wnba":             "🏀",
    "tennis":                      "🎾",
    "tennis_atp_french_open":      "🎾",
    "soccer":                      "⚽",
    "soccer_france_ligue_one":     "⚽",
    "soccer_conmebol_copa_libertadores": "⚽",
    "pga":                         "⛳",
    "ufc":                         "🥊",
    "nascar":                      "🏁",
}


def sport_emoji(sport: str) -> str:
    return SPORT_EMOJI.get(sport.lower(), "🎯")


def fmt_odds(odds) -> str:
    try:
        o = int(odds)
        return f"+{o}" if o > 0 else str(o)
    except Exception:
        return str(odds)


def fmt_pl(profit) -> str:
    if profit is None:
        return "—"
    return f"+{profit:.2f}u" if profit >= 0 else f"{profit:.2f}u"


def result_class(result) -> str:
    r = str(result or "").lower()
    if r == "win":   return "win"
    if r == "loss":  return "loss"
    if r == "push":  return "push"
    return "pending"


def result_label(result) -> str:
    r = str(result or "").lower()
    if r == "win":   return "WIN ✓"
    if r == "loss":  return "LOSS ✗"
    if r == "push":  return "PUSH"
    return "LIVE"


def build_html(date_str: str, picks: list[dict], potd: dict | None) -> str:
    date_disp = datetime.strptime(date_str, "%Y%m%d").strftime("%B %d, %Y")

    # Summary stats
    wins     = sum(1 for p in picks if str(p.get("result","")).lower() == "win")
    losses   = sum(1 for p in picks if str(p.get("result","")).lower() == "loss")
    pending  = sum(1 for p in picks if not p.get("result"))
    total_pl = sum(p.get("profit", 0) or 0 for p in picks)
    pl_color = "#00e676" if total_pl >= 0 else "#ff5252"
    pl_str   = f"+{total_pl:.2f}u" if total_pl >= 0 else f"{total_pl:.2f}u"

    # Group by sport
    from collections import defaultdict
    by_sport: dict[str, list[dict]] = defaultdict(list)
    for p in sorted(picks, key=lambda x: (x.get("sport",""), -(x.get("edge_pct") or 0))):
        by_sport[p.get("sport", "unknown")].append(p)

    # POTD section
    potd_html = ""
    if potd:
        potd_odds   = fmt_odds(potd.get("odds", 0))
        potd_result = result_label(potd.get("result"))
        potd_pl     = fmt_pl(potd.get("profit"))
        potd_res_cls = result_class(potd.get("result"))
        potd_sport_emoji = sport_emoji(potd.get("sport",""))
        potd_edge = potd.get("edge_pct", 0)
        potd_team = potd.get("team", "")
        potd_matchup = potd.get("matchup", "")
        potd_market  = potd.get("market", "").replace("_", " ").upper()

        potd_html = f"""
        <div class="potd-section">
          <div class="potd-label">⭐ PICK OF THE DAY</div>
          <div class="potd-sport">{potd_sport_emoji} {potd.get('sport','').upper()[:3]} · {potd_market}</div>
          <div class="potd-team">{potd_team}</div>
          <div class="potd-matchup">{potd_matchup}</div>
          <div class="potd-row">
            <span class="potd-odds">{potd_odds}</span>
            <span class="potd-edge">Edge {potd_edge:.1f}%</span>
            <span class="potd-result {potd_res_cls}-badge">{potd_result}</span>
            <span class="potd-pl" style="color:{pl_color}">{potd_pl}</span>
          </div>
        </div>"""

    # Picks rows by sport
    rows_html = ""
    for sport, sport_picks in by_sport.items():
        emoji = sport_emoji(sport)
        sport_label = sport.upper().replace("BASEBALL_MLB","MLB").replace(
            "BASKETBALL_NBA","NBA").replace("ICEHOCKEY_NHL","NHL").replace(
            "BASKETBALL_WNBA","WNBA").replace("TENNIS_ATP_FRENCH_OPEN","TENNIS")[:10]
        sw = sum(1 for p in sport_picks if str(p.get("result","")).lower()=="win")
        sl = sum(1 for p in sport_picks if str(p.get("result","")).lower()=="loss")
        spl = sum(p.get("profit",0) or 0 for p in sport_picks)

        rows_html += f"""
        <div class="sport-group">
          <div class="sport-header">
            <span class="sport-name">{emoji} {sport_label}</span>
            <span class="sport-record">{sw}-{sl}</span>
            <span class="sport-pl" style="color:{'#00e676' if spl>=0 else '#ff5252'}">{fmt_pl(spl)}</span>
          </div>"""

        for p in sport_picks:
            team    = p.get("team", "")[:30]
            market  = p.get("market","").replace("_"," ").upper()[:10]
            odds    = fmt_odds(p.get("odds", 0))
            edge    = p.get("edge_pct", 0)
            res     = result_label(p.get("result"))
            res_cls = result_class(p.get("result"))
            pl      = fmt_pl(p.get("profit"))
            book    = (p.get("sportsbook","") or "")[:10]

            rows_html += f"""
          <div class="pick-row {res_cls}">
            <div class="pick-info">
              <span class="pick-market">{market}</span>
              <span class="pick-team">{team}</span>
              <span class="pick-odds">{odds}</span>
            </div>
            <div class="pick-meta">
              <span class="pick-edge">e{edge:.0f}%</span>
              <span class="pick-book">{book}</span>
              <span class="pick-result {res_cls}-badge">{res}</span>
              <span class="pick-pl">{pl}</span>
            </div>
          </div>"""
        rows_html += "</div>"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Inter', -apple-system, sans-serif;
    background: #0a0a0f;
    color: #e8e8f0;
    width: 1080px;
    min-height: 1920px;
    padding: 60px 50px;
  }}

  /* Header */
  .header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 40px;
    border-bottom: 2px solid #1e1e2e;
    padding-bottom: 30px;
  }}
  .brand {{ font-size: 28px; font-weight: 900; color: #a78bfa; letter-spacing: -0.5px; }}
  .brand-sub {{ font-size: 15px; color: #6b6b8a; margin-top: 4px; }}
  .date-badge {{
    background: #1e1e2e; border: 1px solid #2e2e4e;
    padding: 10px 20px; border-radius: 12px;
    font-size: 17px; font-weight: 700; color: #c4b5fd;
  }}

  /* Summary bar */
  .summary {{
    display: grid; grid-template-columns: 1fr 1fr 1fr 1fr;
    gap: 16px; margin-bottom: 40px;
  }}
  .stat-box {{
    background: #111120; border: 1px solid #1e1e3a;
    border-radius: 16px; padding: 20px 16px; text-align: center;
  }}
  .stat-val {{ font-size: 36px; font-weight: 900; line-height: 1; }}
  .stat-lbl {{ font-size: 13px; color: #6b6b8a; margin-top: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}

  /* POTD */
  .potd-section {{
    background: linear-gradient(135deg, #1a1040 0%, #0f0f2a 100%);
    border: 2px solid #7c3aed;
    border-radius: 20px; padding: 28px 30px; margin-bottom: 36px;
    box-shadow: 0 0 40px rgba(124,58,237,0.15);
  }}
  .potd-label {{
    font-size: 13px; font-weight: 800; color: #a78bfa;
    text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 10px;
  }}
  .potd-sport {{ font-size: 14px; color: #6b6b8a; margin-bottom: 6px; font-weight: 600; }}
  .potd-team {{ font-size: 34px; font-weight: 900; color: #ffffff; margin-bottom: 4px; line-height: 1.1; }}
  .potd-matchup {{ font-size: 15px; color: #8b8baa; margin-bottom: 16px; }}
  .potd-row {{ display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }}
  .potd-odds {{ font-size: 24px; font-weight: 800; color: #c4b5fd; }}
  .potd-edge {{ font-size: 15px; color: #8b8baa; background: #1e1e3a; padding: 5px 12px; border-radius: 8px; }}
  .potd-pl {{ font-size: 20px; font-weight: 800; }}

  /* Sport groups */
  .sport-group {{ margin-bottom: 28px; }}
  .sport-header {{
    display: flex; align-items: center; gap: 12px;
    padding: 10px 16px; background: #111120;
    border-radius: 10px; margin-bottom: 8px;
    border-left: 3px solid #7c3aed;
  }}
  .sport-name {{ font-size: 15px; font-weight: 800; color: #c4b5fd; flex: 1; }}
  .sport-record {{ font-size: 14px; color: #8b8baa; font-weight: 700; }}
  .sport-pl {{ font-size: 14px; font-weight: 700; }}

  /* Pick rows */
  .pick-row {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 16px; margin-bottom: 6px;
    border-radius: 10px; border-left: 3px solid transparent;
    background: #0e0e1c;
  }}
  .pick-row.win   {{ border-left-color: #00e676; background: #0a1a12; }}
  .pick-row.loss  {{ border-left-color: #ff5252; background: #1a0a0a; }}
  .pick-row.push  {{ border-left-color: #ffd740; background: #1a1a0a; }}
  .pick-row.pending {{ border-left-color: #448aff; background: #0a0e1a; }}

  .pick-info {{ display: flex; align-items: center; gap: 10px; }}
  .pick-market {{ font-size: 11px; color: #6b6b8a; font-weight: 700; text-transform: uppercase;
                  background: #1a1a2e; padding: 3px 8px; border-radius: 5px; min-width: 60px; text-align: center; }}
  .pick-team  {{ font-size: 16px; font-weight: 700; color: #e8e8f0; max-width: 320px; }}
  .pick-odds  {{ font-size: 15px; font-weight: 800; color: #a78bfa; }}

  .pick-meta  {{ display: flex; align-items: center; gap: 10px; }}
  .pick-edge  {{ font-size: 12px; color: #6b6b8a; }}
  .pick-book  {{ font-size: 12px; color: #4b4b6a; }}
  .pick-pl    {{ font-size: 15px; font-weight: 700; min-width: 70px; text-align: right; color: #8b8baa; }}
  .win .pick-pl  {{ color: #00e676; }}
  .loss .pick-pl {{ color: #ff5252; }}

  /* Result badges */
  .win-badge     {{ background: #00e676; color: #000; font-size: 11px; font-weight: 800;
                    padding: 3px 10px; border-radius: 6px; text-transform: uppercase; }}
  .loss-badge    {{ background: #ff5252; color: #fff; font-size: 11px; font-weight: 800;
                    padding: 3px 10px; border-radius: 6px; text-transform: uppercase; }}
  .push-badge    {{ background: #ffd740; color: #000; font-size: 11px; font-weight: 800;
                    padding: 3px 10px; border-radius: 6px; text-transform: uppercase; }}
  .pending-badge {{ background: #448aff; color: #fff; font-size: 11px; font-weight: 700;
                    padding: 3px 10px; border-radius: 6px; text-transform: uppercase; }}

  /* Footer */
  .footer {{
    margin-top: 40px; padding-top: 24px;
    border-top: 1px solid #1e1e2e;
    text-align: center; color: #3b3b5a; font-size: 13px;
  }}
</style>
</head>
<body>

  <!-- Header -->
  <div class="header">
    <div>
      <div class="brand">ChefTonyBets</div>
      <div class="brand-sub">ML-Powered Edge Detection</div>
    </div>
    <div class="date-badge">{date_disp}</div>
  </div>

  <!-- Summary -->
  <div class="summary">
    <div class="stat-box">
      <div class="stat-val" style="color:#00e676">{wins}</div>
      <div class="stat-lbl">Wins</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#ff5252">{losses}</div>
      <div class="stat-lbl">Losses</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:{pl_color}">{pl_str}</div>
      <div class="stat-lbl">P/L</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#448aff">{pending}</div>
      <div class="stat-lbl">Pending</div>
    </div>
  </div>

  <!-- Pick of the Day -->
  {potd_html}

  <!-- All picks by sport -->
  {rows_html}

  <div class="footer">
    ChefTonyBets · AI-powered sports betting edges · Not financial advice
  </div>

</body>
</html>"""
    return html


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────

def run(date_str: str, deploy: bool = False) -> Path | None:
    print(f"\n  ── Nightly Recap Card — {date_str} ─────────────────────────")

    picks = load_card_picks(date_str)
    if not picks:
        print(f"  ⚠  No card picks for {date_str}")
        return None

    wins    = sum(1 for p in picks if str(p.get("result","")).lower() == "win")
    losses  = sum(1 for p in picks if str(p.get("result","")).lower() == "loss")
    pending = sum(1 for p in picks if not p.get("result"))
    pl      = sum(p.get("profit",0) or 0 for p in picks)
    print(f"  {len(picks)} card picks — {wins}W {losses}L {pending} pending — {pl:+.2f}u")

    # Identify POTD
    potd = identify_potd(picks)
    if potd:
        print(f"  ⭐ POTD: {potd.get('team','')} ({fmt_odds(potd.get('odds',0))}) — {result_label(potd.get('result'))}")

    # Save POTD metadata
    out_dir = RECAP_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    if potd:
        (out_dir / "potd.json").write_text(json.dumps(potd, indent=2))

    # Build HTML
    html = build_html(date_str, picks, potd)
    html_path = out_dir / "recap_card.html"
    html_path.write_text(html)
    print(f"  ✓ HTML → {html_path}")

    # Screenshot with Playwright
    png_path = out_dir / "recap_card.png"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page    = browser.new_page(viewport={"width": 1080, "height": 1920})
            page.goto(f"file://{html_path.resolve()}", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(png_path), full_page=True)
            browser.close()
        print(f"  ✓ PNG  → {png_path}  ({wins}W-{losses}L {pl:+.2f}u)")
    except Exception as e:
        print(f"  ⚠  Playwright unavailable ({e}) — use HTML version")
        png_path = html_path

    # Deploy if requested
    if deploy:
        print("\n  ▸ Deploying to Vercel...")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "deploy_picks.py"),
             "--date", date_str, "--message", f"recap: {date_str}"],
            cwd=str(ROOT)
        )

    return png_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate nightly recap card")
    parser.add_argument("--date",   default=date.today().strftime("%Y%m%d"), metavar="YYYYMMDD")
    parser.add_argument("--deploy", action="store_true", help="Also push to Vercel after generating")
    args = parser.parse_args()
    result = run(args.date, deploy=args.deploy)
    if result:
        print(f"\n  📲 Post this to IG / X: {result}\n")


if __name__ == "__main__":
    main()
