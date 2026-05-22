# HawkNetic Predictor Tools - PRD

## Original Problem Statement
> "Create this app similar in style to Bet365, but instead of placing bets, they press 'Run algorithm.' GitHub has my repository with all of the algorithms inside ... Right now, we have it on Railway Hosting, but we are having problems, and some files need to be rearranged or deleted because there are items on the front end that are not supposed to be used. Postgres is what we are using for our database, Python is what we have been using for our back end ... we want the same layout as Bet365, but ... we are not a betting site. We are a tool and predictor site."

## Architecture
- **Backend** – FastAPI (port 8001 via Emergent supervisor). `/app/backend/server.py` bridges to the real HawkNetic app at `/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/app/main.py`. SQLite locally (`HAWKNETIC_ALLOW_SQLITE=1`), PostgreSQL-ready via `DATABASE_URL` for Railway. CORS patched to accept arbitrary preview-domain subdomains.
- **Frontend** – Next.js 16 React app at `/app/frontend`, served via `yarn start` → `next start -H 0.0.0.0 -p 3000` (production build). Reads API URL from `NEXT_PUBLIC_API_BASE_URL`.
- **Database** – 41-table HawkNetic schema (users, props, odds, parlays, historical_*, raw_*, bdl_*, plans, subscriptions, audit, etc.). Seeded with 8 teams, 10 players, 7 games, 25 props, 8 odds rows via `/app/scripts/seed_demo.py`.
- **External APIs** (already wired in HawkNetic source): Ball Don't Lie, Basketball Reference scraper, OpenAI, Stripe — all gracefully degrade when keys are absent.

## User Personas
1. **NBA bettor / analyst** — wants algorithmic verdicts on the same slate they'd build on Bet365.
2. **Operator (admin)** — runs data backfills, monitors BDL sync, checks readiness via `/admin`.

## What's been implemented (Jan 2026)
- Wired HawkNetic FastAPI + Next.js codebase into Emergent supervisor (bridge `/app/backend/server.py`, `/app/backend/.env`, `/app/backend/requirements.txt`).
- Switched local DB to SQLite (`HAWKNETIC_ALLOW_SQLITE=1`) so the app runs without Railway Postgres.
- Frontend switched to production build (`next start`) — dev mode had Turbopack hydration issues under preview proxy.
- Seeded 8 teams / 10 players / 7 games / 25 props / 8 odds rows.
- **Rebranded the Bet365-style dashboard end-to-end → "Algorithm Run / Predictor Tools"**:
  - Page title: "HawkNetic Predictor Tools"
  - Tagline: "Prediction tool · no wagers placed"
  - "Bet Slip" → **"Algorithm Run"**
  - "Stake" → **"Confidence weight"**
  - "Payout preview" → **"Projected payout multiple"**
  - "Bet365" → **"Reference sportsbook lines"**
  - Footer: "Prediction tool only. HawkNetic does not accept or place wagers."
  - Zero "Bet365" / "Bet Slip" text remains in the rendered UI (verified).
- Added "Refresh markets" button for manual reload.
- Patched fetch to use `credentials: "same-origin"` so the preview proxy doesn't drop requests.
- **Deleted legacy frontend artifacts**: all 22 Jinja templates in `app/templates/` (landing, pricing, contact, terms, refund_policy, dashboard.html, login.html, register.html, etc.), the `app/static/` folder, and `app/routes/web.py`. React dashboard is now the only customer surface.
- Wrote `/app/DEPLOYMENT.md` with Railway Postgres re-deploy instructions.

## Verified (testing agent iteration 1)
- 9/9 backend pytest tests pass (`/app/backend/tests/test_hawknetic_api.py`)
- All required data-testids present: `hawknetic-dashboard`, `run-algorithm-button`, `sports-board`, `market-board`, `algorithm-slip`, `refresh-markets-btn`, `stake-input`, `payout-preview`, etc.
- Full E2E flow: click game → click odds → leg added → press Run Algorithm → POST `/api/slips/analyze` returns 200 → verdict UI renders with model win %, edge %, EV, fair odds, confidence tier.
- 7 games visible on load, 14 market rows when game 1 (Lakers vs Celtics) is selected.

## API endpoints preserved
All `/api/*` HawkNetic endpoints intact:
- `GET /api/health`, `/api/data-status`, `/api/database/readiness`
- `GET /api/games`, `/api/players`, `/api/teams`, `/api/props`, `/api/odds`
- `POST /api/slips/analyze` ← powers Run Algorithm
- `POST /api/simulations/run`, `/api/parlays/build`, `/api/parlays/reorder`
- `POST /api/historical/backfill/*`, `/api/bdl/sync/*`
- `POST /api/billing/stripe/webhook`
- `GET /api/me`, `POST /api/ai/chat`, `GET /api/findings`, `/api/conversations`

## Next Action Items
- Push to GitHub via Emergent's "Save to GitHub" button in the chat input.
- Re-deploy to Railway: set `DATABASE_URL` + `HAWKNETIC_SECRET_KEY` + `HAWKNETIC_FRONTEND_ORIGINS` on backend service, `NEXT_PUBLIC_API_BASE_URL` on frontend service. See `/app/DEPLOYMENT.md`.

## Backlog (P1)
- Wire real `BALLDONTLIE_API_KEY` for live NBA props/games instead of seed.
- Persist algorithm-run history per user (rename `parlays` table semantically or add `algorithm_runs`).
- Re-enable Stripe paywall (`starter`/`pro`/`elite` plans already in `PlanRepository`).
- Add an "Insights" tab that surfaces `services/probability_engine.py` and `risk_engine.py` outputs directly.

## Smart enhancement suggestion
**Shareable algorithm runs**: when a user presses Run Algorithm, generate a short URL (`/r/<hash>`) that anyone can open to see the same verdict — turns every prediction into a social/marketing object and brings new users in via shared links. Powerful for an analyst-tool brand like HawkNetic.
