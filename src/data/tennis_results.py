"""
Tennis results for grading — from tennis-data.co.uk (both tours).

The old grader used ESPN Core API (Grand Slams only, winners only) and never
settled anything — 149 Wimbledon shadow picks sat "pending" forever, so the
shadow experiment couldn't learn. tennis-data gives winner/loser AND per-set
game scores, which grades both moneyline and games-total picks, for every
tour-level event, with ~daily updates during tournaments.

Match keying: normalized player keys (see tennis_data.norm_odds_name) with a
±1 day window (late finishes cross the UTC/ET boundary).
"""
from __future__ import annotations

from datetime import date as _date, timedelta

from src.data.tennis_data import load_matches, norm_td_name, norm_odds_name


def _games_total(row) -> float | None:
    """Total games from set-score columns W1..W5 / L1..L5. None if unparsable."""
    import pandas as pd
    total = 0.0
    found = False
    for i in range(1, 6):
        w = getattr(row, f"W{i}", None)
        l = getattr(row, f"L{i}", None)
        if w is None or l is None or pd.isna(w) or pd.isna(l):
            continue
        total += float(w) + float(l)
        found = True
    return total if found else None


def build_results_index(tour: str, verbose: bool = False) -> dict:
    """{frozenset({winner_key, loser_key}): {"date", "winner_key", "games",
    "completed"}} for the current year's matches of one tour.

    A later entry for the same pair overwrites an earlier one — for grading a
    dated pick the caller checks the date window, and rematches within ±1 day
    of each other don't happen at tour level.
    """
    import pandas as pd

    year = _date.today().year
    matches = load_matches(tour, years=[year - 1, year], verbose=verbose)
    if len(matches) == 0:
        return {}

    index: dict[frozenset, list[dict]] = {}
    for row in matches.itertuples(index=False):
        w_raw, l_raw = getattr(row, "Winner", None), getattr(row, "Loser", None)
        if not isinstance(w_raw, str) or not isinstance(l_raw, str):
            continue
        comment = str(getattr(row, "Comment", "") or "").lower()
        if "walkover" in comment:
            continue
        wk, lk = norm_td_name(w_raw), norm_td_name(l_raw)
        d = getattr(row, "Date", None)
        try:
            match_date = d.date() if hasattr(d, "date") else None
        except Exception:
            match_date = None
        rec = {
            "date":       match_date,
            "winner_key": wk,
            "games":      _games_total(row),
            # Retirements settle the moneyline but NOT the total (the match
            # didn't run its full course — books void or grade totals by
            # rules that vary; we void to be safe).
            "completed":  "retired" not in comment,
        }
        index.setdefault(frozenset({wk, lk}), []).append(rec)
    return index


def find_result(index: dict, player_a: str, player_b: str,
                pick_date: _date, window_days: int = 1) -> dict | None:
    """Look up the result of player_a vs player_b near pick_date.

    player names are Odds API display names ("Jannik Sinner").
    """
    ka, kb = norm_odds_name(player_a), norm_odds_name(player_b)
    recs = index.get(frozenset({ka, kb}))

    def _tokens(key: str) -> set[str]:
        """Surname tokens of a normalized key ('camila osorio serrano m' →
        {'camila','osorio','serrano'}). Handles Odds API names whose extra
        given names leak into our surname slot."""
        return set(key.rsplit(" ", 1)[0].split()) if " " in key else {key}

    def _player_match(pick_key: str, idx_key: str, check_initial: bool) -> bool:
        # tennis-data surnames are single tokens ('vallejo d', 'wang xin');
        # match if that token appears anywhere in the pick's surname tokens,
        # and the initials are prefix-compatible ('x' vs 'xin' for the two
        # Wangs; equal initials otherwise).
        idx_last, idx_init = idx_key.rsplit(" ", 1) if " " in idx_key else (idx_key, "")
        pick_init = pick_key.rsplit(" ", 1)[1] if " " in pick_key else ""
        if idx_last not in _tokens(pick_key):
            return False
        if not check_initial:
            # Players who go by a middle name break initials entirely
            # ("Adolfo Daniel Vallejo" is 'vallejo d'). The surname *pair*
            # plus the date window below still identifies the match.
            return True
        return (not idx_init or not pick_init
                or idx_init.startswith(pick_init) or pick_init.startswith(idx_init))

    if not recs:
        # Fallback: token/initial-tolerant pair match. Collect ALL candidate
        # pairs — the date filter below disambiguates (e.g. both Wang sisters).
        # Strict initials first; if nothing at all, retry on surnames alone.
        for check_initial in (True, False):
            recs = []
            for pair, rr in index.items():
                names = sorted(pair)
                if len(names) != 2:
                    continue
                if ((_player_match(ka, names[0], check_initial) and _player_match(kb, names[1], check_initial))
                        or (_player_match(ka, names[1], check_initial) and _player_match(kb, names[0], check_initial))):
                    recs.extend(rr)
            if recs:
                break
    if not recs:
        return None
    hits = [
        rec for rec in recs
        if rec["date"] is not None
        and abs((rec["date"] - pick_date).days) <= window_days
    ]
    return hits[0] if len(hits) == 1 else None
