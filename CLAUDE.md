# Overlay — Multi-Sport Betting Edge Detection

## Project Goal
Build an ML-powered sports betting edge detection system that finds mathematically proven
edges against sportsbook lines using ensemble models (XGBoost + LightGBM + CatBoost),
generates daily picks with Kelly sizing, tracks CLV, and serves picks through a Next.js
subscription web app.

## Tech Stack
- Python 3.12+
- Data: pandas, numpy
- ML: scikit-learn, xgboost, lightgbm, catboost
- API: requests (MLB Stats API, Odds API, OpenWeatherMap)
- Web: Next.js 14 (App Router), Tailwind CSS, TypeScript
- Deployment: Vercel (web), cron (Python pipeline)

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
