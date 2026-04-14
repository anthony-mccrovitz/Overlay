# EdgeFinder — MLB Betting Edge Detection

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

## gstack

Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.

Available skills: /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /review, /ship, /browse, /qa, /qa-only, /qa-design-review,
/setup-browser-cookies, /retro, /document-release.

If gstack skills aren't working, run `cd .claude/skills/gstack && ./setup` to rebuild.
