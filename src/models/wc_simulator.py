"""
World Cup 2026 Monte Carlo tournament simulator.

Drives SoccerModelV2 through the full 48-team bracket thousands of times to
produce *futures* probabilities — win the cup, reach the final, advance from
the group, etc. — the centrepiece numbers for World Cup content.

Bracket (groups, fixtures, venues, knockout wiring) is loaded live from the
openfootball world-cup.json/2026 dataset and parsed generically, so if FIFA
tweaks a fixture the sim follows automatically.

Format: 12 groups of 4 → top 2 of each group + 8 best third-place teams = 32 →
Round of 32 → R16 → QF → SF → Final.

Usage:
    from src.models.soccer_model_v2 import load_or_fit_model_v2
    from src.models.wc_simulator import WorldCup2026

    model = load_or_fit_model_v2(); model.seed_from_eloratings()
    wc = WorldCup2026(model)
    futures = wc.simulate(n_sims=20000)
    futures["champion"]  # → {team: prob, ...} sorted desc
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from src.data.soccer_data import _fetch_json, normalize_team_name

BRACKET_URL = ("https://raw.githubusercontent.com/openfootball/"
               "world-cup.json/master/2026/worldcup.json")

# 2026 co-hosts get a real home edge at their own venues (Tier 1b / Tier 4).
HOSTS = {"United States", "Mexico", "Canada"}
# Host cities by country (used to award home advantage when a host plays there).
HOST_CITIES = {
    "United States": {"Atlanta", "Boston", "Dallas", "Houston", "Kansas City",
                      "Los Angeles", "Miami", "New York", "Philadelphia",
                      "San Francisco", "Seattle", "East Rutherford",
                      "Inglewood", "Arlington", "Foxborough", "Santa Clara"},
    "Mexico": {"Mexico City", "Guadalajara", "Guadalajara (Zapopan)", "Monterrey"},
    "Canada": {"Toronto", "Vancouver"},
}
# High-altitude venues (m). Mexico City ~2240m, Guadalajara ~1566m, Monterrey ~540m.
ALTITUDE_VENUES = {"Mexico City": 2240, "Guadalajara": 1566,
                   "Guadalajara (Zapopan)": 1566, "Monterrey": 540}
# Teams habituated to altitude (host highlands + Andean CONMEBOL). At a high
# venue these sides keep their legs while sea-level visitors fade (Tier 4).
ALTITUDE_ACCLIMATED = {"Mexico", "Bolivia", "Ecuador", "Colombia", "Peru"}
ALT_THRESHOLD_M = 1500   # below this, altitude is a non-factor
ALT_MAX_ELO = 55.0       # Elo-equiv edge at Mexico City for an acclimated side


@dataclass
class Group:
    letter: str
    teams: list[str]
    fixtures: list[tuple[str, str, str]]  # (home, away, city)


# Knockout round → internal code and ordering.
ROUND_CODE = {
    "Round of 32": "R32", "Round of 16": "R16", "Quarter-final": "QF",
    "Semi-final": "SF", "Final": "final",
}
ROUND_SEQ = ["R32", "R16", "QF", "SF", "final", "champion"]
NEXT_ROUND = {"R32": "R16", "R16": "QF", "QF": "SF", "SF": "final", "final": "champion"}


@dataclass
class KOMatch:
    num: int
    spec1: str
    spec2: str
    code: str          # R32 / R16 / QF / SF / final
    city: str = ""


@dataclass
class Bracket:
    groups: dict[str, Group]
    ko: list[KOMatch] = field(default_factory=list)
    third_slots: dict[int, list[str]] = field(default_factory=dict)  # match num → eligible group letters


def load_bracket_2026() -> Bracket:
    """Parse the openfootball 2026 dataset into a structured bracket."""
    data = _fetch_json(BRACKET_URL, "wc_2026_struct", max_age_days=7)
    if not data:
        raise RuntimeError("Could not load 2026 World Cup bracket data.")
    matches = data["matches"]

    groups: dict[str, Group] = {}
    ko: list[KOMatch] = []
    third_slots: dict[int, list[str]] = {}

    for m in matches:
        grp = m.get("group")
        t1, t2 = m.get("team1", ""), m.get("team2", "")
        city = m.get("ground", "")
        if grp:
            letter = grp.replace("Group ", "").strip()
            g = groups.setdefault(letter, Group(letter, [], []))
            for t in (t1, t2):
                tn = normalize_team_name(t)
                if tn not in g.teams:
                    g.teams.append(tn)
            g.fixtures.append((normalize_team_name(t1), normalize_team_name(t2), city))
        else:
            rnd = m.get("round", "")
            code = ROUND_CODE.get(rnd)
            if code is None:
                continue  # skip "Match for third place" — irrelevant to futures
            num = int(m.get("num", 0)) or 103  # Final has no num → place it last
            ko.append(KOMatch(num, t1, t2, code, city))
            # Parse best-third eligibility, e.g. "3A/B/C/D/F" → [A,B,C,D,F]
            for spec in (t1, t2):
                mm = re.match(r"3([A-L/]+)", spec)
                if mm:
                    third_slots[num] = mm.group(1).split("/")

    return Bracket(groups=groups, ko=ko, third_slots=third_slots)


class WorldCup2026:
    """Monte Carlo engine over the 2026 bracket using a SoccerModelV2."""

    def __init__(self, model, bracket: Bracket | None = None):
        self.model = model
        self.bracket = bracket or load_bracket_2026()
        self._grid_cache: dict[tuple, np.ndarray] = {}
        self._rng = np.random.default_rng()

    # ── Match sampling ────────────────────────────────────────────────────────

    def _host_adv(self, home: str, away: str, city: str) -> float:
        """
        Net Elo-equivalent edge for the home side from venue effects:
        co-host home advantage + altitude acclimatization. Positive favors home.
        """
        adv = 0.0
        # Co-host home advantage
        for country, cities in HOST_CITIES.items():
            if city in cities:
                if home == country:
                    adv += self.model.HOST_BONUS
                elif away == country:
                    adv -= self.model.HOST_BONUS
                break
        # Altitude: acclimatized side gains vs a non-acclimatized opponent.
        alt = ALTITUDE_VENUES.get(city, 0)
        if alt >= ALT_THRESHOLD_M:
            scale = (alt - ALT_THRESHOLD_M) / (2240 - ALT_THRESHOLD_M)
            bonus = ALT_MAX_ELO * max(0.0, min(scale, 1.0))
            h_ok = home in ALTITUDE_ACCLIMATED
            a_ok = away in ALTITUDE_ACCLIMATED
            if h_ok and not a_ok:
                adv += bonus
            elif a_ok and not h_ok:
                adv -= bonus
        return adv

    def _cache(self, home: str, away: str, city: str = "") -> tuple:
        """Cached (cumulative scoreline distribution, grid_dim, home shootout share)."""
        adv = self._host_adv(home, away, city)
        key = (home, away, round(adv, 1))
        c = self._grid_cache.get(key)
        if c is None:
            grid = self.model.score_grid(home, away, neutral=True, home_adv_elo=adv)
            n = grid.shape[0]
            flat = grid.flatten()
            flat = flat / flat.sum()
            cum = np.cumsum(flat)
            # Shootout share = P(home wins outright) / P(decisive)
            ph = float(np.tril(grid, -1).sum())
            pa = float(np.triu(grid, 1).sum())
            share = ph / (ph + pa) if (ph + pa) > 0 else 0.5
            c = (cum, n, share)
            self._grid_cache[key] = c
        return c

    def _play(self, home: str, away: str, city: str = "") -> tuple[int, int]:
        """Sample a scoreline (home_goals, away_goals)."""
        cum, n, _ = self._cache(home, away, city)
        idx = int(np.searchsorted(cum, self._rng.random()))
        return divmod(idx, n)

    def _play_knockout(self, home: str, away: str, city: str = "") -> str:
        """Play a knockout match; resolve draws by a strength-weighted shootout."""
        cum, n, share = self._cache(home, away, city)
        idx = int(np.searchsorted(cum, self._rng.random()))
        hg, ag = divmod(idx, n)
        if hg > ag:
            return home
        if ag > hg:
            return away
        return home if self._rng.random() < share else away

    # ── Group stage ───────────────────────────────────────────────────────────

    def _sim_group(self, g: Group) -> dict[str, dict]:
        """Simulate one group, return per-team {pts, gd, gf} standings."""
        table = {t: {"pts": 0, "gd": 0, "gf": 0} for t in g.teams}
        for home, away, city in g.fixtures:
            hg, ag = self._play(home, away, city)
            table[home]["gf"] += hg
            table[away]["gf"] += ag
            table[home]["gd"] += hg - ag
            table[away]["gd"] += ag - hg
            if hg > ag:
                table[home]["pts"] += 3
            elif ag > hg:
                table[away]["pts"] += 3
            else:
                table[home]["pts"] += 1
                table[away]["pts"] += 1
        return table

    @staticmethod
    def _rank(table: dict[str, dict]) -> list[str]:
        """Rank teams in a group by pts, gd, gf (ties broken randomly via jitter)."""
        return sorted(table, key=lambda t: (table[t]["pts"], table[t]["gd"],
                                            table[t]["gf"], np.random.random()),
                      reverse=True)

    # ── One full tournament ───────────────────────────────────────────────────

    def _sim_once(self) -> dict[str, str]:
        """Simulate a whole tournament; return team → furthest round reached."""
        reached: dict[str, str] = {}
        winners: dict[str, str] = {}   # "1A" → team, "2A" → team
        thirds: list[tuple[str, str, dict]] = []  # (group_letter, team, stats)

        for letter, g in self.bracket.groups.items():
            table = self._sim_group(g)
            order = self._rank(table)
            winners[f"1{letter}"] = order[0]
            winners[f"2{letter}"] = order[1]
            thirds.append((letter, order[2], table[order[2]]))
            for t in order[2:]:
                reached[t] = "group"          # eliminated in group (3rd may upgrade)
            for t in order[:2]:
                reached[t] = "R32"

        # Best 8 third-place teams
        thirds.sort(key=lambda x: (x[2]["pts"], x[2]["gd"], x[2]["gf"],
                                   np.random.random()), reverse=True)
        qualified_thirds = thirds[:8]
        for _, t, _ in qualified_thirds:
            reached[t] = "R32"

        # Assign thirds to their R32 slots (keyed by match num) respecting
        # group eligibility (greedy, most-constrained slot first).
        third_by_num = self._assign_thirds(qualified_thirds)

        # Knockout rounds — process in bracket order (num), Final last.
        results: dict[int, str] = {}
        for ko in sorted(self.bracket.ko, key=lambda k: (ROUND_SEQ.index(k.code), k.num)):
            home = self._resolve(ko.spec1, winners, results, third_by_num.get(ko.num))
            away = self._resolve(ko.spec2, winners, results, third_by_num.get(ko.num))
            if not home or not away:
                continue
            w = self._play_knockout(home, away, ko.city)
            results[ko.num] = w
            loser = away if w == home else home
            reached[loser] = ko.code
            reached[w] = NEXT_ROUND[ko.code]

        return reached

    def _assign_thirds(self, qualified_thirds) -> dict[int, str]:
        """
        Assign the 8 qualified third-place teams to the 8 R32 third-slots via a
        complete bipartite matching (augmenting paths), so every slot is filled
        and the knockout chain never breaks. Slots ↔ group letters by eligibility.
        """
        slots = list(self.bracket.third_slots.items())   # [(num, [letters]), ...]
        team_by_letter = {letter: team for letter, team, _ in qualified_thirds}
        qualified_letters = set(team_by_letter)

        # match_for[num] = group letter assigned
        match_for: dict[int, str] = {}

        def augment(num, eligible, seen):
            for letter in eligible:
                if letter in qualified_letters and letter not in seen:
                    seen.add(letter)
                    # letter free, or its current slot can be reassigned
                    cur = next((n for n, l in match_for.items() if l == letter), None)
                    if cur is None or augment(cur, slots_map[cur], seen):
                        match_for[num] = letter
                        return True
            return False

        slots_map = {num: letters for num, letters in slots}
        for num, letters in sorted(slots, key=lambda s: len(s[1])):
            augment(num, letters, set())

        return {num: team_by_letter[letter] for num, letter in match_for.items()}

    def _resolve(self, spec: str, winners: dict, results: dict,
                 third_team: str | None) -> str | None:
        """Resolve a bracket spec ('1A', '2B', 'W74', '3C/D/..') to a team."""
        spec = spec.strip()
        if spec.startswith("3"):
            return third_team
        if spec in winners:
            return winners[spec]
        if spec.startswith("W"):
            try:
                return results.get(int(spec[1:]))
            except ValueError:
                return None
        return None

    # ── Public: run many sims ─────────────────────────────────────────────────

    def simulate(self, n_sims: int = 20000) -> dict[str, dict[str, float]]:
        """
        Run n_sims tournaments. Returns probability tables keyed by milestone:
            advance (out of group), R16, QF, SF, final, champion
        Each maps team → probability, sorted descending.
        """
        rank_order = ["R32", "R16", "QF", "SF", "final", "champion"]
        rank_idx = {r: i for i, r in enumerate(rank_order)}
        counts: dict[str, dict[str, int]] = {r: defaultdict(int) for r in rank_order}

        for _ in range(n_sims):
            reached = self._sim_once()
            for team, furthest in reached.items():
                if furthest == "group":
                    continue
                fi = rank_idx.get(furthest, 0)
                # Team counts for every milestone up to and including 'furthest'
                for r in rank_order[:fi + 1]:
                    counts[r][team] += 1

        out: dict[str, dict[str, float]] = {}
        labels = {"R32": "advance", "R16": "reach_R16", "QF": "reach_QF",
                  "SF": "reach_SF", "final": "reach_final", "champion": "champion"}
        for r in rank_order:
            tbl = {t: c / n_sims for t, c in counts[r].items()}
            out[labels[r]] = dict(sorted(tbl.items(), key=lambda x: x[1], reverse=True))
        return out
