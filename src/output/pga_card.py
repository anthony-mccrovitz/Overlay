"""
PGA Championship card renderer — two cards:
  1. Single pick card: Scheffler +560 (E3 design adapted for golf)
  2. Field preview: top 10 players model vs market table
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

OUTPUT_DIR = Path("output/picks/golf_pga")


def _playwright_render(html: str, html_path: Path, png_path: Path, width: int = 1080) -> Path:
    html_path.write_text(html, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1920})
        page.goto(f"file://{html_path.resolve()}", wait_until="networkidle")
        card = page.query_selector("#card")
        if card:
            card.screenshot(path=str(png_path), type="png")
        else:
            page.screenshot(path=str(png_path), full_page=True)
        browser.close()
    return png_path


# ── Pick card (Scheffler outright) ────────────────────────────────────────────

def _pick_card_html(pick: dict) -> str:
    player = pick["player"]
    odds_str = f"+{pick['best_odds']}"
    model_pct = f"{pick['model_win']:.1f}%"
    edge_pct  = f"+{pick['edge_pct']:.1f}%"
    top5      = f"{pick['top5_prob']:.0f}%"
    top10     = f"{pick['top10_prob']:.0f}%"
    top20     = f"{pick['top20_prob']:.0f}%"
    book      = pick.get("best_book", "").replace("_", " ").upper()
    mkt_pct   = f"{pick['market_impl']:.1f}%"

    MUT    = "rgba(255,255,255,0.65)"
    BORDER = "rgba(255,255,255,0.09)"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#000; font-family:'Inter',sans-serif; display:flex; justify-content:center; padding:40px 0; }}
#card {{
  width: 1000px;
  background: linear-gradient(145deg, #0d1117 0%, #0a0f1a 50%, #060b12 100%);
  border-radius: 24px;
  overflow: hidden;
  border: 1px solid {BORDER};
  position: relative;
}}
.rainbow-bar {{
  height: 5px;
  background: linear-gradient(90deg, #ff6b6b, #ffd93d, #6bcb77, #4d96ff, #c77dff);
}}
.header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 28px 40px 20px;
  border-bottom: 1px solid {BORDER};
}}
.brand {{ font-size: 13px; font-weight: 700; letter-spacing: 0.18em; color: {MUT}; text-transform: uppercase; }}
.event-badge {{
  background: rgba(255,255,255,0.06);
  border: 1px solid {BORDER};
  border-radius: 20px;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  color: {MUT};
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.main {{
  padding: 36px 40px 32px;
}}
.top-play-badge {{
  display: inline-block;
  background: linear-gradient(90deg, #f5a623, #e8870e);
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
  color: #000;
  text-transform: uppercase;
  margin-bottom: 20px;
}}
.player-name {{
  font-size: 64px;
  font-weight: 900;
  color: #fff;
  line-height: 1.0;
  letter-spacing: -0.02em;
  margin-bottom: 6px;
}}
.market-label {{
  font-size: 16px;
  font-weight: 600;
  color: {MUT};
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 28px;
}}
.odds-row {{
  display: flex;
  align-items: baseline;
  gap: 20px;
  margin-bottom: 32px;
}}
.odds-val {{
  font-size: 80px;
  font-weight: 900;
  letter-spacing: -0.03em;
  background: linear-gradient(90deg, #00e5a0, #00cfff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  line-height: 1.0;
}}
.book-badge {{
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  align-self: center;
}}
.data-strip {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 1px;
  background: {BORDER};
  border: 1px solid {BORDER};
  border-radius: 14px;
  overflow: hidden;
  margin-bottom: 28px;
}}
.data-cell {{
  background: rgba(255,255,255,0.03);
  padding: 18px 24px;
  text-align: center;
}}
.data-label {{
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.15em;
  color: {MUT};
  text-transform: uppercase;
  margin-bottom: 8px;
}}
.data-val {{
  font-size: 28px;
  font-weight: 800;
  color: #fff;
  letter-spacing: -0.01em;
}}
.data-val.edge {{
  background: linear-gradient(90deg, #00e5a0, #00cfff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}}
.finish-strip {{
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
  margin-bottom: 32px;
}}
.finish-cell {{
  background: rgba(255,255,255,0.03);
  border: 1px solid {BORDER};
  border-radius: 12px;
  padding: 16px;
  text-align: center;
}}
.finish-label {{
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: {MUT};
  text-transform: uppercase;
  margin-bottom: 6px;
}}
.finish-val {{
  font-size: 24px;
  font-weight: 800;
  color: #fff;
}}
.footer {{
  padding: 20px 40px;
  border-top: 1px solid {BORDER};
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
.footer-note {{
  font-size: 11px;
  color: rgba(255,255,255,0.3);
  letter-spacing: 0.06em;
}}
.course-info {{
  font-size: 11px;
  color: rgba(255,255,255,0.3);
  letter-spacing: 0.06em;
  text-align: right;
}}
</style>
</head>
<body>
<div id="card">
  <div class="rainbow-bar"></div>

  <div class="header">
    <div class="brand">⛳ Overlay AI</div>
    <div class="event-badge">PGA Championship 2026</div>
  </div>

  <div class="main">
    <div class="top-play-badge">⭐ TOP PLAY</div>
    <div class="player-name">{player}</div>
    <div class="market-label">Tournament Winner · Outright</div>

    <div class="odds-row">
      <div class="odds-val">{odds_str}</div>
      <div class="book-badge">{book}</div>
    </div>

    <div class="data-strip">
      <div class="data-cell">
        <div class="data-label">Model Win %</div>
        <div class="data-val">{model_pct}</div>
      </div>
      <div class="data-cell">
        <div class="data-label">AI Edge</div>
        <div class="data-val edge">{edge_pct}</div>
      </div>
      <div class="data-cell">
        <div class="data-label">Market Implies</div>
        <div class="data-val">{mkt_pct}</div>
      </div>
    </div>

    <div class="finish-strip">
      <div class="finish-cell">
        <div class="finish-label">Top 5 Prob</div>
        <div class="finish-val">{top5}</div>
      </div>
      <div class="finish-cell">
        <div class="finish-label">Top 10 Prob</div>
        <div class="finish-val">{top10}</div>
      </div>
      <div class="finish-cell">
        <div class="finish-label">Top 20 Prob</div>
        <div class="finish-val">{top20}</div>
      </div>
    </div>
  </div>

  <div class="footer">
    <div class="footer-note">150,000 Monte Carlo simulations · Course-fit adjusted SG model</div>
    <div class="course-info">Quail Hollow · May 14–17, 2026</div>
  </div>
</div>
</body>
</html>"""


# ── Field preview card (top 10 model vs market) ───────────────────────────────

def _field_preview_html(players: list[dict]) -> str:
    MUT    = "rgba(255,255,255,0.65)"
    BORDER = "rgba(255,255,255,0.09)"
    top10  = players[:10]

    rows = ""
    for i, p in enumerate(top10):
        rank       = i + 1
        name       = p["player"]
        odds_str   = f"+{p['best_odds']}"
        model_pct  = f"{p['model_win']:.1f}%"
        top10_prob = f"{p['top10_prob']:.0f}%"
        edge       = p["edge_pct"]
        edge_str   = f"+{edge:.1f}%" if edge > 0 else f"{edge:.1f}%"
        edge_color = "#00e5a0" if edge >= 2.0 else ("#ffd93d" if edge > 0 else "#ff6b6b")
        bg         = "rgba(255,255,255,0.04)" if i % 2 == 0 else "rgba(255,255,255,0.015)"
        rank_color = "#f5a623" if rank == 1 else MUT

        rows += f"""
        <tr style="background:{bg}">
          <td style="padding:14px 16px; font-size:13px; font-weight:700; color:{rank_color}; width:40px; text-align:center;">#{rank}</td>
          <td style="padding:14px 16px; font-size:15px; font-weight:700; color:#fff;">{name}</td>
          <td style="padding:14px 16px; font-size:15px; font-weight:800; color:#fff; text-align:right;">{odds_str}</td>
          <td style="padding:14px 16px; font-size:15px; font-weight:700; color:#fff; text-align:right;">{model_pct}</td>
          <td style="padding:14px 16px; font-size:14px; font-weight:700; color:{MUT}; text-align:right;">{top10_prob}</td>
          <td style="padding:14px 20px; font-size:14px; font-weight:800; color:{edge_color}; text-align:right;">{edge_str}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#000; font-family:'Inter',sans-serif; display:flex; justify-content:center; padding:40px 0; }}
#card {{
  width: 1000px;
  background: linear-gradient(145deg, #0d1117 0%, #0a0f1a 50%, #060b12 100%);
  border-radius: 24px;
  overflow: hidden;
  border: 1px solid {BORDER};
}}
.rainbow-bar {{
  height: 5px;
  background: linear-gradient(90deg, #ff6b6b, #ffd93d, #6bcb77, #4d96ff, #c77dff);
}}
.header {{
  padding: 28px 40px 22px;
  border-bottom: 1px solid {BORDER};
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
}}
.title-block {{ }}
.brand {{ font-size: 13px; font-weight: 700; letter-spacing: 0.18em; color: {MUT}; text-transform: uppercase; margin-bottom: 8px; }}
.title {{ font-size: 32px; font-weight: 900; color: #fff; letter-spacing: -0.02em; line-height: 1.0; }}
.subtitle {{ font-size: 14px; color: {MUT}; font-weight: 500; margin-top: 4px; }}
.event-badge {{
  background: rgba(255,255,255,0.06);
  border: 1px solid {BORDER};
  border-radius: 20px;
  padding: 8px 18px;
  font-size: 12px;
  font-weight: 600;
  color: {MUT};
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
table {{
  width: 100%;
  border-collapse: collapse;
}}
.col-header {{
  padding: 12px 16px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: {MUT};
  text-transform: uppercase;
  border-bottom: 1px solid {BORDER};
  text-align: right;
}}
.col-header.left {{ text-align: left; }}
.footer {{
  padding: 18px 40px;
  border-top: 1px solid {BORDER};
  display: flex;
  justify-content: space-between;
}}
.footer-note {{ font-size: 11px; color: rgba(255,255,255,0.3); letter-spacing: 0.06em; }}
</style>
</head>
<body>
<div id="card">
  <div class="rainbow-bar"></div>
  <div class="header">
    <div class="title-block">
      <div class="brand">⛳ Overlay AI · Field Preview</div>
      <div class="title">PGA Championship 2026</div>
      <div class="subtitle">Model Win% vs Market · 150k Monte Carlo simulations</div>
    </div>
    <div class="event-badge">Quail Hollow · May 14–17</div>
  </div>

  <table>
    <thead>
      <tr style="background:rgba(255,255,255,0.02)">
        <th class="col-header left" style="width:40px; text-align:center;">#</th>
        <th class="col-header left">Player</th>
        <th class="col-header">Best Odds</th>
        <th class="col-header">Model Win%</th>
        <th class="col-header">Top 10%</th>
        <th class="col-header" style="padding-right:20px">AI Edge</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>

  <div class="footer">
    <div class="footer-note">Course-fit adjusted SG model · Quail Hollow weights: SG App 40%, OTT 25%, Putt 25%</div>
    <div class="footer-note">@Overlay</div>
  </div>
</div>
</body>
</html>"""


def render_pga_cards(picks: list[dict], d: date | None = None) -> dict[str, Path]:
    d = d or date.today()
    out_dir = OUTPUT_DIR / d.strftime("%Y%m%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # Card 1: Scheffler pick card
    scheffler = next((p for p in picks if p["player"] == "Scottie Scheffler"), None)
    if scheffler:
        html = _pick_card_html(scheffler)
        png  = _playwright_render(html, out_dir / "scheffler_pick.html", out_dir / "scheffler_pick.png")
        results["pick"] = png
        print(f"  Pick card → {png}")

    # Card 2: Field preview — top 10 by model win% among named players
    from src.models.pga_championship import PLAYER_DB
    modelled = [p for p in picks if p["player"] in PLAYER_DB]
    modelled.sort(key=lambda x: x["model_win"], reverse=True)
    html = _field_preview_html(modelled)
    png  = _playwright_render(html, out_dir / "field_preview.html", out_dir / "field_preview.png")
    results["preview"] = png
    print(f"  Field preview → {png}")

    return results


if __name__ == "__main__":
    from src.models.pga_championship import run_pga_model
    print("Running model (150k sims)...")
    picks = run_pga_model(n_sim=150_000)
    print("Rendering cards...")
    paths = render_pga_cards(picks)
    print("\nDone.")
    for k, p in paths.items():
        print(f"  {k}: {p}")
