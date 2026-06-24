"""
CLV Tracker — Closing Line Value analysis.

CLV = the line at game time vs the line you got.
Positive CLV over many bets = your process is +EV regardless of results.

How to use:
  1. After running `predict.py --daily`, call snapshot_opening_lines() to
     freeze today's odds as the "opening" (pick-time) line.
  2. After games start (or at game time), call fetch_closing_lines() to pull
     the final odds from the cache.
  3. Call compute_clv(date_str) to score each pick.
  4. Call print_clv_report() to see the dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


# ── Paths ──────────────────────────────────────────────────────────────────────

SNAPSHOTS_FILE = Path("data/clv/snapshots.json")
ODDS_CACHE_DIR  = Path("data/cache/odds")
PICKS_OUTPUT_DIR = Path("output/picks")


# ── Helpers ───────────────────────────────────────────────────────────────────

# Canonical sport key aliases — same table as schema.py so CLV join always matches.
_SPORT_ALIASES: dict[str, str] = {
    "baseball_mlb":                 "mlb",
    "basketball_nba":               "nba",
    "basketball_nba_summer_league": "nba",
    "basketball_wnba":              "wnba",
    "americanfootball_nfl":         "nfl",
    "americanfootball_ncaaf":       "ncaaf",
    "basketball_ncaab":             "ncaab",
    "icehockey_nhl":                "nhl",
}


def _normalize_sport(sport: str) -> str:
    """Normalize Odds API sport key to short canonical form (e.g. baseball_mlb → mlb)."""
    s = str(sport).lower().strip()
    return _SPORT_ALIASES.get(s, s)


# Closing-line archives currently store moneyline only (BestHomeML/BestAwayML).
# Scoring any other market against them produces a bogus team-name join — e.g.
# an "F5 UNDER 4.5 (Brewers @ Astros)" totals pick matched to the Brewers'
# moneyline close. Only moneyline-equivalent markets are valid to score today.
_MONEYLINE_MARKETS = {"moneyline", "h2h", "ml"}

# Map full Odds API sport keys → the short prefix capture_closing.py writes
# (e.g. archives are "soccer_DATE", not "soccer_fifa_world_cup_DATE"). Shared by
# every closing-archive reader so soccer/mma resolve consistently.
_SHORT_PREFIX_MAP = {
    "soccer_fifa_world_cup":     "soccer",
    "soccer_spain_la_liga":      "soccer",
    "soccer_italy_serie_a":      "soccer",
    "soccer_germany_bundesliga": "soccer",
    "soccer_usa_mls":            "soccer",
    "mma_mixed_martial_arts":    "ufc",
}


def _is_moneyline_market(market) -> bool:
    """True if a snapshot can be scored against a moneyline-only closing line.

    Legacy snapshots predate the `market` field; they are plain team-vs-team
    moneyline picks (team name + opponent), so a missing/empty market counts.
    """
    if market is None:
        return True
    s = str(market).lower().strip()
    return s == "" or s in _MONEYLINE_MARKETS


def _ou_side(text) -> str | None:
    """'over'/'under' if the text names a totals side, else None."""
    t = str(text or "").lower()
    return "over" if "over" in t else "under" if "under" in t else None


def _parse_prop_selection(team: str) -> tuple[str, str | None, float | None]:
    """Parse a prop pick's packed `team` string into (player, direction, line).

    Picks store props as "Framber Valdez UNDER 5.5". Returns the clean player
    name, OVER/UNDER, and the numeric line — the fields _score_prop needs.
    """
    s = str(team or "").strip()
    direction = None
    for tok in (" OVER ", " UNDER ", " over ", " under "):
        if tok in s:
            direction = tok.strip().upper()
            s_player, _, rest = s.partition(tok)
            # line is the leading numeric token of the remainder
            line = None
            for w in rest.split():
                try:
                    line = float(w)
                    break
                except ValueError:
                    continue
            return s_player.strip(), direction, line
    # No OVER/UNDER token — strip a trailing numeric line if present
    parts = s.split()
    line = None
    if parts:
        try:
            line = float(parts[-1])
            parts = parts[:-1]
        except ValueError:
            pass
    return " ".join(parts).strip(), direction, line


def _odds_to_implied(odds: float | int) -> float:
    """Convert American odds to implied probability (no vig removed)."""
    if odds == 0:
        return 0.5
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _devig_prob(picked_odds: float, *opponent_odds: float) -> float:
    """
    De-vig an N-way market using the additive (Pinnacle) method.
    Returns the fair probability for the picked side.

    2-way (e.g. baseball ML): picked=-150, opponent=+130 → overround 1.035 → 0.580
    3-way (soccer W/D/L): pass BOTH other outcomes (opponent + draw). Omitting the
    draw was a bug — overround summed to ~0.75 (<1), so dividing INFLATED the prob
    (e.g. a +525 dog reading as a huge positive CLV). The fair prob must divide by
    the sum of ALL mutually-exclusive outcomes in the market.
    """
    raw_picked = _odds_to_implied(picked_odds)
    overround  = raw_picked + sum(_odds_to_implied(o) for o in opponent_odds
                                  if o is not None)
    if overround <= 0:
        return raw_picked
    return raw_picked / overround


def _load_snapshots() -> list[dict]:
    SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SNAPSHOTS_FILE.exists():
        return []
    try:
        return json.loads(SNAPSHOTS_FILE.read_text())
    except (json.JSONDecodeError, ValueError):
        return []


def _save_snapshots(records: list[dict]) -> None:
    SNAPSHOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_FILE.write_text(json.dumps(records, indent=2))


# ── Core functions ─────────────────────────────────────────────────────────────

def snapshot_opening_lines(
    picks_json_path: str | Path | None = None,
    sport: str = "baseball_mlb",
    game_date: "date | None" = None,
) -> int:
    """
    Read today's generated picks from output/picks/<sport>/YYYYMMDD/picks.json
    and store each pick's current odds as the "opening line" in
    data/clv/snapshots.json.

    Returns the number of new snapshots added.

    Schema stored per pick:
      {date, team, opponent, opening_odds, opening_implied_prob, snapshot_time}
    """
    from datetime import date as _date

    effective_date = game_date or _date.today()
    today_str = effective_date.strftime("%Y%m%d")

    if picks_json_path is None:
        picks_json_path = PICKS_OUTPUT_DIR / sport / today_str / "picks.json"

    picks_json_path = Path(picks_json_path)
    if not picks_json_path.exists():
        print(f"  [CLV] No picks file found at {picks_json_path}")
        return 0

    try:
        picks = json.loads(picks_json_path.read_text())
    except (json.JSONDecodeError, ValueError):
        print(f"  [CLV] Could not parse {picks_json_path}")
        return 0

    snapshots = _load_snapshots()
    snap_keys = {
        (s.get("date", ""), s.get("team", "").lower().strip())
        for s in snapshots
    }

    now_ts   = datetime.now(tz=timezone.utc).isoformat()
    date_str = effective_date.isoformat()
    added    = 0

    for pick in picks:
        # Support both old format (Team/BestOdds) and canonical schema (team/odds)
        team = str(pick.get("Team") or pick.get("team") or "").strip()
        if not team:
            continue
        key = (date_str, team.lower().strip())
        if key in snap_keys:
            continue

        odds = float(pick.get("BestOdds") or pick.get("odds") or pick.get("best_odds") or 0)
        snap = {
            "date":                 date_str,
            "team":                 team,
            "opponent":             str(pick.get("Opponent") or pick.get("matchup") or "?").strip(),
            "sport":                _normalize_sport(sport),
            "market":               str(pick.get("market") or pick.get("Market") or "moneyline"),
            "opening_odds":         odds,
            "opening_implied_prob": round(_odds_to_implied(odds), 6),
            "snapshot_time":        now_ts,
            "closing_odds":         None,
            "closing_implied_prob": None,
            "clv":                  None,
            "clv_pct":              None,
        }
        snapshots.append(snap)
        snap_keys.add(key)
        added += 1

    if added > 0:
        _save_snapshots(snapshots)

    return added


def snapshot_from_pnl(date_str: str | None = None) -> int:
    """
    Snapshot opening lines for all picks on date_str directly from picks.json.
    Works for all sports (MLB, NBA, NHL, WNBA, soccer, tennis, PGA).
    Returns number of new snapshots added.
    """
    from datetime import date as _date
    PNL_FILE = Path("data/pnl/picks.json")
    if not PNL_FILE.exists():
        return 0

    effective_date = date_str or _date.today().isoformat()
    try:
        _raw = json.loads(PNL_FILE.read_text())
        all_picks = _raw.get("picks", []) if isinstance(_raw, dict) else _raw
    except (json.JSONDecodeError, OSError, AttributeError):
        return 0

    day_picks = [p for p in all_picks if isinstance(p, dict) and p.get("date") == effective_date]
    if not day_picks:
        return 0

    snapshots = _load_snapshots()
    # Dedup key includes strategy so a shadow-strategy pick gets its own snapshot
    # even when a card pick exists for the same team/market. Existing rows have
    # strategy=None, so their grouping is unchanged.
    snap_keys = {
        (s.get("date", ""), s.get("team", "").lower().strip(),
         s.get("market", ""), s.get("strategy"))
        for s in snapshots
    }

    now_ts = datetime.now(tz=timezone.utc).isoformat()
    added = 0

    for pick in day_picks:
        team = str(pick.get("team") or "").strip()
        if not team:
            continue
        market = str(pick.get("market") or "moneyline")
        strategy = pick.get("strategy")
        key = (effective_date, team.lower().strip(), market, strategy)
        if key in snap_keys:
            continue

        odds = float(pick.get("odds") or pick.get("best_odds") or 0)
        line = pick.get("line")
        # ── Extract clean player name for prop CLV matching ───────────────────
        # Prop picks store "Player Name OVER 5.5" in `team`. Closing-archive
        # rows store just "Player Name". Strip the OVER/UNDER/line suffix so
        # the prop CLV joiner can match them against the closing snapshot.
        _extra_prop = {"anytime_scorer", "player_goal_scorer_anytime",
                       "method_of_victory", "fight_result_method"}
        player = pick.get("player")
        if not player and (_is_prop_market(market) or market in _extra_prop):
            cleaned = team
            for tok in (" OVER ", " UNDER ", " ATG ", " - "):
                if tok in cleaned:
                    cleaned = cleaned.split(tok)[0]
                    break
            # Strip trailing line numbers like "5.5"
            parts = cleaned.split()
            while parts and (parts[-1].replace(".", "").replace("-", "").isdigit() or parts[-1] in ("+", "-")):
                parts.pop()
            player = " ".join(parts).strip()

        snap = {
            "date":                 effective_date,
            "team":                 team,
            "player":               player,
            "opponent":             str(pick.get("matchup") or "?").strip(),
            "sport":                _normalize_sport(str(pick.get("sport") or "mlb")),
            "market":               market,
            "strategy":             strategy,
            # opening_line + direction are needed to score spread/total CLV
            # (the points you got, not just the price). Null for moneyline.
            "opening_line":         float(line) if line is not None else None,
            "direction":            (str(pick.get("direction")).upper() if pick.get("direction") else None),
            "opening_odds":         odds,
            "opening_implied_prob": round(_odds_to_implied(odds), 6),
            "snapshot_time":        now_ts,
            "closing_odds":         None,
            "closing_implied_prob": None,
            "clv":                  None,
            "clv_pct":              None,
        }
        snapshots.append(snap)
        snap_keys.add(key)
        added += 1

    if added > 0:
        _save_snapshots(snapshots)

    return added


def backfill_snapshots_from_pnl() -> int:
    """
    Backfill opening-line snapshots for all dates in picks.json.
    Safe to run multiple times (deduplicates).
    """
    PNL_FILE = Path("data/pnl/picks.json")
    if not PNL_FILE.exists():
        return 0
    try:
        _raw = json.loads(PNL_FILE.read_text())
        all_picks = _raw.get("picks", []) if isinstance(_raw, dict) else _raw
    except (json.JSONDecodeError, OSError, AttributeError):
        return 0

    dates = sorted({p.get("date") for p in all_picks if isinstance(p, dict) and p.get("date")})
    total = 0
    for d in dates:
        n = snapshot_from_pnl(d)
        if n:
            print(f"  [CLV backfill] {d}: {n} picks snapshotted")
            total += n
    print(f"  [CLV backfill] Total: {total} new snapshots added across {len(dates)} dates")
    return total


_PROP_MARKETS = {
    "prop", "player_prop", "pitcher_strikeouts", "player_points", "player_rebounds",
    "player_assists", "player_threes", "player_goals", "player_shots_on_goal",
    "player_steals", "anytime_scorer", "player_goal_scorer_anytime",
}

# Over/under player props all share a prefix in the Odds API; detect them
# generically so every prop type (batter_hits, pitcher_outs, player_blocks, …)
# is its own CLV-tracked market without maintaining a hardcoded list.
_PROP_PREFIXES = ("batter_", "pitcher_", "player_")


def _is_prop_market(market) -> bool:
    m = str(market or "").lower()
    return m in _PROP_MARKETS or m.startswith(_PROP_PREFIXES)


def upgrade_snapshots() -> int:
    """Repair legacy prop snapshots in place so they can be scored.

    Older snapshots packed everything into `team` ("Framber Valdez UNDER 5.5")
    and never set `player`/`opening_line`/`direction` — the fields _score_prop
    requires. This re-derives them from the team string for any prop snapshot
    that is missing them. Idempotent. Returns the number of snapshots upgraded.
    """
    snapshots = _load_snapshots()
    upgraded = 0
    for s in snapshots:
        market = str(s.get("market") or "").lower()
        if market not in _PROP_MARKETS:
            continue
        needs = (s.get("player") is None or s.get("opening_line") is None
                 or s.get("direction") is None)
        if not needs:
            continue
        player, direction, line = _parse_prop_selection(s.get("team", ""))
        changed = False
        if s.get("player") is None and player:
            s["player"] = player; changed = True
        if s.get("direction") is None and direction:
            s["direction"] = direction; changed = True
        if s.get("opening_line") is None and line is not None:
            s["opening_line"] = line; changed = True
        if changed:
            upgraded += 1
    if upgraded:
        _save_snapshots(snapshots)
        print(f"  [CLV] upgraded {upgraded} legacy prop snapshot(s)")
    return upgraded


def backfill_snapshot_markets() -> int:
    """Repair legacy snapshots whose `market` field was never set.

    Early snapshots (≤ mid-May 2026) were written without a market, so the CLV
    engine defaulted them to the moneyline scoring path — meaning spread/total
    picks got scored against a MONEYLINE closing (garbage CLV), not just
    mislabeled. This recovers the true market by matching each orphan snapshot to
    its pick in picks.json on a unique (date, team) key, then CLEARS the stale
    (wrong) CLV fields so the next compute_clv re-scores it on the correct basis.
    Snapshots with no unambiguous pick match are tagged 'unknown_legacy' and
    their bad CLV cleared, so they drop out of the edge gate instead of polluting
    it. Idempotent. Returns the number repaired.
    """
    import json as _json
    snapshots = _load_snapshots()
    unset = [s for s in snapshots
             if isinstance(s, dict) and not str(s.get("market") or "").strip()]
    if not unset:
        return 0

    # Index picks by (date, team_lower) -> set of markets
    pnl = Path("data/pnl/picks.json")
    idx: dict = {}
    try:
        blob = _json.loads(pnl.read_text())
        picks = blob.get("picks", blob) if isinstance(blob, dict) else blob
        for p in picks:
            if not isinstance(p, dict):
                continue
            k = (p.get("date"), str(p.get("team", "")).lower().strip())
            idx.setdefault(k, set()).add(p.get("market"))
    except (OSError, ValueError):
        pass

    _CLV_FIELDS = ("clv", "clv_pct", "line_clv", "price_clv_pct", "beat_close",
                   "closing_odds", "closing_line", "closing_implied_prob")
    repaired = 0
    for s in unset:
        k = (s.get("date"), str(s.get("team", "")).lower().strip())
        mk = idx.get(k)
        if mk and len(mk) == 1 and next(iter(mk)):
            s["market"] = next(iter(mk))
        else:
            s["market"] = "unknown_legacy"
        # Clear any CLV computed under the wrong (defaulted-moneyline) basis so it
        # re-scores correctly for its real market on the next compute_clv pass.
        for f in _CLV_FIELDS:
            s.pop(f, None)
        repaired += 1

    if repaired:
        _save_snapshots(snapshots)
        print(f"  [CLV] backfilled market on {repaired} legacy snapshot(s) "
              f"(stale CLV cleared for re-scoring)")
    return repaired


def backfill_snapshot_lines() -> int:
    """Repair total/spread/f5 snapshots missing opening_line / direction.

    The bet is encoded in the team string ('OVER 9.5', 'UNDER 174.5', 'Team -1.5')
    but legacy snapshots left opening_line/direction null — and the totals/spread
    scorer needs both to compute line CLV, so those picks NEVER score even when the
    closing line was captured and the matchup matches. This re-derives both from the
    team string, in place, and clears any stale CLV so the next compute_clv scores
    them on the recovered line. Idempotent. Returns the number repaired.
    """
    import re
    snapshots = _load_snapshots()
    line_markets = {"total", "totals", "f5_total", "f5_totals", "first_5_total",
                    "spread", "run_line", "runline", "puck_line", "puckline"}
    fixed = 0
    for s in snapshots:
        if not isinstance(s, dict):
            continue
        if str(s.get("market") or "").lower() not in line_markets:
            continue
        if s.get("opening_line") is not None and s.get("direction"):
            continue  # already complete
        team = str(s.get("team") or "")
        changed = False
        m = re.search(r"\b(OVER|UNDER)\b\s*([0-9]+(?:\.[0-9]+)?)", team, re.IGNORECASE)
        if m:  # totals / f5 totals
            if not s.get("direction"):
                s["direction"] = m.group(1).upper(); changed = True
            if s.get("opening_line") is None:
                s["opening_line"] = float(m.group(2)); changed = True
        else:  # spread / run line / puck line — trailing signed number
            m2 = re.search(r"([+-][0-9]+(?:\.[0-9]+)?)\s*$", team.strip())
            if m2 and s.get("opening_line") is None:
                s["opening_line"] = float(m2.group(1)); changed = True
        if changed:
            for f in ("line_clv", "price_clv_pct", "beat_close", "closing_line"):
                s.pop(f, None)  # stale → re-score on the recovered line
            fixed += 1
    if fixed:
        _save_snapshots(snapshots)
        print(f"  [CLV] backfilled opening_line/direction on {fixed} total/spread snapshot(s)")
    return fixed


def fetch_closing_pairs(
    date_str: str | None = None,
    sport: str = "baseball_mlb",
) -> dict[str, tuple[float, float]]:
    """
    Like fetch_closing_lines but returns two-sided data for de-vig.
    Returns {team_lower: (team_odds, opponent_odds)} from the closing archive.
    Only available for archive files (not live cache fallback).
    """
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    # Use the same full→short prefix map as _load_closing_records — the naive
    # .replace() missed soccer/mma (archives are "soccer_DATE", not
    # "soccer_fifa_world_cup_DATE"), so soccer pairs were never found and
    # de-vig silently never ran for soccer (raw vigged odds → bad CLV).
    short_sport = _SHORT_PREFIX_MAP.get(
        sport,
        sport.replace("baseball_", "").replace("basketball_", "")
             .replace("hockey_", "").replace("icehockey_", ""))

    for prefix in [sport, short_sport]:
        archive_path = Path("data/clv/closing") / f"{prefix}_{date_str}.json"
        if not archive_path.exists():
            continue
        try:
            records = json.loads(archive_path.read_text().replace("NaN", "null"))
            pairs: dict[str, tuple] = {}
            is_soccer = "soccer" in prefix
            for row in records:
                # Accept both archive casings (HomeTeam / home_team).
                home = str(row.get("HomeTeam") or row.get("home_team") or "").lower().strip()
                away = str(row.get("AwayTeam") or row.get("away_team") or "").lower().strip()
                home_ml = row.get("BestHomeML")
                away_ml = row.get("BestAwayML")
                if not (home and away and home_ml is not None and away_ml is not None):
                    continue
                # Soccer is a 3-way market — pull the Draw price so de-vig divides
                # by all three outcomes. Without it the overround < 1 and CLV blows up.
                draw_ml = None
                if is_soccer:
                    for o in (row.get("all_odds") or []):
                        if str(o.get("Market")) == "h2h" and \
                           str(o.get("Selection") or o.get("Name")).lower() == "draw":
                            d = o.get("Odds")
                            if d is not None and (draw_ml is None or float(d) > draw_ml):
                                draw_ml = float(d)  # best (highest) draw price, matching Best*ML
                if draw_ml is not None:
                    pairs[home]   = (float(home_ml), float(away_ml), draw_ml)
                    pairs[away]   = (float(away_ml), float(home_ml), draw_ml)
                    pairs["draw"] = (draw_ml, float(home_ml), float(away_ml))
                else:
                    pairs[home] = (float(home_ml), float(away_ml))
                    pairs[away] = (float(away_ml), float(home_ml))
            if pairs:
                return pairs
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
    return {}


def fetch_closing_pinnacle(
    date_str: str | None = None,
    sport: str = "baseball_mlb",
) -> dict[str, tuple]:
    """
    Like fetch_closing_pairs, but pulls ONLY Pinnacle's h2h closing prices.

    Returns {team_lower: (pinn_odds, *other_pinn_odds)} from the closing archive's
    per-book `all_odds` rows. Pinnacle is the sharpest book (lowest margin, fastest
    to true) — its de-vigged close is the market's best estimate of true probability.
    CLV measured against THIS line is the honest test: "best price across all books"
    flatters us (we cherry-pick the loosest book), whereas beating Pinnacle's close
    is what actually predicts profit. Quants benchmark against the sharp close, not
    the best available number — this is that benchmark.

    Returns {} when the archive has no Pinnacle h2h rows (older captures, or a sport
    Pinnacle doesn't price) — callers fall back to the best-price pairs.
    """
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    short_sport = _SHORT_PREFIX_MAP.get(
        sport,
        sport.replace("baseball_", "").replace("basketball_", "")
             .replace("hockey_", "").replace("icehockey_", ""))

    for prefix in [sport, short_sport]:
        archive_path = Path("data/clv/closing") / f"{prefix}_{date_str}.json"
        if not archive_path.exists():
            continue
        try:
            records = json.loads(archive_path.read_text().replace("NaN", "null"))
            pairs: dict[str, tuple] = {}
            is_soccer = "soccer" in prefix
            for row in records:
                home = str(row.get("HomeTeam") or row.get("home_team") or "").lower().strip()
                away = str(row.get("AwayTeam") or row.get("away_team") or "").lower().strip()
                if not (home and away):
                    continue
                # Collect Pinnacle's h2h price for each selection in this event.
                pinn: dict[str, float] = {}
                for o in (row.get("all_odds") or []):
                    if str(o.get("Sportsbook")) != "Pinnacle":
                        continue
                    if str(o.get("Market")) != "h2h":
                        continue
                    sel = str(o.get("Selection") or o.get("Name") or "").lower().strip()
                    odds = o.get("Odds")
                    if sel and odds is not None:
                        pinn[sel] = float(odds)
                home_ml = pinn.get(home)
                away_ml = pinn.get(away)
                if home_ml is None or away_ml is None:
                    continue
                draw_ml = pinn.get("draw") if is_soccer else None
                if draw_ml is not None:
                    pairs[home]   = (home_ml, away_ml, draw_ml)
                    pairs[away]   = (away_ml, home_ml, draw_ml)
                    pairs["draw"] = (draw_ml, home_ml, away_ml)
                else:
                    pairs[home] = (home_ml, away_ml)
                    pairs[away] = (away_ml, home_ml)
            if pairs:
                return pairs
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
    return {}


def fetch_closing_lines(
    date_str: str | None = None,
    sport: str = "baseball_mlb",
) -> dict[str, float]:
    """
    Read closing lines from the date-specific archive first, then fall back
    to today's live odds cache.

    Returns a dict mapping team name (lower-case) -> best moneyline odds.
    """
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    closing: dict[str, list[float]] = {}

    # Try date-specific closing archive (most accurate — captured at game time).
    # Closing files may use either the full sport key (e.g. baseball_mlb_DATE.json)
    # or the short key (e.g. mlb_DATE.json). Use the SHARED prefix map — a naive
    # .replace() misses soccer/mma (archive is "soccer_DATE", not
    # "soccer_fifa_world_cup_DATE"), so World Cup closings were never read from the
    # archive and fell back to the live cache (absent in the cloud → 0 WC scored).
    short_sport = _SHORT_PREFIX_MAP.get(
        sport,
        sport.replace("baseball_", "").replace("basketball_", "").replace("hockey_", ""))
    for prefix in [sport, short_sport]:
        archive_path = Path("data/clv/closing") / f"{prefix}_{date_str}.json"
        if not archive_path.exists():
            continue
        try:
            records = json.loads(archive_path.read_text())
            for row in records:
                # Archive schema drifted: older files use HomeTeam/AwayTeam
                # (PascalCase), newer ones use home_team/away_team (snake_case).
                # Accept either so every date's closings join.
                home = str(row.get("HomeTeam") or row.get("home_team") or "").lower().strip()
                away = str(row.get("AwayTeam") or row.get("away_team") or "").lower().strip()
                home_ml = row.get("BestHomeML")
                away_ml = row.get("BestAwayML")
                if home and home_ml is not None:
                    closing.setdefault(home, []).append(float(home_ml))
                if away and away_ml is not None:
                    closing.setdefault(away, []).append(float(away_ml))
            if closing:
                return {
                    team: max(prices, key=lambda p: p if p > 0 else -10000 / abs(p))
                    for team, prices in closing.items()
                }
        except (json.JSONDecodeError, ValueError, KeyError):
            pass  # fall through to next prefix or live cache

    # Fall back to live odds cache (today's picks only — don't mix dates)
    cache_path = ODDS_CACHE_DIR / f"{sport}_latest.json"
    if not cache_path.exists():
        print(f"  [CLV] No closing archive for {date_str} and no live cache found.")
        return {}

    try:
        raw = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, ValueError):
        print(f"  [CLV] Could not parse odds cache: {cache_path}")
        return {}

    for game in raw:
        for book in game.get("bookmakers", []):
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    team_lower = outcome.get("name", "").lower().strip()
                    price      = outcome.get("price")
                    if team_lower and price is not None:
                        closing.setdefault(team_lower, []).append(float(price))

    return {
        team: max(prices, key=lambda p: p if p > 0 else -10000 / abs(p))
        for team, prices in closing.items()
    }


# ── Spread / total closings ─────────────────────────────────────────────────
# capture_closing.py already archives every book's spread+total lines inside
# each game's `all_odds`. These readers parse that (retroactively across every
# archive on disk) so spread/total CLV needs no new capture step.

# Sharpest-first book preference — the closing line we compare against. Pinnacle
# first (the reference book), then the major US books.
_SHARP_BOOK_ORDER = ["Pinnacle", "BetOnline.ag", "Circa", "FanDuel",
                     "DraftKings", "BetMGM", "Caesars", "BetRivers"]


def _pick_book_row(rows: list[dict], book: str | None = None) -> dict | None:
    """From rows for one event/market/selection, pick a book's row.

    book=None → sharpest available (Pinnacle-first via _SHARP_BOOK_ORDER, the
    "best estimate" map used for scoring). book="Pinnacle" → ONLY that book,
    returning None if it didn't price the selection — that's the strict sharp
    benchmark, never silently substituting a softer book.
    """
    by_book = {str(r.get("Sportsbook", "")): r for r in rows}
    if book is not None:
        return by_book.get(book)
    for b in _SHARP_BOOK_ORDER:
        if b in by_book:
            return by_book[b]
    return rows[0] if rows else None


# ── Sharp-CLV companion fields ────────────────────────────────────────────────
# Every market gets a "_sharp" twin of its CLV fields: the SAME pick scored
# against Pinnacle's close instead of the best price. Stored alongside (never
# overwriting) the best-price fields so the gate can show both and flag mirages
# (positive vs best, negative vs sharp = book-shopping, not skill).
_SHARP_KEY_MAP = {
    "clv":                  "clv_sharp",
    "clv_pct":              "clv_sharp_pct",
    "closing_implied_prob": "closing_imp_sharp",
    "closing_odds":         "closing_odds_sharp",
    "closing_line":         "closing_line_sharp",
    "line_clv":             "line_clv_sharp",
    "price_clv_pct":        "price_clv_sharp_pct",
    "beat_close":           "beat_close_sharp",
}
_SHARP_KEYS = set(_SHARP_KEY_MAP.values())


def _apply_sharp(snap: dict, result: dict | None) -> None:
    """Clear any stale sharp fields, then stamp the Pinnacle-scored result (if any).
    Always clearing first means a snapshot never keeps a sharp value from a prior
    run when Pinnacle no longer prices that game."""
    for k in _SHARP_KEYS:
        snap.pop(k, None)
    if result:
        for k, v in result.items():
            snap[_SHARP_KEY_MAP.get(k, k + "_sharp")] = v


def _resolve_spread_team(label: str, matchup: str) -> str | None:
    """Map a spread pick's team label (e.g. 'LAD -1.5 RL') to the full team name
    in `matchup` ('Away @ Home'). Handles full names, abbreviations, initials."""
    if "@" not in (matchup or ""):
        return None
    away, home = [t.strip() for t in matchup.split("@", 1)]
    ll = label.lower()
    for full in (home, away):
        if full and full.lower() in ll:           # full name appears in label
            return full
    lead = (ll.split()[0] if ll.split() else "")  # leading token, e.g. "lad"
    for full in (home, away):
        toks = full.lower().replace(".", "").split()
        if not toks:
            continue
        initials = "".join(t[0] for t in toks)
        if lead and (lead == initials or lead == toks[0][:3] or lead in toks):
            return full
    return None


def _load_closing_records(date_str: str, sport: str) -> list[dict]:
    """Load a closing archive trying both the full and short sport prefixes."""
    short = _SHORT_PREFIX_MAP.get(sport,
            sport.replace("baseball_", "").replace("basketball_", "")
                 .replace("hockey_", "").replace("icehockey_", ""))
    for prefix in (sport, short):
        path = Path("data/clv/closing") / f"{prefix}_{date_str}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, ValueError):
                continue
    return []


def _rec_matchup_key(rec: dict) -> frozenset | None:
    """frozenset({away_lower, home_lower}) for a closing record, or None."""
    home = str(rec.get("home_team") or rec.get("HomeTeam") or "").lower().strip()
    away = str(rec.get("away_team") or rec.get("AwayTeam") or "").lower().strip()
    return frozenset({away, home}) if home and away else None


def _select_windowed_records(date_str: str, sport: str,
                             day_window: int = 1) -> dict[frozenset, dict]:
    """Pick one closing record per game, tolerant of UTC date-boundary shifts.

    Night games (NBA/NHL) commence after midnight UTC, so their closing capture
    lands in the *next* day's archive file and an exact-date join misses them.
    This searches [date-window .. date+window] and, per matchup, applies a rule
    that is safe against recurring same-matchup series (MLB plays a team 3 days
    in a row — grabbing an adjacent day's file would score the wrong game):

      • prefer the exact-date record (distance 0) — always correct;
      • else accept an adjacent-date record ONLY if that matchup appears in
        exactly one file across the window (unambiguous singleton);
      • else skip (ambiguous — refuse to guess).
    """
    from datetime import date as _date, timedelta

    try:
        base = _date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return {rec_key: rec for rec in ()  # empty
                for rec_key in ()}

    # matchup -> list of (distance, record)
    groups: dict[frozenset, list[tuple[int, dict]]] = {}
    for off in range(-day_window, day_window + 1):
        ds = (base + timedelta(days=off)).isoformat()
        for rec in _load_closing_records(ds, sport):
            key = _rec_matchup_key(rec)
            if key is not None:
                groups.setdefault(key, []).append((abs(off), rec))

    chosen: dict[frozenset, dict] = {}
    for key, items in groups.items():
        exact = [rec for dist, rec in items if dist == 0]
        if exact:
            chosen[key] = exact[0]
        elif len(items) == 1:
            chosen[key] = items[0][1]
        # else: appears only on adjacent days in >1 file → ambiguous → skip
    return chosen


def fetch_closing_spreads(date_str: str, sport: str = "mlb",
                          book: str | None = None) -> dict[str, dict]:
    """{team_lower: {"line", "odds", "opp_odds"}} from the closing archive's
    spreads rows, using the sharpest available book per side. Pass book="Pinnacle"
    for the strict sharp benchmark (only games Pinnacle priced)."""
    out: dict[str, dict] = {}
    for _mkey, rec in _select_windowed_records(date_str, sport).items():
        rows = [r for r in (rec.get("all_odds") or []) if r.get("Market") == "spreads"]
        if not rows:
            continue
        home = str(rec.get("home_team") or rec.get("HomeTeam") or "")
        away = str(rec.get("away_team") or rec.get("AwayTeam") or "")
        bysel: dict[str, list[dict]] = {}
        for r in rows:
            bysel.setdefault(str(r.get("Selection") or ""), []).append(r)
        chosen: dict[str, tuple[float, float]] = {}
        for team, trows in bysel.items():
            row = _pick_book_row(trows, book)
            if row and row.get("Line") is not None and row.get("Odds") is not None:
                chosen[team] = (float(row["Line"]), float(row["Odds"]))
        for team, (line, odds) in chosen.items():
            opp = away if team == home else (home if team == away else None)
            opp_odds = chosen[opp][1] if opp in chosen else None
            out[team.lower().strip()] = {"line": line, "odds": odds, "opp_odds": opp_odds}
    return out


def fetch_closing_totals(date_str: str, sport: str = "mlb",
                         market_key: str = "totals",
                         book: str | None = None) -> dict[frozenset, dict]:
    """{frozenset({away_lower, home_lower}): {"line", "over", "under"}} from the
    closing archive's Over/Under rows for `market_key`, using the sharpest book
    offering both sides. market_key="totals_1st_5_innings" gives F5 totals.
    Pass book="Pinnacle" for the strict sharp benchmark."""
    out: dict[frozenset, dict] = {}
    for _mkey, rec in _select_windowed_records(date_str, sport).items():
        rows = [r for r in (rec.get("all_odds") or []) if r.get("Market") == market_key]
        if not rows:
            continue
        home = str(rec.get("home_team") or rec.get("HomeTeam") or "").lower().strip()
        away = str(rec.get("away_team") or rec.get("AwayTeam") or "").lower().strip()
        by_book: dict[str, dict[str, dict]] = {}
        for r in rows:
            by_book.setdefault(str(r.get("Sportsbook", "")), {})[str(r.get("Selection") or "")] = r
        chosen = None
        if book is not None:
            sides = by_book.get(book)
            if sides and "Over" in sides and "Under" in sides:
                chosen = sides
        else:
            for b in _SHARP_BOOK_ORDER:
                if b in by_book and "Over" in by_book[b] and "Under" in by_book[b]:
                    chosen = by_book[b]
                    break
            if chosen is None:
                for sides in by_book.values():
                    if "Over" in sides and "Under" in sides:
                        chosen = sides
                        break
        if not chosen:
            continue
        o, u = chosen["Over"], chosen["Under"]
        if o.get("Line") is None or o.get("Odds") is None or u.get("Odds") is None:
            continue
        out[frozenset({away, home})] = {
            "line": float(o["Line"]), "over": float(o["Odds"]), "under": float(u["Odds"]),
        }
    return out


def fetch_closing_f5_totals(date_str: str, sport: str = "mlb",
                            book: str | None = None) -> dict[frozenset, dict]:
    """First-5-innings totals (F5) — same shape as fetch_closing_totals."""
    return fetch_closing_totals(date_str, sport, market_key="totals_1st_5_innings",
                                book=book)


def fetch_closing_props(date_str: str, sport: str = "mlb", market_key: str = "pitcher_strikeouts",
                        book: str | None = None) -> dict[tuple, dict]:
    """
    Closing prop lines keyed by (player_name_lower, market).
    Returns {(player_lower, market): {"line": float, "over": odds, "under": odds, "book": str}}

    Supports any over/under prop market (pitcher_strikeouts, player_points,
    player_rebounds, player_assists, player_threes, player_goals, etc.)
    Pass book="Pinnacle" for the strict sharp benchmark (Pinnacle-priced props only).
    """
    out: dict[tuple, dict] = {}
    for _mkey, rec in _select_windowed_records(date_str, sport).items():
        rows = [r for r in (rec.get("all_odds") or []) if r.get("Market") == market_key]
        if book is not None:
            rows = [r for r in rows if str(r.get("Sportsbook", "")) == book]
        if not rows:
            continue
        # Group rows by (player, line) — a prop has Over + Under at the same line.
        # Archive schema drifted: newer rows store the player in `Name` and the
        # side in `Selection` ("Over"/"Under"); older rows put the side in `Name`
        # and the player in `Description`. Derive both robustly: the side is
        # whichever field reads over/under, the player is the remaining text field.
        by_player_line: dict[tuple, dict[str, dict]] = {}
        for r in rows:
            sel  = str(r.get("Selection") or "")
            nm   = str(r.get("Name") or "")
            desc = str(r.get("Description") or "")
            side = _ou_side(sel) or _ou_side(nm)
            if not side:
                continue
            player = next((c for c in (desc, nm, sel) if c and _ou_side(c) is None), "")
            line = r.get("Line") or r.get("Point")
            if not player or line is None:
                continue
            by_player_line.setdefault((player.lower().strip(), float(line)), {})[side] = r
        for (p_lower, line), sides in by_player_line.items():
            if "over" not in sides or "under" not in sides:
                continue
            o = sides["over"]; u = sides["under"]
            if o.get("Odds") is None or u.get("Odds") is None:
                continue
            # Keep the BEST line per player (longest over price; tie → first)
            key = (p_lower, market_key)
            cand = {"line": line, "over": float(o["Odds"]), "under": float(u["Odds"]),
                    "book": str(o.get("Sportsbook", ""))}
            if key not in out:
                out[key] = cand
        # Note: simple last-write-wins per player; for multi-line alternate markets
        # the scoring function below pivots on the snapshot's line value anyway.
    return out


def fetch_closing_scorer_anytime(date_str: str, sport: str = "soccer",
                                 book: str | None = None) -> dict[str, dict]:
    """
    Closing anytime-scorer prices keyed by player_name_lower.
    Returns {player_lower: {"odds": american_price, "book": book}}.
    No de-vig (markets are 110-130% book; we surface raw odds and let the
    scoring function compare against snapshot opening_implied_prob, which
    was also raw — apples to apples). Pass book="Pinnacle" for the sharp benchmark.
    """
    out: dict[str, dict] = {}
    for _mkey, rec in _select_windowed_records(date_str, sport).items():
        rows = [r for r in (rec.get("all_odds") or []) if r.get("Market") == "player_goal_scorer_anytime"]
        if book is not None:
            rows = [r for r in rows if str(r.get("Sportsbook", "")) == book]
        if not rows:
            continue
        for r in rows:
            player = str(r.get("Description") or r.get("Selection") or r.get("Name") or "").strip()
            odds = r.get("Odds")
            if not player or odds is None:
                continue
            key = player.lower()
            if key not in out or float(odds) > out[key]["odds"]:
                out[key] = {"odds": float(odds), "book": str(r.get("Sportsbook", ""))}
    return out


def fetch_closing_method(date_str: str, sport: str = "ufc",
                         book: str | None = None) -> dict[tuple, dict]:
    """
    MMA fight_result_method closing prices keyed by (fighter_lower, method).
    method ∈ {"ko_tko", "submission", "decision"}.
    Pass book="Pinnacle" for the sharp benchmark.
    """
    out: dict[tuple, dict] = {}
    for _mkey, rec in _select_windowed_records(date_str, sport).items():
        rows = [r for r in (rec.get("all_odds") or []) if r.get("Market") == "fight_result_method"]
        if book is not None:
            rows = [r for r in rows if str(r.get("Sportsbook", "")) == book]
        if not rows:
            continue
        for r in rows:
            nm = str(r.get("Description") or r.get("Selection") or r.get("Name") or "")
            odds = r.get("Odds")
            if not nm or odds is None:
                continue
            parts = nm.split(" - ") if " - " in nm else nm.rsplit(" by ", 1)
            if len(parts) != 2:
                continue
            fighter = parts[0].strip().lower()
            method_raw = parts[1].strip().lower()
            method = ("ko_tko" if any(k in method_raw for k in ("ko", "tko", "knockout"))
                      else "submission" if "sub" in method_raw
                      else "decision" if "decision" in method_raw or "points" in method_raw
                      else None)
            if method is None:
                continue
            key = (fighter, method)
            if key not in out or float(odds) > out[key]["odds"]:
                out[key] = {"odds": float(odds), "book": str(r.get("Sportsbook", ""))}
    return out


def fetch_closing_total_rounds(date_str: str, sport: str = "ufc") -> dict[tuple, dict]:
    """
    MMA total_rounds closing prices keyed by (matchup_frozenset, line).
    Returns {fz({fighter_a, fighter_b}): {line: {"over": odds, "under": odds}}}.
    """
    out: dict[frozenset, dict] = {}
    for _mkey, rec in _select_windowed_records(date_str, sport).items():
        rows = [r for r in (rec.get("all_odds") or []) if r.get("Market") == "total_rounds"]
        if not rows:
            continue
        home = str(rec.get("home_team") or rec.get("HomeTeam") or "").lower().strip()
        away = str(rec.get("away_team") or rec.get("AwayTeam") or "").lower().strip()
        key = frozenset({home, away})
        pairs: dict[float, dict] = {}
        for r in rows:
            line = r.get("Line") or r.get("Point")
            side = str(r.get("Name") or "").lower()
            odds = r.get("Odds")
            if line is None or odds is None: continue
            side_key = "over" if "over" in side else "under" if "under" in side else None
            if not side_key: continue
            pairs.setdefault(float(line), {})[side_key] = float(odds)
        if pairs:
            out[key] = pairs
    return out


def _score_prop(snap: dict, closing: dict) -> dict | None:
    """
    CLV for an over/under prop: line CLV (lines, direction-aware) + price CLV.
    Same algebra as totals. If close line == open line, also compute price CLV.
    """
    open_line = snap.get("opening_line")
    direction = str(snap.get("direction") or "").upper()
    if open_line is None or direction not in ("OVER", "UNDER"):
        return None
    close_line = closing["line"]
    # OVER wants the close to be HIGHER (your low number cleared more easily); UNDER mirror.
    line_clv = round((close_line - open_line) if direction == "OVER"
                     else (open_line - close_line), 2)
    price_clv_pct = None
    if abs(close_line - open_line) < 1e-9:
        close_imp = _odds_to_implied(closing["over"] if direction == "OVER" else closing["under"])
        price_clv_pct = round((close_imp - snap["opening_implied_prob"]) * 100, 3)
    close_odds = closing["over"] if direction == "OVER" else closing["under"]
    beat = line_clv > 0 or (abs(line_clv) < 1e-9 and (price_clv_pct or 0) > 0)
    return {"closing_line": close_line, "closing_odds": close_odds,
            "line_clv": line_clv, "price_clv_pct": price_clv_pct, "beat_close": beat}


def _score_scorer_anytime(snap: dict, closing: dict) -> dict | None:
    """CLV for an anytime-scorer pick: pure price CLV (binary, no line)."""
    close_imp = _odds_to_implied(closing["odds"])
    clv = close_imp - snap["opening_implied_prob"]
    return {"closing_odds": closing["odds"],
            "closing_implied_prob": round(close_imp, 6),
            "clv": round(clv, 6), "clv_pct": round(clv * 100, 3)}


def fetch_closing_nrfi(date_str: str, sport: str = "mlb",
                       book: str | None = None) -> dict[frozenset, dict]:
    """{frozenset({away,home}): {"nrfi", "yrfi"}} closing prices from the first-
    inning total (totals_1st_1_innings). NRFI = Under 0.5 (no run), YRFI = Over.
    Pass book="Pinnacle" for the sharp benchmark."""
    out: dict[frozenset, dict] = {}
    for _mkey, rec in _select_windowed_records(date_str, sport).items():
        rows = [r for r in (rec.get("all_odds") or []) if r.get("Market") == "totals_1st_1_innings"]
        if not rows:
            continue
        home = str(rec.get("home_team") or rec.get("HomeTeam") or "").lower().strip()
        away = str(rec.get("away_team") or rec.get("AwayTeam") or "").lower().strip()
        by_book: dict[str, dict[str, dict]] = {}
        for r in rows:
            by_book.setdefault(str(r.get("Sportsbook", "")), {})[str(r.get("Selection") or "")] = r
        chosen = None
        if book is not None:
            sides = by_book.get(book)
            if sides and "Over" in sides and "Under" in sides:
                chosen = sides
        else:
            for b in _SHARP_BOOK_ORDER:
                if b in by_book and "Over" in by_book[b] and "Under" in by_book[b]:
                    chosen = by_book[b]
                    break
            if chosen is None:
                for sides in by_book.values():
                    if "Over" in sides and "Under" in sides:
                        chosen = sides
                        break
        if not chosen or chosen["Under"].get("Odds") is None or chosen["Over"].get("Odds") is None:
            continue
        out[frozenset({away, home})] = {
            "nrfi": float(chosen["Under"]["Odds"]),  # Under 0.5 = no run = NRFI
            "yrfi": float(chosen["Over"]["Odds"]),
        }
    return out


def _score_nrfi(snap: dict, closing: dict) -> dict | None:
    """NRFI/YRFI is a binary prob bet (no line) — price CLV only, in prob points.
    Stored in clv/clv_pct like moneyline since the unit is identical."""
    direction = str(snap.get("direction") or "").upper()
    picked_yrfi = "YRFI" in direction or "OVER" in direction or direction == "YES_RUN"
    if picked_yrfi:
        close_imp = _devig_prob(closing["yrfi"], closing["nrfi"])
    else:
        close_imp = _devig_prob(closing["nrfi"], closing["yrfi"])
    clv = close_imp - snap["opening_implied_prob"]
    return {"closing_odds": closing["yrfi"] if picked_yrfi else closing["nrfi"],
            "closing_implied_prob": round(close_imp, 6),
            "clv": round(clv, 6), "clv_pct": round(clv * 100, 3)}


def _score_spread(snap: dict, closing: dict) -> dict | None:
    """CLV for a spread/run-line/puck-line pick: line CLV (points) + price CLV
    (cents, only when the closing line matches the line you took)."""
    open_line = snap.get("opening_line")
    if open_line is None:
        return None
    close_line = closing["line"]
    # Signed team handicap: positive line_clv = you got a better number.
    # Favorite -1.5 closing -2.5 → +1.0; underdog +1.5 closing +2.5 → -1.0.
    line_clv = round(open_line - close_line, 2)
    price_clv_pct = None
    if abs(open_line - close_line) < 1e-9:
        if closing.get("opp_odds") is not None:
            close_imp = _devig_prob(closing["odds"], closing["opp_odds"])
        else:
            close_imp = _odds_to_implied(closing["odds"])
        price_clv_pct = round((close_imp - snap["opening_implied_prob"]) * 100, 3)
    beat = line_clv > 0 or (abs(line_clv) < 1e-9 and (price_clv_pct or 0) > 0)
    return {"closing_line": close_line, "closing_odds": closing["odds"],
            "line_clv": line_clv, "price_clv_pct": price_clv_pct, "beat_close": beat}


def _score_total(snap: dict, closing: dict) -> dict | None:
    """CLV for a totals pick: line CLV (points, direction-aware) + price CLV."""
    open_line = snap.get("opening_line")
    direction = str(snap.get("direction") or "").upper()
    if open_line is None or direction not in ("OVER", "UNDER"):
        return None
    close_line = closing["line"]
    # OVER wants a lower bar: took Over 8.0, closed 8.5 → your 8.0 is easier → +0.5.
    # UNDER is the mirror.
    line_clv = round((close_line - open_line) if direction == "OVER"
                     else (open_line - close_line), 2)
    price_clv_pct = None
    if abs(close_line - open_line) < 1e-9:
        if direction == "OVER":
            close_imp = _devig_prob(closing["over"], closing["under"])
        else:
            close_imp = _devig_prob(closing["under"], closing["over"])
        price_clv_pct = round((close_imp - snap["opening_implied_prob"]) * 100, 3)
    close_odds = closing["over"] if direction == "OVER" else closing["under"]
    beat = line_clv > 0 or (abs(line_clv) < 1e-9 and (price_clv_pct or 0) > 0)
    return {"closing_line": close_line, "closing_odds": close_odds,
            "line_clv": line_clv, "price_clv_pct": price_clv_pct, "beat_close": beat}


def compute_clv(date_str: str | None = None) -> list[dict]:
    """
    For each snapshot on date_str, fill in closing odds from the cache and
    compute CLV:

      clv     = closing_implied_prob - opening_implied_prob
      clv_pct = clv * 100

    Positive CLV means you got a better number than the closing line —
    a sign of genuine edge.

    Updates snapshots in-place and returns the updated records for that date.
    """
    from datetime import date

    if date_str is None:
        date_str = date.today().isoformat()

    snapshots = _load_snapshots()
    day_snaps = [s for s in snapshots if s.get("date") == date_str]

    if not day_snaps:
        return []

    # Normalize sport keys in snapshots (may have been written with old Odds API slug)
    for s in day_snaps:
        s["sport"] = _normalize_sport(s.get("sport", "mlb"))

    # Build per-sport closing maps for all sports present that day
    sports_today = {s.get("sport", "mlb") for s in day_snaps}
    closing_maps: dict[str, dict] = {}
    closing_pairs: dict[str, dict] = {}  # two-sided for de-vig (best price)
    pinnacle_pairs: dict[str, dict] = {} # two-sided Pinnacle-only (sharp benchmark)
    spread_maps: dict[str, dict] = {}    # team_lower -> {line, odds, opp_odds}
    total_maps: dict[str, dict] = {}     # frozenset({away,home}) -> {line, over, under}
    f5_maps: dict[str, dict] = {}        # frozenset -> {line, over, under} (first 5 inn)
    nrfi_maps: dict[str, dict] = {}      # frozenset -> {nrfi, yrfi} (first inning)
    prop_maps: dict[str, dict] = {}      # sport -> {(player_lower, market_key): {line, over, under}}
    scorer_maps: dict[str, dict] = {}    # sport -> {player_lower: {odds, book}}
    method_maps: dict[str, dict] = {}    # sport -> {(fighter, method): {odds, book}}
    # ── Pinnacle-only "sharp" twins of every map above. Same shapes, restricted
    #    to Pinnacle's close. These drive the *_sharp CLV fields — the honest test
    #    (beating the sharp market), vs the best-price maps that flatter us. ──
    sharp_spread_maps: dict[str, dict] = {}
    sharp_total_maps: dict[str, dict] = {}
    sharp_f5_maps: dict[str, dict] = {}
    sharp_nrfi_maps: dict[str, dict] = {}
    sharp_prop_maps: dict[str, dict] = {}
    sharp_scorer_maps: dict[str, dict] = {}
    sharp_method_maps: dict[str, dict] = {}
    for sport in sports_today:
        closing_maps[sport]   = fetch_closing_lines(date_str=date_str, sport=sport)
        closing_pairs[sport]  = fetch_closing_pairs(date_str=date_str, sport=sport)
        pinnacle_pairs[sport] = fetch_closing_pinnacle(date_str=date_str, sport=sport)
        spread_maps[sport]   = fetch_closing_spreads(date_str=date_str, sport=sport)
        total_maps[sport]    = fetch_closing_totals(date_str=date_str, sport=sport)
        f5_maps[sport]       = fetch_closing_f5_totals(date_str=date_str, sport=sport)
        nrfi_maps[sport]     = fetch_closing_nrfi(date_str=date_str, sport=sport)
        sharp_spread_maps[sport] = fetch_closing_spreads(date_str=date_str, sport=sport, book="Pinnacle")
        sharp_total_maps[sport]  = fetch_closing_totals(date_str=date_str, sport=sport, book="Pinnacle")
        sharp_f5_maps[sport]     = fetch_closing_f5_totals(date_str=date_str, sport=sport, book="Pinnacle")
        sharp_nrfi_maps[sport]   = fetch_closing_nrfi(date_str=date_str, sport=sport, book="Pinnacle")
        # Prop-style markets — keyed by (player, market). Fetch closings for
        # exactly the prop types that appear in THIS day's snapshots (dynamic, so
        # any prop — batter_hits, player_blocks, etc. — is covered without a list).
        sport_props: dict = {}
        sharp_props: dict = {}
        day_prop_types = {str(s.get("market") or "").lower()
                          for s in day_snaps if _is_prop_market(s.get("market"))}
        for mk in (day_prop_types or {"pitcher_strikeouts"}):
            sport_props.update(fetch_closing_props(date_str=date_str, sport=sport, market_key=mk))
            sharp_props.update(fetch_closing_props(date_str=date_str, sport=sport, market_key=mk, book="Pinnacle"))
        prop_maps[sport] = sport_props
        sharp_prop_maps[sport] = sharp_props
        scorer_maps[sport] = fetch_closing_scorer_anytime(date_str=date_str, sport=sport)
        method_maps[sport] = fetch_closing_method(date_str=date_str, sport=sport)
        sharp_scorer_maps[sport] = fetch_closing_scorer_anytime(date_str=date_str, sport=sport, book="Pinnacle")
        sharp_method_maps[sport] = fetch_closing_method(date_str=date_str, sport=sport, book="Pinnacle")

    # Merged maps: all teams from all sports (used as fallback)
    merged_map: dict[str, float] = {}
    merged_pairs: dict[str, tuple] = {}
    merged_pinnacle: dict[str, tuple] = {}
    merged_spreads: dict[str, dict] = {}
    merged_totals: dict[frozenset, dict] = {}
    merged_sharp_spreads: dict[str, dict] = {}
    merged_sharp_totals: dict[frozenset, dict] = {}
    for sport in sports_today:
        merged_map.update(closing_maps[sport])
        merged_pairs.update(closing_pairs[sport])
        merged_pinnacle.update(pinnacle_pairs[sport])
        merged_spreads.update(spread_maps[sport])
        merged_totals.update(total_maps[sport])
        merged_sharp_spreads.update(sharp_spread_maps[sport])
        merged_sharp_totals.update(sharp_total_maps[sport])

    updated = 0
    cleared = 0
    for snap in day_snaps:
        market = str(snap.get("market") or "").lower()

        # ── Spreads / run lines / puck lines ──────────────────────────────────
        if market in ("spread", "run_line", "runline", "puck_line", "puckline"):
            snap_sport = snap.get("sport", "mlb")
            full = _resolve_spread_team(snap.get("team", ""), snap.get("opponent", ""))
            key = (full or snap.get("team", "")).lower().strip()
            closing = spread_maps.get(snap_sport, {}).get(key) or merged_spreads.get(key)
            res = _score_spread(snap, closing) if closing else None
            if res:
                snap.update(res)
                updated += 1
                sharp_closing = sharp_spread_maps.get(snap_sport, {}).get(key) or merged_sharp_spreads.get(key)
                _apply_sharp(snap, _score_spread(snap, sharp_closing) if sharp_closing else None)
            elif snap.get("line_clv") is not None:
                for k in ("closing_line", "closing_odds", "line_clv", "price_clv_pct", "beat_close"):
                    snap.pop(k, None)
                _apply_sharp(snap, None)
                cleared += 1
            continue

        # ── Totals ────────────────────────────────────────────────────────────
        if market in ("total", "totals"):
            snap_sport = snap.get("sport", "mlb")
            mu = snap.get("opponent", "")
            tkey = None
            if "@" in mu:
                a, h = [t.strip().lower() for t in mu.split("@", 1)]
                tkey = frozenset({a, h})
            closing = (total_maps.get(snap_sport, {}).get(tkey) if tkey else None) \
                      or (merged_totals.get(tkey) if tkey else None)
            res = _score_total(snap, closing) if closing else None
            if res:
                snap.update(res)
                updated += 1
                sharp_closing = (sharp_total_maps.get(snap_sport, {}).get(tkey) if tkey else None) \
                                or (merged_sharp_totals.get(tkey) if tkey else None)
                _apply_sharp(snap, _score_total(snap, sharp_closing) if sharp_closing else None)
            elif snap.get("line_clv") is not None:
                for k in ("closing_line", "closing_odds", "line_clv", "price_clv_pct", "beat_close"):
                    snap.pop(k, None)
                _apply_sharp(snap, None)
                cleared += 1
            continue

        # ── First-5-innings totals (F5) ───────────────────────────────────────
        if market in ("f5_total", "f5_totals", "first_5_total"):
            snap_sport = snap.get("sport", "mlb")
            mu = snap.get("opponent", "")
            tkey = frozenset({*(t.strip().lower() for t in mu.split("@", 1))}) if "@" in mu else None
            closing = (f5_maps.get(snap_sport, {}).get(tkey) if tkey else None)
            res = _score_total(snap, closing) if closing else None
            if res:
                snap.update(res)
                updated += 1
                sharp_closing = (sharp_f5_maps.get(snap_sport, {}).get(tkey) if tkey else None)
                _apply_sharp(snap, _score_total(snap, sharp_closing) if sharp_closing else None)
            elif snap.get("line_clv") is not None:
                for k in ("closing_line", "closing_odds", "line_clv", "price_clv_pct", "beat_close"):
                    snap.pop(k, None)
                _apply_sharp(snap, None)
                cleared += 1
            continue

        # ── NRFI / YRFI (first-inning, binary prob CLV) ───────────────────────
        if market in ("nrfi", "yrfi"):
            snap_sport = snap.get("sport", "mlb")
            mu = snap.get("opponent", "")
            tkey = frozenset({*(t.strip().lower() for t in mu.split("@", 1))}) if "@" in mu else None
            closing = (nrfi_maps.get(snap_sport, {}).get(tkey) if tkey else None)
            res = _score_nrfi(snap, closing) if closing else None
            if res:
                snap.update(res)
                updated += 1
                sharp_closing = (sharp_nrfi_maps.get(snap_sport, {}).get(tkey) if tkey else None)
                _apply_sharp(snap, _score_nrfi(snap, sharp_closing) if sharp_closing else None)
            elif snap.get("clv") is not None:
                for k in ("closing_odds", "closing_implied_prob", "clv", "clv_pct"):
                    snap.pop(k, None)
                _apply_sharp(snap, None)
                cleared += 1
            continue

        # ── Player props (pitcher Ks / NBA points / NHL goals / etc) ──────────
        # Snapshots store the specific market (e.g. "pitcher_strikeouts",
        # "batter_hits") OR a generic "prop". Prefix-detected so every prop type
        # routes here as its own market.
        if _is_prop_market(market):
            snap_sport = snap.get("sport", "mlb")
            # Find best match in the merged prop map for this sport
            player_lower = (snap.get("player") or snap.get("team") or "").lower().strip()
            def _prop_lookup(pmap: dict):
                c = pmap.get((player_lower, market))
                if not c:
                    # Fallback: any market key for this player (model stored generic "prop")
                    for (p_l, _mk), v in pmap.items():
                        if p_l == player_lower:
                            return v
                return c
            sport_prop_map = prop_maps.get(snap_sport, {})
            closing = _prop_lookup(sport_prop_map)
            res = _score_prop(snap, closing) if closing else None
            if res:
                snap.update(res); updated += 1
                sharp_closing = _prop_lookup(sharp_prop_maps.get(snap_sport, {}))
                _apply_sharp(snap, _score_prop(snap, sharp_closing) if sharp_closing else None)
            continue

        # ── Anytime goal scorer (soccer/WC) ───────────────────────────────────
        if market in ("anytime_scorer", "player_goal_scorer_anytime", "scorer"):
            snap_sport = snap.get("sport", "soccer")
            player_lower = (snap.get("player") or snap.get("team") or "").lower().strip()
            # Some snapshots include "(Team)" in name — strip it
            if "(" in player_lower:
                player_lower = player_lower.split("(")[0].strip()
            def _scorer_lookup(smap: dict):
                c = smap.get(player_lower)
                if not c:
                    for k, v in smap.items():
                        if k.split()[-1] == player_lower.split()[-1] and len(player_lower.split()[-1]) > 3:
                            return v
                return c
            sport_map_local = scorer_maps.get(snap_sport, {})
            closing = _scorer_lookup(sport_map_local)
            res = _score_scorer_anytime(snap, closing) if closing else None
            if res:
                snap.update(res); updated += 1
                sharp_closing = _scorer_lookup(sharp_scorer_maps.get(snap_sport, {}))
                _apply_sharp(snap, _score_scorer_anytime(snap, sharp_closing) if sharp_closing else None)
            continue

        # ── MMA method-of-victory ─────────────────────────────────────────────
        if market in ("method_of_victory", "fight_result_method"):
            snap_sport = snap.get("sport", "mma")
            fighter_lower = (snap.get("fighter") or snap.get("team") or "").lower().strip()
            method = (snap.get("direction") or "").lower()
            method = ("ko_tko" if any(k in method for k in ("ko", "tko"))
                      else "submission" if "sub" in method
                      else "decision" if "decision" in method else None)
            if method is None:
                continue
            def _method_score(c: dict | None):
                if not c:
                    return None
                close_imp = _odds_to_implied(c["odds"])
                clv = close_imp - snap["opening_implied_prob"]
                return {"closing_odds": c["odds"], "closing_implied_prob": round(close_imp, 6),
                        "clv": round(clv, 6), "clv_pct": round(clv * 100, 3)}
            closing = method_maps.get(snap_sport, {}).get((fighter_lower, method))
            res = _method_score(closing)
            if res:
                snap.update(res)
                updated += 1
                _apply_sharp(snap, _method_score(
                    sharp_method_maps.get(snap_sport, {}).get((fighter_lower, method))))
            continue

        # ── Everything else has no closing archive — moneyline-only closings ──
        if not _is_moneyline_market(snap.get("market")):
            if snap.pop("clv", None) is not None:
                cleared += 1
            for k in ("closing_odds", "closing_implied_prob", "clv_pct", "clv_devigged"):
                snap.pop(k, None)
            continue

        team_lower = snap["team"].lower().strip()
        snap_sport = snap.get("sport", "baseball_mlb")

        # Try sport-specific map first, then merged fallback
        sport_map   = closing_maps.get(snap_sport, {})
        sport_pairs = closing_pairs.get(snap_sport, {})
        closing_odds = sport_map.get(team_lower) or merged_map.get(team_lower)

        if closing_odds is None:
            # Partial match
            for cm in (sport_map, merged_map):
                for key, val in cm.items():
                    if team_lower in key or key in team_lower:
                        closing_odds = val
                        break
                if closing_odds is not None:
                    break

        if closing_odds is None:
            continue  # no closing line available yet

        # De-vig closing probability using two-sided data when available.
        # Falls back to raw implied prob for markets without a paired opponent line
        # (e.g. live-cache fallback, totals, props).
        pair = sport_pairs.get(team_lower) or merged_pairs.get(team_lower)
        if pair:
            # pair = (picked, opp[, draw]) — pass ALL other outcomes so 3-way
            # (soccer) de-vigs correctly, not just the 2-way opponent.
            closing_imp = _devig_prob(pair[0], *pair[1:])
        else:
            closing_imp = _odds_to_implied(closing_odds)

        clv = closing_imp - snap["opening_implied_prob"]

        snap["closing_odds"]         = closing_odds
        snap["closing_implied_prob"] = round(closing_imp, 6)
        snap["clv"]                  = round(clv, 6)
        snap["clv_pct"]              = round(clv * 100, 3)
        snap["clv_devigged"]         = pair is not None  # flag for reporting

        # ── Sharp CLV: same pick measured against PINNACLE's de-vigged close ──
        # clv_pct above uses the BEST price across all books, which flatters us
        # (we score against the loosest number any book offered). Pinnacle is the
        # sharp, low-margin reference — beating ITS close is the honest predictor
        # of profit. We store it alongside, never overwriting clv_pct, so the gate
        # can show both and flag "best-price mirages" (positive vs best, negative
        # vs sharp). Falls back silently when Pinnacle didn't price the game.
        sharp_pair = (pinnacle_pairs.get(snap_sport, {}).get(team_lower)
                      or merged_pinnacle.get(team_lower))
        if sharp_pair:
            sharp_imp = _devig_prob(sharp_pair[0], *sharp_pair[1:])
            clv_sharp = sharp_imp - snap["opening_implied_prob"]
            _apply_sharp(snap, {
                "closing_odds": sharp_pair[0],
                "closing_implied_prob": round(sharp_imp, 6),
                "clv": round(clv_sharp, 6),
                "clv_pct": round(clv_sharp * 100, 3),
                "beat_close": bool(clv_sharp > 0),
            })
        else:
            _apply_sharp(snap, None)  # clear stale sharp fields if Pinnacle absent
        updated += 1

    if updated > 0 or cleared > 0:
        _save_snapshots(snapshots)

    return day_snaps


def get_clv_by_market(sport_filter: str | None = None) -> dict:
    """
    Per-market CLV breakdown — the view that answers "which market actually beats
    the closing line?" Moneyline-style markets report probability-CLV (clv_pct);
    spread/total markets report line-CLV (points won at the number) + beat-close %.
    Pass sport_filter (e.g. "soccer") to isolate one sport — e.g. to compare the
    World Cup model's moneyline vs totals after the tournament.

    Returns: {market: {picks, scored, metric, avg_*, beat_close_pct}}
    """
    snaps = _load_snapshots()
    buckets: dict[str, dict] = {}
    for s in snaps:
        if sport_filter and sport_filter.lower() not in (s.get("sport") or "").lower():
            continue
        mk = str(s.get("market") or "moneyline").lower()
        if mk in ("h2h", "ml"):
            mk = "moneyline"
        elif mk in ("totals",):
            mk = "total"
        elif mk in ("run_line", "runline", "puck_line", "puckline"):
            mk = "spread"
        b = buckets.setdefault(mk, {"picks": 0, "prob": [], "line": [], "beats": 0,
                                    "scored": 0, "sharp": [], "sharp_beats": 0})
        b["picks"] += 1
        if s.get("clv_pct") is not None:           # moneyline-style prob-CLV
            b["scored"] += 1
            b["prob"].append(s["clv_pct"])
            if s["clv_pct"] > 0:
                b["beats"] += 1
            if s.get("clv_sharp_pct") is not None:  # sharp twin (vs Pinnacle close)
                b["sharp"].append(s["clv_sharp_pct"])
                if s["clv_sharp_pct"] > 0:
                    b["sharp_beats"] += 1
        elif s.get("line_clv") is not None:        # spread/total line-CLV
            b["scored"] += 1
            b["line"].append(s["line_clv"])
            if s.get("beat_close"):
                b["beats"] += 1
            if s.get("line_clv_sharp") is not None:
                b["sharp"].append(s["line_clv_sharp"])
                if s.get("beat_close_sharp"):
                    b["sharp_beats"] += 1

    out: dict[str, dict] = {}
    for mk, b in buckets.items():
        entry = {"picks": b["picks"], "scored": b["scored"]}
        if b["prob"]:
            entry["metric"] = "prob_clv_pct"
            entry["avg_clv_pct"] = round(sum(b["prob"]) / len(b["prob"]), 3)
        elif b["line"]:
            entry["metric"] = "line_clv_points"
            entry["avg_line_clv"] = round(sum(b["line"]) / len(b["line"]), 3)
        else:
            entry["metric"] = "none"   # picks logged but no closing line joined yet
        if b["scored"]:
            entry["beat_close_pct"] = round(b["beats"] / b["scored"] * 100, 1)
        # Sharp (vs Pinnacle close) — the honest read, when Pinnacle priced it.
        if b["sharp"]:
            entry["sharp_n"] = len(b["sharp"])
            entry["avg_sharp"] = round(sum(b["sharp"]) / len(b["sharp"]), 3)
            entry["sharp_beat_pct"] = round(b["sharp_beats"] / len(b["sharp"]) * 100, 1)
        out[mk] = entry
    return out


def print_clv_by_market(sport_filter: str | None = None) -> None:
    """Pretty-print the per-market CLV breakdown (see get_clv_by_market)."""
    data = get_clv_by_market(sport_filter)
    label = f" — {sport_filter.upper()}" if sport_filter else ""
    print(f"\n  CLV BY MARKET{label}")
    if not data:
        print("    (no snapshots yet)")
        return
    for mk, e in sorted(data.items(), key=lambda x: -x[1]["picks"]):
        if e["metric"] == "prob_clv_pct":
            sign = "+" if e["avg_clv_pct"] >= 0 else ""
            metric = f"avg CLV {sign}{e['avg_clv_pct']}%"
        elif e["metric"] == "line_clv_points":
            sign = "+" if e["avg_line_clv"] >= 0 else ""
            metric = f"avg line-CLV {sign}{e['avg_line_clv']} pts"
        else:
            metric = "no closing line joined yet"
        beat = f", beat close {e['beat_close_pct']}%" if "beat_close_pct" in e else ""
        if "avg_sharp" in e:
            ssign = "+" if e["avg_sharp"] >= 0 else ""
            sharp = f"  │ vs Pinnacle: {ssign}{e['avg_sharp']}, beat {e['sharp_beat_pct']}% (n={e['sharp_n']})"
        else:
            sharp = ""
        print(f"    {mk:<11} {e['scored']}/{e['picks']} scored — {metric}{beat}{sharp}")


def get_clv_matrix() -> dict:
    """Per-SPORT × per-MARKET CLV — the full grid, every sport broken out (not
    pooled the way get_clv_by_market sums all sports into one 'moneyline' row).

    Pooling sports hides which sport's market is real: a tennis edge washes out
    against MLB moneyline. This keys on (sport, market) so each cell stands alone,
    and it INCLUDES cells with picks but 0 scored CLV so the coverage gaps are
    visible (off-season archives, futures with no closing source, props that
    didn't match a closing).

    Returns {sport: {market: {picks, scored, sharp_n, unit, avg, avg_sharp,
                              beat_pct, sharp_beat_pct}}}.
    """
    snaps = _load_snapshots()
    grid: dict[str, dict[str, dict]] = {}
    for s in snaps:
        if not isinstance(s, dict):
            continue
        sport = _normalize_sport(s.get("sport", "?"))
        mk = str(s.get("market") or "(unset)").lower()
        if mk in ("h2h", "ml"):
            mk = "moneyline"
        elif mk == "totals":
            mk = "total"
        elif mk in ("run_line", "runline", "puck_line", "puckline"):
            mk = "spread"
        b = grid.setdefault(sport, {}).setdefault(
            mk, {"picks": 0, "scored": 0, "prob": [], "line": [],
                 "beats": 0, "sharp": [], "sharp_beats": 0})
        b["picks"] += 1
        if s.get("clv_pct") is not None:
            b["scored"] += 1; b["prob"].append(s["clv_pct"])
            if s["clv_pct"] > 0: b["beats"] += 1
            if s.get("clv_sharp_pct") is not None:
                b["sharp"].append(s["clv_sharp_pct"])
                if s["clv_sharp_pct"] > 0: b["sharp_beats"] += 1
        elif s.get("line_clv") is not None:
            b["scored"] += 1; b["line"].append(s["line_clv"])
            if s.get("beat_close"): b["beats"] += 1
            if s.get("line_clv_sharp") is not None:
                b["sharp"].append(s["line_clv_sharp"])
                if s.get("beat_close_sharp"): b["sharp_beats"] += 1

    out: dict[str, dict] = {}
    for sport, markets in grid.items():
        out[sport] = {}
        for mk, b in markets.items():
            e = {"picks": b["picks"], "scored": b["scored"], "sharp_n": len(b["sharp"])}
            if b["prob"]:
                e["unit"] = "%"; e["avg"] = round(sum(b["prob"]) / len(b["prob"]), 3)
            elif b["line"]:
                e["unit"] = "pt"; e["avg"] = round(sum(b["line"]) / len(b["line"]), 3)
            else:
                e["unit"] = ""; e["avg"] = None
            e["beat_pct"] = round(b["beats"] / b["scored"] * 100, 1) if b["scored"] else None
            if b["sharp"]:
                e["avg_sharp"] = round(sum(b["sharp"]) / len(b["sharp"]), 3)
                e["sharp_beat_pct"] = round(b["sharp_beats"] / len(b["sharp"]) * 100, 1)
            else:
                e["avg_sharp"] = None; e["sharp_beat_pct"] = None
            out[sport][mk] = e
    return out


def _sport_short(sp: str) -> str:
    """Short label for a sport key — matches chef.py's gate labels."""
    sp = _normalize_sport(str(sp or "?"))
    return {
        "baseball_mlb": "mlb", "basketball_nba": "nba", "basketball_wnba": "wnba",
        "icehockey_nhl": "nhl", "mma_mixed_martial_arts": "mma",
        "soccer_fifa_world_cup": "wc",
    }.get(sp, sp.replace("soccer_", "").replace("tennis_atp_", "atp-")
              .replace("tennis_wta_", "wta-").replace("golf_", "golf-")[:14])


def print_clv_matrix(min_picks: int = 3) -> None:
    """Print the full per-sport × per-market CLV grid (see get_clv_matrix).

    Every sport gets its own block; within it, each market shows picks, how many
    scored CLV, the avg best-price CLV + beat%, and the sharp (Pinnacle) twin.
    Cells with picks but 0 scored are shown with a reason so gaps are explicit."""
    data = get_clv_matrix()
    if not data:
        print("\n  CLV MATRIX — (no snapshots yet)")
        return
    # Futures / season-long markets that have no game-line closing source.
    _futures = {"outright", "win", "winner", "championship", "futures"}
    print(f"\n  CLV MATRIX — every sport × market (best price │ vs Pinnacle close)")
    print(f"  {'─'*86}")
    # Order sports by total picks desc
    order = sorted(data, key=lambda sp: -sum(m["picks"] for m in data[sp].values()))
    for sport in order:
        markets = data[sport]
        tot = sum(m["picks"] for m in markets.values())
        if tot < min_picks:
            continue
        print(f"\n  {_sport_short(sport).upper()}  ({tot} picks)")
        for mk, e in sorted(markets.items(), key=lambda x: -x[1]["picks"]):
            if e["picks"] < min_picks:
                continue
            if e["scored"]:
                a = e["avg"]; sign = "+" if a is not None and a >= 0 else ""
                best = f"{sign}{a}{e['unit']} (beat {e['beat_pct']:.0f}%)"
                if e["sharp_n"]:
                    sa = e["avg_sharp"]; ssign = "+" if sa >= 0 else ""
                    sharp = f"│ Pinn {ssign}{sa}{e['unit']} (beat {e['sharp_beat_pct']:.0f}%, n={e['sharp_n']})"
                else:
                    sharp = "│ Pinn — (no per-book close in archive)"
                metric = f"{best:<26} {sharp}"
            else:
                # 0 scored — say WHY (the actionable part)
                why = ("futures — no game-line closing source" if mk in _futures
                       else "no closing captured/matched yet")
                metric = f"0 scored — {why}"
            print(f"    {mk:<20} {e['scored']:>4}/{e['picks']:<5} {metric}")
    print(f"  {'─'*86}")
    print(f"  scored = closing line joined · Pinn = same pick vs Pinnacle's close (sharp truth)")


def get_clv_by_strategy() -> dict:
    """Per-strategy CLV — the view that answers "which shadow strategy beats the
    close?" Same buckets as get_clv_by_market but keyed on the `strategy` tag;
    untagged picks (normal model/card picks) bucket under "model".

    Returns: {strategy: {picks, scored, metric, avg_*, beat_close_pct}}
    """
    snaps = _load_snapshots()
    buckets: dict[str, dict] = {}
    for s in snaps:
        strat = s.get("strategy") or "model"
        b = buckets.setdefault(strat, {"picks": 0, "prob": [], "line": [], "beats": 0, "scored": 0})
        b["picks"] += 1
        if s.get("clv_pct") is not None:            # moneyline-style prob-CLV
            b["scored"] += 1
            b["prob"].append(s["clv_pct"])
            if s["clv_pct"] > 0:
                b["beats"] += 1
        elif s.get("line_clv") is not None:         # spread/total line-CLV
            b["scored"] += 1
            b["line"].append(s["line_clv"])
            if s.get("beat_close"):
                b["beats"] += 1

    out: dict[str, dict] = {}
    for strat, b in buckets.items():
        entry = {"picks": b["picks"], "scored": b["scored"]}
        if b["prob"]:
            entry["metric"] = "prob_clv_pct"
            entry["avg_clv_pct"] = round(sum(b["prob"]) / len(b["prob"]), 3)
        elif b["line"]:
            entry["metric"] = "line_clv_points"
            entry["avg_line_clv"] = round(sum(b["line"]) / len(b["line"]), 3)
        else:
            entry["metric"] = "none"
        if b["scored"]:
            entry["beat_close_pct"] = round(b["beats"] / b["scored"] * 100, 1)
        out[strat] = entry
    return out


def print_clv_by_strategy() -> None:
    """Pretty-print the per-strategy CLV breakdown (see get_clv_by_strategy)."""
    data = get_clv_by_strategy()
    print(f"\n  CLV BY STRATEGY")
    if not data:
        print("    (no snapshots yet)")
        return
    for strat, e in sorted(data.items(), key=lambda x: -x[1]["picks"]):
        if e["metric"] == "prob_clv_pct":
            sign = "+" if e["avg_clv_pct"] >= 0 else ""
            metric = f"avg CLV {sign}{e['avg_clv_pct']}%"
        elif e["metric"] == "line_clv_points":
            sign = "+" if e["avg_line_clv"] >= 0 else ""
            metric = f"avg line-CLV {sign}{e['avg_line_clv']} pts"
        else:
            metric = "no closing line joined yet"
        beat = f", beat close {e['beat_close_pct']}%" if "beat_close_pct" in e else ""
        print(f"    {strat:<16} {e['scored']}/{e['picks']} scored — {metric}{beat}")


def get_clv_summary() -> dict:
    """
    Aggregate CLV stats across all snapshots with closing-line data.

    Returns:
      total_picks, with_clv, avg_clv_pct, positive_clv_pct,
      clv_by_tier (dict of tier -> {count, avg_clv_pct})
    """
    snapshots = _load_snapshots()
    with_clv  = [s for s in snapshots if s.get("clv") is not None]

    if not with_clv:
        return {
            "total_picks":    len(snapshots),
            "with_clv":       0,
            "avg_clv_pct":    0.0,
            "positive_clv_pct": 0.0,
            "clv_by_tier":    {},
            "verdict":        "No CLV data yet — run compute_clv() after games start.",
        }

    clv_vals = [s["clv_pct"] for s in with_clv]
    avg_clv  = sum(clv_vals) / len(clv_vals)
    pos_pct  = sum(1 for v in clv_vals if v > 0) / len(clv_vals) * 100

    # Group by edge tier if available in snapshot (from picks.json source)
    # We infer tier from opening_implied_prob vs model pick data if present
    tier_buckets: dict[str, list[float]] = {"HIGH": [], "MED": [], "LOW": [], "UNKNOWN": []}
    for s in with_clv:
        edge = s.get("edge")
        if edge is None:
            tier_buckets["UNKNOWN"].append(s["clv_pct"])
        elif edge >= 0.08:
            tier_buckets["HIGH"].append(s["clv_pct"])
        elif edge >= 0.04:
            tier_buckets["MED"].append(s["clv_pct"])
        else:
            tier_buckets["LOW"].append(s["clv_pct"])

    clv_by_tier = {}
    for tier, vals in tier_buckets.items():
        if vals:
            clv_by_tier[tier] = {
                "count":       len(vals),
                "avg_clv_pct": round(sum(vals) / len(vals), 3),
            }

    # Group by sport
    sport_buckets: dict[str, list[float]] = {}
    for s in with_clv:
        sp = (s.get("sport") or "unknown").lower()
        # Normalize to short form
        if "mlb" in sp or sp == "baseball": sp = "mlb"
        elif "nba" in sp or sp == "basketball": sp = "nba"
        elif "nhl" in sp or sp == "hockey": sp = "nhl"
        sport_buckets.setdefault(sp, []).append(s["clv_pct"])

    clv_by_sport = {
        sp: {"count": len(vals), "avg_clv_pct": round(sum(vals) / len(vals), 3)}
        for sp, vals in sport_buckets.items()
    }

    n = len(with_clv)
    if n < 20:
        verdict = f"EARLY DATA — {n} picks with CLV (need 50+ for significance)"
    elif avg_clv > 2.0:
        verdict = "STRONG EDGE — consistently beating the closing line"
    elif avg_clv > 0.5:
        verdict = "POSITIVE CLV — model shows real edge against the market"
    elif avg_clv > -0.5:
        verdict = "NEUTRAL — model roughly matches closing line efficiency"
    else:
        verdict = "NEGATIVE CLV — getting worse lines than closing"

    return {
        "total_picks":      len(snapshots),
        "with_clv":         n,
        "avg_clv_pct":      round(avg_clv, 3),
        "positive_clv_pct": round(pos_pct, 1),
        "clv_by_tier":      clv_by_tier,
        "clv_by_sport":     clv_by_sport,
        "verdict":          verdict,
    }


def get_spread_total_clv_summary() -> dict:
    """Aggregate line-CLV for spread/total picks: points (primary) + cents at
    matched line. Kept separate from the moneyline prob-CLV so units don't mix."""
    snaps = _load_snapshots()
    scored = [s for s in snaps if s.get("line_clv") is not None]
    out: dict = {"count": len(scored), "by_market": {}}
    if not scored:
        return out
    buckets: dict[str, list] = {}
    for s in scored:
        mk = str(s.get("market") or "?").lower()
        if mk in ("run_line", "runline", "puck_line", "puckline"):
            mk = "spread"
        elif mk == "totals":
            mk = "total"
        buckets.setdefault(mk, []).append(s)
    for mk, rows in buckets.items():
        lvals = [r["line_clv"] for r in rows]
        pvals = [r["price_clv_pct"] for r in rows if r.get("price_clv_pct") is not None]
        beats = sum(1 for r in rows if r.get("beat_close"))
        out["by_market"][mk] = {
            "count":             len(rows),
            "avg_line_clv":      round(sum(lvals) / len(lvals), 3),
            "beat_close_pct":    round(beats / len(rows) * 100, 1),
            "avg_price_clv_pct": round(sum(pvals) / len(pvals), 3) if pvals else None,
            "matched_price_n":   len(pvals),
        }
    return out


def print_clv_report() -> None:
    """Print a formatted CLV dashboard to the terminal."""
    W = 60
    summary = get_clv_summary()

    print(f"\n{'═' * W}")
    print(f"  CLV REPORT — CLOSING LINE VALUE")
    print(f"{'═' * W}")
    print(f"  Total picks tracked : {summary['total_picks']}")
    print(f"  Picks with CLV data : {summary['with_clv']}")

    if summary["with_clv"] == 0:
        print(f"\n  {summary['verdict']}")
        print(f"\n  Run after generating picks:")
        print(f"    from src.analytics.clv_tracker import snapshot_opening_lines, compute_clv")
        print(f"    snapshot_opening_lines()   # right after predict.py --daily")
        print(f"    compute_clv()              # at game time / after lines move")
        print(f"{'═' * W}\n")
        return

    sign = "+" if summary["avg_clv_pct"] >= 0 else ""
    print(f"  Avg CLV             : {sign}{summary['avg_clv_pct']:.2f}%")
    print(f"  % bets positive CLV : {summary['positive_clv_pct']:.1f}%")
    print(f"\n  VERDICT: {summary['verdict']}")

    if summary["clv_by_tier"]:
        print(f"\n  CLV by Edge Tier:")
        print(f"  {'Tier':<10} {'Count':>6}  {'Avg CLV':>8}")
        print(f"  {'─'*30}")
        for tier in ("HIGH", "MED", "LOW", "UNKNOWN"):
            if tier in summary["clv_by_tier"]:
                d    = summary["clv_by_tier"][tier]
                s    = "+" if d["avg_clv_pct"] >= 0 else ""
                print(f"  {tier:<10} {d['count']:>6}  {s}{d['avg_clv_pct']:>7.2f}%")

    # ── Spreads & totals — line CLV (points), separate units from ML ──────────
    st = get_spread_total_clv_summary()
    if st["count"]:
        print(f"\n  Spreads & Totals — line CLV (points moved in your favor):")
        print(f"  {'Market':<8} {'N':>5} {'AvgLine':>9} {'Beat%':>7}  {'AvgPrice (matched)':>20}")
        print(f"  {'─'*52}")
        for mk, d in sorted(st["by_market"].items()):
            ap = (f"{d['avg_price_clv_pct']:+.2f}% (n={d['matched_price_n']})"
                  if d["avg_price_clv_pct"] is not None else "—")
            print(f"  {mk:<8} {d['count']:>5} {d['avg_line_clv']:>+8.2f}p {d['beat_close_pct']:>6.0f}%  {ap:>20}")

    snapshots = _load_snapshots()
    recent = [s for s in snapshots if s.get("clv") is not None][-10:]
    if recent:
        print(f"\n  Recent picks:")
        print(f"  {'Date':<12} {'Team':<28} {'Open':>6}  {'Close':>6}  {'CLV':>7}")
        print(f"  {'─'*62}")
        for s in recent:
            open_s  = f"{int(s['opening_odds']):+d}"  if s.get("opening_odds") else "  —"
            close_s = f"{int(s['closing_odds']):+d}" if s.get("closing_odds") else "  —"
            clv_s   = f"{s['clv_pct']:+.1f}%" if s.get("clv_pct") is not None else "  —"
            print(f"  {s['date']:<12} {s['team']:<28} {open_s:>6}  {close_s:>6}  {clv_s:>7}")

    print(f"{'═' * W}\n")
