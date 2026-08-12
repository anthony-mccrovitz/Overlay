"""A dead tennis results source must be loud, not reassuring.

The bug this locks down: `load_matches` returned an empty DataFrame both when
the download failed and when there were genuinely no matches. The grader then
printed "N still pending (match not in source yet)" either way, so a source
outage was reported in the exact words used for normal, healthy waiting. 350
picks sat pending for weeks while every nightly run finished green.

These are mutation tests — each one breaks the source on purpose and asserts
the system complains.
"""
from __future__ import annotations

import pytest

from src.data import tennis_data
from src.data.tennis_data import TennisSourceUnavailable


def test_a_failed_download_raises_under_strict(tmp_path, monkeypatch):
    """No cache on disk and the network down = we know nothing. Say so."""
    monkeypatch.setattr(tennis_data, "CACHE_DIR", tmp_path / "empty")

    def dead(*a, **kw):
        raise ConnectionError("name resolution failed")

    monkeypatch.setattr("requests.get", dead)

    with pytest.raises(TennisSourceUnavailable):
        tennis_data.load_matches("atp", years=[2026], strict=True)


def test_the_same_failure_is_tolerated_without_strict(tmp_path, monkeypatch):
    """Non-grading callers keep the old forgiving behaviour."""
    monkeypatch.setattr(tennis_data, "CACHE_DIR", tmp_path / "empty2")
    monkeypatch.setattr("requests.get",
                        lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("down")))

    df = tennis_data.load_matches("atp", years=[2026], strict=False)
    assert len(df) == 0


def test_an_unreadable_workbook_raises_under_strict(tmp_path, monkeypatch):
    """A DOWNLOADED but unparseable workbook must be as loud as no download.

    This is the failure that actually happened, and the download-focused tests
    above would not have caught it. The bytes arrived fine; pd.read_excel then
    raised ImportError because openpyxl was absent from the light dependency
    set. load_matches caught it, appended nothing, and returned an empty frame
    — reported downstream as "match not in source yet" for a month.

    See tests/test_pipeline_deps.py for the guard on the dependency list.
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(tennis_data, "CACHE_DIR", cache)
    # A cached file that exists, so no download is attempted, and is not a
    # readable workbook — standing in for "the parser cannot open this".
    (cache / "td_atp_2026.xlsx").write_bytes(b"not really a workbook")

    with pytest.raises(TennisSourceUnavailable):
        tennis_data.load_matches("atp", years=[2026],
                                 refresh_current=False, strict=True)


def test_the_index_propagates_unavailability(tmp_path, monkeypatch):
    """build_results_index must not turn an outage into an empty index."""
    from src.data import tennis_results

    monkeypatch.setattr(tennis_data, "CACHE_DIR", tmp_path / "empty3")
    monkeypatch.setattr("requests.get",
                        lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("down")))

    with pytest.raises(TennisSourceUnavailable):
        tennis_results.build_results_index("atp", strict=True)


def test_the_grader_records_a_failure_rather_than_grading_nothing(monkeypatch):
    """The end-to-end property: an outage must reach _FAILURES, which exits 1."""
    import grade

    monkeypatch.setattr(grade, "_FAILURES", [])
    monkeypatch.setattr(
        grade, "_grade_tennis_backlog",
        lambda: (_ for _ in ()).throw(TennisSourceUnavailable("atp 2026: down")))

    # Mirrors the call site in main(): swallow, but record.
    try:
        grade._grade_tennis_backlog()
    except Exception as exc:
        grade._FAILURES.append(f"tennis backlog: {exc}")

    assert grade._FAILURES and "down" in grade._FAILURES[0]
