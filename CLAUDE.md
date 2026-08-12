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

**Fantasy Premier League (classic — the FPL app):**
```
python3 chef.py fpl squad --save           # optimal legal 15 under £100m, saved to file
python3 chef.py fpl lineup                 # this week's XI, captain, bench order
python3 chef.py fpl transfers              # 1-3 transfer plans, net of -4 hits
python3 chef.py fpl league --league <id>   # mini-league table, EO, differentials
python3 chef.py fpl chips                  # best week for WC/FH/BB/TC
python3 chef.py fpl captain --league <id>  # EV when ahead, differential when chasing
```

**NFL in-season (role, not box score):**
```
python3 chef.py waivers --week 8           # free agents by USAGE trend, with FAAB bid
python3 chef.py waivers --all              # include rostered players
```
- `src/fantasy/usage.py` — snaps, target share, air-yards share, red-zone touches
  from nflverse; fixes the "right team, wrong role" gap `market.py` flags
- `src/fantasy/waivers.py` — ranks on CHANGE IN OPPORTUNITY, never points scored;
  a 20-point week on 4 touches with flat usage is deliberately absent
- `src/fantasy/recency.py` — blends the 2025 prior with current-season usage at
  `games / (games + 6)`, so 3 games barely moves it and 14 games mostly does
- Snap counts join on NAME (nflverse uses PFR ids for snaps, GSIS for stats);
  an unmatched player reports `snap_pct=None`, never 0
- `src/fpl/optimize.py` is an **exact** MILP (scipy/HiGHS), not a heuristic — every
  solution is checked by `optimize.validate` against all FPL legality rules
- Projections regress goals/assists to xG/xA, shrink over 900 minutes toward a
  **price-implied prior** (fitted per position from players who do have a
  record), then scale by expected minutes and fixture difficulty
- **Pre-season the API serves LAST season's stats.** A player new to the league
  is projected from price alone (flagged `+`); a player who changed clubs is
  projected on his OLD club's output (flagged `>`) and the data cannot fix that
  — override in `data/fpl/overrides.json` when your judgement beats the model
- The bench is real cover by default: `--min-bench-minutes 45` refuses to spend
  a squad slot on someone who will not play. Pass `0` for classic £4.0m fodder
- Table flags: `!` unavailable, `+` priced-in (no PL history), `>` changed
  clubs, `?` under 900 minutes of evidence, `*` overridden

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

- **Never re-implement the promotion gate either.**
  `model_standard.clears_promotion_gate` is the ONLY promote/refuse decision.
  Three copies had accreted by 2026-07-31: the scoreboard printed "✅ READY"
  for usa_mls while `chef.py promote` refused the same lane, because the
  scoreboard's inline copy skipped the independence check — the exact check
  the lane fails. Surfaces may pre-filter with a strict SUBSET of the gate's
  checks for speed, but READY/PROMOTED must come from the gate itself.
  `tests/test_gate_single_source.py` fails the build on a divergent copy.

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

## Coding behavior — always apply

Follow `.claude/skills/karpathy-guidelines/SKILL.md` on every code change in this
repo: surface assumptions instead of guessing, write the minimum that solves the
problem, keep diffs surgical, and state a verifiable success criterion before
starting. Load the skill for the full text.

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
