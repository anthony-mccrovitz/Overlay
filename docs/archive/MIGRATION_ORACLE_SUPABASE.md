> **ARCHIVED 2026-07-30 — not pursued; the pipeline runs on GitHub Actions instead**
>
> Kept for history. This describes a past plan, not current state.
> For current state run `chef.py scoreboard` / `chef.py moneypath`, or read README.md.

# Migration Plan: Oracle Cloud VPS + Supabase

**Goal:** Move the betting pipeline off the always-on laptop onto a free, always-running
server, and migrate the transactional bet record from flat JSON into Postgres for easier
querying and visualization.

**Two independent tracks — do them in this order:**

1. **Track A — Hosting** (highest ROI, do first): move the cron pipeline to an Oracle
   Cloud "Always Free" VPS so jobs never silently miss when the laptop sleeps.
2. **Track B — Database** (do after A is stable): migrate `picks.json` + CLV records into
   Supabase Postgres behind the existing `schema.py` API.

Each track is shippable on its own. Track A alone fixes the reliability problem. Track B
alone improves data work. Doing A first means B happens on a stable, observable box.

**Cost: $0/month** — Oracle Always Free shapes + Supabase free tier.

---

## Current state (verified)

- **Runtime:** Python 3.11.3, ML stack (pandas, numpy, scikit-learn, xgboost, lightgbm,
  catboost), FastAPI for the API.
- **Scheduling:** ~21 cron jobs wrapped in `caffeinate -i` (only keeps laptop awake during
  scheduled windows — everything outside those windows silently no-ops when the lid closes).
- **Data:** 821 MB total. Bulk/blob (`cache/` 521MB, `kaggle/` 208MB, `kenpom/` 25MB,
  `models/`) belongs on disk. Transactional record (`picks.json` 1.7MB, CLV records) is what
  moves to Postgres.
- **Secrets:** `ODDS_API_KEY`, `OPENWEATHER_API_KEY`, `KALSHI_API_KEY`, `KALSHI_EMAIL`,
  `KALSHI_PASSWORD`.
- **The I/O chokepoint:** every pick read/write goes through
  `src/tracking/schema.py` → `load_picks_safe` / `append_picks_safe` / `rewrite_picks_safe`
  (with a `picks.lock` flock), and `src/tracking/pnl.py` → `_load` / `_save`. Swapping these
  is the entire DB migration surface; the ~60 caller files don't change.
- **Web:** Vercel `overlay/` app reads pre-built JSON (`deploy_picks.py` writes it). Untouched
  by this migration until an optional Phase B4.

---

## Track A — Oracle Cloud VPS

### A1. Provision the box

1. Sign up at cloud.oracle.com. A credit card is required for identity verification;
   **Always Free shapes are not charged.** To be safe from accidental paid resources, after
   signup consider staying on the "Always Free" account tier.
2. Create a compute instance:
   - **Shape:** `VM.Standard.A1.Flex` (Ampere ARM). Always Free allowance = up to 4 OCPU /
     24 GB RAM total. Allocate **2 OCPU / 12 GB** (leaves headroom; bump later if needed).
   - **Image:** Ubuntu 22.04 (aarch64).
   - **Boot volume:** 100 GB (Always Free gives 200 GB block total).
3. **ARM capacity caveat:** A1 shapes are sometimes "out of capacity" in busy regions. If so,
   retry over a few hours, or pick a less-busy home region at signup (home region can't be
   changed later). As a fallback, the `VM.Standard.E2.1.Micro` (AMD, x86) is also Always Free
   but only 1 GB RAM — too small for the ML stack, so prefer A1.
4. Add your SSH public key during creation. Save the auto-generated `opc`/`ubuntu` login.
5. Networking: the default VCN is fine. You do **not** need to open inbound ports — this box
   only makes outbound API calls and pushes to git/Vercel. (If you later self-host a dashboard,
   open that port in both the OCI Security List *and* `ufw`.)

### A2. Base setup

```bash
ssh ubuntu@<public-ip>
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git rsync
sudo timedatectl set-timezone America/New_York   # cron schedule is ET — match it
```

ARM wheels: pandas/numpy/scikit-learn/xgboost/lightgbm all ship aarch64 wheels.
**catboost** is the one to verify — if `pip install catboost` fails to find an ARM wheel,
install build deps (`sudo apt install -y cmake build-essential`) or pin a version with an
aarch64 wheel. Test this early (step A3) so it's not a cutover surprise.

### A3. Deploy the code

```bash
git clone <your-repo-url> ~/march-madness
cd ~/march-madness
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # watch catboost here
python3 chef.py test                   # run the 54 grading tests — must pass on ARM
```

### A4. Move the data

From the **laptop**, one-time sync of the 821 MB `data/` tree (and `output/` if the pipeline
reads its own history):

```bash
rsync -avz --progress ~/march-madness/data/   ubuntu@<public-ip>:~/march-madness/data/
rsync -avz --progress ~/march-madness/output/ ubuntu@<public-ip>:~/march-madness/output/
```

### A5. Secrets

Cron does **not** load your shell profile, so env vars must be explicit. Put them in a root-owned
`.env` and load it in each cron line (or use a systemd EnvironmentFile):

```bash
cat > ~/march-madness/.env <<'EOF'
ODDS_API_KEY=...
OPENWEATHER_API_KEY=...
KALSHI_API_KEY=...
KALSHI_EMAIL=...
KALSHI_PASSWORD=...
EOF
chmod 600 ~/march-madness/.env
```

Confirm the code calls `load_dotenv()` early (python-dotenv is already a dep). If any entry
point doesn't, add it, or prefix cron lines with `set -a; . ~/march-madness/.env; set +a`.

### A6. Install cron (the key change: drop `caffeinate`)

Export the laptop's crontab, transform it, install on the server:

```bash
# on laptop
crontab -l > /tmp/cron_old.txt
```

Transform each line:
- **Remove** `/usr/bin/caffeinate -i` (a server never sleeps).
- Replace `/usr/local/bin/python3` and bare `python3` with the venv:
  `/home/ubuntu/march-madness/.venv/bin/python3`.
- Replace `cd /Users/anthonymccrovitz/march-madness` with `cd /home/ubuntu/march-madness`.
- Keep the same minute/hour fields — timezone is now ET on the box (step A2).

Example, before → after:

```
# before (laptop)
30 21 * * * cd /Users/anthonymccrovitz/march-madness && /usr/bin/caffeinate -i /usr/local/bin/python3 chef.py night --sport mlb >> .../logs/night.log 2>&1
# after (server)
30 21 * * * cd /home/ubuntu/march-madness && /home/ubuntu/march-madness/.venv/bin/python3 chef.py night --sport mlb >> /home/ubuntu/march-madness/logs/night.log 2>&1
```

Install with `crontab /tmp/cron_new.txt`.

### A7. Parallel run (de-risk the cutover)

Run **both** laptop and server for 2–3 days, but **disable git push / Vercel deploy on the
server** first (comment out `deploy_picks.py` and any `git push` in server cron) so the two
don't fight over the same remote/picks history. Compare:

- `logs/*.log` on the server — every job runs clean, no missing API keys, no ARM import errors.
- Server-generated picks/grades match the laptop's for the same slate.

When satisfied: re-enable deploy on the **server**, disable all cron on the **laptop**
(`crontab -r` after backing it up), and let the laptop go to sleep. **Server is now primary.**

### A8. Operational hygiene

- `df -h` after a week — confirm `data/`/`output/`/`logs/` growth is sane; add `logrotate` for
  `logs/` if needed.
- Reboot test: `sudo reboot`, confirm cron resumes (it will — cron is a system service).
- Backups: the hourly `backup_picks.py` keeps running; once on Track B, the DB has its own.

---

## Track B — Supabase Postgres

Do this **after Track A is primary and stable.** The strategy: model the canonical `picks`
record as a table, then swap the bodies of the `schema.py` / `pnl.py` I/O functions to read/write
Postgres while keeping their signatures identical. ~60 callers are untouched.

### B1. Create the project

1. supabase.com → new project (free tier: 500 MB DB, ample — `picks.json` is 1.7 MB).
2. Grab the connection string (Settings → Database) and the project URL + service-role key.
3. Add to the server `.env`: `DATABASE_URL=postgresql://...`
4. `pip install psycopg[binary]` (add to requirements.txt). Note: Supabase free tier pauses a
   project after 7 days of **inactivity** — yours runs daily, so it stays awake.

### B2. Schema

Model from the canonical fields (see `CLAUDE.md` + `src/tracking/schema.py`):

```sql
create table picks (
  pick_id      text primary key,           -- {sport}_{YYYYMMDD}_{team-slug}_{market}_{direction}
  date         date not null,
  sport        text not null,
  market       text not null,
  direction    text,
  team         text,
  matchup      text,
  odds         integer,
  line         numeric,
  sportsbook   text,
  model_prob   numeric,
  edge_pct     numeric,                     -- percentage points (8.4 = 8.4%), do NOT *100
  stake        numeric default 1,
  card_pick    boolean default false,
  result       text,                        -- win | loss | push | null(pending)
  profit       numeric,
  recorded_at  timestamptz,
  resulted_at  timestamptz
);
create index on picks (date);
create index on picks (sport, market);
create index on picks (card_pick) where card_pick = true;
create index on picks (result) where result is null;   -- fast pending lookups

-- CLV records + snapshots: mirror data/clv/*.json similarly (separate tables, FK to pick_id)
```

### B3. Backfill + swap the chokepoint

1. **Backfill once:** script reads `picks.json` via `load_picks_safe`, upserts every row into
   `picks` by `pick_id`. Re-runnable (idempotent upsert). Verify counts + a profit-sum spot check
   against `chef.py record`.
2. **Swap I/O bodies** behind unchanged signatures:
   - `load_picks_safe(path)` → `SELECT *` → return the same `{"picks": [...]}` dict shape.
   - `append_picks_safe(path, new)` → `INSERT ... ON CONFLICT (pick_id) DO NOTHING`, return count.
   - `rewrite_picks_safe(path, data)` → transactional upsert of the set.
   - `pnl.py` `_load`/`_save` → same DB calls (or refactor `pnl.py` to call the schema.py fns).
   - The `picks.lock` flock becomes unnecessary — Postgres handles concurrency. Leave the param
     in place (ignored) so signatures don't change.
   - Gate with an env flag: `PICKS_BACKEND=postgres|json` (default `json`) so you can flip back
     instantly if something's off.
3. **`chef.py test` must pass** against the DB backend. The 54 grading tests are the safety net —
   point them at a throwaday test schema/transaction-rollback fixture, not prod.

### B4. (Optional) Visualization + web

- **Visualize now:** Supabase's built-in Table + SQL editors cover ad-hoc queries immediately.
  For dashboards, point **Metabase** or **Grafana** (both free) at the same Postgres — charts of
  ROI by market, CLV trend, win-rate by sport, etc.
- **Web app later:** the Vercel `overlay/` app can query Supabase directly instead of reading
  pre-built JSON. Until then, keep `deploy_picks.py` writing JSON — no rush.

### B5. Dual-write safety window

For the first week of `PICKS_BACKEND=postgres`, keep the JSON writes happening too (write to
both), so `picks.json` stays a warm fallback. After a clean week, make Postgres the sole source
and let JSON go stale (the hourly backup still snapshots the DB).

---

## Rollback

- **Track A:** laptop cron is only disabled (backed up), not deleted. Re-enable it, sleep the
  server. You're back in minutes.
- **Track B:** flip `PICKS_BACKEND=json`. `picks.json` stayed current through the dual-write
  window (B5), so no data loss.

## Sequenced checklist

- [ ] A1 provision A1.Flex Ubuntu box
- [ ] A2/A3 base setup, clone, venv, **`chef.py test` green on ARM** (verify catboost)
- [ ] A4 rsync data/ + output/
- [ ] A5 secrets in `.env`, dotenv loading confirmed
- [ ] A6 install transformed crontab (no caffeinate, venv paths, ET tz)
- [ ] A7 parallel run 2–3 days, deploy disabled on server
- [ ] A7 cut over: server primary, laptop cron off
- [ ] B1 Supabase project + DATABASE_URL
- [ ] B2 create schema
- [ ] B3 backfill + swap I/O behind `PICKS_BACKEND` flag, tests green
- [ ] B5 dual-write week, then Postgres sole source
- [ ] B4 (optional) Metabase/Grafana dashboard; web app → Supabase
```
