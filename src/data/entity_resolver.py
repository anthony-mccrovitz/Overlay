"""
Cross-market entity resolution.

The same event shows up with different names on every platform:
  Kalshi:      "Will the Chicago Cubs win on April 17?"
  Polymarket:  "Cubs win 4/17/26"
  Sportsbook:  home_team="Chicago Cubs", away_team="St. Louis Cardinals"

This module normalizes market titles across sources so the arb finder
can match the same event across Kalshi, Polymarket, and sportsbooks.

Approach:
  1. Normalize: lowercase, strip punctuation, remove stopwords
  2. Entity extraction: find known team/player names, dates
  3. Fuzzy title match (difflib SequenceMatcher)
  4. Score = entity_overlap * 0.6 + title_similarity * 0.4
  5. Cache confirmed matches to disk
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

CACHE_PATH = Path("data/cache/entity_matches.json")

# Minimum score to consider two markets the same event
MATCH_THRESHOLD = 0.65

# Words that add no signal
_STOPWORDS = frozenset({
    "will", "the", "a", "an", "on", "in", "at", "to", "be", "is", "are",
    "their", "this", "of", "for", "vs", "versus", "win", "wins", "lose",
    "loses", "beat", "beats", "game", "match", "series", "tonight", "today",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
})

# MLB team names and all known aliases
MLB_TEAMS: dict[str, list[str]] = {
    "angels": ["angels", "los angeles angels", "la angels", "laa"],
    "astros": ["astros", "houston astros", "hou"],
    "athletics": ["athletics", "oakland athletics", "as", "oak", "oakland as"],
    "blue_jays": ["blue jays", "toronto blue jays", "tor"],
    "braves": ["braves", "atlanta braves", "atl"],
    "brewers": ["brewers", "milwaukee brewers", "mil"],
    "cardinals": ["cardinals", "st louis cardinals", "stl", "st. louis cardinals"],
    "cubs": ["cubs", "chicago cubs", "chc"],
    "diamondbacks": ["diamondbacks", "arizona diamondbacks", "ari", "dbacks"],
    "dodgers": ["dodgers", "los angeles dodgers", "la dodgers", "lad"],
    "giants": ["giants", "san francisco giants", "sf"],
    "guardians": ["guardians", "cleveland guardians", "cle"],
    "mariners": ["mariners", "seattle mariners", "sea"],
    "marlins": ["marlins", "miami marlins", "mia"],
    "mets": ["mets", "new york mets", "nym"],
    "nationals": ["nationals", "washington nationals", "was", "wsh"],
    "orioles": ["orioles", "baltimore orioles", "bal"],
    "padres": ["padres", "san diego padres", "sd"],
    "phillies": ["phillies", "philadelphia phillies", "phi"],
    "pirates": ["pirates", "pittsburgh pirates", "pit"],
    "rangers": ["rangers", "texas rangers", "tex"],
    "rays": ["rays", "tampa bay rays", "tb"],
    "red_sox": ["red sox", "boston red sox", "bos"],
    "reds": ["reds", "cincinnati reds", "cin"],
    "rockies": ["rockies", "colorado rockies", "col"],
    "royals": ["royals", "kansas city royals", "kc"],
    "tigers": ["tigers", "detroit tigers", "det"],
    "twins": ["twins", "minnesota twins", "min"],
    "white_sox": ["white sox", "chicago white sox", "cws"],
    "yankees": ["yankees", "new york yankees", "nyy"],
}

# NBA team names
NBA_TEAMS: dict[str, list[str]] = {
    "bucks": ["bucks", "milwaukee bucks", "mil"],
    "bulls": ["bulls", "chicago bulls", "chi"],
    "cavaliers": ["cavaliers", "cleveland cavaliers", "cle", "cavs"],
    "celtics": ["celtics", "boston celtics", "bos"],
    "clippers": ["clippers", "los angeles clippers", "lac"],
    "grizzlies": ["grizzlies", "memphis grizzlies", "mem"],
    "hawks": ["hawks", "atlanta hawks", "atl"],
    "heat": ["heat", "miami heat", "mia"],
    "hornets": ["hornets", "charlotte hornets", "cha"],
    "jazz": ["jazz", "utah jazz", "uta"],
    "kings": ["kings", "sacramento kings", "sac"],
    "knicks": ["knicks", "new york knicks", "nyk"],
    "lakers": ["lakers", "los angeles lakers", "lal"],
    "magic": ["magic", "orlando magic", "orl"],
    "mavericks": ["mavericks", "dallas mavericks", "dal", "mavs"],
    "nets": ["nets", "brooklyn nets", "bkn"],
    "nuggets": ["nuggets", "denver nuggets", "den"],
    "pacers": ["pacers", "indiana pacers", "ind"],
    "pelicans": ["pelicans", "new orleans pelicans", "nop"],
    "pistons": ["pistons", "detroit pistons", "det"],
    "raptors": ["raptors", "toronto raptors", "tor"],
    "rockets": ["rockets", "houston rockets", "hou"],
    "sixers": ["sixers", "philadelphia 76ers", "phi", "76ers"],
    "spurs": ["spurs", "san antonio spurs", "sas"],
    "suns": ["suns", "phoenix suns", "phx"],
    "thunder": ["thunder", "oklahoma city thunder", "okc"],
    "timberwolves": ["timberwolves", "minnesota timberwolves", "min", "wolves"],
    "trail_blazers": ["trail blazers", "portland trail blazers", "por", "blazers"],
    "warriors": ["warriors", "golden state warriors", "gsw"],
    "wizards": ["wizards", "washington wizards", "was"],
}

# Build reverse lookup: alias → canonical key
_MLB_ALIAS_TO_KEY: dict[str, str] = {}
for _k, _aliases in MLB_TEAMS.items():
    for _a in _aliases:
        _MLB_ALIAS_TO_KEY[_a.lower()] = _k

_NBA_ALIAS_TO_KEY: dict[str, str] = {}
for _k, _aliases in NBA_TEAMS.items():
    for _a in _aliases:
        _NBA_ALIAS_TO_KEY[_a.lower()] = _k

# Date extraction patterns
_DATE_PATTERNS = [
    r"\b(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?\b",   # 4/17, 4/17/26, 04-17-2026
    r"\b(april|may|june|july|august|september|october|november|december|january|february|march)\s+(\d{1,2})\b",
]
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


@dataclass
class MatchResult:
    score: float
    matched_teams: list[str]
    matched_date: str | None
    title_similarity: float


def normalize_title(title: str) -> str:
    """
    Normalize a market title for comparison.
    "Will the Chicago Cubs win on April 17?" → "chicago cubs april 17"
    """
    # Unicode normalize
    title = unicodedata.normalize("NFKD", title)
    # Lowercase
    title = title.lower()
    # Remove punctuation except / and - (used in dates)
    title = re.sub(r"[^\w\s/\-]", " ", title)
    # Remove stopwords
    tokens = [t for t in title.split() if t not in _STOPWORDS]
    return " ".join(tokens)


def extract_teams(text: str) -> list[str]:
    """Extract canonical team keys from a normalized text string."""
    found: set[str] = set()
    lower = text.lower()

    def _word_match(alias: str, text: str) -> bool:
        """Match alias as a whole word (not substring of a longer word)."""
        pattern = r"\b" + re.escape(alias) + r"\b"
        return bool(re.search(pattern, text))

    # Check MLB
    for alias, key in _MLB_ALIAS_TO_KEY.items():
        if _word_match(alias, lower):
            found.add(f"mlb:{key}")

    # Check NBA
    for alias, key in _NBA_ALIAS_TO_KEY.items():
        if _word_match(alias, lower):
            found.add(f"nba:{key}")

    return sorted(found)


def extract_date(text: str) -> str | None:
    """
    Extract a date from a market title, normalized to MM-DD format.
    "April 17" or "4/17" or "04/17/2026" → "04-17"
    """
    lower = text.lower()

    # Numeric pattern: 4/17, 4/17/26
    for m in re.finditer(r"\b(\d{1,2})[/\-](\d{1,2})(?:[/\-]\d{2,4})?\b", lower):
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{month:02d}-{day:02d}"

    # Month-name pattern: "April 17"
    for m in re.finditer(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})\b",
        lower,
    ):
        month = _MONTH_MAP.get(m.group(1), 0)
        day = int(m.group(2))
        if month and 1 <= day <= 31:
            return f"{month:02d}-{day:02d}"

    return None


def score_match(title_a: str, title_b: str) -> MatchResult:
    """
    Score how likely two market titles refer to the same event.
    Returns MatchResult with score 0.0–1.0.
    """
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)

    # Title similarity (token-set ratio style using SequenceMatcher)
    title_sim = SequenceMatcher(None, norm_a, norm_b).ratio()

    # Entity extraction
    teams_a = set(extract_teams(title_a))
    teams_b = set(extract_teams(title_b))
    date_a = extract_date(title_a)
    date_b = extract_date(title_b)

    # Team overlap score
    if teams_a or teams_b:
        union = teams_a | teams_b
        intersect = teams_a & teams_b
        team_score = len(intersect) / len(union) if union else 0.0
    else:
        team_score = 0.0

    # Date match score
    date_score = 0.0
    matched_date = None
    if date_a and date_b:
        if date_a == date_b:
            date_score = 1.0
            matched_date = date_a
        else:
            date_score = 0.0  # different dates = definitely different events

    # If we have strong entity signal, weight it heavily
    has_entities = bool(teams_a or teams_b)
    has_date = bool(date_a or date_b)

    if has_entities and has_date:
        # Both teams and date extracted — trust entity match most
        score = team_score * 0.5 + date_score * 0.3 + title_sim * 0.2
    elif has_entities:
        score = team_score * 0.6 + title_sim * 0.4
    elif has_date:
        # No teams but dates — only useful if dates match AND text is similar
        score = date_score * 0.4 + title_sim * 0.6
    else:
        # Pure text similarity
        score = title_sim

    return MatchResult(
        score=round(score, 4),
        matched_teams=sorted(teams_a & teams_b),
        matched_date=matched_date,
        title_similarity=round(title_sim, 4),
    )


def find_matches(
    titles_a: list[str],
    titles_b: list[str],
    threshold: float = MATCH_THRESHOLD,
) -> list[tuple[int, int, MatchResult]]:
    """
    Find all matching pairs between two lists of market titles.

    Returns:
        List of (idx_a, idx_b, MatchResult) sorted by score descending.
        Each index appears at most once (best match wins).
    """
    scored: list[tuple[float, int, int, MatchResult]] = []

    for i, ta in enumerate(titles_a):
        for j, tb in enumerate(titles_b):
            result = score_match(ta, tb)
            if result.score >= threshold:
                scored.append((result.score, i, j, result))

    scored.sort(reverse=True)

    # Greedy dedup: each index used at most once
    used_a: set[int] = set()
    used_b: set[int] = set()
    matches: list[tuple[int, int, MatchResult]] = []

    for _, i, j, result in scored:
        if i not in used_a and j not in used_b:
            matches.append((i, j, result))
            used_a.add(i)
            used_b.add(j)

    return matches


class EntityResolver:
    """
    Stateful resolver that caches confirmed matches across sessions.

    Usage:
        resolver = EntityResolver()
        match = resolver.match("Will Cubs win today?", "Chicago Cubs Win")
        if match and match.score > 0.8:
            # same event
    """

    def __init__(self, cache_path: Path = CACHE_PATH):
        self._cache_path = cache_path
        self._cache: dict[str, dict] = self._load_cache()

    def _load_cache(self) -> dict[str, dict]:
        if self._cache_path.exists():
            with open(self._cache_path) as f:
                return json.load(f)
        return {}

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._cache_path, "w") as f:
            json.dump(self._cache, f, indent=2)

    def _cache_key(self, a: str, b: str) -> str:
        return f"{normalize_title(a)}|||{normalize_title(b)}"

    def match(self, title_a: str, title_b: str) -> MatchResult:
        """Return match score for two titles, with caching."""
        key = self._cache_key(title_a, title_b)
        if key in self._cache:
            c = self._cache[key]
            return MatchResult(
                score=c["score"],
                matched_teams=c.get("matched_teams", []),
                matched_date=c.get("matched_date"),
                title_similarity=c.get("title_similarity", 0),
            )
        result = score_match(title_a, title_b)
        self._cache[key] = {
            "score": result.score,
            "matched_teams": result.matched_teams,
            "matched_date": result.matched_date,
            "title_similarity": result.title_similarity,
        }
        self._save_cache()
        return result

    def bulk_match(
        self,
        titles_a: list[str],
        titles_b: list[str],
        threshold: float = MATCH_THRESHOLD,
    ) -> list[tuple[int, int, MatchResult]]:
        """Find all cross-list matches, using cache for each pair."""
        scored: list[tuple[float, int, int, MatchResult]] = []

        for i, ta in enumerate(titles_a):
            for j, tb in enumerate(titles_b):
                result = self.match(ta, tb)
                if result.score >= threshold:
                    scored.append((result.score, i, j, result))

        scored.sort(reverse=True)

        used_a: set[int] = set()
        used_b: set[int] = set()
        matches: list[tuple[int, int, MatchResult]] = []

        for _, i, j, result in scored:
            if i not in used_a and j not in used_b:
                matches.append((i, j, result))
                used_a.add(i)
                used_b.add(j)

        return matches
