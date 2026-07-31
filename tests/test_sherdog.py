"""The Sherdog client: parsing, caching, and above all identity.

NOTHING HERE TOUCHES THE NETWORK. Every test drives the parser or a monkeypatched
fetch. A test suite that reaches a third-party site is slow, flaky, and rude.

The identity tests are the important ones. Searching "Michael Oliveira" returns
four fighters; the first is 0-2 and is plainly not the man on a UFC card. The
client got that wrong before the date-of-birth check existed.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from src.data import sherdog

# A row with itemprop="award" (the common form).
_ROW_AWARD = """
<tr><td><span class="final_result win">win</span></td>
<td><a href="/fighter/Aleksandar-Rakic-89926">Aleksandar Rakic</a></td>
<td><a href="/events/UFC-on-ESPN-36-1234"><span itemprop="award">UFC on ESPN 36 - Blachowicz vs. Rakic</span></a><br />
<span class="sub_line">May / 14 / 2022</span></td>
<td class="winby"><b>TKO (Knee Injury)</b><br /><span class="sub_line">
<a href="/referee/Mark-Smith-1">Mark Smith</a></span>
<br /><a class="pbp_btn" href="/news/x">VIEW PLAY-BY-PLAY</a></td>
<td>3</td><td>1:11</td></tr>
"""

# The SAME site also emits the event as bare anchor text with no award span.
# Missing this blanked 36% of bouts, including every ARMMADA and HFL card.
_ROW_PLAIN = """
<tr><td><span class="final_result loss">loss</span></td>
<td><a href="/fighter/Ion-Pascu-53418">Ion Pascu</a></td>
<td><a href="/events/HFL-6-95752">HFL 6 - Heroes 6 &amp; ARMMADA 3: Fight In The Balkans</a><br />
<span class="sub_line">Dec / 16 / 2022</span></td>
<td class="winby"><b>Decision (Unanimous)</b><br /><span class="sub_line">
<a href="/referee/Y-2">Yamato Zaharia</a></span></td>
<td>3</td><td>5:00</td></tr>
"""

_PAGE = f"""<html><head><title>Test Fighter</title></head><body>
<span class="fn">Test Fighter</span>
<span itemprop="birthDate">Feb 24, 1983</span>
<span>6'2"</span>
<span itemprop="nationality">Poland</span>
<div class="association"><span>WCA Fight Team</span></div>
<table>{_ROW_AWARD}{_ROW_PLAIN}</table></body></html>"""


# ── parsing ──────────────────────────────────────────────────────────────────
def test_parses_both_event_markup_shapes():
    f = sherdog.parse_fighter(_PAGE, "Test-Fighter-1")
    assert len(f.bouts) == 2
    events = {b.event for b in f.bouts}
    assert all(e for e in events), "an empty event name means the row was half-parsed"
    assert any("UFC on ESPN 36" in e for e in events)
    assert any("HFL 6" in e for e in events)


def test_parses_bio_fields():
    f = sherdog.parse_fighter(_PAGE, "Test-Fighter-1")
    assert f.name == "Test Fighter"
    assert f.dob == date(1983, 2, 24)
    assert f.height_in == pytest.approx(74.0)
    assert f.nationality == "Poland"


def test_bouts_are_chronological():
    f = sherdog.parse_fighter(_PAGE, "Test-Fighter-1")
    whens = [b.when for b in f.bouts]
    assert whens == sorted(whens), "Elo replay depends on chronological order"


def test_opponent_slug_is_captured():
    """The graph keys on slugs, not names — that is what keeps the identity
    problem confined to the entry point."""
    f = sherdog.parse_fighter(_PAGE, "Test-Fighter-1")
    assert {b.opponent_slug for b in f.bouts} == {
        "Aleksandar-Rakic-89926", "Ion-Pascu-53418"}


def test_round_survives_a_play_by_play_link():
    """The method cell sometimes gains an extra anchor. Indexing cells from the
    front broke on exactly those rows."""
    f = sherdog.parse_fighter(_PAGE, "Test-Fighter-1")
    assert all(b.rnd == 3 for b in f.bouts)


def test_record_counts_correctly():
    f = sherdog.parse_fighter(_PAGE, "Test-Fighter-1")
    assert f.record == (1, 1, 0)


@pytest.mark.parametrize("event,expected", [
    ("UFC 323 - Dvalishvili vs. Yan 2", "UFC"),
    ("UFC Fight Night 255 - Edwards vs. X", "UFC"),
    ("UFC on ESPN 36 - Blachowicz vs. Rakic", "UFC"),
    ("Oktagon MMA - Oktagon 77", "Oktagon"),
    ("KSW 91 - Colosseum 2", "KSW"),
    ("ROC 9 - Ring of Combat 9", "ROC"),
    ("ROC 18 - Ring of Combat 18", "ROC"),
])
def test_promotion_normalisation(event, expected):
    """Card numbers must not each become their own promotion — a strength
    adjustment fitted on one observation per level adjusts nothing."""
    assert sherdog._promotion(event) == expected


def test_finish_detection():
    f = sherdog.parse_fighter(_PAGE, "Test-Fighter-1")
    by_method = {b.method: b.is_finish for b in f.bouts}
    assert by_method["TKO (Knee Injury)"] is True
    assert by_method["Decision (Unanimous)"] is False


def test_a_page_with_no_fights_does_not_raise():
    f = sherdog.parse_fighter("<html><span class='fn'>Nobody</span></html>", "Nobody-1")
    assert f.bouts == []
    assert f.record == (0, 0, 0)


# ── caching ──────────────────────────────────────────────────────────────────
def test_cache_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(sherdog, "_CACHE", tmp_path)
    monkeypatch.setattr(sherdog, "_get", lambda *a, **k: _PAGE)
    first = sherdog.fetch_fighter("Test-Fighter-1")
    assert first is not None and len(first.bouts) == 2

    # Second call must not fetch. If it does, this raises.
    monkeypatch.setattr(sherdog, "_get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("network hit despite a warm cache")))
    second = sherdog.fetch_fighter("Test-Fighter-1")
    assert second is not None
    assert [b.opponent_slug for b in second.bouts] == \
           [b.opponent_slug for b in first.bouts]
    assert second.dob == first.dob


def test_a_failed_fetch_returns_none_rather_than_a_hollow_fighter(tmp_path, monkeypatch):
    """A network failure must not cache an empty record — that would look
    identical to a fighter with no fights, forever."""
    monkeypatch.setattr(sherdog, "_CACHE", tmp_path)
    monkeypatch.setattr(sherdog, "_get", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("timeout")))
    assert sherdog.fetch_fighter("Whoever-1") is None
    assert not list(tmp_path.glob("*.json"))


# ── identity: the part that actually matters ─────────────────────────────────
def _fake_world(monkeypatch, tmp_path, candidates: dict[str, tuple[str, date | None]]):
    """candidates: slug -> (display name, dob). Builds search + fetch stubs."""
    monkeypatch.setattr(sherdog, "_CACHE", tmp_path)
    monkeypatch.setattr(sherdog, "search",
                        lambda name: [(s, d) for s, (d, _) in candidates.items()])

    def fake_fetch(slug, refresh=False):
        if slug not in candidates:
            return None
        disp, dob = candidates[slug]
        return sherdog.Fighter(slug=slug, name=disp, dob=dob, bouts=[
            sherdog.Bout("win", "X", "X-1", "E", "UFC", date(2020, 1, 1), "KO", 1)])
    monkeypatch.setattr(sherdog, "fetch_fighter", fake_fetch)


def test_a_single_clean_match_resolves(tmp_path, monkeypatch):
    _fake_world(monkeypatch, tmp_path, {
        "Jovan-Leka-403812": ("Jovan Leka", date(2002, 3, 15))})
    f = sherdog.resolve("Jovan Leka", dob=date(2002, 3, 15))
    assert f is not None and f.slug == "Jovan-Leka-403812"


def test_search_padding_is_ignored(tmp_path, monkeypatch):
    """Sherdog appends unrelated 'featured' fighters to every result set. Taking
    the first row is how you end up with Magomed Ankalaev's record."""
    _fake_world(monkeypatch, tmp_path, {
        "Magomed-Ankalaev-170785": ("Magomed Ankalaev", date(1992, 6, 2)),
        "Jovan-Leka-403812": ("Jovan Leka", date(2002, 3, 15)),
    })
    f = sherdog.resolve("Jovan Leka")
    assert f is not None and f.slug == "Jovan-Leka-403812"


def test_date_of_birth_separates_identical_names(tmp_path, monkeypatch):
    """THE bug. Four Michael Oliveiras; the first is 0-2 and is not the one on
    the card. Only the DOB tells them apart."""
    _fake_world(monkeypatch, tmp_path, {
        "Michael-Oliveira-118103": ("Michael Oliveira", date(1988, 5, 5)),
        "Michael-Oliveira-400985": ("Michael Oliveira", date(1998, 1, 21)),
    })
    f = sherdog.resolve("Michael Oliveira", dob=date(1998, 1, 21))
    assert f is not None and f.slug == "Michael-Oliveira-400985"


def test_identical_names_without_a_dob_refuse(tmp_path, monkeypatch):
    """Ambiguity is a refusal, not a coin flip. Guessing attaches a confident
    number to the wrong person, which is worse than saying nothing."""
    _fake_world(monkeypatch, tmp_path, {
        "Michael-Oliveira-118103": ("Michael Oliveira", date(1988, 5, 5)),
        "Michael-Oliveira-400985": ("Michael Oliveira", date(1998, 1, 21)),
    })
    assert sherdog.resolve("Michael Oliveira") is None


def test_a_wrong_dob_refuses_rather_than_falling_back(tmp_path, monkeypatch):
    _fake_world(monkeypatch, tmp_path, {
        "Jovan-Leka-403812": ("Jovan Leka", date(2002, 3, 15))})
    assert sherdog.resolve("Jovan Leka", dob=date(1975, 1, 1)) is None


def test_name_variant_resolves_only_with_an_exact_dob_and_surname(tmp_path, monkeypatch):
    """Tier 2. The odds feed says 'Vlasto Cepo'; Sherdog files him as
    'Vlastislav Cepo'. Legitimate, and common enough to matter — but only
    accepted on an exact date-of-birth match AND a shared surname."""
    _fake_world(monkeypatch, tmp_path, {
        "Vlastislav-Cepo-330615": ("Vlastislav Cepo", date(1995, 1, 25))})
    f = sherdog.resolve("Vlasto Cepo", dob=date(1995, 1, 25))
    assert f is not None and f.slug == "Vlastislav-Cepo-330615"


def test_name_variant_without_a_dob_refuses(tmp_path, monkeypatch):
    _fake_world(monkeypatch, tmp_path, {
        "Vlastislav-Cepo-330615": ("Vlastislav Cepo", date(1995, 1, 25))})
    assert sherdog.resolve("Vlasto Cepo") is None


def test_a_shared_dob_with_a_different_surname_refuses(tmp_path, monkeypatch):
    """Birthdays collide. Surname must agree too, or tier 2 would eventually
    pair two unrelated fighters born on the same day."""
    _fake_world(monkeypatch, tmp_path, {
        "Someone-Else-1": ("Someone Else", date(1995, 1, 25))})
    assert sherdog.resolve("Vlasto Cepo", dob=date(1995, 1, 25)) is None


def test_nobody_resolves_to_nobody(tmp_path, monkeypatch):
    _fake_world(monkeypatch, tmp_path, {})
    assert sherdog.resolve("Zzzz Notarealfighter", dob=date(1990, 1, 1)) is None


# ── politeness ───────────────────────────────────────────────────────────────
def test_throttle_state_is_shared_across_processes(tmp_path, monkeypatch):
    """The interval is enforced through a file, not a module global, so a
    backfill and a card read cannot each believe they are the only caller."""
    monkeypatch.setattr(sherdog, "_CACHE", tmp_path)
    monkeypatch.setattr(sherdog, "_STAMP", tmp_path / ".last_request")
    monkeypatch.setattr(sherdog, "_MIN_INTERVAL", 0.0)
    sherdog._throttle()
    assert (tmp_path / ".last_request").exists()
    assert float((tmp_path / ".last_request").read_text()) > 0


def test_the_configured_interval_is_not_zero():
    """Guards against someone 'speeding up the crawl' in a hurry."""
    assert sherdog._MIN_INTERVAL >= 1.0
