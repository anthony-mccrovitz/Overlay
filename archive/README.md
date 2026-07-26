# archive/ — retired code & stashed model versions

Two distinct conventions live here. Both keep the daily pipeline lean without
losing history.

## `retired_sports/` — DROPPED (not coming back)

A sport/market we've decided to stop running entirely. The runnable code is
frozen here so git history and the logic are preserved, but nothing in the live
pipeline imports or runs it.

To drop a sport:
1. `git mv` its runner + model + data modules into `archive/retired_sports/`.
2. In `src/config/models.py`, set its registry entries to `"status": "retired"`.
3. Delete generated artifacts (`output/picks/<sport>/`, caches).
4. Leave the sport-normalization maps and `KNOWN_MANUAL_ONLY` grading path
   intact so **historical picks in `data/pnl/picks.json` stay gradeable**.

Currently retired: **Motorsport** (NASCAR / IndyCar / F1) — dropped 2026-07-26.

## `v1/` — STASHED for rebuild (the "stash v1 → build v2" pattern)

When a model is weak/broken but the *market* is worth keeping (we're rebuilding
it, not dropping it), snapshot the old model here as v1 and build a fresh v2 in
place. The v1 copy is a frozen reference to compare against — never imported by
the live pipeline.

To stash-and-rebuild a model:
1. Copy (don't move) the current model to
   `archive/v1/<sport>_<market>_v1_<YYYYMMDD>.py`.
2. In `src/config/models.py`, set the market to `"status": "incubating"`
   (tier `shadow`) so the **new v2 logs picks silently** (`card_pick=False`)
   and accrues CLV without risking money.
3. Rebuild v2 at the original path.
4. Promote v2 to `live` only after it clears the gate:
   **≥50 settled shadow picks, positive ROI, and CLV that beats the close
   (≥55% beat-rate).** Prefer `incubating` over `retired` while rebuilding —
   we keep collecting signal to detect when v2 actually works.

See the rebuild roadmap for the queue (MLB totals → soccer expansion → WNBA →
NFL → tennis → NBA/NHL → combat sports + props R&D).
