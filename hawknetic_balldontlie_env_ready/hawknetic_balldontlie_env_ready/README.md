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


## Railway PostgreSQL-first architecture

HawkNetic production uses Railway PostgreSQL through `DATABASE_URL`. The app only falls back to SQLite when `HAWKNETIC_ALLOW_SQLITE=1`, which is intended for local tests and quick developer smoke checks. In production, set:

```bash
HAWKNETIC_ENV=production
DATABASE_URL=postgresql://...
HAWKNETIC_SECRET_KEY=replace-me
BALLDONTLIE_API_KEY=...
```

The FastAPI startup path initializes the PostgreSQL schema idempotently. There is no Next.js project in this repository at the moment; the current customer dashboard is served by FastAPI/Jinja and calls FastAPI JSON endpoints from `/static/js/dashboard.js`. If a separate Next.js frontend is added later, set `HAWKNETIC_FRONTEND_ORIGINS` so CORS allows it.

### Data separation

Railway PostgreSQL is organized into separate structures:

- Historical HawkNetic tables: `historical_teams`, `historical_players`, `historical_games`, `historical_player_game_stats`, `historical_team_game_stats`, `historical_season_stats`, `historical_player_ratings`, `historical_team_ratings`
- Ball Don't Lie ingestion tables: `bdl_teams`, `bdl_players`, `bdl_games`, `bdl_player_game_stats`, `bdl_team_game_stats`, `bdl_live_games`, `bdl_ingestion_logs`
- Identity maps: `team_identity_map`, `player_identity_map`, `game_identity_map`
- Modeling/customer tables: `odds`, `props`, `simulations`, `simulation_players`, `parlays`, `parlay_legs`, `users`, `data_quality_reports`

Ball Don't Lie syncs write to `bdl_*` tables and ingestion logs. They do not blindly overwrite historical HawkNetic records. Mapping tables connect BDL IDs to internal historical IDs when a reliable match exists.

### Run backend/frontend locally

```bash
cd hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready
python3 -m pip install -r requirements.txt
export HAWKNETIC_ALLOW_SQLITE=1   # local fallback only
python3 run_local.py
```

Open `http://127.0.0.1:8000/dashboard`. The dashboard is the current frontend and consumes `/api/*` endpoints. API/database failures are shown in dashboard status badges and panels.

### Production deploy on Railway

1. Create a Railway PostgreSQL database.
2. Set `DATABASE_URL` in the web service environment.
3. Set `HAWKNETIC_ENV=production`.
4. Set `HAWKNETIC_SECRET_KEY`.
5. Set `BALLDONTLIE_API_KEY` when live API ingestion is needed.
6. Deploy the FastAPI service.
7. Check `GET /api/health` and `GET /api/database/status`.

### Key endpoints

- `GET /api/health`
- `GET /api/data-status`
- `GET /api/database/status`
- `GET /api/database/coverage`
- `GET /api/teams`, `GET /api/players`, `GET /api/games`
- `GET /api/props`, `GET /api/odds`, `GET /api/simulations`
- `POST /api/simulations/run`
- `GET /api/parlays`, `POST /api/parlays/build`, `POST /api/parlays/reorder`
- `POST /api/historical/rebuild`, `POST /api/historical/backfill`, `GET /api/historical/coverage`
- `POST /api/bdl/sync/teams`, `POST /api/bdl/sync/players`, `POST /api/bdl/sync/games`, `GET /api/bdl/status`, `GET /api/bdl/logs`

### Historical rebuild/backfill

`POST /api/historical/rebuild` verifies seasons 1996-2026 against the historical tables and writes coverage rows into `data_quality_reports`. Without a configured historical source file/API, missing seasons are reported as `incomplete` rather than faked as complete. A real historical loader can safely upsert into the `historical_*` tables and rerun coverage.

### Ball Don't Lie ingestion

Use:

```bash
curl -X POST http://127.0.0.1:8000/api/bdl/sync/teams
curl -X POST 'http://127.0.0.1:8000/api/bdl/sync/players?search=lebron'
curl -X POST 'http://127.0.0.1:8000/api/bdl/sync/games?date=2026-01-27'
```

Each sync writes normalized provider records to `bdl_*` tables and records status/errors in `bdl_ingestion_logs`.

### Test path proving frontend -> backend -> database

```bash
python3 -m pytest
```

Coverage includes dashboard rendering, core `/api/*` endpoints, database health/coverage, simulation creation, parlay creation, BDL storage, and account flows.
