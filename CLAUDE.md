# Overlay — Multi-Sport Betting Edge Detection

## Project Goal
Build an ML-powered sports betting edge detection system that finds mathematically proven
edges against sportsbook lines using ensemble models (XGBoost + LightGBM + CatBoost),
generates daily picks with Kelly sizing, tracks CLV, and serves picks through a Next.js
subscription web app.

## Daily Workflow

All operations go through `chef.py` — the unified CLI.

**Morning (generate picks):**
```
python3 chef.py picks mlb                  # today's MLB slate
python3 chef.py picks mlb --date 20260512  # specific slate date (output folder)
python3 chef.py picks nba                  # today's NBA slate
python3 chef.py picks nba --date 20260418  # specific date
python3 chef.py morning --date 20260512    # full morning pipeline for that slate
```

**Evening (grade results):**
```
python3 chef.py grade                      # grade both MLB + NBA (yesterday)
python3 chef.py grade --sport mlb          # MLB only
python3 chef.py grade --date 20260417      # specific date
```

**Check record anytime:**
```
python3 chef.py record                     # full P&L breakdown by market + sport
python3 chef.py record --market nrfi       # NRFI record only
python3 chef.py record --sport nba         # NBA record only
```

**Utilities:**
```
python3 chef.py migrate                    # normalize picks.json after schema changes
python3 chef.py test                       # run grading unit tests (pytest)
python3 chef.py stats                      # refresh public_stats.json
```

## Data & Schema

- **`data/pnl/picks.json`** — canonical pick record. All picks use the same schema:
  `pick_id`, `date`, `sport`, `market`, `direction`, `team`, `matchup`, `odds`, `line`,
  `sportsbook`, `model_prob`, `edge_pct`, `stake`, `card_pick`, `result`, `profit`,
  `recorded_at`, `resulted_at`
- **`card_pick=True`** — only officially posted picks count toward the public record
- **`pick_id`** — deterministic dedup key: `{sport}_{YYYYMMDD}_{team-slug}_{market}_{direction}`
- **Units**: `1u = 1 unit staked flat`. Win at +140 → +1.40u. Win at -110 → +0.909u. Loss → -1.0u
- **`edge_pct`** — stored as percentage points (8.4 = 8.4%). Do NOT multiply by 100
- **Schema source of truth**: `src/tracking/schema.py` — normalization, validation, migration

## Invariants (enforced by tests — don't work around them)

- **Never re-implement `src/config/models._key`.** It is the registry lane key
  that joins picks to the registry, the CLV gate, calibrators and the promotion
  gate. Six modules had each hand-copied it and drifted to different answers,
  which made real lanes report as un-instrumented while holding hundreds of rows
  (tennis had 246 CLV snapshots and reported zero). Delegate:
  `from src.config.models import _key; canonical = _key(sport, "")[0]`.
  `tests/test_sport_key_single_source.py` fails the build on a new copy.
  Two other sport mappings legitimately exist and are NOT this one: the ledger
  storage key (`schema._SPORT_ALIASES`, leaves `soccer_usa_mls` intact) and
  display/path maps (human labels, archive prefixes, tag slugs).

- **A lane cannot go live by omission.** `src/config/model_standard.py` defines
  seven checks and `tests/test_model_standard.py` fails the build when a live
  lane violates one. Legacy uses documented `EXEMPTIONS` (reason + retirement
  condition), never weakened checks — and a stale exemption fails too.
  `edge_shrink`, `clv_coverage` and `promotion_gate` are NON_EXEMPTIBLE.

- **"Clears the promotion gate" ≠ "proven".** `PROMOTE_MIN_N=30` is a
  data-sufficiency floor, not a significance test. Every gate line reports z and
  the n needed; mlb/total is z=+1.69 (~90% confidence), and that is accepted
  deliberately, not overlooked.

- **Judge a MODEL at flat 1u**, not on the stored `profit` field — shadow stakes
  are often 0.0 or 0.5, so dividing stored profit by pick count is meaningless.
  `market_stats` recomputes from odds for this reason.

- **Prop CLV is an artifact.** Prop models echo the book's line (r≈0.97), so
  beat-close measures line-following, not skill. Judge props on ROI alone.

## Key Files

- `chef.py` — unified CLI dispatcher (picks / grade / record / migrate / test / stats)
- `predict.py` — MLB model + picks generation (run via `chef.py picks mlb`)
- `run_nba.py` — NBA model + picks generation + grading (run via `chef.py picks nba`)
- `grade.py` — grades settled picks, writes public_stats.json (run via `chef.py grade`)
- `src/tracking/schema.py` — canonical schema: `make_pick_id`, `normalize_pick`, `validate_pick`, `migrate_picks_file`
- `src/analytics/public_stats.py` — computes and writes public_stats.json for web app
- `src/output/card_html.py` — HTML pick card generator (MLB + NBA)
- `tests/test_grading.py` — grading unit tests (54 tests, run via `chef.py test`)
- `data/pnl/picks.json` — the canonical bet record
- `data/public_stats.json` — computed stats for web API
- `web/public/data/public_stats.json` — mirror for Vercel/Next.js

## gstack

Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.

Available skills: /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /review, /ship, /browse, /qa, /qa-only, /qa-design-review,
/setup-browser-cookies, /retro, /document-release.

If gstack skills aren't working, run `cd .claude/skills/gstack && ./setup` to rebuild.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
