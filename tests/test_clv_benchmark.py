"""A CLV benchmark must be declared and reproducible, not incidental.

THE BUG THIS LOCKS OUT (found 2026-07-30): `fetch_closing_props` selected the
closing quote with `if key not in out: out[key] = cand` — first-write-wins,
where "first" meant whichever row the archive JSON happened to list first. The
comment above it claimed "keep the BEST line per player", which is not what the
code did.

Measured consequences on real archives before the fix:
  · the "closing book" was theScore Bet 58% of the time, FanDuel 32%
  · books disagreed on the same prop at the same line by a median of 20 cents,
    p90 218 cents
  · re-scoring the SAME archive under shuffled row order changed 96% of closing
    prices — e.g. freddy peralta closed +100, +110 or -109 depending on order

So every prop CLV figure in the ledger — including the 91.2% "beat close" on
mlb/batter_total_bases that the watcher was promoting as an edge candidate —
was measured against a randomly chosen book.

The property under test is simple and total: the closing benchmark is a pure
function of the archive CONTENT, never of its ORDER.
"""
import random

import pytest

from src.analytics.clv_tracker import fetch_closing_props


def _row(player, side, line, odds, book):
    return {"Market": "pitcher_strikeouts", "Description": player,
            "Selection": side, "Line": line, "Odds": odds, "Sportsbook": book}


def _archive(rows):
    return [{"all_odds": rows}]


@pytest.fixture
def patched(monkeypatch):
    """Feed a synthetic archive straight into the selector."""
    def install(rows):
        monkeypatch.setattr("src.analytics.clv_tracker._select_windowed_records",
                            lambda *a, **k: {"evt": {"all_odds": rows}})
    return install


def _books_disagreeing():
    """One player, one line, five books, deliberately wide price disagreement."""
    return [
        _row("Freddy Peralta", "Over",  5.5, +100, "BetMGM"),
        _row("Freddy Peralta", "Under", 5.5, -120, "BetMGM"),
        _row("Freddy Peralta", "Over",  5.5, +110, "BetRivers"),
        _row("Freddy Peralta", "Under", 5.5, -130, "BetRivers"),
        _row("Freddy Peralta", "Over",  5.5, -109, "theScore Bet"),
        _row("Freddy Peralta", "Under", 5.5, -111, "theScore Bet"),
        _row("Freddy Peralta", "Over",  5.5, +105, "FanDuel"),
        _row("Freddy Peralta", "Under", 5.5, -125, "FanDuel"),
        _row("Freddy Peralta", "Over",  5.5, +102, "DraftKings"),
        _row("Freddy Peralta", "Under", 5.5, -122, "DraftKings"),
    ]


def test_benchmark_is_invariant_to_archive_row_order(patched):
    """THE regression test. Shuffle the rows, get the identical closing quote."""
    rows = _books_disagreeing()
    results = []
    for seed in range(8):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        patched(shuffled)
        results.append(fetch_closing_props("2026-07-30", "mlb", "pitcher_strikeouts"))
    first = results[0]
    assert first, "selector returned nothing for a well-formed archive"
    for r in results[1:]:
        assert r == first, (
            "closing benchmark changed with archive row order — the selector is "
            "picking a book incidentally again, which is the exact defect this "
            "file exists to prevent"
        )


def test_pinnacle_is_preferred_when_it_prices_the_prop(patched):
    """Sharp reference wins over the consensus whenever it is available."""
    rows = _books_disagreeing() + [
        _row("Freddy Peralta", "Over",  5.5, -105, "Pinnacle"),
        _row("Freddy Peralta", "Under", 5.5, -105, "Pinnacle"),
    ]
    random.Random(0).shuffle(rows)
    patched(rows)
    got = fetch_closing_props("2026-07-30", "mlb", "pitcher_strikeouts")
    rec = got[("freddy peralta", "pitcher_strikeouts")]
    assert rec["source"] == "pinnacle"
    assert rec["over"] == -105 and rec["under"] == -105


def test_consensus_median_used_when_pinnacle_absent(patched):
    """Without a sharp price, fall back to a DECLARED median, tagged as such."""
    patched(_books_disagreeing())
    rec = fetch_closing_props("2026-07-30", "mlb",
                              "pitcher_strikeouts")[("freddy peralta", "pitcher_strikeouts")]
    assert rec["source"].startswith("median_"), rec["source"]
    assert rec["n_books"] == 5
    # Median of the five over prices (+100,+110,-109,+105,+102) in probability
    # space is +105 — strictly inside the range, never an outlier book.
    assert -109 < rec["over"] < 110


def test_source_is_always_tagged(patched):
    """Downstream must be able to separate sharp from consensus. A blend of the
    two measures neither, so the tag is not optional."""
    patched(_books_disagreeing())
    for rec in fetch_closing_props("2026-07-30", "mlb", "pitcher_strikeouts").values():
        assert rec.get("source"), "closing record carries no benchmark provenance"


def test_modal_line_wins_not_the_first_line_seen(patched):
    """When books post different LINES, the consensus number is the market's
    opinion; one early row is not."""
    rows = [
        _row("Joe Ryan", "Over",  6.5, -110, "theScore Bet"),   # lone outlier, listed first
        _row("Joe Ryan", "Under", 6.5, -110, "theScore Bet"),
    ]
    for bk in ("BetMGM", "FanDuel", "DraftKings"):
        rows += [_row("Joe Ryan", "Over", 5.5, -110, bk),
                 _row("Joe Ryan", "Under", 5.5, -110, bk)]
    patched(rows)
    rec = fetch_closing_props("2026-07-30", "mlb",
                              "pitcher_strikeouts")[("joe ryan", "pitcher_strikeouts")]
    assert rec["line"] == 5.5, "took an outlier book's line over the consensus line"
