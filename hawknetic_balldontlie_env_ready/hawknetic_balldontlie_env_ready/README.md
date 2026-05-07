# HawkNetic customer platform

A Cursor-ready, IntelliJ-runnable FastAPI project for:
- marketing landing page
- lead capture
- account registration and login
- pricing and subscriptions
- self-serve cancellation
- AI explanations stored with user findings
- BALLDONTLIE provider integration for teams, players, and games

## Stack
- FastAPI
- Jinja2 templates
- SQLite by default for immediate local startup
- backend-only OpenAI Responses API integration when `OPENAI_API_KEY` is present
- BALLDONTLIE provider client using the documented `Authorization` header shape
- local fallback explainer so the site still works end to end without third-party keys

## Run locally
```bash
pip install -r requirements.txt
python run_local.py
```

Open:
- `http://127.0.0.1:8000`

## What works immediately
- landing page
- lead capture
- register / login / logout
- seeded free account for quick platform access (`free@hawknetic.local` / `free-access`)
- pricing page
- local subscription activation
- easy cancellation from account page
- AI history and explanations
- BALLDONTLIE provider health endpoint
- BALLDONTLIE teams / players / games routes
- provider sync routes that store BALLDONTLIE payloads into local tables

## What becomes live when keys are added
- real ChatGPT responses: set `OPENAI_API_KEY`
- real Stripe billing: add your Stripe keys and replace the local checkout path with your live session creator
- real BALLDONTLIE pulls: set `BALLDONTLIE_API_KEY`

## BALLDONTLIE routes
- `GET /api/providers/balldontlie/health`
- `GET /api/providers/balldontlie/teams`
- `GET /api/providers/balldontlie/players?search=lebron`
- `GET /api/providers/balldontlie/games?date=2026-01-27`
- `POST /api/providers/balldontlie/sync/teams`
- `POST /api/providers/balldontlie/sync/players?search=lebron`
- `POST /api/providers/balldontlie/sync/games?date=2026-01-27`
- `GET /api/providers/balldontlie/storage-summary`

## Local provider storage
The app now stores BALLDONTLIE data in provider-aligned local tables:
- `provider_sync_runs`
- `provider_teams`
- `provider_players`
- `provider_games`

These use provider IDs as external IDs and keep the raw provider JSON so later normalization steps do not destroy source fidelity.

## Project structure
- `app/main.py` - app factory and middleware
- `app/routes/` - HTML routes and JSON API routes
- `app/services/` - auth, billing, AI orchestration, BALLDONTLIE provider orchestration
- `app/repositories.py` - database access layer
- `app/db.py` - schema bootstrap and seed data
- `tests/` - regression coverage
- `docs/uml.md` - system diagrams
- `docs/CURSOR_MASTER_HANDOFF.md` - full system handoff
- `docs/CONVERSATION_DECISION_LOG.md` - architecture decision log

## Notes
The project is structured so you can open it in Cursor and continue building from clean modules instead of rewiring a giant single file.

## BALLDONTLIE integration structure
HawkNetic now keeps BALLDONTLIE isolated in a provider area and then maps that data into HawkNetic's own canonical structure.

Flow:
1. BALLDONTLIE API response
2. `raw_balldontlie_*` tables store provider-shaped payloads
3. normalization writes to `canonical_*` tables
4. HawkNetic algorithms should read canonical tables, not provider payloads

Current raw tables:
- `raw_balldontlie_teams`
- `raw_balldontlie_players`
- `raw_balldontlie_games`

Current canonical tables:
- `canonical_teams`
- `canonical_players`
- `canonical_games`

Main routes:
- `GET /api/providers/balldontlie/health`
- `GET /api/providers/balldontlie/teams`
- `GET /api/providers/balldontlie/players?search=lebron`
- `GET /api/providers/balldontlie/games?date=2026-01-27`
- `POST /api/providers/balldontlie/sync/teams`
- `POST /api/providers/balldontlie/sync/players?search=lebron`
- `POST /api/providers/balldontlie/sync/games?date=2026-01-27`
- `GET /api/providers/balldontlie/storage-summary`
