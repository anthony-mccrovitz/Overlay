"""One sport-key mapping, one implementation.

This is the most expensive recurring defect in the repo. SIX modules were found
re-deriving `src.config.models._key` by hand, and every copy had drifted to a
different answer for the same sport:

  clv_gate            truncated to 14 chars -> 'atp-french_ope', 'golf-the_open_'
  clv_tracker         'mma' where the registry says 'ufc'
  algo_stockboard     every club league collapsed to 'soccer'
  weekly_audit        invented 'soccer_mls' and 'soccer_copa'
  calibration         stopped at mlb/nba/wnba/nhl, so calibrators were written as
                      'tennis_atp_wimbledon_moneyline' and never found again
  calibration_gate    collapsed club leagues, so MLS's edge-shrink record was
                      stored at 'soccer::moneyline' and every lookup came back
                      empty

The symptom was identical every time and never looked like a key bug: a lane
reported as un-instrumented, uncalibrated, or unmeasurable while holding
hundreds of perfectly good rows. Tennis had 246 CLV snapshots and reported zero.

These tests fail when a new hand-rolled mapping appears. A mapping that produces
a HUMAN LABEL ("UFC/MMA", "Liga MX") is a different thing and is allowed — the
rule is about keys that must join the registry.
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Three genuinely different sport mappings exist, and conflating them is part of
# how this went wrong. Only the FIRST must be single-sourced:
#
#   1. REGISTRY LANE KEY  — models._key. Joins picks to the registry, the CLV
#      gate, calibrators and the promotion gate. Club leagues stay distinct
#      (soccer_usa_mls -> usa_mls); tournaments collapse (tennis_* -> tennis).
#      Every consumer MUST delegate. Six didn't.
#
#   2. LEDGER STORAGE KEY — schema._SPORT_ALIASES. How a sport is written onto a
#      pick. Narrower on purpose: normalises baseball_mlb -> mlb but leaves
#      soccer_usa_mls intact, which is why consumers have to normalise at all.
#
#   3. DISPLAY / PATH maps — human labels ("UFC/MMA", "Liga MX"), archive
#      filename prefixes, third-party tag slugs. Not keys; no join to protect.
ALLOWED = {
    "src/config/models.py",                  # (1) the definition
    "src/tracking/schema.py",                # (2) the ledger storage table
    "src/analytics/clv_tracker.py",          # (2) imports schema's table
    "src/strategies/line_shop_scanner.py",   # (3) SPORT_NAMES: display labels
    "scripts/build_customer_feed.py",        # (3) customer-facing display names
    "scripts/gen_caption.py",                # (3) caption copy
    "src/output/card_html.py",               # (3) card rendering
    "scripts/backtest_consensus.py",         # (3) closing-archive filename prefix
    "scripts/polymarket_scanner.py",         # (3) Polymarket Gamma tag slugs
}

# Fingerprints of a registry-key mapping: turning a full Odds API sport key into
# a short lane key. Display-name maps don't produce these values.
FINGERPRINTS = (
    re.compile(r'["\']baseball_mlb["\']\s*:\s*["\']mlb["\']'),
    re.compile(r'["\']icehockey_nhl["\']\s*:\s*["\']nhl["\']'),
    re.compile(r'["\']mma_mixed_martial_arts["\']\s*:\s*["\'](?:ufc|mma)["\']'),
    re.compile(r'startswith\(["\']soccer["\']\)\s*:?\s*\n?\s*(?:raw|s|sp)\s*=\s*["\']soccer["\']'),
)


def _source_files():
    for base in ("src", "scripts"):
        for p in sorted((ROOT / base).rglob("*.py")):
            rel = p.relative_to(ROOT).as_posix()
            if rel in ALLOWED or "__pycache__" in rel:
                continue
            yield rel, p


class TestSingleSourceOfTruth:
    def test_no_module_reimplements_the_sport_key_map(self):
        offenders = []
        for rel, path in _source_files():
            try:
                src = path.read_text()
            except OSError:
                continue
            for fp in FINGERPRINTS:
                if fp.search(src):
                    offenders.append(f"{rel}: matches {fp.pattern[:48]}")
                    break
        assert not offenders, (
            "Module(s) appear to re-implement src.config.models._key:\n  "
            + "\n  ".join(offenders)
            + "\n\nDelegate instead:\n"
              "    from src.config.models import _key\n"
              "    canonical = _key(sport, '')[0]\n\n"
              "Six copies of this mapping existed and each answered differently, "
              "which made real lanes look empty. If your map produces a HUMAN "
              "LABEL rather than a registry key, add the file to ALLOWED with a "
              "comment saying so."
        )

    def test_no_module_truncates_a_sport_key(self):
        """clv_gate sliced labels to 14 chars, producing 'atp-french_ope' — a key
        that could never join anything. Nothing should length-slice a sport."""
        offenders = []
        pat = re.compile(r'(?:sport|sp|raw)\b[^\n]{0,80}\[:\s*\d+\s*\]')
        for rel, path in _source_files():
            try:
                src = path.read_text()
            except OSError:
                continue
            for line in src.splitlines():
                if "replace(" in line and pat.search(line):
                    offenders.append(f"{rel}: {line.strip()[:88]}")
        assert not offenders, (
            "Sport key truncated to a fixed width:\n  " + "\n  ".join(offenders)
            + "\n\nA truncated key joins nothing. Use models._key."
        )


class TestKeyBehaviourIsStable:
    """Pin the mappings that six different modules disagreed about, so a future
    edit to _key can't silently un-fix them."""

    @pytest.mark.parametrize("raw,expected", [
        ("tennis_atp_wimbledon", "tennis"),
        ("tennis_wta_washington_open", "tennis"),
        ("mma_mixed_martial_arts", "ufc"),
        ("golf_us_open_winner", "pga"),
        ("golf_the_open_championship_winner", "pga"),
        ("soccer_usa_mls", "usa_mls"),
        ("soccer_mexico_ligamx", "mexico_ligamx"),
        ("soccer_fifa_world_cup", "wc"),
        ("baseball_mlb", "mlb"),
        ("basketball_wnba", "wnba"),
        ("basketball_nba", "nba"),
        ("icehockey_nhl", "nhl"),
    ])
    def test_canonical_mapping(self, raw, expected):
        from src.config.models import _key
        assert _key(raw, "")[0] == expected

    def test_club_leagues_stay_distinct(self):
        """Collapsing them to one 'soccer' bucket is what hid MLS's edge-shrink
        record. Liga MX and MLS must never share a verdict."""
        from src.config.models import _key
        assert _key("soccer_usa_mls", "")[0] != _key("soccer_mexico_ligamx", "")[0]

    def test_wnba_is_not_swallowed_by_nba(self):
        """'nba' is a substring of 'wnba'; an ordering slip pools WNBA picks into
        the NBA fit and applies NBA calibrators to WNBA probabilities."""
        from src.config.models import _key
        from src.analytics.calibration import _normalize_sport
        assert _key("basketball_wnba", "")[0] == "wnba"
        assert _normalize_sport("basketball_wnba") == "wnba"
        assert _normalize_sport("wnba") == "wnba"


class TestConsumersAgreeWithTheRegistry:
    """The consumers that were broken today must now answer identically."""

    CASES = ["tennis_atp_wimbledon", "mma_mixed_martial_arts", "soccer_usa_mls",
             "golf_us_open_winner", "baseball_mlb", "basketball_wnba"]

    def test_calibration_matches_registry(self):
        from src.config.models import _key
        from src.analytics.calibration import _normalize_sport
        for raw in self.CASES:
            assert _normalize_sport(raw) == _key(raw, "")[0], raw

    def test_calibration_gate_matches_registry(self):
        from src.config.models import _key
        from src.analytics.calibration_gate import _key as gate_key
        for raw in self.CASES:
            assert gate_key(raw, "moneyline") == f"{_key(raw, '')[0]}::moneyline", raw

    def test_coverage_matches_registry(self):
        from src.config.models import _key
        from src.analytics.coverage import canon_sport
        for raw in self.CASES:
            assert canon_sport(raw) == _key(raw, "")[0], raw

    def test_clv_tracker_matches_registry(self):
        from src.config.models import _key
        from src.analytics.clv_tracker import _sport_short
        for raw in self.CASES:
            assert _sport_short(raw) == _key(raw, "")[0], raw
