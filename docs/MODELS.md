# Models & Markets — Overlay

> **Status claims in this file are NOT maintained by hand.** They drifted badly
> once — on 2026-07-30 this document described World Cup, tennis, golf, WNBA
> props and UFC as "live" (all were retired or incubating) while also asserting
> "Nothing is bet. All markets shadow", by which point `mlb/total` had been
> taking real money for weeks. Wrong in both directions at the same time.
>
> **For current state, run the commands — they read the registry and cannot drift:**
>
> ```
> chef.py grid          every lane and its status
> chef.py scoreboard    how close each lane is to earning real money
> chef.py moneypath     can I bet today, link by link
> ```
>
> What stays here is what a command CANNOT tell you: which algorithm each lane
> uses and why it was built that way.


Source of truth for **every model, the markets it prices, how it's validated, and
its known limitations.** Updated 2026-06-21.

Two independent validation signals are tracked for each market:
- **`chef.py edge`** — CLV vs the closing line (the market's own verdict). The
  promotion gate: t-test of mean CLV > 0, sample floor (200), Bonferroni
  correction, 30-day recency. Nothing is bet until a market clears this **and**
  persists out-of-sample.
- **`chef.py validate`** — outcome calibration (stated model prob vs actual hit
  rate + Brier). Flags OVERCONFIDENT models whose stated edge is inflated.

**Everything is shadow (`card_pick=False`, `stake=0`) until both signals agree.**
EV is never trusted on its own — overconfident models produce gaudy fake EV.

---

## New models built 2026-06-21 (this build)

### World Cup spreads — `soccer_model_v2.handicap_cover_prob()`
- **Method:** Asian-handicap cover probability from the Dixon-Coles score grid,
  reweighted so the grid's 1X2 margins match the calibrated (temperature-scaled)
  win/draw/loss probs.
- **Validation:** exact at boundaries (home −0.5 cover == calibrated win prob;
  away +0.5 == away_win + draw). Sanity: cover decreases monotonically with
  handicap.
- **Limitation:** calibration matches 1X2 but **not the margin-distribution shape
  beyond ±0.5**, so favorite multi-goal covers (−2, −2.5) may be overestimated
  (raw Poisson over-predicts blowouts). Shadow; CLV will quantify.

### World Cup anytime scorer — `src/models/soccer_scorer.py`
- **Method:** `P(scores) = 1 − exp(−share × team_xG)`, share = player's recent
  (3yr) goal share of his national team (own goals excluded), team_xG from the
  calibrated Dixon-Coles matchup.
- **Validation:** 103 teams covered; sensible probs (Lukaku 25%, De Bruyne 20%).
- **Limitation:** historical shares are **not lineup/injury aware** → conservative
  for star strikers (xG-thinning dilutes the designated scorer), misses new
  call-ups. Only flags players the book *underprices*. Shadow.

### Tennis games-total — `tennis_model.games_total_prob()`
- **Method:** Monte-Carlo (20k sims) of total games, simulating each set
  game-by-game from the two players' hold probabilities (same per-point serve
  probs as the win model), 13-game tiebreak set.
- **Validation:** expected games in plausible range; even match > lopsided;
  over+under = 1.
- **Limitation:** minor-event players with sparse Elo default to ~50% serve
  (noisy); totals are more robust than the ML defaults but thin-data matches are
  unreliable. Shadow.

### WNBA player props — `src/models/wnba_props.py`
- **Method:** project PTS/REB/AST from season per-game averages; points ~
  Normal(mean, 0.35·mean), rebounds ~ Normal(0.40), assists ~ Poisson; OVER-shade
  correction (books set lines low to attract Over money).
- **Validation:** monotonic in line; sensible probs; low-minutes players skipped.
- **Limitation:** season averages, **not matchup/minutes/injury-aware**; variance
  coefficients borrowed from NBA (validation will retune). Shadow.

---

## CLV & validation infrastructure (this build)

- **Each prop type is its own market** (`batter_hits`, `pitcher_strikeouts`,
  `player_points`, …) — prefix-detected (`batter_/pitcher_/player_`), dynamic
  closing-fetch. No generic `prop` bucket.
- **Soccer 3-way de-vig fixed** — `_devig_prob` is N-way; `fetch_closing_pairs`
  pulls the Draw price. (WC CLV was +72% garbage; now sane.)
- **`chef.py edge`** keys on `(sport, market)` — no Simpson's-paradox blending.
- **`chef.py validate`** — outcome calibration per market.
