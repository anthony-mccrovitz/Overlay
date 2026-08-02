"""
src/tracking/schema.py — Canonical pick schema for Overlay.

Every pick written to data/pnl/picks.json uses this schema.
Both MLB and NBA write paths import from here — one format, no surprises.

SCHEMA (all fields, all sports)
────────────────────────────────────────────────────────────────────
  pick_id     str    "{sport}_{YYYYMMDD}_{team-slug}_{market}_{direction}"
  date        str    "YYYY-MM-DD"  game date in Eastern time
  sport       str    "mlb" | "nba" | "nfl"
  market      str    "moneyline" | "spread" | "total" | "nrfi" | "prop"
  direction   str    "WIN" | "COVER" | "OVER" | "UNDER" | "NRFI" | "YRFI"
  team        str    the bet side: team name, or "OVER 8.5" for totals
  matchup     str    "Away @ Home"  canonical game string
  odds        int    American odds: +140 or -110
  line        float  spread/total line; None for moneyline/NRFI
  sportsbook  str    "DraftKings" | "FanDuel" | "BetMGM" | "BetRivers" | None
  model_prob  float  model win probability [0, 1]
  edge_pct    float  (model_prob − implied_prob) × 100 — percentage points, not fraction
  stake       float  units staked: 1.0 = card pick; 0.0 = logged-only (not counted)
  card_pick   bool   True → posted on pick card → counts toward official record
  result      str    None | "win" | "loss" | "push"
  profit      float  units profit: +1.40 for +140 win on 1u; −1.0 for any loss
  recorded_at str    ISO 8601 UTC when pick was created
  resulted_at str    ISO 8601 UTC when result was set; None if pending
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


# ── Atomic picks I/O ─────────────────────────────────────────────────────────
# All 12+ scripts that write picks.json run concurrently from cron.
# Without a lock + atomic rename, last-writer-wins causes data loss.

_LOCK_PATH = Path("data/pnl/picks.lock")


def load_picks_safe(path: str | Path) -> dict:
    """Read picks.json under an exclusive lock. Returns {"picks": [...]}."""
    path = Path(path)
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            if not path.exists():
                return {"picks": []}
            raw = json.loads(path.read_text())
            if isinstance(raw, list):
                return {"picks": raw}
            if "picks" not in raw:
                return {"picks": []}
            return raw
        except (json.JSONDecodeError, OSError):
            return {"picks": []}
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


# Terminal settlement states. "void" is written by grade.py in five places
# (cancelled game, withdrawn player, postponed event) and is treated as settled
# by market_stats and public_stats — but this module only ever knew about
# win/loss/push, so normalize_pick silently nulled it. That made every migrate
# convert legitimately-voided picks back into "pending": 1,628 of them, which
# then read as a grading backlog that no grader could ever clear.
SETTLED_RESULTS = ("win", "loss", "push", "void")


def _is_ungraded(pick: dict) -> bool:
    """A pick is ungraded (safe to refresh) only if it has no settled result.
    Any settled result — or a booked profit — means it's final and immutable."""
    result = str(pick.get("result") or "").strip().lower()
    if result in SETTLED_RESULTS:
        return False
    return pick.get("profit") is None


def append_picks_safe(path: str | Path, new_picks: list[dict]) -> int:
    """Append new_picks to picks.json atomically under an exclusive lock.

    Every incoming pick is passed through normalize_pick first — this is THE
    normalization choke point. Emitters that hand-build dicts (predict.py's
    _auto_log_picks/_auto_log_props et al.) get canonical sport keys, the
    calibration-gate edge shrink, and card demotion applied here, so no write
    path can bypass them. Extra emitter fields (player, prop_market,
    model_agreement, …) are preserved by merging the normalized fields over
    the original dict.

    Deduplicates on pick_id. Returns count of picks actually added.
    Uses write-to-temp + os.replace (atomic rename on POSIX).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(_LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            # Read current state inside the lock
            if path.exists():
                try:
                    raw = json.loads(path.read_text())
                    data = raw if isinstance(raw, dict) and "picks" in raw else {"picks": raw if isinstance(raw, list) else []}
                except (json.JSONDecodeError, OSError):
                    # NEVER treat an unreadable ledger as an empty one. On
                    # 2026-08-02 a reader caught a non-atomic writer mid-write,
                    # took this branch as {"picks": []}, and its next append
                    # replaced 14,609 picks with 6. A truly fresh start is a
                    # missing or zero-byte file; anything else is corruption,
                    # and appending to corruption erases history. Preserve the
                    # evidence and refuse — today's picks re-log on the next
                    # run, the ledger doesn't come back.
                    if path.stat().st_size > 0:
                        import shutil
                        corrupt = path.with_suffix(path.suffix + ".corrupt")
                        shutil.copy(path, corrupt)
                        print(f"  [ledger] {path} is non-empty but unparseable — "
                              f"REFUSING to append (copy kept at {corrupt})")
                        return 0
                    data = {"picks": []}
            else:
                data = {"picks": []}

            existing_by_id = {p.get("pick_id", ""): p for p in data["picks"]
                              if isinstance(p, dict) and p.get("pick_id")}
            added = 0
            collisions: list[str] = []
            for pick in new_picks:
                norm = normalize_pick(pick)
                if norm is None:
                    continue  # fundamentally corrupted — never write it
                # Merge: canonical fields win, emitter extras survive
                merged = {**pick, **norm}
                pid = merged.get("pick_id", "")
                if pid and pid in existing_by_id:
                    # Re-logging an existing pick. If it's still UNGRADED, refresh
                    # its gate decision from the latest generation so a registry
                    # change (e.g. a retuned edge band) propagates to picks whose
                    # line didn't move. A SETTLED pick is immutable — never touch
                    # its card_pick/result. CLV lock fields (odds/line/recorded_at)
                    # are left as first logged.
                    cur = existing_by_id[pid]
                    if _is_ungraded(cur):
                        cur["card_pick"] = merged.get("card_pick", cur.get("card_pick"))
                    # A COLLISION IS NOT ALWAYS A RE-LOG. Same id + different
                    # game means two distinct wagers fighting over one key, and
                    # the loser vanishes. That is how 90 picks were lost before
                    # the id carried the matchup. Re-logging the identical bet
                    # (same game) is normal and stays quiet.
                    if _differs_by_game(cur, merged):
                        collisions.append(
                            f"{pid}: kept {cur.get('matchup')!r}, "
                            f"DROPPED {merged.get('matchup')!r}")
                    continue
                data["picks"].append(merged)
                existing_by_id[pid] = merged
                added += 1

            # Write to temp file then rename — atomic on POSIX
            tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_path, path)
            except Exception:
                os.unlink(tmp_path)
                raise

            if collisions:
                print(f"  [picks] {len(collisions)} pick(s) DROPPED on an id "
                      f"collision between different games — this is data loss, "
                      f"not deduplication:")
                for c in collisions[:5]:
                    print(f"    {c}")
                if len(collisions) > 5:
                    print(f"    … and {len(collisions) - 5} more")

            return added
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def overlay_graded_picks(path: str | Path, picks: list[dict]) -> tuple[int, int]:
    """Persist in-place grading mutations WITHOUT rewriting history.

    grade.py's flow is load → fetch scores (minutes pass) → mutate rows →
    save. Writing that whole snapshot back (the old `_save`) is a lock-free
    last-writer-wins: every pick a concurrent writer appended in the window
    was erased, and a crash mid-write truncated the ledger. This helper holds
    the ledger lock, RE-READS the current file, replaces only the rows the
    caller has (matched by pick_id, composite-field fallback for id-less
    rows), and renames atomically. The incumbent on-disk shape (bare list vs
    {"picks": ...}) is preserved.

    Caller-only rows are DROPPED, not appended: a concurrent migrate
    legitimately collapsed them, and a lost grade re-runs on the next sweep
    while a resurrected duplicate never dies.

    Returns (replaced, dropped).
    """
    path = Path(path)

    def _row_key(p: dict):
        pid = p.get("pick_id")
        if pid:
            return ("id", pid)
        return ("row", p.get("date"), p.get("sport"), p.get("team"),
                p.get("market"), p.get("direction"), p.get("line"),
                p.get("odds"), p.get("sportsbook"), p.get("strategy"))

    by_key = {_row_key(p): p for p in picks if isinstance(p, dict)}

    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            bare_list = False
            disk = None
            if path.exists():
                try:
                    raw = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    raw = None
                if isinstance(raw, list):
                    bare_list, disk = True, {"picks": raw}
                elif isinstance(raw, dict) and "picks" in raw:
                    disk = raw
            if disk is None:
                # Missing/unreadable ledger: grades are replayable, history
                # is not — refuse rather than write a snapshot over it.
                print(f"  [ledger] {path} unreadable — grading NOT persisted "
                      f"(re-runs on the next sweep)")
                return (0, len(by_key))

            used: set = set()
            replaced = 0
            out = []
            for row in disk["picks"]:
                k = _row_key(row) if isinstance(row, dict) else None
                if k is not None and k in by_key:
                    out.append(by_key[k])
                    used.add(k)
                    replaced += 1
                else:
                    out.append(row)
            dropped = len(by_key) - len(used)
            disk["picks"] = out

            payload = out if bare_list else disk
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(payload, f, indent=2)
                os.replace(tmp, path)
            except Exception:
                os.unlink(tmp)
                raise
            return (replaced, dropped)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _differs_by_game(a: dict, b: dict) -> bool:
    """True when two picks sharing an id describe DIFFERENT games.

    Only meaningful when both carry a matchup: an older row without one cannot
    be shown to be a different game, and guessing would turn every ordinary
    re-log into a false alarm.
    """
    ma, mb = str(a.get("matchup") or "").strip(), str(b.get("matchup") or "").strip()
    return bool(ma and mb and ma.lower() != mb.lower())


def rewrite_picks_safe(path: str | Path, data: dict) -> None:
    """Atomically rewrite the entire picks file (e.g. after grading results).

    Use only when you need to mutate existing picks (set result/profit).
    For adding new picks, prefer append_picks_safe.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(_LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_path, path)
            except Exception:
                os.unlink(tmp_path)
                raise
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


# Required fields — every canonical pick must have these.
# Markets validate_pick accepts. The list previously held only the six original
# game markets, so every per-market prop lane added since — batter_hits,
# pitcher_strikeouts, player_points and the rest — reported as an invalid market.
# That was 8,815 of 13,996 rows flagged on every migrate, which is loud enough
# that nobody reads the output and a REAL validation failure hides in it.
VALID_MARKETS = frozenset({
    # game markets
    "moneyline", "spread", "total", "f5_total", "nrfi", "outright", "unknown",
    # generic prop bucket (legacy) + per-market prop lanes
    "prop",
    "batter_hits", "batter_walks", "batter_rbis", "batter_home_runs",
    "batter_total_bases", "pitcher_strikeouts",
    "player_points", "player_assists", "player_rebounds", "player_goals",
    "player_shots_on_goal", "player_blocks", "player_steals", "player_threes",
    "player_pra", "player_blocked_shots",
    "anytime_scorer", "draw_no_bet", "win",
})

# Required fields, enforced by validate_pick. home_team/away_team are
# deliberately NOT here: they're derived from `matchup` on a best-effort basis
# and are absent whenever the fixture format is ambiguous, so requiring them
# would fail valid picks.
CANONICAL_FIELDS = (
    "pick_id", "date", "sport", "market", "direction",
    "team", "matchup", "odds", "line", "sportsbook",
    "model_prob", "edge_pct", "stake", "card_pick",
    "result", "profit", "recorded_at", "resulted_at",
)


def _split_matchup(matchup) -> tuple[str | None, str | None]:
    """('AWAY @ HOME') -> (away, home). Returns (None, None) if unparseable.

    Only " @ " is accepted as the separator. Soccer and tennis boards sometimes
    render fixtures with " v " or " vs ", where the ordering convention is NOT
    reliably away-first, and guessing there would silently invert home and away
    on entire leagues.
    """
    s = str(matchup or "").strip()
    if " @ " not in s:
        return None, None
    away, home = s.split(" @ ", 1)
    away, home = away.strip(), home.strip()
    return (away or None), (home or None)

# Strategies whose edge is an OBSERVED price difference between two venues,
# not a probability our models estimated. The calibration gate corrects model
# overconfidence; these have no model in them, so gating them shrinks real
# arithmetic. Keep this set tiny and justified — anything derived from our own
# probability estimates belongs under the gate.
_PRICE_OBSERVED_STRATEGIES: frozenset[str] = frozenset({"polymarket_ev"})

_SPORT_ALIASES: dict[str, str] = {
    "baseball_mlb":              "mlb",
    "basketball_nba":            "nba",
    "basketball_nba_summer_league": "nba",
    "basketball_wnba":           "wnba",
    "americanfootball_nfl":      "nfl",
    "americanfootball_ncaaf":    "ncaaf",
    "basketball_ncaab":          "ncaab",
    "icehockey_nhl":             "nhl",
}

def canonical_sport(sport: str) -> str:
    """Normalize any sport value to its short canonical form
    ('basketball_wnba' → 'wnba'). Public — use this instead of importing
    _SPORT_ALIASES; the alias table is the single source of truth here."""
    s = str(sport or "").lower().strip()
    return _SPORT_ALIASES.get(s, s)


_DIRECTION_ALIASES: dict[str, str] = {
    "ML":   "WIN",
    "H2H":  "WIN",
    "AWAY": "WIN",
}

_MARKET_ALIASES: dict[str, str] = {
    "h2h":        "moneyline",
    "ml":         "moneyline",
    "money_line": "moneyline",
    "moneylines": "moneyline",
    "run_line":   "spread",
    "runline":    "spread",
    "rl":         "spread",
    "spreads":    "spread",
    "puck_line":  "spread",
    "puck-line":  "spread",
    "over_under": "total",
    "totals":     "total",
    "ou":         "total",
    "f5_total":   "f5_total",
    "f5 total":   "f5_total",
}

# Canonical bet directions, shared by normalize_pick and validate_pick — they
# previously kept separate inline copies and drifted apart. YES/NO are the
# convention every anytime_scorer pick already used ("will this player score"),
# but only normalize_pick knew that, so all 35 of them failed validation while
# being perfectly well-formed.
VALID_DIRECTIONS: frozenset[str] = frozenset({
    "WIN", "HOME", "AWAY", "COVER", "OVER", "UNDER",
    "NRFI", "YRFI", "DRAW", "YES", "NO",
})

_DEFAULT_DIRECTION: dict[str, str] = {
    # WIN, not HOME: a moneyline direction we can't parse (e.g. a soccer model
    # emitting the team name) says nothing about which side of the venue the
    # team is on. Stamping HOME was a lie for away teams — WIN is always true.
    "moneyline": "WIN",
    "spread":    "COVER",
    "nrfi":      "NRFI",
    "prop":      "OVER",
}


# ─────────────────────────── Public helpers ─────────────────────────────────

def make_pick_id(sport: str, date: str, team: str, market: str,
                 direction: str, game: str = "") -> str:
    """
    Deterministic pick ID — safe to use as a deduplication key.

    Format: "{sport}_{YYYYMMDD}_{team-slug}[_{game-slug}]_{market}_{direction}"
    Examples:
      mlb_20260418_milwaukee-brewers_moneyline_win
      nba_20260417_orlando-magic_spread_cover
      mlb_20260418_over-8.5_g-tex-hou_total_over

    WHY `game` EXISTS. `team` does not always identify a game. For a total it is
    the packed line label ("OVER 7.5"), which is the SAME STRING in every game
    on the slate carrying that number; for a doubleheader it is the same team
    twice. The id was therefore not unique per wager, and `append_picks_safe`
    dedups on it — so the second and third OVER 7.5 games of a day were silently
    discarded. Measured on the source boards: 90 picks lost this way (64 totals,
    26 moneylines), including on mlb/total, the one lane betting real money,
    whose record was consequently built from a first-in-file-wins sample.

    `game` is a short slug of the matchup, not the full string: ids get read by
    humans in logs, and a 60-character id helps nobody.
    """
    date_c = date.replace("-", "")[:8]
    slug   = re.sub(r"[^a-z0-9]+", "-", team.lower()).strip("-")[:40]
    parts  = [sport, date_c, slug]
    if game:
        parts.append(_game_slug(game))
    parts += [market, direction]
    return "_".join(parts).lower()


def _game_slug(matchup: str) -> str:
    """'Texas Rangers @ Houston Astros' -> 'g-texran-houast'.

    CITY + NICKNAME, never the first two words. A city-only slug collapses
    'New York Yankees' and 'New York Mets' onto each other, which would
    reintroduce the very collision this qualifier exists to prevent — the
    nickname is the distinguishing token in every co-located pair (Cubs/White
    Sox, Angels/Dodgers, Yankees/Mets).
    """
    sides = re.split(r"\s+@\s+|\s+vs\.?\s+", str(matchup or "").strip(), maxsplit=1)
    out = []
    for side in sides[:2]:
        words = re.sub(r"[^a-z0-9 ]+", "", side.lower()).split()
        if not words:
            out.append("x")
        elif len(words) == 1:
            out.append(words[0][:6])
        else:
            out.append(words[0][:3] + words[-1][:3])
    return ("g-" + "-".join(out)) if out else ""


def profit_from_odds(odds: int | float, stake: float, won: bool) -> float:
    """
    Compute units profit from American odds.

    Canonical profit scale: stake=1.0 → 1 unit.
      win  +140 → +1.40u
      win  −110 → +0.909u
      loss any  → −stake
      push any  → 0.0u  (caller passes won=False, profit=0.0)
    """
    if not won:
        return -stake
    o = float(odds)
    if o >= 0:
        return stake * o / 100.0
    return stake * 100.0 / abs(o)


def validate_pick(pick: dict) -> list[str]:
    """Return a list of schema violations. Empty list means valid."""
    issues: list[str] = []
    for f in CANONICAL_FIELDS:
        if f not in pick:
            issues.append(f"missing field: {f}")

    market = pick.get("market", "")
    if market not in VALID_MARKETS:
        issues.append(f"invalid market: {market!r}")

    direction = pick.get("direction", "")
    if direction not in VALID_DIRECTIONS | {""}:
        issues.append(f"invalid direction: {direction!r}")

    result = pick.get("result")
    if result not in (None,) + SETTLED_RESULTS:
        issues.append(f"invalid result: {result!r}")

    odds = pick.get("odds")
    if odds is not None and not isinstance(odds, (int, float)):
        issues.append(f"odds must be numeric, got {type(odds).__name__}")

    profit = pick.get("profit")
    result_v = pick.get("result")
    odds_v   = pick.get("odds")
    # NRFI picks have odds=None (market not available on standard books)
    # so profit=None on a settled NRFI is acceptable.
    if result_v in ("win", "loss") and profit is None and odds_v is not None:
        issues.append("profit is None but result is set — grading bug")

    return issues


# ─────────────────────────── Normalization ──────────────────────────────────

def _clv_status_safe(sport: str, market: str) -> str:
    """CLV honesty tag for a pick; defaults to 'heuristic' if the registry is
    unavailable (never block pick logging on this)."""
    try:
        from src.config.models import clv_status
        return clv_status(sport, market)
    except Exception:
        return "heuristic"


def normalize_pick(raw: dict[str, Any]) -> dict | None:
    """
    Map any legacy pick dict to the canonical schema.

    Returns None for entries that are fundamentally corrupted and should be
    removed (e.g. paper-trade dollar-scale entries with bet_type instead of
    market, or entries with no identifiable team or date).

    The normalizer is idempotent: passing an already-canonical pick returns
    an identical pick. It never re-calculates profit for picks that already
    have a result — it trusts the stored value.
    """
    # ── Filter corrupted entries ─────────────────────────────────────────────
    # Paper-trade entries from an old code path use bet_type (not market) and
    # store dollar-scale profits (e.g. profit=96.15 on bet_size=100).
    if raw.get("bet_type") and not raw.get("market"):
        return None
    if not raw.get("team") or not raw.get("date"):
        return None

    # ── Sport ────────────────────────────────────────────────────────────────
    sport = str(raw.get("sport") or "mlb").lower().strip()
    sport = _SPORT_ALIASES.get(sport, sport)

    # ── Market ───────────────────────────────────────────────────────────────
    raw_market = str(raw.get("market") or "moneyline").lower().strip()
    market = _MARKET_ALIASES.get(raw_market, raw_market)

    # ── Team ─────────────────────────────────────────────────────────────────
    team = str(raw.get("team") or "").strip()

    # ── Date ─────────────────────────────────────────────────────────────────
    date_ = str(raw.get("date") or "").strip()
    # Normalize YYYY-MM-DD; leave YYYYMMDD as-is (pick_id will strip dashes)
    if len(date_) == 8 and "-" not in date_:
        date_ = f"{date_[:4]}-{date_[4:6]}-{date_[6:]}"

    # ── Direction ────────────────────────────────────────────────────────────
    direction = str(raw.get("direction") or "").upper().strip()
    direction = _DIRECTION_ALIASES.get(direction, direction)
    if not direction:
        if market == "total":
            parts = team.upper().split()
            direction = parts[0] if parts and parts[0] in ("OVER", "UNDER") else "OVER"
        else:
            direction = _DEFAULT_DIRECTION.get(market, "WIN")
    elif direction not in VALID_DIRECTIONS:
        # Numeric string used as direction (e.g. "-15.5" from WNBA spread bug)
        try:
            float(direction)
            direction = "COVER" if market == "spread" else "OVER"
        except ValueError:
            # A team name used as the direction (soccer/tennis model bug). This
            # used to be gated on len(direction) > 5, which quietly let every
            # SHORT name through — PISA, NICE, IRAN, IRAQ, QATAR all survived
            # normalization and then failed validation forever. Length was never
            # the signal; "not a valid direction" is.
            #
            # Prefer HOME/AWAY when the venue is known: home_team/away_team are
            # now derived from the matchup, so the old objection that stamping
            # HOME would be "a lie for away teams" no longer applies. Fall back
            # to the market default only when the venue is genuinely unknown.
            away_t, home_t = _split_matchup(raw.get("matchup"))
            home_t = (raw.get("home_team") or home_t or "").upper().strip()
            away_t = (raw.get("away_team") or away_t or "").upper().strip()
            if home_t and direction == home_t:
                direction = "HOME"
            elif away_t and direction == away_t:
                direction = "AWAY"
            else:
                direction = _DEFAULT_DIRECTION.get(market, "WIN")

    # ── Line ─────────────────────────────────────────────────────────────────
    line: float | None = raw.get("line") or raw.get("bet_line")
    if line is None and market == "total":
        parts = team.upper().split()
        try:
            line = float(parts[1]) if len(parts) > 1 else None
        except (ValueError, IndexError):
            line = None
    if line is not None:
        try:
            line = float(line)
        except (ValueError, TypeError):
            line = None

    # ── Matchup ──────────────────────────────────────────────────────────────
    matchup = str(raw.get("matchup") or "").strip()
    if not matchup:
        opponent = str(raw.get("opponent") or "").strip()
        if market == "nrfi":
            matchup = team      # NRFI team field IS the matchup ("Away @ Home")
        elif market == "total" and opponent:
            matchup = opponent  # totals opponent = "Away @ Home" already
        elif opponent:
            matchup = f"{team} vs {opponent}"

    # ── Sportsbook ───────────────────────────────────────────────────────────
    sportsbook = raw.get("sportsbook") or raw.get("book") or None
    if sportsbook:
        sportsbook = str(sportsbook).strip() or None

    # ── Odds ─────────────────────────────────────────────────────────────────
    odds_raw = raw.get("odds") or raw.get("best_odds")
    odds: int | None = None
    if odds_raw is not None:
        try:
            odds = int(float(odds_raw))
        except (ValueError, TypeError):
            odds = None

    # ── Stake ────────────────────────────────────────────────────────────────
    stake_raw = raw.get("stake") or raw.get("bet_size") or 0.0
    try:
        stake = float(stake_raw)
    except (ValueError, TypeError):
        stake = 0.0

    # ── Card pick ────────────────────────────────────────────────────────────
    # Existing entries may have card_pick set. For old entries without it,
    # treat stake > 0 as the card-pick signal.
    if "card_pick" in raw:
        card_pick = bool(raw["card_pick"])
    else:
        card_pick = stake > 0

    # ── Model prob ───────────────────────────────────────────────────────────
    model_prob_raw = raw.get("model_prob") or raw.get("win_prob")
    model_prob: float | None = None
    if model_prob_raw is not None:
        try:
            model_prob = float(model_prob_raw)
        except (ValueError, TypeError):
            model_prob = None

    # ── Edge (percentage points) ──────────────────────────────────────────────
    # Canonical: edge_pct is already a percentage (2.52 = 2.52%).
    # Legacy "edge" field was also stored as percentage (confirmed from data).
    edge_pct: float | None = None
    edge_raw = raw.get("edge_pct") or raw.get("edge")
    if edge_raw is not None:
        try:
            edge_pct = float(edge_raw)
        except (ValueError, TypeError):
            edge_pct = None

    # Sanity clamp. Tennis Elo edges against qualifiers legitimately reach
    # 40-60pp, so the upper bound is set generously at 100. The negative
    # bound (-100) catches sign-flip bugs without clipping legitimate losses.
    if edge_pct is not None:
        edge_pct = max(-100.0, min(edge_pct, 100.0))

    # ── Result / Profit ───────────────────────────────────────────────────────
    result = raw.get("result")
    if result not in (None,) + SETTLED_RESULTS:
        result = None

    # ── Calibration gate (X1) ─────────────────────────────────────────────────
    # Shrink the model's *claimed* edge to what has historically materialized on
    # this (sport, market), so an overconfident model can't manufacture phantom
    # edges (tennis totals once claimed +43% while winning 38%). Applied to
    # PENDING picks only — graded picks keep their recorded edge so the public
    # record and CLV history are never rewritten. Idempotent: raw_edge_pct pins
    # the original model claim, so re-normalizing never double-shrinks.
    #
    # EXEMPT: strategies whose "edge" is an observed price difference rather
    # than a model claim. polymarket_ev compares one venue's ask to another's
    # devigged price — arithmetic on two quoted numbers, with no probability
    # estimate of ours anywhere in it. There is no overconfidence to correct,
    # so applying mlb::moneyline's k (~0.04, fitted on OUR model's realised
    # edge) zeroed genuine 2-4% price gaps: on 2026-07-20 every MLB Polymarket
    # pick recorded edge_pct 0.0 against raw_edge_pct 2.0-4.5. The gate was
    # answering a question these picks never asked.
    raw_edge_pct = raw.get("raw_edge_pct")
    if raw_edge_pct is None:
        raw_edge_pct = edge_pct          # first pass: current edge IS the claim
    if (result is None and raw_edge_pct is not None
            and str(raw.get("strategy") or "") not in _PRICE_OBSERVED_STRATEGIES):
        try:
            from src.analytics.calibration_gate import calibrate_edge
            edge_pct = calibrate_edge(sport, market, raw_edge_pct)
        except Exception:
            pass  # never block pick logging on the gate

    profit_raw = raw.get("profit")
    profit: float | None = None
    if profit_raw is not None:
        try:
            profit = float(profit_raw)
        except (ValueError, TypeError):
            profit = None

    # ── Timestamps ────────────────────────────────────────────────────────────
    recorded_at = str(raw.get("recorded_at") or "")
    resulted_at = raw.get("resulted_at") or None

    # ── Card demotion on calibrated edge (X1/X2) ──────────────────────────────
    # A pick can only reach the card if its CALIBRATED edge still clears the
    # market's threshold. This can demote (never promote) — a phantom edge that
    # looked postable on the raw number is dropped centrally, no matter what the
    # runner decided. Pending picks only; graded card picks are frozen.
    if card_pick and result is None:
        try:
            from src.config.models import is_card_pick as _is_card_pick
            prop_arg = market if market not in (
                "moneyline", "spread", "total", "nrfi", "f5_total") else None
            if not _is_card_pick(sport, market, edge_pct, prop_arg,
                                 model_prob=model_prob):
                card_pick = False
                stake = 0.0
        except Exception:
            pass

    # ── Pick ID ───────────────────────────────────────────────────────────────
    pick_id = raw.get("pick_id")
    if pick_id:
        # Repair ids minted with a non-canonical sport prefix ("baseball_mlb_…"):
        # the same bet logged by two runners must collide in dedup, and it can't
        # if one id says baseball_mlb and the other says mlb. Only the prefix is
        # rewritten — the rest of the id is preserved so unaffected ids (and all
        # snapshot/CLV joins on them) stay stable.
        raw_sport = str(raw.get("sport") or "").lower().strip()
        if raw_sport in _SPORT_ALIASES and pick_id.startswith(raw_sport + "_"):
            pick_id = sport + pick_id[len(raw_sport):]
    else:
        # The matchup qualifies the id so two games sharing a line (or a
        # doubleheader sharing a team) cannot dedup each other away.
        pick_id = make_pick_id(sport, date_, team, market, direction,
                               game=str(raw.get("matchup") or ""))

    norm = {
        "pick_id":         pick_id,
        "date":            date_,
        "sport":           sport,
        "market":          market,
        "direction":       direction,
        "team":            team,
        "matchup":         matchup,
        "odds":            odds,
        "line":            line,
        "sportsbook":      sportsbook,
        "model_prob":      round(model_prob, 4) if model_prob is not None else None,
        # PRE-calibration model probability, stamped by the emitter. Calibrator
        # fitting trains on THIS (raw → outcome); training on the stored
        # post-calibration model_prob was a feedback loop (train-on-calibrated,
        # apply-on-raw) that compounded shrinkage on every refit.
        "model_prob_raw":  (round(float(raw["model_prob_raw"]), 4)
                            if raw.get("model_prob_raw") is not None else None),
        "edge_pct":        round(edge_pct, 2) if edge_pct is not None else None,
        # The model's original pre-calibration claim, pinned for idempotency and
        # so we can audit how much the gate shrank each pick.
        "raw_edge_pct":    round(float(raw_edge_pct), 2) if raw_edge_pct is not None else None,
        "stake":           stake,
        "card_pick":       card_pick,
        "result":          result,
        "profit":          round(profit, 4) if profit is not None else None,
        "recorded_at":     recorded_at,
        "resulted_at":     resulted_at,
        "model_version":   raw.get("model_version"),
        "model_tier":      raw.get("model_tier") or None,
        "weather_context": raw.get("weather_context") or None,
        "team_form":       raw.get("team_form") or None,
        "shadow_filter":   raw.get("shadow_filter") or None,
        # Shadow-strategy tag: which research rule/model produced this pick.
        # null = a normal model/card pick. Used to slice CLV by strategy.
        "strategy":        raw.get("strategy") or None,
        # Taint tag: set by scripts/taint_bad_picks.py on picks produced by a
        # known-broken mechanism (degenerate calibrator, team-blind ratings, …).
        # Tainted picks keep their graded results but are excluded from public
        # stats, the record, and calibration/gate fitting.
        "tainted":         raw.get("tainted") or None,
        # CLV honesty tag: 'validated' only if the market passed the CLV gate
        # (chef.py promote); otherwise 'heuristic'. Stamped on EVERY pick so a
        # card pick is never mistaken for a proven-edge bet. Auto-flips to
        # 'validated' the moment a market is promoted — no per-runner change.
        "clv_status":      raw.get("clv_status") or _clv_status_safe(sport, market),
    }
    # Derive home/away from the matchup. Both fields exist on the schema and
    # essentially nothing ever wrote them — 0% populated on every lane with a
    # meaningful sample — while `matchup` is populated ~100% of the time in
    # "AWAY @ HOME" form. Any home/away split therefore silently classified every
    # pick as away and produced a bias that looked real. Deriving here means one
    # implementation instead of one per runner, and `chef.py migrate` backfills
    # the history.
    if not norm.get("home_team") or not norm.get("away_team"):
        away, home = _split_matchup(norm.get("matchup"))
        norm["home_team"] = raw.get("home_team") or home
        norm["away_team"] = raw.get("away_team") or away

    # Auto-classify shadow_filter if missing — keeps every pipeline tagged
    # without each one needing to import the filter explicitly.
    if not norm["shadow_filter"]:
        try:
            from src.analytics.shadow_filters import classify_form_filter
            norm["shadow_filter"] = classify_form_filter(norm)
        except Exception:
            pass
    return norm


def migrate_picks_file(path_in: str, path_out: str | None = None) -> dict:
    """Locked entry point — see _migrate_picks_file_unlocked for the work.

    Migrate's read→normalize→write cycle spans seconds on a 14k-pick ledger;
    unlocked, an append_picks_safe landing in that window is silently undone
    by migrate's write (or vice versa, whichever finishes second loses).
    """
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOCK_PATH, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            return _migrate_picks_file_unlocked(path_in, path_out)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _migrate_picks_file_unlocked(path_in: str, path_out: str | None = None) -> dict:
    """
    Migrate a picks.json file to the canonical schema.

    - Normalizes all picks to canonical fields.
    - Removes corrupted entries (bet_type schema, no team/date).
    - Deduplicates on pick_id, keeping the first occurrence by recorded_at.
    - Writes atomically: writes to a temp path then renames.

    Returns summary: {total_in, removed, deduplicated, total_out}
    """
    import json
    import os
    import tempfile
    from pathlib import Path

    src = Path(path_in)
    dst = Path(path_out or path_in)

    if not src.exists():
        return {"error": f"{src} not found"}

    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):        # legacy bare-list picks file
        data = {"picks": data}

    raw_picks = data.get("picks", [])
    total_in  = len(raw_picks)
    removed   = 0
    normalized: list[dict] = []

    for raw in raw_picks:
        pick = normalize_pick(raw)
        if pick is None:
            removed += 1
            continue
        normalized.append(pick)

    # Deduplicate per pick_id. Sport-key canonicalization above makes the
    # double-logged twins collide here (an ungated "baseball_mlb" pitcher-K row
    # and its gated "mlb" duplicate now share one id) — keep the BEST row, not
    # the first-recorded one: graded beats pending, gated (raw_edge_pct
    # stamped) beats ungated, then earliest recorded_at wins.
    def _quality(p: dict) -> tuple:
        return (
            p.get("result") is not None,          # graded first
            p.get("raw_edge_pct") is not None,    # gate ran on it
        )  # ties: the earlier-recorded row wins (ascending scan keeps first)

    normalized.sort(key=lambda p: p.get("recorded_at") or "")
    best_by_id: dict[str, dict] = {}
    deduplicated = 0
    for p in normalized:
        pid = p["pick_id"]
        cur = best_by_id.get(pid)
        if cur is None:
            best_by_id[pid] = p
            continue
        deduplicated += 1
        if _quality(p) > _quality(cur):
            best_by_id[pid] = p

    # Collapse game-slug twins: one wager logged under a g- qualified id
    # (…_over-6-5_g-newyan-chicub_total_over) by one writer and under the
    # unqualified id (…_over-6-5_total_over) by another. The exact-id dedup
    # above cannot see the pair, so a card pick counts twice — 3 doubled card
    # totals were live on 2026-08-02 when this landed. The g- id survives
    # (every writer mints it now, so the next pipeline run collides against
    # it); the _quality-better row's fields win and its gaps fill from the
    # twin. Matchups must MATCH to merge — an unqualified "OVER 7.5" from a
    # different game on the same slate is a distinct wager, not a twin.
    _g_seg = re.compile(r"_g-[a-z0-9-]+(?=_)")
    base_to_g: dict[str, list[str]] = {}
    for gid in best_by_id:
        if "_g-" not in gid:
            continue
        base = _g_seg.sub("", gid, count=1)
        if base != gid and base in best_by_id:
            base_to_g.setdefault(base, []).append(gid)

    def _fill_gaps(dst: dict, src: dict) -> None:
        for k, v in src.items():
            cur = dst.get(k)
            blank = cur is None or cur == "" or (isinstance(cur, float) and cur != cur)
            if blank and v is not None and v != "":
                dst[k] = v

    for base, gids in base_to_g.items():
        b_row = best_by_id[base]
        same_game = [g for g in gids
                     if (b_row.get("matchup") or "") == (best_by_id[g].get("matchup") or "")]
        if len(same_game) != 1:
            continue  # ambiguous (doubleheader) or different games — keep both
        gid = same_game[0]
        g_row = best_by_id[gid]
        primary, other = (g_row, b_row)
        if _quality(b_row) > _quality(g_row) or (
            _quality(b_row) == _quality(g_row)
            and (b_row.get("recorded_at") or "") > (g_row.get("recorded_at") or "")
        ):
            primary, other = b_row, g_row
        merged = dict(primary)
        _fill_gaps(merged, other)
        merged["pick_id"] = gid
        best_by_id[gid] = merged
        del best_by_id[base]
        deduplicated += 1

    deduped = list(best_by_id.values())

    # Restore chronological order
    deduped.sort(key=lambda p: p.get("recorded_at") or "")

    out_data = {**data, "picks": deduped}

    # Atomic write
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(out_data, f, indent=2)
        os.replace(tmp, dst)
    except Exception:
        os.unlink(tmp)
        raise

    return {
        "total_in":     total_in,
        "removed":      removed,
        "deduplicated": deduplicated,
        "total_out":    len(deduped),
    }
