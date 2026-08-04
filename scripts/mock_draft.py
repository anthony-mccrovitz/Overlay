#!/usr/bin/env python3
"""Practice mock draft against ADP-anchored opponents.

Rehearsal for the live assistant: the recommendation screen is rendered by the
SAME code path as `chef.py draft --live` (build_board + recommend), and the
other eleven seats pick the way the Monte-Carlo sim's opponents do — near ADP
with realistic noise, nudged by their own roster holes. What this does NOT
rehearse is your league-mates' actual tendencies; it rehearses reading the
board under clock pressure.

Usage:
    python3 scripts/mock_draft.py                  # slot 10, fresh random seed
    python3 scripts/mock_draft.py --slot 3         # practice a different slot
    python3 scripts/mock_draft.py --seed 42        # reproducible opponents
    python3 scripts/mock_draft.py --auto           # watch a full auto-draft

At your pick:  Enter = take the top recommendation · a number = take that row
               · type a name fragment = take that player · b = show board · q = quit
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fantasy.draft import (DraftState, positional_run, recommend,
                               roster_counts, run_alert)
from src.fantasy.league import load as load_league
from src.fantasy.simulate import _opponent_pick, _starting_slots, lineup_value
from src.fantasy.valuation import build_board, starters_from_settings

# Real draft order, slot 1-12 (fetched from Sleeper 2026-08-03; cosmetic only).
SLOT_NAMES = ["Jpeen2018", "joeydonuts28", "mattsand28", "lufisher", "JLem11",
              "ConorD14", "Jakepacilio", "Joebaz75", "DaddyZilla", "amccrovitz",
              "jugss", "TheBoBus"]


def slot_of(overall: int, teams: int) -> int:
    rnd, pos = divmod(overall - 1, teams)
    return pos + 1 if rnd % 2 == 0 else teams - pos


def find_player(text: str, available, recs):
    """Resolve the user's input to a player: row number, else name fragment."""
    text = text.strip()
    if text.isdigit():
        i = int(text) - 1
        if 0 <= i < len(recs):
            return recs[i].value
        return None
    frag = text.lower()
    hits = [p for p in available if frag in p.name.lower()]
    if len(hits) > 1:
        exact = [p for p in hits if p.name.lower() == frag]
        if exact:
            return exact[0]
        print("    ambiguous: " + ", ".join(p.name for p in hits[:6]))
        return None
    if len(hits) == 1:
        hit = hits[0]
        # A fragment that lands on a deep-bench name is usually a typo for a
        # star who is already gone ("cook" → Brady Cook once James Cook is
        # taken). Require the full name before burning the pick on him.
        top60 = {p.player_id for p in available[:60]}
        if hit.player_id not in top60 and hit.name.lower() != frag:
            print(f"    only match is {hit.name} ({hit.position}, "
                  f"adp {hit.adp or 0:.0f}) — type his full name to confirm")
            return None
        return hit
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, default=10)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--rounds", type=int, default=14)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--auto", action="store_true",
                    help="No prompts: always take the top recommendation")
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else random.randrange(10 ** 6)
    rng = random.Random(seed)

    cfg = load_league()
    teams = cfg.teams
    board = build_board(cfg.scoring_settings, cfg.roster_positions, teams)
    bmap = {v.player_id: v for v in board}
    starters = {k: int(round(v / teams))
                for k, v in starters_from_settings(cfg.roster_positions, teams).items()}

    slots, _flex = _starting_slots(cfg.roster_positions)
    targets = dict(slots)
    targets["RB"] = targets.get("RB", 0) + 1
    targets["WR"] = targets.get("WR", 0) + 1
    opp_need = [dict(targets) for _ in range(teams + 1)]

    st = DraftState(draft_id="mock", teams=teams, rounds=args.rounds,
                    my_slot=args.slot)
    available = sorted((p for p in board if p.vorp is not None),
                       key=lambda p: (p.adp if p.adp is not None else 999.0))
    picks: list[dict] = []          # for positional_run, same shape as Sleeper's
    mine: list = []

    line = "═" * 96
    print(f"\n  {line}")
    print(f"  MOCK DRAFT — {cfg.summary()}")
    print(f"  slot {args.slot} ({SLOT_NAMES[args.slot - 1] if args.slot <= len(SLOT_NAMES) else '?'})"
          f"   ·   seed {seed}   ·   opponents draft near ADP with noise")
    print(f"  {line}")

    total = teams * args.rounds
    for overall in range(1, total + 1):
        if not available:
            break
        slot = slot_of(overall, teams)
        who = SLOT_NAMES[slot - 1] if slot <= len(SLOT_NAMES) else f"slot{slot}"

        if slot == args.slot:
            have = roster_counts(st.my_players, bmap)
            alert = run_alert(positional_run(picks, bmap))
            nexts = st.my_next_picks(3)
            print(f"\n  Pick {st.current_pick} of {total}"
                  f"   ·   your slot {st.my_slot}"
                  f"   ·   your next: {', '.join(map(str, nexts)) or '—'}"
                  f"   ← ON THE CLOCK")
            roster_line = "  ".join(f"{k}:{v}" for k, v in have.items() if v)
            if roster_line:
                print(f"  roster: {roster_line}")
            if alert:
                print(f"  ⚠  {alert}")

            recs = recommend(board, st, starters, top=args.top)
            print(f"\n  {'':<3}{'PLAYER':<24}{'POS':<5}{'VORP':>6}{'ADJ':>7}"
                  f"{'SURV':>6}{'ADP':>6}  WHY")
            print(f"  {'─' * 92}")
            for i, s_ in enumerate(recs, 1):
                v = s_.value
                print(f"  {i:<3}{v.name:<24}{v.position:<5}{v.vorp:>6.0f}"
                      f"{s_.adjusted:>7.0f}{s_.survives:>6.0%}"
                      f"{(v.adp or 0):>6.0f}  {s_.reason}")

            pick = None
            if args.auto:
                pick = recs[0].value
            else:
                while pick is None:
                    try:
                        text = input("\n  your pick [Enter = #1, number, name, b, q]: ")
                    except EOFError:
                        text = ""
                    if text.strip().lower() == "q":
                        print("\n  Mock abandoned.\n")
                        return 0
                    if text.strip().lower() == "b":
                        for j, p in enumerate(available[:25], 1):
                            print(f"    {j:<4}{p.name:<26}{p.position:<5}"
                                  f"{p.vorp:>6.0f}  adp {p.adp or 0:.0f}")
                        continue
                    if not text.strip():
                        pick = recs[0].value
                        break
                    pick = find_player(text, available, recs)
                    if pick is None:
                        print("    no match — try a row number or more of the name")
            mine.append(pick)
            st.my_players.append(pick.player_id)
            print(f"  ✓ you took {pick.name} ({pick.position})")
        else:
            pick = _opponent_pick(available, opp_need[slot], rng)
            opp_need[slot][pick.position] = max(
                0, opp_need[slot].get(pick.position, 0) - 1)
            rnd = (overall - 1) // teams + 1
            print(f"  {overall:>5}  r{rnd:<3}{who:<14}{pick.name:<26}{pick.position}")

        available.remove(pick)
        st.taken.add(pick.player_id)
        st.picks_made += 1
        picks.append({"player_id": pick.player_id})

    have = defaultdict(int)
    print(f"\n  {line}")
    print("  YOUR ROSTER")
    print(f"  {'─' * 60}")
    for i, p in enumerate(mine, 1):
        have[p.position] += 1
        print(f"  r{i:<4}{p.name:<26}{p.position:<5}{p.team:<4}"
              f"vorp {p.vorp:>4.0f}   adp {p.adp or 0:>5.0f}")
    lv = lineup_value(mine, cfg.roster_positions)
    print(f"\n  starting-lineup VORP: {lv:.0f}")
    print("  (sim benchmark from slot 10: RB-RB mean ≈ 407, p25 385, p75 435)")
    print(f"  replay these opponents: --seed {seed}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
