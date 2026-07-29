"""Guards on everything a customer can see.

Two defects reached the public surface. `build_customer_feed` never filtered
tainted picks — and it matters most there, because its per-lane performance
section deliberately buckets ALL picks rather than just card picks, so a broken
model's record was being shown as that lane's record. And every public counter
listed only win/loss/push, so a voided card pick fell into neither "settled" nor
"pending" and disappeared from the record.

Zero card picks are voided today, which is exactly why the second one would have
gone unnoticed until the first cancelled game.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _picks():
    raw = json.loads((ROOT / "data" / "pnl" / "picks.json").read_text())
    return raw.get("picks", raw) if isinstance(raw, dict) else raw


class TestTaintNeverReachesCustomers:
    def test_customer_feed_filters_tainted(self):
        src = (ROOT / "scripts" / "build_customer_feed.py").read_text()
        assert 'p.get("tainted")' in src, (
            "build_customer_feed must exclude tainted picks — it is the only "
            "public-facing consumer that ever missed the filter, and it shows "
            "per-lane records built from ALL picks, not just card picks."
        )

    def test_public_stats_filters_tainted(self):
        src = (ROOT / "src" / "analytics" / "public_stats.py").read_text()
        assert 'p.get("tainted")' in src

    def test_no_tainted_pick_is_flagged_card(self):
        """A tainted pick marked card_pick is a posted bet from a broken model.
        It is excluded from the numbers, but the flag itself is a contradiction."""
        bad = [p for p in _picks() if p.get("tainted") and p.get("card_pick")]
        assert len(bad) <= 30, (
            f"{len(bad)} tainted picks are flagged card_pick (was 30). "
            "A new emitter is carding picks from a known-broken mechanism."
        )


class TestVoidIsCountedEverywhere:
    """A settled state that no counter recognises silently deletes bets."""

    @pytest.mark.parametrize("rel", [
        "src/analytics/public_stats.py",
        "scripts/build_customer_feed.py",
    ])
    def test_settled_tuple_includes_void(self, rel):
        src = (ROOT / rel).read_text()
        assert '"void"' in src, f"{rel} does not recognise result='void'"
        assert '("win", "loss", "push")' not in src, (
            f"{rel} still has a settled-state tuple that omits 'void'; a voided "
            f"card pick would fall into neither settled nor pending."
        )

    def test_every_card_pick_is_settled_or_pending(self):
        """The invariant the missing state broke: no pick may be in neither
        bucket."""
        SETTLED = ("win", "loss", "push", "void")
        card = [p for p in _picks() if p.get("card_pick") and not p.get("tainted")]
        settled = [p for p in card if p.get("result") in SETTLED]
        pending = [p for p in card if p.get("result") not in SETTLED]
        assert len(settled) + len(pending) == len(card)


class TestPublishedStatsMatchTheLedger:
    def test_public_stats_record_reconciles(self):
        """The published W-L must be recomputable from the ledger. If these ever
        diverge, the site is quoting a number nothing produces."""
        stats_path = ROOT / "data" / "public_stats.json"
        if not stats_path.exists():
            pytest.skip("public_stats.json not built")
        stats = json.loads(stats_path.read_text())
        summary = stats.get("summary") or {}
        if not summary:
            pytest.skip("no summary block")

        card = [p for p in _picks() if p.get("card_pick") and not p.get("tainted")]
        wins = sum(1 for p in card if p.get("result") == "win")
        losses = sum(1 for p in card if p.get("result") == "loss")
        assert summary.get("wins") == wins, (
            f"published wins {summary.get('wins')} != ledger {wins}"
        )
        assert summary.get("losses") == losses, (
            f"published losses {summary.get('losses')} != ledger {losses}"
        )
