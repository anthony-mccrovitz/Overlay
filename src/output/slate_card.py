"""
Full-slate pick card — Overlay.
Shows every game: matchup | ML pick | Run Line pick | Total pick.
One tall card, all games, share with friends.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import json

OUTPUT_DIR    = Path("output/picks")
_TRACKER_FILE = Path("data/pnl/picks.json")

# ── Palette ───────────────────────────────────────────────────────────────────
_BG          = ( 8,  10,  18)
_HDR_BG      = (10,  12,  22)
_ROW_A       = (14,  17,  28)   # alternating row
_ROW_B       = (18,  22,  34)
_ROW_TOP     = (20,  24,  40)   # best bet row
_COL_HDR     = (26,  30,  46)   # column header strip
_DIVIDER     = (32,  36,  54)

_GOLD        = (255, 184,   0)
_GREEN       = ( 70, 210,  90)
_AMBER       = (255, 160,  20)
_WHITE       = (248, 248, 252)
_GRAY_LT     = (155, 158, 180)
_GRAY_MID    = ( 88,  92, 116)
_GRAY_DK     = ( 30,  34,  52)
_BLACK       = (  8,   8,  12)

_FONT_COND = [("/System/Library/Fonts/HelveticaNeue.ttc", 9),
              ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)]
_FONT_BOLD = [("/System/Library/Fonts/HelveticaNeue.ttc", 1),
              ("/System/Library/Fonts/HelveticaNeue.ttc", 9),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)]
_FONT_REG  = [("/System/Library/Fonts/HelveticaNeue.ttc", 0),
              ("/System/Library/Fonts/SFNS.ttf", 0),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)]


def _load_font(paths, size: int):
    from PIL import ImageFont
    for path, idx in paths:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _load_tracker_stats() -> dict | None:
    if not _TRACKER_FILE.exists():
        return None
    try:
        data = json.loads(_TRACKER_FILE.read_text())
        settled = [p for p in data.get("picks", []) if p.get("result") in ("win", "loss")]
        if not settled:
            return None
        wins   = sum(1 for p in settled if p["result"] == "win")
        losses = len(settled) - wins
        staked = sum(float(p.get("stake", p.get("bet_size", 1.0))) for p in settled)
        profit = sum(float(p.get("profit") or 0.0) for p in settled)
        roi    = (profit / staked * 100) if staked > 0 else 0.0
        return {"wins": wins, "losses": losses, "profit": profit, "roi": roi}
    except Exception:
        return None


# Short team name map
_SHORT = {
    "Kansas City Royals":      "KC Royals",
    "Cleveland Guardians":     "Cleveland",
    "Baltimore Orioles":       "Baltimore",
    "Chicago White Sox":       "Chi. White Sox",
    "Arizona Diamondbacks":    "Arizona",
    "New York Mets":           "NY Mets",
    "Chicago Cubs":            "Chi. Cubs",
    "Tampa Bay Rays":          "Tampa Bay",
    "Cincinnati Reds":         "Cincinnati",
    "Miami Marlins":           "Miami",
    "San Diego Padres":        "San Diego",
    "Pittsburgh Pirates":      "Pittsburgh",
    "Milwaukee Brewers":       "Milwaukee",
    "Boston Red Sox":          "Boston",
    "St. Louis Cardinals":     "St. Louis",
    "Washington Nationals":    "Washington",
    "Athletics":               "Athletics",
    "New York Yankees":        "NY Yankees",
    "Los Angeles Dodgers":     "LA Dodgers",
    "Toronto Blue Jays":       "Toronto",
    "Detroit Tigers":          "Detroit",
    "Minnesota Twins":         "Minnesota",
    "Seattle Mariners":        "Seattle",
    "Texas Rangers":           "Texas",
    "Houston Astros":          "Houston",
    "Colorado Rockies":        "Colorado",
    "Atlanta Braves":          "Atlanta",
    "Los Angeles Angels":      "LA Angels",
    "Philadelphia Phillies":   "Philadelphia",
    "San Francisco Giants":    "SF Giants",
}


def _s(name: str) -> str:
    """Short team name."""
    return _SHORT.get(name, name[:14])


def _fmt_odds(o: int) -> str:
    if o == 0:
        return "—"
    return f"+{o}" if o > 0 else str(o)


def _edge_color(edge: float) -> tuple:
    if edge >= 0.09:  return _GREEN
    if edge >= 0.05:  return _GOLD
    if edge >= 0.02:  return _AMBER
    return _GRAY_LT


def generate_slate_card(
    games: list[dict],
    sport_label: str = "MLB",
    card_date: date | None = None,
) -> Path | None:
    """
    Generate a full-slate pick card image.

    Each game dict requires:
      away, home, ml_pick, ml_odds, rl_pick, rl_spread, rl_odds,
      total, ou_pick, ou_odds, model_edge, commence
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  Pillow not installed.")
        return None

    d = card_date or date.today()

    # ── Fonts ─────────────────────────────────────────────────────────────────
    f_brand_lg = _load_font(_FONT_COND, 56)
    f_brand_sm = _load_font(_FONT_BOLD, 42)
    f_hdr      = _load_font(_FONT_BOLD, 19)
    f_hdr_sm   = _load_font(_FONT_REG,  17)
    f_col_hdr  = _load_font(_FONT_BOLD, 17)
    f_matchup  = _load_font(_FONT_BOLD, 21)
    f_pick     = _load_font(_FONT_COND, 26)   # bigger — must be readable at a glance
    f_odds_sm  = _load_font(_FONT_BOLD, 20)
    f_edge_lg  = _load_font(_FONT_BOLD, 18)   # edge % — prominent
    f_sub      = _load_font(_FONT_REG,  15)
    f_footer   = _load_font(_FONT_BOLD, 18)

    PAD    = 30
    W      = 1080
    HDR_H  = 130
    COL_H  = 36     # column header strip
    ROW_H  = 80     # taller rows — more breathing room
    FOOT_H = 60
    H      = HDR_H + COL_H + len(games) * ROW_H + FOOT_H + 10

    img  = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    # Background gradient (subtle)
    try:
        import numpy as np
        arr = np.zeros((H, W, 3), dtype=np.uint8)
        for y in range(H):
            t = y / max(H - 1, 1)
            arr[y] = [int(_BG[c] + ((4, 6, 10)[c] - _BG[c]) * t) for c in range(3)]
        from PIL import Image as _I
        img.paste(_I.fromarray(arr, "RGB"))
        draw = ImageDraw.Draw(img)
    except ImportError:
        pass

    # ── Header ────────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, W, HDR_H], fill=_HDR_BG)
    draw.rectangle([0, 0, W, 5],     fill=_GOLD)       # top gold
    draw.rectangle([0, HDR_H - 3, W, HDR_H], fill=_GOLD)

    # Brand
    draw.text((PAD, 16), "Overlay", fill=_WHITE, font=f_brand_lg)
    cw = draw.textlength("Overlay", font=f_brand_lg)
    draw.text((PAD + cw + 5, 22), "Bets", fill=_GOLD, font=f_brand_sm)

    # Date + handle (right)
    date_str = f"{sport_label}  ·  {d.strftime('%b %d, %Y').upper()}"
    dw = draw.textlength(date_str, font=f_hdr)
    draw.text((W - PAD - dw, 16), date_str, fill=_WHITE, font=f_hdr)
    hw = draw.textlength("@Overlay", font=f_hdr)
    draw.text((W - PAD - hw, 44), "@Overlay", fill=_GOLD, font=f_hdr)

    # Tagline + stats
    draw.text((PAD, 82), "A.I. Sports Picks  ·  Cooking Up Parlays", fill=_GRAY_MID, font=f_hdr_sm)

    # Sub-label
    sub = f"ALL {len(games)} GAMES  —  MODEL PICKS  ·  ML  ·  RUN LINE  ·  TOTALS"
    subw = draw.textlength(sub, font=f_hdr_sm)
    draw.text(((W - subw) // 2, 106), sub, fill=_GRAY_LT, font=f_hdr_sm)

    # ── Column headers ────────────────────────────────────────────────────────
    cy = HDR_H
    draw.rectangle([0, cy, W, cy + COL_H], fill=_COL_HDR)
    draw.rectangle([0, cy + COL_H - 2, W, cy + COL_H], fill=_GOLD)

    # Column X positions (fixed widths)
    GAME_X  = PAD           # matchup column  — 360px wide
    ML_X    = PAD + 368     # ML column       — 215px wide
    RL_X    = PAD + 593     # RL column       — 215px wide
    OU_X    = PAD + 814     # O/U column      — 200px wide

    for label, x in [("MATCHUP", GAME_X), ("MONEYLINE", ML_X), ("RUN LINE", RL_X), ("TOTAL", OU_X)]:
        draw.text((x, cy + 9), label, fill=_GRAY_LT, font=f_col_hdr)

    # Vertical dividers in column header
    for x in [ML_X - 10, RL_X - 10, OU_X - 10]:
        draw.rectangle([x, cy, x + 2, cy + COL_H], fill=_DIVIDER)

    # ── Game rows ─────────────────────────────────────────────────────────────
    gy = HDR_H + COL_H

    for i, g in enumerate(games):
        row_fill = _ROW_TOP if g["model_edge"] >= 0.09 else (_ROW_A if i % 2 == 0 else _ROW_B)
        draw.rectangle([0, gy, W, gy + ROW_H], fill=row_fill)

        # Subtle row separator
        draw.rectangle([0, gy + ROW_H - 1, W, gy + ROW_H], fill=_DIVIDER)

        # Vertical dividers (faint, in rows)
        for x in [ML_X - 10, RL_X - 10, OU_X - 10]:
            draw.rectangle([x, gy + 6, x + 1, gy + ROW_H - 6], fill=_DIVIDER)

        ec = _edge_color(g["model_edge"])
        has_edge = g["model_edge"] >= 0.05

        # ── MATCHUP column ─────────────────────────────────────────────────────
        away_s = _s(g["away"])
        home_s = _s(g["home"])
        ml_pick_team = g["ml_pick"]   # full name for comparison

        # Highlight the picked team in the matchup column
        away_color = _GOLD if ml_pick_team == g["away"] else _GRAY_LT
        home_color = _GOLD if ml_pick_team == g["home"] else _GRAY_LT

        t = g.get("commence", "")
        if "T" in t:
            t_parts = t.split("T")[1][:5].split(":")
            h, m = int(t_parts[0]), int(t_parts[1])
            h = (h - 4) % 24
            ampm = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            time_str = f"{h12}:{m:02d} {ampm}"
        else:
            time_str = ""

        draw.text((GAME_X, gy + 8),  away_s, fill=away_color, font=f_matchup)
        draw.text((GAME_X, gy + 34), home_s, fill=home_color, font=f_matchup)
        if time_str:
            draw.text((GAME_X, gy + 60), time_str, fill=_GRAY_MID, font=f_sub)

        # Edge % badge — right side of matchup column, prominent
        if has_edge:
            edge_txt = f"+{g['model_edge']*100:.0f}% EDGE"
            ew = draw.textlength(edge_txt, font=f_edge_lg)
            ex = ML_X - 14 - ew
            # small pill background
            draw.rectangle([ex - 6, gy + 10, ex + ew + 6, gy + 34], fill=_GRAY_DK)
            draw.text((ex, gy + 12), edge_txt, fill=ec, font=f_edge_lg)

        # ── ML column ──────────────────────────────────────────────────────────
        ml_team = _s(ml_pick_team)
        ml_odds = _fmt_odds(g["ml_odds"])
        # Always gold for the pick — this is THE pick, make it obvious
        ml_color = _GOLD if has_edge else _WHITE

        draw.text((ML_X, gy + 6),   ml_team, fill=ml_color, font=f_pick)
        draw.text((ML_X, gy + 40),  ml_odds, fill=ml_color, font=f_odds_sm)

        # ── RL column ──────────────────────────────────────────────────────────
        rl_team    = _s(g["rl_pick"])
        spread_str = f"{g['rl_spread']:+.1f}"
        rl_odds    = _fmt_odds(g["rl_odds"])

        draw.text((RL_X, gy + 6),  rl_team,                    fill=_WHITE,   font=f_pick)
        draw.text((RL_X, gy + 40), f"{spread_str}  ({rl_odds})", fill=_GRAY_LT, font=f_odds_sm)

        # ── Total column ───────────────────────────────────────────────────────
        ou_label = g["ou_pick"]
        ou_line  = f"o/u {g['total']:.1f}"
        ou_odds  = _fmt_odds(g["ou_odds"])
        ou_color = _GREEN if ou_label == "OVER" else _AMBER

        draw.text((OU_X, gy + 6),  ou_label,               fill=ou_color, font=f_pick)
        draw.text((OU_X, gy + 40), f"{ou_line}  ({ou_odds})", fill=_GRAY_LT, font=f_odds_sm)

        gy += ROW_H

    # ── Footer ────────────────────────────────────────────────────────────────
    fy = gy + 8
    draw.rectangle([PAD, fy, W - PAD, fy + 2], fill=_GOLD)

    cta = "Follow @Overlay · Free picks every day  ·  All picks AI-model backed"
    ctaw = draw.textlength(cta, font=f_footer)
    draw.text(((W - ctaw) // 2, fy + 10), cta, fill=_GOLD, font=f_footer)

    disclaimer = "For entertainment only · Not financial advice"
    disw = draw.textlength(disclaimer, font=f_sub)
    draw.text(((W - disw) // 2, fy + 36), disclaimer, fill=_GRAY_MID, font=f_sub)

    # ── Save ──────────────────────────────────────────────────────────────────
    save_dir = OUTPUT_DIR / "baseball_mlb" / d.strftime("%Y%m%d")
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / "slate_card.png"
    img.save(path, quality=95)
    return path
