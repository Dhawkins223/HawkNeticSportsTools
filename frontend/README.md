# HawkNetic React Dashboard

This is the Next.js / React customer dashboard for HawkNetic Sports Tools. It is a separate frontend that consumes the FastAPI backend.

## Run locally

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Open `http://localhost:3000`.

## Required backend

The FastAPI backend must be running and connected to Railway PostgreSQL in production. The dashboard calls:

- `/api/health`
- `/api/data-status`
- `/api/games`
- `/api/players`
- `/api/props`
- `/api/simulations`
- `/api/parlays`
- `/api/bdl/logs`

If FastAPI, Railway PostgreSQL, or Ball Don't Lie ingestion fails, the dashboard shows the error instead of silently falling back to fake data.
