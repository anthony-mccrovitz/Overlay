# legacy/ — archived, not deleted

Moved out of the active tree on 2026-06-16 to shrink the project down to the
**CLV core loop** (capture closing lines → snapshot picks → compute CLV → grade)
plus the one live frontend, **`overlay/`**.

Nothing here is deleted. To restore any item, move it back to the repo root:

```bash
mv legacy/<item> ./<item>
```

## What's here and why

| Item | Why archived |
|------|--------------|
| `web/` | Redundant Next.js frontend. `overlay/` is the live app (`chef deploy` target). The only active coupling — the `public_stats.json` mirror in `scripts/deploy_picks.py` — was removed when this moved. If a Vercel project still points at `web/`, repoint or delete it. |
| `dashboard/` | Abandoned third frontend. Referenced by no active code, cron, or CI. |
| `catboost_info/` | CatBoost training scratch output. Regenerated on the next train run. |
| `morning.py` | Unreferenced root script (superseded by `chef.py morning`). |
| `track.py` | Unreferenced root script. |
| `train_nhl.py` | Unreferenced root script. |

## Still in the active tree (intentionally)

- `output/` — generated pick cards/captions. Regenerable but actively written and
  staged by `deploy_picks.py`, so left in place. Old date dirs can be cleaned later.
- 10 orphaned `src/` modules (backtests, `season_sim`, `paper_trade_autopilot`,
  `narratives`, `visualize`, `upset_dna`, `historical_clv`, `prediction_arb`,
  `mlb_nrfi`) — flagged unimported but left for now (low space, higher breakage risk
  to move; `mlb_nrfi` especially needs a real check since NRFI is an active market).
