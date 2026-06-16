"""
Minimal "calibration card" — replaces the busy Bloomberg-style game cards for
social-feed deployment. One pick, one number, one fact per line.

Visual goal: thumb-stops on FYP/IG. Not a data dashboard.
"""
from __future__ import annotations

from datetime import date as _date
from pathlib import Path

from src.output.card_html import _playwright_render


_OUTPUT_DIR = Path("output/picks")


_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #06080f;
  font-family: 'Inter', -apple-system, sans-serif;
  color: #ffffff;
}
.card-wrap {
  width: 1080px;
  min-height: 1080px;
  padding: 96px 80px;
  background: linear-gradient(180deg, #06080f 0%, #0c121f 100%);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.top { display: flex; flex-direction: column; gap: 16px; }
.label-sport {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.4em;
  color: #6480ff;
  text-transform: uppercase;
}
.label-when {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.3em;
  color: rgba(255,255,255,0.4);
  text-transform: uppercase;
}

.pick-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 28px;
  padding: 40px 0;
}
.pick-main {
  font-size: 128px;
  font-weight: 900;
  letter-spacing: -0.04em;
  line-height: 1;
  color: #ffffff;
}
.pick-teams {
  font-size: 36px;
  font-weight: 600;
  color: rgba(255,255,255,0.7);
}

.stats {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 32px 0;
  border-top: 1px solid rgba(255,255,255,0.08);
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.stat-block { flex: 1; text-align: center; }
.stat-label {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.2em;
  color: rgba(255,255,255,0.4);
  text-transform: uppercase;
}
.stat-value {
  font-size: 48px;
  font-weight: 800;
  margin-top: 8px;
}
.stat-edge { color: #39ff78; }

.bottom {
  display: flex;
  flex-direction: column;
  gap: 12px;
  text-align: center;
}
.record {
  font-size: 22px;
  font-weight: 700;
  color: rgba(255,255,255,0.85);
  letter-spacing: 0.04em;
}
.brier {
  font-size: 16px;
  font-weight: 500;
  color: rgba(255,255,255,0.45);
  letter-spacing: 0.05em;
}
.brand {
  font-size: 18px;
  font-weight: 700;
  color: rgba(255,255,255,0.55);
  letter-spacing: 0.3em;
  text-transform: uppercase;
  margin-top: 8px;
}
.brand-handle { color: #6480ff; }
"""


def _build_html(
    sport_label: str,
    market_label: str,
    pick_main: str,
    pick_teams: str,
    model_pct: str,
    book_pct: str,
    edge_pct: str,
    record_line: str,
    brier_line: str,
) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="card-wrap">
  <div class="top">
    <div class="label-sport">{sport_label} · {market_label}</div>
    <div class="label-when">Tonight's Call</div>
  </div>

  <div class="pick-zone">
    <div class="pick-main">{pick_main}</div>
    <div class="pick-teams">{pick_teams}</div>
  </div>

  <div class="stats">
    <div class="stat-block">
      <div class="stat-label">Model</div>
      <div class="stat-value">{model_pct}</div>
    </div>
    <div class="stat-block">
      <div class="stat-label">Book</div>
      <div class="stat-value">{book_pct}</div>
    </div>
    <div class="stat-block">
      <div class="stat-label">Edge</div>
      <div class="stat-value stat-edge">{edge_pct}</div>
    </div>
  </div>

  <div class="bottom">
    <div class="record">{record_line}</div>
    <div class="brier">{brier_line}</div>
    <div class="brand">@<span class="brand-handle">getoverlay</span></div>
  </div>
</div></body></html>"""


def render_calibration_card(
    pick: dict,
    sport: str,
    market: str,
    record_line: str = "",
    brier_line: str = "",
    card_date: _date | None = None,
    filename: str = "calibration_card",
) -> Path | None:
    """Render one minimal calibration card to PNG.

    `pick` accepts either the MLB legacy schema (capitalized keys) or the
    NBA-style lowercase schema. `record_line` and `brier_line` should be
    pre-formatted strings from receipts_caption helpers.
    """
    d = card_date or _date.today()

    def _s(v) -> str:
        if v is None:
            return ""
        if isinstance(v, float) and v != v:  # NaN
            return ""
        return str(v)

    # Pick display
    market_l = (market or "").lower()
    team = _s(pick.get("Team") or pick.get("team")) or "—"
    matchup = _s(pick.get("Matchup") or pick.get("matchup"))
    direction = _s(pick.get("Direction") or pick.get("direction")).upper()
    line = pick.get("BetLine") or pick.get("bet_line") or pick.get("line")
    if isinstance(line, float) and line != line:
        line = None
    odds = pick.get("BestOdds") or pick.get("best_odds") or pick.get("odds")
    if isinstance(odds, float) and odds != odds:
        odds = None

    if market_l in ("total", "f5_total"):
        pick_main = f"{direction} {line}"
        pick_teams = matchup
    elif market_l in ("spread", "puck_line"):
        line_s = f"{float(line):+.1f}" if line is not None else ""
        pick_main = f"{team} {line_s}".strip()
        pick_teams = matchup
    else:
        pick_main = f"{team}"
        pick_teams = matchup or ""

    if odds:
        try:
            pick_teams = f"{pick_teams}  ({int(odds):+d})".strip()
        except (TypeError, ValueError):
            pass

    # Model / book / edge percentages
    model_prob = pick.get("ModelProb") or pick.get("model_prob") or 0
    edge = pick.get("Edge") or pick.get("edge_pct") or 0
    if isinstance(model_prob, (int, float)) and model_prob > 1:
        model_prob = model_prob / 100
    if isinstance(edge, (int, float)) and 0 < edge < 1:
        edge = edge * 100
    book_prob = (model_prob - (edge / 100)) if (model_prob and edge) else 0

    model_pct = f"{model_prob * 100:.1f}%" if model_prob else "—"
    book_pct = f"{book_prob * 100:.1f}%" if book_prob else "—"
    edge_pct = f"+{edge:.1f}%" if edge else "—"

    # Labels
    sport_label = sport.upper().replace("_", " ")
    market_label = {
        "moneyline": "Moneyline",
        "spread":    "Spread",
        "puck_line": "Puck Line",
        "total":     "Totals",
        "f5_total":  "F5 Totals",
        "nrfi":      "NRFI",
        "prop":      "Player Prop",
    }.get(market_l, market.title())

    html = _build_html(
        sport_label, market_label,
        pick_main, pick_teams,
        model_pct, book_pct, edge_pct,
        record_line, brier_line,
    )

    # Output dir mirrors the sport convention used elsewhere
    sport_dir = {
        "mlb":    "baseball_mlb",
        "nba":    "basketball_nba",
        "nhl":    "icehockey_nhl",
        "wnba":   "basketball_wnba",
        "tennis": "tennis",
        "soccer": "soccer",
    }.get(sport.lower(), sport.lower())

    save_dir = _OUTPUT_DIR / sport_dir / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    return _playwright_render(
        html,
        save_dir / f"{filename}.html",
        save_dir / f"{filename}.png",
        target_height=1080,
    )
