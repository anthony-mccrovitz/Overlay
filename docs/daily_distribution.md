# Daily Distribution Routine

A 45–60 minute daily routine that uses the new "show your work" content
generators (receipts caption, minimal calibration card, TikTok script) to
deploy Overlay's verification rigor where the eyes actually are.

This document assumes the morning pipeline has already run and produced today's
content artifacts. Cron is set up to run picks across all sports starting at
9:00 AM ET — see `scripts/setup_cron.sh`.

## Today's content artifacts (where to find everything)

Per `output/picks/<sport>/<YYYYMMDD>/`:

| File | Use for |
|---|---|
| `receipts_post.txt` | Reddit megathread comment + X tweet (raw copy-paste) |
| `calibration_card.png` | Instagram post |
| `talking_head/show_your_work.md` | TikTok face video script |
| `picks.json`, `props.json`, etc. | Raw data if you want to write a manual post |

Sports directories: `baseball_mlb`, `basketball_nba`, `icehockey_nhl`,
`basketball_wnba`, etc.

## The 45–60 min routine

### Morning — 20 min (after 9 AM pipeline run)

1. **Reddit r/sportsbook daily megathread** — open today's `receipts_post.txt`
   for the live model (NBA Totals on NBA days, MLB Run Line on MLB days). Paste
   as a comment in the megathread. Lead with the trailing-14-day record. Do NOT
   post a standalone thread; commenting in the megathread gets 10× the eyes.

2. **X — receipts tweet** — first 4 lines of `receipts_post.txt`. One tweet,
   quote-style. No emoji, no link in the body. Profile bio handles the link.

3. **Instagram** — post `calibration_card.png` with a 2-line caption pulled
   from `receipts_post.txt`. Daily as requested.

### Midday — 15 min

4. **3 sharp X replies** to bigger sports betting accounts (Action Network,
   Bet Karma, Sharp Tank, etc). Cite a number from today's `picks.json` or
   `chef.py record`. Sharp, helpful, no link.

5. **One Reddit comment** in someone else's thread on r/sportsbook. Search for
   "model" / "today's slate" / "edge" threads. Drop a calibrated take with a
   Brier score or CLV figure if relevant.

### Evening — 15 min

6. **TikTok** — face on camera. Read off `talking_head/show_your_work.md`.
   30 seconds. Shot on phone, no edits. Don't over-think it.

7. **X — yesterday's W/L** — single tweet pulled from `chef.py record --recent 1`.
   "Yesterday: WIN. Model 62%, line 219.5, finale 248. Logged before tip-off."
   Build the public-record habit.

### Weekly add-ons (Sunday, 30 min)

- **Build-log X post** — Anthony's personal voice. Bug post-mortem, model
   journey, what was wrong this week. Different audience than picks; converts
   to customers later.
- **Long-form Reddit recap** — full W/L table + CLV trend. Use
   `python3 -c "from src.output.captions_overlay import weekly_recap; print(weekly_recap('nba'))"`
   to generate the markdown.

## Hard rules

1. **Live model only on public feeds.** NBA Totals on NBA days, MLB Run Line on
   MLB days. Posting incubating-model picks breaks the no-cherry-picking
   narrative.
2. **Don't cite CLV until coverage is >50%.** Currently CLV records cover
   ~147 of 1,029 settled picks after the backfill fix. Going forward this
   number will climb; check `chef.py record` CLV section before quoting a
   number publicly.
3. **Face on camera every day for TikTok.** No AI-voiceover pivot.
4. **Don't delete old captions.** They live in `captions_platform.py` and
   `captions_platform.py` outputs — keep available behind a `--legacy` flag.

## How to manually regenerate one artifact

If a caption looks off (or you want a fresh take), you can regenerate just
the one piece:

```bash
# Receipts caption only
python3 -c "
from src.output.captions_overlay import receipts_caption
import json
pick = json.loads(open('output/picks/basketball_nba/20260516/picks.json').read())[0]
print(receipts_caption(pick, 'nba', pick['market']))
"

# Minimal calibration card only
python3 -c "
from src.output.card_overlay_minimal import render_calibration_card
import json
pick = json.loads(open('output/picks/basketball_nba/20260516/picks.json').read())[0]
print(render_calibration_card(pick, 'nba', pick['market']))
"

# TikTok script only
python3 -c "
from src.output.talking_head_show_your_work import build_script
print(build_script('nba', 'total',
    pick_line='OVER 219.5 Spurs vs Thunder (-105)',
    model_prob_pct=62.7, edge_pct=11.6,
    record_str='8-3 ATS · +6.4u',
    brier=0.241, clv_avg_cents=1.8))
"
```

## Distribution tracking

Log one line per day in `logs/distribution.log`:

```
2026-05-16 reddit:megathread X:1tweet IG:card tiktok:1
```

After 7 days, count engagement (replies/comments). Target: ≥10/week by week 4.
If a channel doesn't move after 6 weeks, cut it.

## Critical generators (this is the new ammunition)

- `src/output/captions_overlay.py` — `receipts_caption()`, `weekly_recap()`
- `src/output/card_overlay_minimal.py` — `render_calibration_card()`
- `src/output/talking_head_show_your_work.py` — `build_script()`, `write_script()`

These are called automatically by `predict.py` (MLB pipeline) and `run_nba.py`
when the pipeline runs. Output to `output/picks/<sport>/<date>/`.
