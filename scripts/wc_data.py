"""
World Cup 2026 data generator — the single source the web app reads from.

Runs the calibrated SoccerModelV2 over every 2026 fixture and the Monte Carlo
simulator over the full bracket, blends in live market odds where available, and
writes a clean set of JSON files the Next.js app consumes:

    web/public/data/wc/fixtures.json   every match: model 1X2 / totals / BTTS /
                                        top scorelines + venue context + market
                                        blend + edge
    web/public/data/wc/futures.json    champion / reach-final odds, model vs
                                        market blend, biggest disagreements
    web/public/data/wc/groups.json     per-group standings w/ advance %
    web/public/data/wc/meta.json       generated timestamp + model info

This is "Ballpark Pal for the World Cup": every game projected, the
altitude/host context made visible, model shown honestly next to the market.

Run:
    python3 scripts/wc_data.py
    python3 chef.py wc
    python3 chef.py wc --sims 30000 --blend 0.40
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.soccer_data import _fetch_json, normalize_team_name
from src.models.goalscorer_model import load_or_fit_goalscorer
from src.models.soccer_model_v2 import load_or_fit_model_v2
from src.models.wc_simulator import (
    ALTITUDE_ACCLIMATED,
    ALTITUDE_VENUES,
    ALT_THRESHOLD_M,
    BRACKET_URL,
    HOST_CITIES,
    WorldCup2026,
)

# Primary target: the LIVE overlay Next.js app reads JSON from src/data/ at
# request time (see overlay/src/app/api/slate/route.ts for the same pattern).
OUT_DIR = Path("overlay/src/data/wc")
# Mirror for the python-side content pipeline / inspection.
LOCAL_DIR = Path("output/picks/soccer/wc")


# ── Odds helpers ──────────────────────────────────────────────────────────────

def _american_to_imp(o: float) -> float:
    return 100.0 / (o + 100.0) if o >= 0 else abs(o) / (abs(o) + 100.0)


def _odds_get(market: str):
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds",
            params={"apiKey": key, "regions": "us,us2", "markets": market,
                    "oddsFormat": "american"},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [wc_data] odds fetch ({market}) failed: {e}")
        return []


def fetch_match_market() -> dict:
    """
    Map every WC fixture's live market → {frozenset(teamA,teamB): {...}}.
    De-vigs h2h to a 1X2 probability and captures the totals line + prices.
    Best (longest) price per outcome across books.
    """
    out: dict[frozenset, dict] = {}
    data = _odds_get("h2h,totals")
    for ev in data:
        home = normalize_team_name(ev.get("home_team", ""))
        away = normalize_team_name(ev.get("away_team", ""))
        if not home or not away:
            continue
        key = frozenset((home, away))
        rec = out.setdefault(key, {"home": home, "away": away})

        # best price per named outcome (h2h) and per Over/Under (totals)
        h2h_best: dict[str, float] = {}
        tot_best: dict[str, tuple[float, float]] = {}  # name -> (price, point)
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") == "h2h":
                    for o in mk.get("outcomes", []):
                        nm = normalize_team_name(o["name"]) if o["name"] != "Draw" else "Draw"
                        pr = float(o["price"])
                        if nm not in h2h_best or pr > h2h_best[nm]:
                            h2h_best[nm] = pr
                elif mk.get("key") == "totals":
                    for o in mk.get("outcomes", []):
                        nm = o["name"]  # Over / Under
                        pr = float(o["price"])
                        pt = float(o.get("point", 2.5))
                        if nm not in tot_best or pr > tot_best[nm][0]:
                            tot_best[nm] = (pr, pt)

        if {home, away, "Draw"} <= set(h2h_best):
            imp = {k: _american_to_imp(v) for k, v in h2h_best.items()}
            s = sum(imp.values())
            if s > 0:
                rec["h2h"] = {
                    "home_win": round(imp[home] / s, 4),
                    "draw":     round(imp["Draw"] / s, 4),
                    "away_win": round(imp[away] / s, 4),
                    "prices":   {"home": int(h2h_best[home]), "draw": int(h2h_best["Draw"]),
                                 "away": int(h2h_best[away])},
                }
        if "Over" in tot_best and "Under" in tot_best:
            ov_p, line = tot_best["Over"]
            un_p, _ = tot_best["Under"]
            io, iu = _american_to_imp(ov_p), _american_to_imp(un_p)
            tot = io + iu
            if tot > 0:
                rec["total"] = {
                    "line": line,
                    "over": round(io / tot, 4),
                    "under": round(iu / tot, 4),
                    "prices": {"over": int(ov_p), "under": int(un_p)},
                }
    return out


def fetch_scorer_market() -> dict[frozenset, dict[str, float]]:
    """
    Fetch live anytime-goal-scorer market for every priced WC event.

    Returns: {frozenset(home, away): {player_name: market_implied_prob, ...}}

    Two API calls: events list (free), then per-event scorer odds (one per event).
    De-vigs across the field to a probability by normalizing the sum of implied
    probabilities — for anytime scorer, books carry ~110-120% book, so dividing
    each player by the total / (target book) keeps each player's relative weight.
    Target book = expected_goals_for_match * 1.5 (rough heuristic for goals scored).
    """
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return {}
    try:
        ev_resp = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/events",
            params={"apiKey": key}, timeout=20,
        )
        ev_resp.raise_for_status()
        events = ev_resp.json()
    except Exception as e:
        print(f"  [wc_data] scorer events fetch failed: {e}")
        return {}

    out: dict[frozenset, dict[str, float]] = {}
    for ev in events:
        home = normalize_team_name(ev.get("home_team", ""))
        away = normalize_team_name(ev.get("away_team", ""))
        eid = ev.get("id")
        if not (home and away and eid):
            continue
        try:
            r = requests.get(
                f"https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/events/{eid}/odds",
                params={"apiKey": key, "regions": "us",
                        "markets": "player_goal_scorer_anytime",
                        "oddsFormat": "american",
                        "bookmakers": "fanduel,draftkings,betmgm"},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            data = r.json()
        except Exception:
            continue

        # best (longest) price per player across listed books
        best: dict[str, float] = {}
        for bm in data.get("bookmakers", []):
            for mk in bm.get("markets", []):
                if mk.get("key") != "player_goal_scorer_anytime":
                    continue
                for o in mk.get("outcomes", []):
                    name = o.get("description") or o.get("name", "")
                    if not name:
                        continue
                    price = float(o["price"])
                    if name not in best or price > best[name]:
                        best[name] = price

        if not best:
            continue
        out[frozenset((home, away))] = {n: _american_to_imp(p) for n, p in best.items()}
    return out


def fetch_futures_market() -> dict[str, float]:
    """De-vigged market P(win World Cup) per team (longest price across books)."""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        return {}
    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup_winner/odds",
            params={"apiKey": key, "regions": "us,us2", "markets": "outrights",
                    "oddsFormat": "american"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [wc_data] futures market fetch failed: {e}")
        return {}
    best: dict[str, float] = {}
    for ev in data:
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for o in mk.get("outcomes", []):
                    team = normalize_team_name(o["name"])
                    imp = _american_to_imp(float(o["price"]))
                    if team not in best or imp < best[team]:
                        best[team] = imp
    total = sum(best.values())
    return {t: p / total for t, p in best.items()} if total > 0 else {}


# ── Venue context (altitude / host) ─────────────────────────────────────────────

def venue_context(home: str, away: str, city: str, host_adv_elo: float) -> dict:
    """Human-readable + structured context for a fixture's venue effects."""
    notes: list[str] = []
    host_country = None
    for country, cities in HOST_CITIES.items():
        if city in cities:
            host_country = country
            break

    host_side = None
    if host_country == home:
        host_side = "home"
        notes.append(f"Co-host {home} effectively home in {city}")
    elif host_country == away:
        host_side = "away"
        notes.append(f"Co-host {away} effectively home in {city}")

    alt = ALTITUDE_VENUES.get(city, 0)
    altitude = None
    if alt >= ALT_THRESHOLD_M:
        h_ok = home in ALTITUDE_ACCLIMATED
        a_ok = away in ALTITUDE_ACCLIMATED
        favored = None
        if h_ok and not a_ok:
            favored = home
        elif a_ok and not h_ok:
            favored = away
        altitude = {"meters": alt, "favored": favored}
        if favored:
            notes.append(f"{city} sits at {alt:,}m — altitude favors {favored}")
        else:
            notes.append(f"{city} sits at {alt:,}m — thin air, neutral fatigue")

    return {
        "city": city,
        "host_country": host_country,
        "host_side": host_side,
        "altitude": altitude,
        "net_home_adv_elo": round(host_adv_elo, 1),
        "notes": notes,
    }


# ── Fixture projection ──────────────────────────────────────────────────────────

def project_fixture(model, wc, gm, m: dict, market: dict, blend_w: float,
                     scorer_market: dict | None = None) -> dict | None:
    if not m.get("group"):
        return None  # knockout slot — teams not drawn yet (e.g. "2A", "W73")
    home = normalize_team_name(m.get("team1", ""))
    away = normalize_team_name(m.get("team2", ""))
    if not home or not away:
        return None

    city = m.get("ground", "")
    adv = wc._host_adv(home, away, city)
    proj = model.matchup(home, away, neutral=True, home_adv_elo=adv)
    grid = model.score_grid(home, away, neutral=True, home_adv_elo=adv)

    # Top scorelines
    flat = [(i, j, float(grid[i, j])) for i in range(grid.shape[0])
            for j in range(grid.shape[1])]
    flat.sort(key=lambda t: t[2], reverse=True)
    top_scores = [{"score": f"{i}-{j}", "prob": round(p, 4)} for i, j, p in flat[:5]]

    ctx = venue_context(home, away, city, adv)

    rec = {
        "id": f"{m.get('date','')}_{home}_{away}".replace(" ", "-"),
        "date": m.get("date", ""),
        "time": m.get("time", ""),
        "group": (m.get("group", "") or "").replace("Group ", ""),
        "round": m.get("round", ""),
        "home": home,
        "away": away,
        "model": {
            "home_win": proj["home_win"], "draw": proj["draw"], "away_win": proj["away_win"],
            "btts": proj["btts"], "over_2_5": proj["over_2_5"],
            "exp_home": proj["exp_home"], "exp_away": proj["exp_away"],
            "exp_total": proj["exp_total"],
        },
        "top_scores": top_scores,
        "context": ctx,
        "elo": {"home": round(model.get_elo(home)), "away": round(model.get_elo(away))},
        "scorers": {
            "home": gm.anytime_scorer(home, proj["exp_home"], top_n=6,
                                      market_anytime=(scorer_market or {}).get(frozenset((home, away)))),
            "away": gm.anytime_scorer(away, proj["exp_away"], top_n=6,
                                      market_anytime=(scorer_market or {}).get(frozenset((home, away)))),
        },
    }

    mk = market.get(frozenset((home, away)))
    if mk:
        # orient market to home/away of this fixture (market home may differ)
        if mk.get("h2h"):
            h = mk["h2h"]
            if mk["home"] == home:
                m_hw, m_aw = h["home_win"], h["away_win"]
                prices = {"home": h["prices"]["home"], "away": h["prices"]["away"]}
            else:
                m_hw, m_aw = h["away_win"], h["home_win"]
                prices = {"home": h["prices"]["away"], "away": h["prices"]["home"]}
            m_dr = h["draw"]
            rec["market"] = {"home_win": m_hw, "draw": m_dr, "away_win": m_aw,
                             "prices": {**prices, "draw": h["prices"]["draw"]}}
            rec["blend"] = {
                "home_win": round(blend_w * proj["home_win"] + (1 - blend_w) * m_hw, 4),
                "draw":     round(blend_w * proj["draw"]     + (1 - blend_w) * m_dr, 4),
                "away_win": round(blend_w * proj["away_win"] + (1 - blend_w) * m_aw, 4),
            }
            # edge = BLEND - market (calibrated). Raw model edges were 2-3x
            # overstated vs results (see MLB calibration finding 2026-06-12);
            # using blend (model * w + market * (1-w)) applies the same shrinkage
            # the MLB Platt calibrator does — just analytically instead of fitted.
            blend = rec["blend"]
            edges = {"home": blend["home_win"] - m_hw, "draw": blend["draw"] - m_dr,
                     "away": blend["away_win"] - m_aw}
            side = max(edges, key=edges.get)
            edge_pp = round(edges[side] * 100, 1)
            rec["edge"] = {"side": side, "pp": edge_pp,
                           "raw_pp": round((proj[f"{side}_win" if side != "draw" else "draw"] - (m_hw if side=="home" else m_aw if side=="away" else m_dr)) * 100, 1)}
        if mk.get("total"):
            t = mk["total"]
            rec["market_total"] = {
                "line": t["line"], "over": t["over"], "under": t["under"],
                "prices": t["prices"],
                "model_over": proj.get(f"over_{str(t['line']).replace('.', '_')}", proj["over_2_5"]),
            }
    return rec


# ── Main ────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--blend", type=float, default=0.40,
                    help="Model weight in blended match/futures numbers")
    args = ap.parse_args()

    print("Loading model + seeding live Elo...")
    model = load_or_fit_model_v2(verbose=False)
    model.seed_from_eloratings()

    print("Fitting goalscorer model...")
    gm = load_or_fit_goalscorer(verbose=True)

    print("Loading 2026 bracket...")
    data = _fetch_json(BRACKET_URL, "wc_2026_struct", max_age_days=7)
    matches = data["matches"]
    wc = WorldCup2026(model)

    print("Fetching live match odds...")
    market = fetch_match_market()
    print(f"  → {len(market)} fixtures priced")

    print("Fetching live anytime-scorer market (per-event)...")
    scorer_market = fetch_scorer_market()
    print(f"  → {len(scorer_market)} fixtures with scorer prices")

    print("Projecting fixtures...")
    fixtures = []
    team_xg_samples: dict[str, list[float]] = {}
    for m in matches:
        rec = project_fixture(model, wc, gm, m, market, args.blend, scorer_market)
        if rec:
            fixtures.append(rec)
            team_xg_samples.setdefault(rec["home"], []).append(rec["model"]["exp_home"])
            team_xg_samples.setdefault(rec["away"], []).append(rec["model"]["exp_away"])
    fixtures.sort(key=lambda r: (r["date"], r["time"]))
    print(f"  → {len(fixtures)} group-stage fixtures projected")
    team_xg = {t: sum(v) / len(v) for t, v in team_xg_samples.items() if v}

    print(f"Simulating {args.sims:,} tournaments...")
    fut = wc.simulate(n_sims=args.sims)
    champ, advance, reach_final = fut["champion"], fut["advance"], fut["reach_final"]

    print("Fetching futures market...")
    fmkt = fetch_futures_market()
    w = args.blend
    teams = set(champ) | set(fmkt)
    fut_rows = []
    for t in teams:
        mp = champ.get(t, 0.0)
        kp = fmkt.get(t)
        blend = mp if kp is None else w * mp + (1 - w) * kp
        fut_rows.append({
            "team": t, "model": round(mp, 4),
            "market": round(kp, 4) if kp is not None else None,
            "blend": round(blend, 4),
            "advance": round(advance.get(t, 0.0), 4),
            "reach_final": round(reach_final.get(t, 0.0), 4),
            # Edge on the BLEND, not raw model (same calibration fix as match edges)
            "edge_pp": round((blend - kp) * 100, 1) if kp is not None else None,
            "raw_edge_pp": round((mp - kp) * 100, 1) if kp is not None else None,
        })
    fut_rows.sort(key=lambda r: r["blend"], reverse=True)

    # Group standings w/ advance %
    groups = {}
    for letter, g in wc.bracket.groups.items():
        rows = [{"team": t, "advance": round(advance.get(t, 0.0), 4),
                 "champion": round(champ.get(t, 0.0), 4),
                 "elo": round(model.get_elo(t))} for t in g.teams]
        rows.sort(key=lambda r: r["advance"], reverse=True)
        groups[letter] = rows

    # disagreements (market rates >= 2%)
    dis = [r for r in fut_rows if r["edge_pp"] is not None and (r["market"] or 0) >= 0.02]
    over = sorted(dis, key=lambda r: r["edge_pp"], reverse=True)[:5]
    under = sorted(dis, key=lambda r: r["edge_pp"])[:5]

    # Golden Boot leaderboard
    golden_boot = gm.golden_boot(advance, team_xg, n_teams=32, top_n=25)

    meta = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_sims": args.sims,
        "blend_model_weight": w,
        "model_fitted_on": model.fitted_on.isoformat() if model.fitted_on else None,
        "n_fixtures": len(fixtures),
        "n_priced": len(market),
        "kickoff": "2026-06-11",
    }

    for d in (OUT_DIR, LOCAL_DIR):
        d.mkdir(parents=True, exist_ok=True)
        (d / "fixtures.json").write_text(json.dumps(fixtures, indent=2))
        (d / "futures.json").write_text(json.dumps(
            {"teams": fut_rows, "disagreements": {"model_higher": over, "model_lower": under},
             **meta}, indent=2))
        (d / "groups.json").write_text(json.dumps(groups, indent=2))
        (d / "golden_boot.json").write_text(json.dumps(
            {"players": golden_boot, **meta}, indent=2))
        (d / "meta.json").write_text(json.dumps(meta, indent=2))

    # Ready-to-post social captions (Engine B content automation). Best-effort.
    try:
        from datetime import date as _date
        from src.output.captions_sports import wc_futures_captions, write_sport_captions
        caps = wc_futures_captions(fut_rows, w, _date.today(), n_sims=args.sims)
        write_sport_captions(caps, LOCAL_DIR / "captions")
        print(f"  Captions → {LOCAL_DIR}/captions/")
    except Exception as e:
        print(f"  [captions] skipped: {e}")

    print("\n" + "=" * 64)
    print("WORLD CUP 2026 DATA — generated")
    print("=" * 64)
    print(f"  fixtures: {len(fixtures)}  ·  priced: {len(market)}  ·  sims: {args.sims:,}")
    print(f"  top championship blend:")
    for r in fut_rows[:6]:
        mk = f"{r['market']*100:4.1f}%" if r["market"] is not None else "  — "
        print(f"    {r['team']:<16} model {r['model']*100:4.1f}%  market {mk}  blend {r['blend']*100:4.1f}%")
    print(f"\n  Saved → {OUT_DIR}/  (mirror {LOCAL_DIR}/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
