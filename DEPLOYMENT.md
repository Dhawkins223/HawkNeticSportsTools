# HawkNetic Predictor Tools — Deployment Guide

## Local / Emergent preview (current setup)
- Backend: `/app/backend/server.py` bridges Emergent's supervisor (uvicorn on 8001) to the HawkNetic FastAPI app at `/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/app/main.py`.
- Frontend: `/app/frontend` (Next.js 16). Supervisor runs `yarn start` which is wired to `next start -H 0.0.0.0 -p 3000` (production build). Run `yarn build` after pulling new code.
- Database: SQLite at `/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/data/hawknetic.sqlite` (set by `HAWKNETIC_ALLOW_SQLITE=1`).
- Seed demo data: `python3 /app/scripts/seed_demo.py` (idempotent — re-runnable).

## Re-deploying to Railway with PostgreSQL
The HawkNetic backend auto-detects Postgres when `DATABASE_URL` is set and `HAWKNETIC_ALLOW_SQLITE` is unset (or `0`).

### Backend service (Railway)
Set these environment variables on the FastAPI/uvicorn service:
```
DATABASE_URL=postgresql://<user>:<pass>@<host>:<port>/<db>     # provided by Railway Postgres plugin
HAWKNETIC_ENV=production
HAWKNETIC_SECRET_KEY=<generate a long random string>
HAWKNETIC_FRONTEND_ORIGINS=https://<your-frontend-domain>      # exact origin or comma-separated list
BALLDONTLIE_API_KEY=<optional — enables live NBA data>
OPENAI_API_KEY=<optional — enables AI insights>
STRIPE_SECRET_KEY=<optional — enables paid plans>
STRIPE_WEBHOOK_SECRET=<optional>
PORT=8000                                                       # Railway injects this automatically
```
Do **NOT** set `HAWKNETIC_ALLOW_SQLITE` on Railway. The backend will fail-fast with a clear error if `DATABASE_URL` is missing on production.

### Frontend service (Railway)
```
NEXT_PUBLIC_API_BASE_URL=https://<your-backend-service>.up.railway.app
```
Run `yarn build && yarn start`. The `next.config.ts` already includes preview/cloud subdomains in `allowedDevOrigins` so HMR works locally.

## Files removed in this rebrand
- `app/templates/` (all 22 Jinja HTML pages: landing, pricing, contact, terms, refund_policy, dashboard.html, etc.)
- `app/static/` (legacy CSS/JS for server-rendered UI)
- `app/routes/web.py` (login/register/dashboard/etc. server-rendered routes)
The React dashboard at `/app/frontend/` is now the only customer surface.

## API surface preserved
All `/api/*` endpoints remain unchanged — see `app/routes/api.py`. Highlights:
- `GET  /api/health`, `/api/data-status`
- `GET  /api/games`, `/api/players`, `/api/teams`, `/api/props`, `/api/odds`
- `POST /api/slips/analyze`    ← powers the **Run Algorithm** button
- `POST /api/simulations/run`, `/api/parlays/build`
- `POST /api/historical/backfill/*`, `/api/bdl/sync/*`
- `POST /api/billing/stripe/webhook`
