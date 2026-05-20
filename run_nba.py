"""
NBA Daily Picks Pipeline — ChefTonyBets

Generates picks + player props for today's NBA slate and saves to:
    output/picks/basketball_nba/YYYYMMDD/picks.json
    output/picks/basketball_nba/YYYYMMDD/props.json

Run:
    python3 run_nba.py
    python3 run_nba.py --refresh     # force-refresh odds cache
    python3 run_nba.py --date 20260415
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from src.data.odds_api import MY_BOOKS_PARAM
from src.data.nba_stats import fetch_team_ratings, fetch_player_stats
from src.models.nba_model import find_nba_edges, project_game
from src.data.nba_props import find_nba_prop_edges
from src.output.cards import render_nba_totals_card
# Old card renderers preserved in card_html.py but no longer called from here.
# Spreads paused, props shadow — only totals card active.
from src.output.captions import (
    nba_picks_caption, nba_props_caption, print_nba_captions,
    nba_spread_caption, nba_moneyline_caption, nba_totals_caption,
    nba_pick_of_day_caption, nba_slate_caption,
)

import requests

API_BASE = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path("data/cache/odds")


def fetch_nba_odds(refresh: bool = False) -> list[dict]:
    """Fetch today's NBA odds from The Odds API."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("  ⚠  No ODDS_API_KEY in env. Using cached data.")
        cache = CACHE_DIR / "basketball_nba_latest.json"
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []

    cache = CACHE_DIR / "basketball_nba_latest.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache.exists() and not refresh:
        age = (datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime)
        if age < 1800:
            with open(cache) as f:
                return json.load(f)

    try:
        resp = requests.get(
            f"{API_BASE}/sports/basketball_nba/odds",
            params={
                "apiKey": key,
                "regions": "us,us2",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
                "bookmakers": MY_BOOKS_PARAM,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        with open(cache, "w") as f:
            json.dump(data, f)
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  ✓  Live NBA odds fetched. API requests remaining: {remaining}")
        return data
    except Exception as e:
        print(f"  [run_nba] Odds fetch error: {e}")
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return []


def _format_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%I:%M %p ET")
    except Exception:
        return iso


def print_picks_table(edges: list[dict], props: list[dict]) -> None:
    line = "─" * 72
    print(f"\n{'NBA PICKS — ChefTonyBets':^72}")
    print(f"{date.today().strftime('%B %d, %Y'):^72}")
    print(line)

    if edges:
        print("\n  GAME PICKS (Model vs Market)")
        print(f"  {'GAME':<32} {'BET':<22} {'EDGE':>6}  {'ODDS':>6}  {'BOOK'}")
        print(f"  {'─'*68}")
        for e in edges[:8]:
            game = e["matchup"][:31]
            bet  = e["team"][:21]
            edge = f"{e['edge_pct']:+.1f}%"
            odds = f"{e['best_odds']:+d}"
            book = e["sportsbook"]
            proj = f"  [proj total {e['proj_total']:.0f}]" if e["market"] == "total" else ""
            print(f"  {game:<32} {bet:<22} {edge:>6}  {odds:>6}  {book}{proj}")
    else:
        print("\n  No game edges found at current threshold.")

    if props:
        print(f"\n  PLAYER PROPS (Top 10 by edge)")
        print(f"  {'PLAYER':<22} {'BET':<28} {'PROJ':>6} {'EDGE':>6}  {'ODDS':>6}  {'BOOK'}")
        print(f"  {'─'*68}")
        for p in props[:10]:
            player = p["player"][:21]
            bet    = f"{p['direction']} {p['line']} {p['market'].split('_')[-1].upper()}"[:27]
            proj   = f"{p['projected']:.1f}"
            edge   = f"{p['edge_pct']:+.1f}%"
            odds   = f"{p['odds']:+d}"
            book   = p["book"]
            print(f"  {player:<22} {bet:<28} {proj:>6} {edge:>6}  {odds:>6}  {book}")
    else:
        print("\n  No prop edges found — NBA stats cache may be loading.")

    print(f"\n{line}")


def _is_postseason_game(event: dict) -> bool:
    """Detect if an event is a playoff/play-in game from its title or id."""
    title = (event.get("sport_title") or event.get("home_team") or "").lower()
    eid = str(event.get("id") or "")
    # The Odds API uses 'basketball_nba' for regular season and the same key
    # for playoffs — detect via month heuristic but make it easy to override.
    return False  # enriched by _context_label below


def _context_label(today: str, events: list[dict]) -> str:
    """Return PLAY-IN TOURNAMENT, NBA PLAYOFFS, or NBA based on date + schedule."""
    from datetime import date as _date
    try:
        d = _date(int(today[:4]), int(today[4:6]), int(today[6:]))
    except (ValueError, IndexError):
        return "NBA"
    # Play-in: mid-April (typically 3rd week). Playoffs: late-April through mid-June.
    # Use month + day heuristic — good enough; doesn't need exact hardcoded dates.
    if d.month == 4 and 14 <= d.day <= 19:
        return "PLAY-IN TOURNAMENT"
    if (d.month == 4 and d.day >= 19) or d.month in (5, 6):
        return "NBA PLAYOFFS"
    return "NBA"


def main(refresh: bool = False, target_date: str | None = None) -> None:
    today = date.today().strftime("%Y%m%d") if not target_date else target_date
    out_dir = Path(f"output/picks/basketball_nba/{today}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n  ChefTonyBets — NBA Picks Pipeline")
    print(f"  Date: {today}")
    print("  Fetching NBA team ratings...")

    # Pre-load injury and rest data
    try:
        from src.data.injury_tracker import fetch_nba_injuries, get_lineup_adjustment
        from src.data.schedule_tracker import get_rest_days
        _nba_injuries = fetch_nba_injuries(today)
        _injury_loaded = True
        n_inj = sum(len(v) for v in _nba_injuries.values() if isinstance(v, list))
        print(f"  ✓  Injury data loaded ({n_inj} reported injuries)")
    except Exception as _inj_err:
        _nba_injuries = {}
        _injury_loaded = False
        print(f"  [injury] {_inj_err} — continuing without adjustment")

    # Pre-warm stats caches
    all_teams = fetch_team_ratings()
    print(f"  ✓  Team ratings loaded: {len(all_teams)} teams")

    all_players = fetch_player_stats()
    print(f"  ✓  Player stats loaded: {len(all_players)} players")

    print("  Fetching NBA odds...")
    events = fetch_nba_odds(refresh=refresh)

    # Filter to games whose local Eastern Time date matches target_date.
    # NBA tip-offs run 7 PM – midnight ET; late games cross into next UTC day
    # so we can't compare UTC date strings directly. Instead convert to ET.
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    target_dt = date(int(today[:4]), int(today[4:6]), int(today[6:]))

    def _et_date(iso: str) -> date:
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET).date()
        except Exception:
            return date.min

    upcoming = [e for e in events if _et_date(e.get("commence_time", "")) == target_dt]

    if not upcoming:
        now_utc = datetime.now(timezone.utc)
        upcoming = [
            e for e in events
            if datetime.fromisoformat(
                e.get("commence_time", "2000-01-01T00:00:00Z").replace("Z", "+00:00")
            ) > now_utc
        ]

    print(f"  Found {len(upcoming)} upcoming games")
    for ev in upcoming:
        ct = _format_time(ev.get("commence_time", ""))
        print(f"    {ev['away_team']} @ {ev['home_team']}  {ct}")

    # ── Game edges ─────────────────────────────────────────────────────────
    print("\n  Running NBA model...")
    edges = find_nba_edges(upcoming, min_edge_pct=3.0, is_playoff=date.today().month in (4, 5, 6))
    print(f"  ✓  {len(edges)} game edges found")

    # ── Project each matchup ───────────────────────────────────────────────
    # NBA playoffs run mid-April through mid-June. Pass is_playoff so the
    # model applies the ~5.7% intensity adjustment only when appropriate.
    today_month = date.today().month
    is_playoff_window = today_month in (4, 5, 6)
    print("\n  Game projections:")
    _game_date = date(int(today[:4]), int(today[4:6]), int(today[6:]))
    for ev in upcoming[:4]:
        away_inj = get_lineup_adjustment(ev["away_team"], "nba", today) if _injury_loaded else 0.0
        home_inj = get_lineup_adjustment(ev["home_team"], "nba", today) if _injury_loaded else 0.0
        away_rest = get_rest_days(ev["away_team"], _game_date, "nba") if _injury_loaded else 2
        home_rest = get_rest_days(ev["home_team"], _game_date, "nba") if _injury_loaded else 2
        proj = project_game(ev["away_team"], ev["home_team"], all_teams,
                            away_rest_days=away_rest, home_rest_days=home_rest,
                            is_playoff=is_playoff_window,
                            away_injury_adj=away_inj, home_injury_adj=home_inj)
        ct = _format_time(ev.get("commence_time", ""))
        print(
            f"    {ev['away_team']} @ {ev['home_team']}  {ct}\n"
            f"      Proj: {proj['away_proj']} - {proj['home_proj']}  "
            f"| Total: {proj['projected_total']}  "
            f"| Away ML: {proj['away_win_prob']*100:.0f}%  "
            f"| Home ML: {proj['home_win_prob']*100:.0f}%"
        )

    # ── Player props ───────────────────────────────────────────────────────
    print("\n  Fetching NBA player props...")
    raw_props = find_nba_prop_edges(upcoming[:4])
    print(f"  ✓  {len(raw_props)} prop edges found")

    # Dedupe: one prop per player (best edge), then sort by edge desc.
    # Confidence gate: 0.53 <= model_prob <= 0.78
    #   - floor 0.53: the Platt calibrator squashes raw probs toward 0.50; in
    #     practice all positive-edge calibrated probs land in 0.49-0.55. The
    #     previous floor of 0.62 was set against the raw (uncalibrated) probs
    #     and silently filtered 100% of edges after calibration. Anything above
    #     0.53 with a positive edge_pct is still +EV relative to the book.
    #   - ceiling 0.78: above this we're either fading a market that's already
    #     pricing the over correctly or eating a juice line (-300+); historic
    #     backtest shows these win the bet but lose money on units.
    MIN_PROP_CONFIDENCE = 0.53
    MAX_PROP_CONFIDENCE = 0.78
    _seen_players: dict[str, dict] = {}
    for prop in sorted(raw_props, key=lambda x: float(x.get("edge_pct", 0)), reverse=True):
        player = prop.get("player", "")
        conf   = float(prop.get("model_prob", 0))
        if (
            player
            and player not in _seen_players
            and MIN_PROP_CONFIDENCE <= conf <= MAX_PROP_CONFIDENCE
        ):
            _seen_players[player] = prop
    props = list(_seen_players.values())[:10]
    print(
        f"  ✓  {len(props)} unique-player props after dedup + confidence filter "
        f"({MIN_PROP_CONFIDENCE} ≤ p ≤ {MAX_PROP_CONFIDENCE})"
    )

    # ── Context label (Play-In / Playoffs / NBA) ──────────────────────────
    context = _context_label(today, upcoming)
    print(f"\n  Context: {context}")

    # ── Save outputs ───────────────────────────────────────────────────────
    picks_path = out_dir / "picks.json"
    props_path = out_dir / "props.json"

    with open(picks_path, "w") as f:
        json.dump(edges, f, indent=2)
    with open(props_path, "w") as f:
        json.dump(props, f, indent=2)

    print(f"\n  Saved → {picks_path}")
    print(f"  Saved → {props_path}")

    # ── Log picks to central pnl tracker ──────────────────────────────────
    _auto_log_nba_picks(edges, today)

    # ── Log props to pnl for tracking (card_pick=False) ───────────────────
    if props:
        try:
            from predict import _auto_log_props
            _prop_date = date(int(today[:4]), int(today[4:6]), int(today[6:]))
            n_props = _auto_log_props(props, sport="nba", game_date=_prop_date)
            if n_props > 0:
                print(f"  Auto-logged {n_props} NBA prop(s) to pnl for tracking")
        except Exception as _nba_prop_err:
            print(f"  [prop log] {_nba_prop_err}")

    # ── Terminal display ───────────────────────────────────────────────────
    print_picks_table(edges, props)

    # ── Generate pick cards ────────────────────────────────────────────────
    card_date_obj = date(int(today[:4]), int(today[4:6]), int(today[6:]))

    # Filter top positive-edge picks for cards (spread + ML + total, best 6)
    top_picks = [e for e in edges if e.get("edge_pct", 0) > 0][:6]
    all_positive = [e for e in edges if e.get("edge_pct", 0) > 0]

    # ── New ChefTonyBets NBA totals card ──────────────────────────────────
    totals_picks = [e for e in all_positive if e.get("market") == "total"]
    if totals_picks:
        print("\n  Generating NBA totals card (new design)...")
        tt = render_nba_totals_card(totals_picks, card_date=card_date_obj)
        if tt:
            print(f"  ✓  NBA totals card → {tt}")
        else:
            print("  ⚠  NBA totals card render failed (is Playwright installed?)")
    # Spreads, moneyline, props, pick-of-day, slate cards all paused/shadow — no render.

    # ── Generate captions ──────────────────────────────────────────────────
    print("\n  Generating captions...")

    # Main picks caption (all markets)
    cap_picks = nba_picks_caption(top_picks, card_date=card_date_obj, context_label=context)
    (out_dir / "caption_picks.txt").write_text(cap_picks, encoding="utf-8")

    # Props caption + cards (combined + one per prop type)
    if props:
        cap_props = nba_props_caption(props, card_date=card_date_obj, context_label=context)
        (out_dir / "caption_props.txt").write_text(cap_props, encoding="utf-8")
        # NBA props card paused (shadow market — no card render)

    # Per-card captions (matching MLB system)
    spread_only = [e for e in all_positive if e.get("market") == "spread"]
    if spread_only:
        (out_dir / "caption_spread.txt").write_text(
            nba_spread_caption(spread_only, card_date=card_date_obj, context_label=context), encoding="utf-8")

    ml_only = [e for e in all_positive if e.get("market") in ("moneyline", "h2h")]
    if ml_only:
        (out_dir / "caption_ml.txt").write_text(
            nba_moneyline_caption(ml_only, card_date=card_date_obj, context_label=context), encoding="utf-8")

    totals_only = [e for e in all_positive if e.get("market") == "total"]
    if totals_only:
        (out_dir / "caption_totals.txt").write_text(
            nba_totals_caption(totals_only, card_date=card_date_obj, context_label=context), encoding="utf-8")

    if all_positive:
        non_total = [p for p in all_positive if p.get("market") != "total"]
        best = max(non_total or all_positive, key=lambda x: float(x.get("edge_pct", 0)))
        (out_dir / "caption_pick_of_day.txt").write_text(
            nba_pick_of_day_caption(best, card_date=card_date_obj, context_label=context), encoding="utf-8")

    if all_positive:
        (out_dir / "caption_slate.txt").write_text(
            nba_slate_caption(all_positive[:5], card_date=card_date_obj, context_label=context), encoding="utf-8")

    # Print all to terminal
    print_nba_captions(top_picks, props, card_date=card_date_obj, context_label=context)

    # ── Parlay card (only when NBA moneyline model is live) ───────────────────
    from src.config.models import is_live as _nba_is_live
    if _nba_is_live("nba", "moneyline"):
        try:
            from src.output.parlay_card import render_parlay_card
            print("\n  Generating NBA parlay card...")
            _parlay_pool: list[dict] = []
            for e in edges:
                _parlay_pool.append({
                    "team":       e.get("team", ""),
                    "matchup":    e.get("matchup", ""),
                    "market":     e.get("market", "moneyline"),
                    "odds":       int(e.get("best_odds", -110) or -110),
                    "best_odds":  int(e.get("best_odds", -110) or -110),
                    "sportsbook": e.get("sportsbook", ""),
                    "edge_pct":   float(e.get("edge_pct", 0) or 0),
                })
            _parlay_pool.sort(key=lambda x: x["edge_pct"], reverse=True)
            parlay_path = render_parlay_card(_parlay_pool, sport="basketball_nba", card_date=card_date_obj)
            if parlay_path:
                print(f"  ✓  Parlay card → {parlay_path}")
            else:
                print("  No parlay card (need ≥2 picks with ≥5% edge).")
        except Exception as _pc_err:
            print(f"  [parlay card] {_pc_err}")
    else:
        print("\n  NBA parlay card skipped — moneyline model incubating.")

    # ── Platform captions (Instagram / Twitter / Reddit) ──────────────────────
    try:
        from src.output.captions_platform import write_platform_captions
        print("\n  Writing captions (Instagram / Twitter / Reddit)...")
        _cap_picks = [
            {
                "team":       e.get("team", ""),
                "matchup":    e.get("matchup", ""),
                "market":     e.get("market", "moneyline"),
                "direction":  e.get("direction", ""),
                "odds":       int(e.get("best_odds", -110) or -110),
                "best_odds":  int(e.get("best_odds", -110) or -110),
                "sportsbook": e.get("sportsbook", ""),
                "edge_pct":   float(e.get("edge_pct", 0) or 0),
            }
            for e in all_positive
        ]
        cap_paths = write_platform_captions(
            picks=_cap_picks,
            sport="basketball_nba",
            card_date=card_date_obj,
        )
        for platform, path in cap_paths.items():
            print(f"  ✓  {platform:12s} → {path}")

        # Reddit daily thread templates
        try:
            from src.output.reddit_templates import write_reddit_templates
            reddit_paths = write_reddit_templates(
                mlb_picks=[],
                mlb_props=[],
                nrfi_picks=[],
                nba_picks=_cap_picks,
                sport="basketball_nba",
                card_date=card_date_obj,
            )
            for name, path in reddit_paths.items():
                print(f"  ✓  reddit_{name:10s} → {path}")
        except Exception as _rt_err:
            print(f"  [reddit templates] {_rt_err}")
    except Exception as _cap_err:
        print(f"  [captions] {_cap_err}")

    # ── Overlay "show your work" content (live model only) ────────────────────
    try:
        from src.config.models import is_live
        from src.output.captions_overlay import receipts_caption
        from src.output.card_overlay_minimal import render_calibration_card
        from src.output.talking_head_show_your_work import write_script

        # Find best live-model edge (NBA Totals is the live market)
        _live_pick = None
        for e in all_positive:
            mkt = (e.get("market") or "").lower()
            if mkt == "h2h":
                mkt = "moneyline"
            if not is_live("nba", mkt):
                continue
            edge_pct_val = float(e.get("edge_pct") or 0)
            if _live_pick is None or edge_pct_val > _live_pick.get("_edge_pct", -999):
                _live_pick = dict(e)
                _live_pick["_market"] = mkt
                _live_pick["_edge_pct"] = edge_pct_val

        if _live_pick is None:
            print("  [overlay content] No live-model edges today.")
        else:
            _live_market = _live_pick.pop("_market")
            _live_pick.pop("_edge_pct", None)
            _out_dir = Path(f"output/picks/basketball_nba/{today}")

            rcap = receipts_caption(_live_pick, "nba", _live_market, today=card_date_obj)
            (_out_dir / "receipts_post.txt").write_text(rcap, encoding="utf-8")
            print(f"  ✓  receipts_post.txt → {_out_dir}/receipts_post.txt")

            _rec_line = ""
            _brier_line = ""
            for ln in rcap.split("\n"):
                if "·" in ln and "ROI" in ln and not _rec_line:
                    _rec_line = ln.strip()
                if ln.lower().startswith("brier "):
                    _brier_line = ln.strip()
            card_path = render_calibration_card(
                _live_pick, "nba", _live_market,
                record_line=_rec_line, brier_line=_brier_line,
                card_date=card_date_obj,
            )
            if card_path:
                print(f"  ✓  calibration_card.png → {card_path}")

            try:
                _direction = (_live_pick.get("direction") or "").upper()
                _line = _live_pick.get("bet_line") or _live_pick.get("line")
                _odds = _live_pick.get("best_odds") or _live_pick.get("odds")
                _team = _live_pick.get("team", "")
                if _live_market == "total":
                    _pick_line = f"{_direction} {_line} ({int(_odds):+d})" if _odds else f"{_direction} {_line}"
                else:
                    _pick_line = f"{_team} ({int(_odds):+d})" if _odds else _team
                write_script(
                    _out_dir, sport="nba", market=_live_market,
                    pick_line=_pick_line,
                    model_prob_pct=float(_live_pick.get("model_prob", 0) or 0) * 100,
                    edge_pct=float(_live_pick.get("edge_pct", 0) or 0),
                    record_str=_rec_line or "—",
                    brier=None,
                    clv_avg_cents=None,
                    today=card_date_obj,
                )
                print(f"  ✓  show_your_work.md → {_out_dir}/talking_head/show_your_work.md")
            except Exception as _th_err:
                print(f"  [show-your-work] {_th_err}")
    except Exception as _ov_err:
        print(f"  [overlay content] Skipped: {_ov_err}")

    # ── CLV opening-line snapshot ──────────────────────────────────────────────
    try:
        from src.analytics.clv_tracker import snapshot_from_pnl
        n_snapped = snapshot_from_pnl(card_date_obj.isoformat())
        if n_snapped:
            print(f"  [CLV] Snapshotted opening lines for {n_snapped} NBA pick(s)")
    except Exception as _clv_err:
        print(f"  [CLV snapshot] {_clv_err}")


_PNL_FILE = Path("data/pnl/picks.json")


def _auto_log_nba_picks(edges: list[dict], today: str) -> int:
    """Log NBA edge picks to data/pnl/picks.json using canonical schema."""
    from src.tracking.schema import make_pick_id

    _PNL_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(_PNL_FILE.read_text()) if _PNL_FILE.exists() else {"picks": []}
        if "picks" not in data:
            data = {"picks": []}
    except (json.JSONDecodeError, ValueError):
        data = {"picks": []}

    now_ts   = datetime.now(timezone.utc).isoformat()
    date_str = f"{today[:4]}-{today[4:6]}-{today[6:]}"

    # Dedup on pick_id
    existing_ids = {p.get("pick_id", "") for p in data["picks"]}

    _NBA_PAUSED = ["spread", "prop"]
    _NBA_TIER: dict[str, str] = {
        "total":       "tier1",
        "moneyline":   "tier2",
        "spread":      "shadow",
        "player_prop": "shadow",
    }

    added = 0
    for rank, e in enumerate(edges):
        team      = str(e.get("team", "")).strip()
        market    = str(e.get("market", "spread")).lower()
        direction = str(e.get("direction", "")).upper()
        matchup   = str(e.get("matchup", "")).strip()

        # Skip paused markets — still modeled, but not logged to public record
        if market in _NBA_PAUSED:
            continue

        if not direction:
            direction = "WIN" if market == "moneyline" else "COVER" if market == "spread" else "OVER"

        if not team:
            continue

        pick_id = make_pick_id("nba", date_str, team, market, direction)
        if pick_id in existing_ids:
            continue

        odds_raw = e.get("best_odds", 0) or 0
        try:
            odds = int(float(odds_raw))
        except (ValueError, TypeError):
            odds = None

        line: float | None = e.get("bet_line")
        if line is not None:
            try:
                line = float(line)
            except (ValueError, TypeError):
                line = None

        from src.config.models import is_live as _is_live
        data["picks"].append({
            "pick_id":     pick_id,
            "date":        date_str,
            "sport":       "nba",
            "market":      market,
            "direction":   direction,
            "team":        team,
            "matchup":     matchup,
            "odds":        odds,
            "line":        line,
            "sportsbook":  e.get("sportsbook"),
            "model_prob":  e.get("model_prob") or e.get("win_prob"),
            "edge_pct":    e.get("edge_pct"),
            "model_tier":  _NBA_TIER.get(market, "shadow"),
            "stake":       1.0,
            "card_pick":   _is_live("nba", market),
            "result":      None,
            "profit":      None,
            "recorded_at": now_ts,
            "resulted_at": None,
        })
        existing_ids.add(pick_id)
        added += 1

    if added > 0:
        _PNL_FILE.write_text(json.dumps(data, indent=2))
        print(f"  ✓  {added} NBA pick(s) logged to pnl")
    return added


def fetch_nba_scores(game_date: date) -> list[dict]:
    """
    Fetch NBA final scores from ESPN API.

    Returns list of dicts: {home_team, away_team, home_score, away_score, state}.
    Uses ESPN's public scoreboard endpoint — no auth needed.
    """
    date_str = game_date.strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_str}"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for event in data.get("events", []):
            comp = event.get("competitions", [{}])[0]
            status = comp.get("status", {}).get("type", {})
            state = "Final" if status.get("completed") else status.get("description", "Scheduled")
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            home_name = home.get("team", {}).get("displayName", "")
            away_name = away.get("team", {}).get("displayName", "")
            try:
                home_score = int(home.get("score", 0) or 0)
                away_score = int(away.get("score", 0) or 0)
            except (TypeError, ValueError):
                home_score, away_score = 0, 0
            results.append({
                "home_team":  home_name,
                "away_team":  away_name,
                "home_score": home_score,
                "away_score": away_score,
                "state":      state,
            })
        return results
    except Exception as e:
        print(f"  [nba grade] Score fetch error: {e}")
        return []


def _normalize_nba(name: str) -> str:
    return name.lower().strip()


def _team_match(a: str, b: str) -> bool:
    """Fuzzy team name matching — handles city vs full name differences."""
    a, b = _normalize_nba(a), _normalize_nba(b)
    return a == b or a in b or b in a


def grade_nba_picks(target_date: str | None = None, flat_stake: float = 1.0, verbose: bool = True) -> dict:
    """
    Grade NBA picks for a given date against actual scores.

    Grades ML, spread, and total picks from picks.json.
    Updates data/pnl/nba_picks.json with per-pick results.
    """
    today = target_date or date.today().strftime("%Y%m%d")
    game_date = date(int(today[:4]), int(today[4:6]), int(today[6:]))
    out_dir = Path(f"output/picks/basketball_nba/{today}")
    picks_path = out_dir / "picks.json"

    if not picks_path.exists():
        if verbose:
            print(f"  [nba grade] No picks found for {today}")
        return {"date": today, "picks": 0, "graded": 0}

    with open(picks_path) as f:
        picks = json.load(f)

    scores = fetch_nba_scores(game_date)
    final_games = [s for s in scores if s["state"] == "Final"]

    if not final_games:
        if verbose:
            print(f"  [nba grade] No final scores yet for {today} ({len(scores)} scheduled)")
        return {"date": today, "picks": len(picks), "graded": 0, "pending": len(picks)}

    wins = losses = pending = 0
    total_profit = total_staked = 0.0
    graded = []

    # Per-category trackers
    by_type: dict[str, dict] = {}

    def _find_score(team: str) -> dict | None:
        for s in final_games:
            if _team_match(team, s["home_team"]) or _team_match(team, s["away_team"]):
                return s
        return None

    if verbose:
        print(f"\n{'='*70}")
        print(f"  NBA GRADING REPORT — {game_date.strftime('%A, %B %d, %Y')}")
        print(f"{'='*70}")
        print(f"  {len(picks)} picks | {len(final_games)} final games\n")

    for pick in picks:
        market   = str(pick.get("market", "spread")).lower()
        team     = str(pick.get("team", ""))
        matchup  = str(pick.get("matchup", ""))
        odds     = int(pick.get("best_odds", 0) or 0)
        book     = str(pick.get("sportsbook", ""))
        edge_pct = float(pick.get("edge_pct", 0) or 0)
        model_p  = float(pick.get("model_prob") or pick.get("win_prob", 0.5) or 0.5)
        direction = str(pick.get("direction", "COVER")).upper()
        bet_line  = float(pick.get("bet_line") or 0)

        # Resolve game — for totals, team is "OVER 215.5" so look up by matchup teams
        if market == "total" and matchup and " @ " in matchup:
            away_t, home_t = matchup.split(" @ ", 1)
            score = _find_score(home_t) or _find_score(away_t)
        else:
            score = _find_score(team)
        if not matchup and score:
            matchup = f"{score['away_team']} @ {score['home_team']}"

        if not score:
            pending += 1
            graded.append({"market": market, "team": team, "status": "pending"})
            if verbose:
                print(f"  PEND  {team} — no final score")
            continue

        hs, aws = score["home_score"], score["away_score"]
        is_home = _team_match(team, score["home_team"])
        ts  = hs if is_home else aws   # team score
        ops = aws if is_home else hs   # opponent score

        if market in ("spread", "runline"):
            # Team covers if ts + line > ops (team side of the spread)
            adj_ts = ts + bet_line
            won = adj_ts > ops
            if adj_ts == ops:  # push
                graded.append({"market": market, "team": team, "status": "push"})
                if verbose:
                    print(f"  PUSH  {team} {bet_line:+.1f} | {aws}-{hs}")
                continue
            label = f"{team} {bet_line:+.1f}"
        elif market == "total":
            total = hs + aws
            if direction == "OVER":
                won = total > bet_line
            else:
                won = total < bet_line
            if total == bet_line:
                graded.append({"market": market, "direction": direction, "line": bet_line, "status": "push"})
                continue
            label = f"{direction} {bet_line}"
        else:
            # moneyline
            won = ts > ops
            label = f"{team}"

        profit = (flat_stake * (odds / 100) if odds >= 0 else flat_stake * (100 / abs(odds))) if won else -flat_stake
        total_profit += profit
        total_staked += flat_stake

        if won:
            wins += 1
        else:
            losses += 1

        # Per-type tracking
        if market not in by_type:
            by_type[market] = {"wins": 0, "losses": 0, "profit": 0.0}
        if won:
            by_type[market]["wins"] += 1
        else:
            by_type[market]["losses"] += 1
        by_type[market]["profit"] += profit

        tag = "WIN " if won else "LOSS"
        score_str = f"{score['away_team']} {aws}, {score['home_team']} {hs}"
        if verbose:
            print(f"  {tag:4s}  {label} ({odds:+d} @ {book}) — ${profit:+.0f} | {score_str}")

        graded.append({
            "market": market, "team": team, "matchup": matchup,
            "odds": odds, "model_prob": model_p, "edge_pct": edge_pct,
            "won": won, "profit": profit, "score": score_str,
            "status": "win" if won else "loss",
        })

    settled = wins + losses
    roi = (total_profit / total_staked * 100) if total_staked > 0 else 0

    if verbose and settled > 0:
        print(f"\n  {'─'*50}")
        print(f"  RECORD:  {wins}-{losses} ({wins/settled:.1%} win rate)")
        print(f"  PROFIT:  ${total_profit:+,.0f} on ${total_staked:,.0f} wagered")
        print(f"  ROI:     {roi:+.1f}%")
        for mtype, stats in by_type.items():
            w, l = stats["wins"], stats["losses"]
            wr = w / (w + l) if (w + l) > 0 else 0
            print(f"  {mtype.upper():10s} {w}-{l} ({wr:.1%}) ${stats['profit']:+.0f}")
        if pending > 0:
            print(f"\n  {pending} game(s) still pending")
        print(f"  {'='*50}\n")

    # Persist grades
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "date": today,
        "total_picks": len(picks),
        "graded": settled,
        "pending": pending,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / settled if settled > 0 else None,
        "total_staked": total_staked,
        "total_profit": total_profit,
        "roi": roi,
        "by_type": {
            k: {
                "wins": v["wins"], "losses": v["losses"],
                "profit": round(v["profit"], 2),
                "win_rate": round(v["wins"] / (v["wins"] + v["losses"]), 4)
                            if (v["wins"] + v["losses"]) > 0 else None,
            }
            for k, v in by_type.items()
        },
        "details": graded,
        "graded_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(out_dir / "grades.json", "w") as f:
        json.dump(report, f, indent=2)

    # Write results back to central pnl file so public_stats tracks NBA too
    if _PNL_FILE.exists():
        try:
            pnl_data = json.loads(_PNL_FILE.read_text())
        except (json.JSONDecodeError, ValueError):
            pnl_data = {"picks": []}
        now_ts = datetime.now(timezone.utc).isoformat()
        date_str = f"{today[:4]}-{today[4:6]}-{today[6:]}"

        def _strip_line(t: str) -> str:
            """Strip trailing spread/total value: 'Celtics +5.5' → 'celtics'"""
            import re
            return re.sub(r'\s+[+-]?\d+\.?\d*$', '', t).strip().lower()

        for g in graded:
            if g.get("status") not in ("win", "loss"):
                continue
            team   = g.get("team", "")
            market = g.get("market", "spread")
            won    = g.get("won", False)
            profit = g.get("profit", 0.0)
            team_base = _strip_line(team)
            direction = str(g.get("direction", "")).upper()
            for p in pnl_data.get("picks", []):
                if (
                    p.get("sport") == "nba"
                    and p.get("date") == date_str
                    and p.get("market", "").lower() == market.lower()
                    and p.get("result") is None
                    and (
                        # Exact match first
                        p.get("team", "").lower() == team.lower()
                        # Fuzzy: strip spread/total line value and compare base team name
                        or _strip_line(p.get("team", "")) == team_base
                        # For totals: match on direction (OVER/UNDER) if no team name
                        or (market == "total" and direction and p.get("direction", "").upper() == direction)
                    )
                ):
                    p["result"]      = "win" if won else "loss"
                    p["profit"]      = round(profit, 4)   # already in units (flat_stake=1.0)
                    p["resulted_at"] = now_ts
                    break
        _PNL_FILE.write_text(json.dumps(pnl_data, indent=2))

    # Update public stats
    try:
        from src.analytics.public_stats import write_public_stats
        write_public_stats()
    except Exception as _e:
        print(f"  [stats] {_e}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NBA Picks Pipeline")
    parser.add_argument("--refresh", action="store_true", help="Force-refresh odds cache")
    parser.add_argument("--date", type=str, default=None, help="Date YYYYMMDD")
    parser.add_argument("--grade", action="store_true", help="Grade picks for --date (default: today)")
    args = parser.parse_args()
    if args.grade:
        grade_nba_picks(target_date=args.date)
    else:
        main(refresh=args.refresh, target_date=args.date)
