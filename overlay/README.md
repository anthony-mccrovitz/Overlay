# Overlay

Customer-facing Next.js app for the Overlay sports analytics subscription. Thin slice of the internal `dashboard/` — only NBA + MLB card picks, no model internals, no full history.

## Architecture

- **`dashboard/`** — internal cockpit (untouched). All sports, all picks, full models. *Not in this folder.*
- **`overlay/`** (this app) — public marketing + paid subscriber feed. NBA + MLB card picks only.
- **`web/`** — DEPRECATED. To be removed.

## Local dev

```bash
cd overlay
cp .env.example .env.local   # fill in Resend API key + PAID_EMAILS
npm install
npm run dev                  # http://localhost:3002
```

Generate the customer feed:

```bash
cd ..   # back to repo root
python3 scripts/build_customer_feed.py
```

Writes `overlay/public/data/customer_feed.json` — the only file the customer app reads.

## Routes

| Path | Public? | Notes |
|---|---|---|
| `/` | yes | Landing + record strip + subscribe CTA |
| `/record` | yes | Public W-L / ROI |
| `/login` | yes | Magic link sign-in (Resend) |
| `/picks` | gated | Today's NBA + MLB card picks |
| `/account` | gated | Email + subscription status |
| `/terms`, `/privacy` | yes | Required for Stripe |

## Granting access

1. Customer pays via Stripe Payment Link.
2. You receive Stripe email confirmation.
3. Append their email (lowercase) to `PAID_EMAILS` env var in Vercel.
4. Redeploy (or use Vercel's "Promote" without rebuild).
5. They sign in at `/login` with that email and get a magic link.

This is intentionally manual for the first ~10 customers. Wire a Stripe webhook → DB later.

## Daily ops

Wire `python3 scripts/build_customer_feed.py` into your morning cron (after `chef.py picks`). Then redeploy or trigger an ISR revalidation.
