#!/usr/bin/env python3
"""
ChefTonyBets — Grading Script
Run this each evening after games finish.

Usage:
    python3 grade.py              # auto-grade yesterday's pending picks via Odds API
    python3 grade.py --date 20260408   # auto-grade a specific date
    python3 grade.py --manual     # interactive W/L prompts (fallback)
    python3 grade.py win "Team"   # quick single result
    python3 grade.py loss "Team"  # quick single result
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_FILE = Path("data/pnl/picks.json")


def _load():
    if not DATA_FILE.exists():
        return {"picks": []}
    return json.loads(DATA_FILE.read_text())


def _save(data):
    DATA_FILE.write_text(json.dumps(data, indent=2))


def _profit(stake: float, odds: float, won: bool) -> float:
    if not won:
        return -stake
    if odds > 0:
        return stake * odds / 100
    return stake * 100 / abs(odds)


def _fetch_scores(date_str: str) -> dict[str, str]:
    """
    Fetch completed MLB game winners for a given date (YYYYMMDD).
    Returns {team_name: winner_name} for every team in every completed game.
    """
    try:
        import requests
    except ImportError:
        print("  requests not installed — cannot auto-grade")
        return {}

    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ODDS_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
    if not api_key:
        print("  ODDS_API_KEY not found — cannot auto-grade")
        return {}

    # daysFrom=1 returns yesterday + today completed games
    resp = requests.get(
        "https://api.the-odds-api.com/v4/sports/baseball_mlb/scores/",
        params={"apiKey": api_key, "daysFrom": 2, "dateFormat": "iso"},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"  Scores API error {resp.status_code}")
        return {}

    winners = {}
    for game in resp.json():
        if not game.get("completed") or not game.get("scores"):
            continue
        # Filter to the requested date
        commence = game.get("commence_time", "")
        # Convert UTC commence time to ET date (UTC-4 during EDT)
        try:
            dt_utc = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            dt_et  = dt_utc - timedelta(hours=4)
            game_date = dt_et.strftime("%Y%m%d")
        except Exception:
            game_date = commence[:10].replace("-", "")

        if game_date != date_str:
            continue

        scores = {s["name"]: int(s["score"]) for s in game["scores"]}
        winner = max(scores, key=lambda t: scores[t])
        for team in scores:
            winners[team] = winner

    return winners


def auto_grade(date_str: str):
    """Auto-grade all pending card picks for date_str using Odds API scores."""
    data   = _load()
    picks  = [
        p for p in data["picks"]
        if p.get("date") == date_str
        and p["result"] is None
        and float(p.get("stake", p.get("bet_size", 1.0)) or 0) > 0
    ]

    if not picks:
        print(f"\n  No pending picks for {date_str}.")
        return

    print(f"\n  Fetching scores for {date_str}...")
    winners = _fetch_scores(date_str)

    if not winners:
        print("  Could not fetch scores. Run with --manual instead.")
        return

    print(f"  Found {len(set(winners.values()))} completed games.\n")
    print(f"  {'='*52}")
    print(f"  Auto-grading {len(picks)} pick(s) for {date_str}")
    print(f"  {'='*52}\n")

    graded = 0
    for pick in picks:
        team = pick["team"]
        odds = float(pick["odds"])
        sign = "+" if odds > 0 else ""

        # Find winner for this team's game
        winner = winners.get(team)
        if winner is None:
            print(f"  ⚠️  No score found for {team} — skipping")
            continue

        won = (winner == team)
        pick["result"]     = "win" if won else "loss"
        pick["profit"]     = round(_profit(pick["stake"], odds, won), 4)
        pick["resulted_at"] = datetime.now(timezone.utc).isoformat()

        icon  = "🟢 WIN " if won else "🔴 LOSS"
        prof  = f"+{pick['profit']:.2f}u" if won else f"{pick['profit']:.2f}u"
        print(f"  {icon}  {team:<30} ({sign}{int(odds)})  →  {prof}")
        print(f"         Winner: {winner}")
        print()
        graded += 1

    _save(data)
    print(f"  Graded {graded}/{len(picks)} picks.")

    # Final record
    settled = [p for p in data["picks"] if p["result"] in ("win", "loss")
               and float(p.get("stake", p.get("bet_size", 1.0)) or 0) > 0]
    wins   = sum(1 for p in settled if p["result"] == "win")
    losses = len(settled) - wins
    profit = sum(p.get("profit") or 0 for p in settled)
    staked = sum(p.get("stake", 1.0) for p in settled)
    roi    = (profit / staked * 100) if staked else 0
    ps = "+" if profit >= 0 else ""
    rs = "+" if roi    >= 0 else ""
    print(f"\n  ─────────────────────────────────────────")
    print(f"  SEASON RECORD   {wins}W – {losses}L")
    print(f"  PROFIT          {ps}{profit:.2f}u  |  ROI {rs}{roi:.1f}%")
    print(f"  ─────────────────────────────────────────\n")


def quick_result(team: str, won: bool, date: str | None = None):
    """Grade a single pick by team name (and optionally date) directly in the JSON."""
    data = _load()
    now  = datetime.now(timezone.utc).isoformat()

    for pick in data["picks"]:
        if pick["team"].lower().strip() != team.lower().strip():
            continue
        if pick["result"] is not None:
            continue
        if float(pick.get("stake", pick.get("bet_size", 1.0)) or 0) <= 0:
            continue
        if date and pick.get("date") != date:
            continue

        pick["result"]     = "win" if won else "loss"
        pick["profit"]     = round(_profit(pick["stake"], pick["odds"], won), 4)
        pick["resulted_at"] = now
        _save(data)

        icon = "🟢 WIN" if won else "🔴 LOSS"
        sign = "+" if pick["profit"] >= 0 else ""
        print(f"\n  {icon}  {team}  →  {sign}{pick['profit']:.2f}u\n")
        return

    print(f"\n  ⚠️  No pending card pick found for '{team}'{' on ' + date if date else ''}.\n")


def interactive():
    data  = _load()
    picks = [p for p in data["picks"]
             if p["result"] is None and float(p.get("stake", p.get("bet_size",1.0)) or 0) > 0]

    if not picks:
        print("\n  No pending card picks to grade.\n")
        _print_record(data)
        return

    print(f"\n  {'='*50}")
    print(f"  ChefTonyBets — Grade {len(picks)} pending pick(s)")
    print(f"  {'='*50}\n")

    for pick in picks:
        team = pick["team"]
        odds = int(pick["odds"])
        sign = "+" if odds > 0 else ""
        opp  = pick.get("opponent","?")
        d    = pick.get("date","?")

        print(f"  {team}  ({sign}{odds})  vs  {opp}  [{d}]")
        while True:
            ans = input("  Result? [W/L/skip]: ").strip().upper()
            if ans == "W":
                quick_result(team, won=True, date=d)
                break
            elif ans == "L":
                quick_result(team, won=False, date=d)
                break
            elif ans in ("S", "SKIP", ""):
                print(f"  Skipping {team}.\n")
                break
            else:
                print("  Type W, L, or skip.")

    data = _load()
    _print_record(data)


def _print_record(data):
    settled = [p for p in data["picks"] if p["result"] in ("win", "loss")
               and float(p.get("stake", p.get("bet_size", 1.0)) or 0) > 0]
    wins   = sum(1 for p in settled if p["result"] == "win")
    losses = len(settled) - wins
    profit = sum(p.get("profit") or 0 for p in settled)
    staked = sum(p.get("stake", 1.0) for p in settled)
    roi    = (profit / staked * 100) if staked else 0
    ps = "+" if profit >= 0 else ""
    rs = "+" if roi    >= 0 else ""
    print(f"  ─────────────────────────────────────────")
    print(f"  SEASON RECORD   {wins}W – {losses}L")
    print(f"  PROFIT          {ps}{profit:.2f}u  |  ROI {rs}{roi:.1f}%")
    print(f"  ─────────────────────────────────────────\n")


def generate_recap_card(grade_date: str) -> Path | None:
    """
    Generate a nightly recap card image for Instagram Stories.
    Shows last night's results + running season record.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  Pillow not installed — skipping recap card.")
        return None

    data    = _load()
    settled = [p for p in data["picks"]
               if p.get("result") in ("win", "loss")
               and float(p.get("stake", p.get("bet_size", 1.0)) or 0) > 0]

    last_night = [p for p in settled if p.get("date") == grade_date]
    if not last_night:
        print(f"  No settled picks for {grade_date} — skipping recap card.")
        return None

    # Season totals
    wins   = sum(1 for p in settled if p["result"] == "win")
    losses = len(settled) - wins
    profit = sum(p.get("profit") or 0 for p in settled)
    staked = sum(p.get("stake", 1.0) for p in settled)
    roi    = (profit / staked * 100) if staked else 0

    # Last night totals
    ln_wins   = sum(1 for p in last_night if p["result"] == "win")
    ln_losses = len(last_night) - ln_wins
    ln_profit = sum(p.get("profit") or 0 for p in last_night)

    # Layout
    W, H   = 1080, 1080
    PAD    = 50
    _BG    = (8, 10, 18)
    _GOLD  = (255, 184, 0)
    _GREEN = (70, 210, 90)
    _RED   = (220, 60, 60)
    _WHITE = (248, 248, 252)
    _GRAY  = (155, 158, 180)
    _DARK  = (14, 17, 28)
    _HDR   = (10, 12, 22)

    def _load_font(size, bold=False):
        paths = [("/System/Library/Fonts/HelveticaNeue.ttc", 1 if bold else 0),
                 ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
                  else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)]
        from PIL import ImageFont
        for path, idx in paths:
            try:
                return ImageFont.truetype(path, size, index=idx)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    f_brand  = _load_font(52, bold=True)
    f_handle = _load_font(28, bold=False)
    f_big    = _load_font(88, bold=True)
    f_mid    = _load_font(42, bold=True)
    f_pick   = _load_font(34, bold=True)
    f_sub    = _load_font(26, bold=False)
    f_label  = _load_font(22, bold=False)

    img  = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    # Gold top bar
    draw.rectangle([0, 0, W, 6], fill=_GOLD)

    # Header
    draw.rectangle([0, 0, W, 110], fill=_HDR)
    draw.text((PAD, 20), "ChefTony", fill=_WHITE, font=f_brand)
    bw = draw.textlength("ChefTony", font=f_brand)
    draw.text((PAD + bw + 8, 26), "Bets", fill=_GOLD, font=_load_font(42, bold=True))
    hw = draw.textlength("@ChefTonyBets", font=f_handle)
    draw.text((W - PAD - hw, 40), "@ChefTonyBets", fill=_GOLD, font=f_handle)

    draw.rectangle([0, 110, W, 114], fill=_GOLD)

    # Date label
    from datetime import datetime as _dt
    try:
        d_obj = _dt.strptime(grade_date, "%Y%m%d")
        date_label = d_obj.strftime("%B %d, %Y").upper()
    except Exception:
        date_label = grade_date
    draw.text((W // 2 - draw.textlength(f"LAST NIGHT · {date_label}", font=f_sub) // 2,
               130), f"LAST NIGHT · {date_label}", fill=_GRAY, font=f_sub)

    # Big W-L
    wl_str   = f"{ln_wins}W - {ln_losses}L"
    wl_color = _GREEN if ln_wins >= ln_losses else _RED
    wl_w     = draw.textlength(wl_str, font=f_big)
    draw.text(((W - wl_w) // 2, 175), wl_str, fill=wl_color, font=f_big)

    # Profit line
    ln_p = f"+{ln_profit:.2f}u" if ln_profit >= 0 else f"{ln_profit:.2f}u"
    ln_pc = _GREEN if ln_profit >= 0 else _RED
    lnpw = draw.textlength(ln_p, font=f_mid)
    draw.text(((W - lnpw) // 2, 290), ln_p, fill=ln_pc, font=f_mid)

    # Divider
    draw.rectangle([PAD, 360, W - PAD, 362], fill=_GOLD)

    # Individual picks
    y = 380
    for pick in last_night:
        won  = pick["result"] == "win"
        icon = "✅" if won else "❌"
        team = pick["team"]
        odds = int(pick["odds"])
        sign = "+" if odds > 0 else ""
        prof = pick.get("profit") or 0
        pstr = f"+{prof:.2f}u" if prof >= 0 else f"{prof:.2f}u"
        pc   = _GREEN if prof >= 0 else _RED

        draw.text((PAD, y), icon, fill=_WHITE, font=f_pick)
        draw.text((PAD + 48, y), f"{team}", fill=_WHITE, font=f_pick)
        tw = draw.textlength(f"{team}", font=f_pick)
        draw.text((PAD + 52 + tw, y + 4), f"({sign}{odds})", fill=_GRAY, font=f_sub)
        pw = draw.textlength(pstr, font=f_pick)
        draw.text((W - PAD - pw, y), pstr, fill=pc, font=f_pick)
        y += 52
        if y > 780:
            break

    # Season record box
    draw.rectangle([PAD, 820, W - PAD, 960], fill=_DARK, outline=_GOLD, width=2)
    draw.text((W // 2 - draw.textlength("SEASON RECORD", font=f_label) // 2, 835),
              "SEASON RECORD", fill=_GRAY, font=f_label)

    season_str = f"{wins}W - {losses}L"
    ssw = draw.textlength(season_str, font=f_mid)
    draw.text(((W - ssw) // 2, 865), season_str, fill=_WHITE, font=f_mid)

    roi_str  = f"+{roi:.1f}% ROI" if roi >= 0 else f"{roi:.1f}% ROI"
    prof_str = f"+{profit:.2f}u" if profit >= 0 else f"{profit:.2f}u"
    detail   = f"{prof_str}  ·  {roi_str}"
    dw = draw.textlength(detail, font=f_sub)
    rc = _GREEN if roi >= 0 else _RED
    draw.text(((W - dw) // 2, 920), detail, fill=rc, font=f_sub)

    # Footer
    draw.rectangle([0, H - 74, W, H], fill=_HDR)
    draw.rectangle([0, H - 74, W, H - 70], fill=_GOLD)
    cta = "Free picks every day  ·  All picks AI-model backed"
    draw.text((W // 2 - draw.textlength(cta, font=f_label) // 2, H - 58),
              cta, fill=_GOLD, font=f_label)

    # Save
    save_dir = Path("output/picks/recaps")
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"{grade_date}.png"
    img.save(path, quality=95)
    print(f"  Recap card saved: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(prog="grade")
    parser.add_argument("cmd",    nargs="?", help="win | loss | (blank=auto)")
    parser.add_argument("team",   nargs="?", help="Team name for win/loss")
    parser.add_argument("--date", help="Date to grade YYYYMMDD (default: yesterday)")
    parser.add_argument("--manual", action="store_true", help="Interactive W/L mode")
    parser.add_argument("--recap-card", action="store_true", help="Generate recap card image")

    args = parser.parse_args()

    if args.cmd == "win" and args.team:
        quick_result(args.team, won=True, date=args.date)
    elif args.cmd == "loss" and args.team:
        quick_result(args.team, won=False, date=args.date)
    elif args.manual:
        interactive()
    else:
        # Default: auto-grade yesterday (or --date), then optionally generate recap card
        if args.date:
            grade_date = args.date
        else:
            yesterday  = datetime.now() - timedelta(days=1)
            grade_date = yesterday.strftime("%Y%m%d")
        auto_grade(grade_date)
        if args.recap_card:
            generate_recap_card(grade_date)


if __name__ == "__main__":
    main()
