# HawkNetic Predictor Tools - PRD

## Original Problem Statement
> "Create this app similar in style to Bet365, but instead of placing bets, they press 'Run algorithm.' GitHub has my repository with all of the algorithms inside ... Right now, we have it on Railway Hosting, but we are having problems, and some files need to be rearranged or deleted because there are items on the front end that are not supposed to be used. Postgres is what we are using for our database, Python is what we have been using for our back end ... we want the same layout as Bet365, but ... we are not a betting site. We are a tool and predictor site."

## Architecture (current, runs on Emergent supervisor)
- **Backend** – FastAPI (port 8001) bridged via `/app/backend/server.py` → real app at `/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/app/main.py`. SQLite locally (`HAWKNETIC_ALLOW_SQLITE=1`), PostgreSQL-ready via `DATABASE_URL` for Railway.
- **Frontend** – Next.js 16 React app at `/app/frontend`, served via `yarn start` → `next dev -H 0.0.0.0 -p 3000`. Reads API URL from `NEXT_PUBLIC_API_BASE_URL` (set to the Emergent preview URL).
- **Database** – 41-table HawkNetic schema (users, props, odds, parlays, historical_*, raw_*, bdl_*, plans, subscriptions, audit, etc.). Seeded with 8 teams, 10 players, 7 games, 15 props, 8 odds rows for instant demo via `/app/scripts/seed_demo.py`.
- **External APIs** (already wired in HawkNetic source): Ball Don't Lie, Basketball Reference scraper, OpenAI, Stripe — all gracefully degrade when keys are absent.

## What was implemented this session
- Wired the existing HawkNetic codebase into Emergent's supervisor (created `/app/backend/server.py` bridge, `/app/backend/.env`, `/app/backend/requirements.txt`).
- Changed frontend `start` script to `next dev` so the Next.js app runs under supervisor.
- Added `allowedDevOrigins` to `next.config.ts` for preview-domain HMR.
- Set up `/app/frontend/.env` with `NEXT_PUBLIC_API_BASE_URL` and `REACT_APP_BACKEND_URL`.
- Patched CORS in the bridge file (regex wildcard + credentials) to support arbitrary preview subdomains.
- **Rebranded the dashboard from Bet365/Bet Slip language to "Algorithm Run / Predictor Tools"**:
  - "HawkNetic Sports Tools" → **"HawkNetic Predictor Tools"**
  - "Bet Slip" → **"Algorithm Run"**
  - "Stake" → **"Confidence weight"**
  - "Payout preview" → **"Projected payout multiple"**
  - "Bet365" data-source dropdown → **"Reference market (Bet365 lines)"**
  - Footer "Decision support only. Bets are placed separately on Bet365." → **"Prediction tool only. HawkNetic does not accept or place wagers."**
  - Page title + meta description rewritten.
- Seeded SQLite with realistic NBA games/props/odds so the algorithm has data to score immediately.

## Verified
- `GET /api/health` returns `{ok: true, database_engine: sqlite, table_count: 41}` ✅
- `GET /api/games`, `/api/props`, `/api/odds` return the seeded NBA slate ✅
- Dashboard renders the rebranded Bet365-style layout with "Run Algorithm" button ✅
- Manual market entry → "Run Algorithm" → `POST /api/slips/analyze` works (backend pipeline intact).

## Known issue / Next Action Items
- **Initial market hydration**: under the preview proxy, the React `useEffect` initial fetch in `HawkBet365DecisionDashboard.tsx` is not visibly firing on first paint in Turbopack dev mode (no API requests observed from headless browser). The endpoints themselves return data correctly. Quick paths to fix:
  1. Replace `credentials: "include"` with `credentials: "same-origin"` in `/app/frontend/lib/api.ts` (cross-origin proxies sometimes drop the request).
  2. Or run `next build && next start` instead of `next dev` (production hydration is more lenient).
  3. Or add a "Load markets" button that calls `api.getGames()` on click — bypasses the auto-fetch.
- Re-enable Railway PostgreSQL by setting `DATABASE_URL` in `/app/backend/.env` and removing `HAWKNETIC_ALLOW_SQLITE=1`.
- Wire real `BALLDONTLIE_API_KEY` to pull live odds/games instead of seed.
- Clean up unused frontend items: the legacy server-rendered Jinja templates in `app/templates/*.html` (landing, pricing, contact, refund_policy, etc.) are still routed by `app/routes/web.py`. If the React dashboard is the only customer surface, delete `routes/web.py` registration in `main.py` and the templates directory.

## Future / Backlog (P1)
- Persist "Algorithm Run history" per user (rename `parlays` table semantics or add `algorithm_runs`).
- Add per-algorithm confidence scoring (the `services/probability_engine.py`, `risk_engine.py`, `slip_analysis.py` are already there).
- Re-enable Stripe paywall with new plan codes (`starter`, `pro`, `elite`).
