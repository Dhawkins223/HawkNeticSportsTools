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
- Railway PostgreSQL in production through `DATABASE_URL`
- SQLite only for explicit local/test fallback with `HAWKNETIC_ALLOW_SQLITE=1`
- backend-only OpenAI Responses API integration when `OPENAI_API_KEY` is present
- BALLDONTLIE provider client using the documented `Authorization` header shape
- local fallback explainer so the site still works end to end without third-party keys

## Railway production setup

Backend service variables:

```bash
DATABASE_URL=${{Postgres.DATABASE_URL}}
HAWKNETIC_ENV=production
HAWKNETIC_ALLOW_SQLITE=0
HAWKNETIC_SECRET_KEY=replace-with-a-long-secret
BALLDONTLIE_API_KEY=optional-until-live-sync
```

Frontend service variables:

```bash
NEXT_PUBLIC_API_BASE_URL=https://YOUR_BACKEND_SERVICE.up.railway.app
```

Production safety rules:
- `DATABASE_URL` is the source of truth for Railway PostgreSQL.
- If `HAWKNETIC_ENV=production` and `DATABASE_URL` is missing, startup fails clearly.
- SQLite is blocked in production and only works locally when `HAWKNETIC_ALLOW_SQLITE=1`.
- Startup initializes/upgrades schema idempotently; it does not drop tables or erase rows.
- Full historical backfills do not run during web startup.

After pushing to GitHub and Railway redeploying, check:

```text
https://YOUR_BACKEND_SERVICE.up.railway.app/api/health
https://YOUR_BACKEND_SERVICE.up.railway.app/api/database/readiness
https://YOUR_BACKEND_SERVICE.up.railway.app/api/debug/table-counts
```

Then run a one-season historical backfill from the Railway shell or a Railway job:

```bash
cd hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready
python3 scripts/historical_backfill.py --season 2024 --skip-existing --sleep-seconds 12
```

Optional Ball Don't Lie sync:

```bash
python3 scripts/bdl_sync.py --teams --players --games --season 2024
```

Then re-check `/api/database/readiness` and the dashboard. A completely empty production database will show: "Database connected, but required tables are empty. Run historical backfill or Ball Don't Lie sync."

## Run locally
```bash
pip install -r requirements.txt
export HAWKNETIC_ALLOW_SQLITE=1
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

## Provider/raw storage
The app stores source payloads before cleaned inserts:
- `raw_import_jobs`
- `raw_import_errors`
- `raw_historical_payloads`
- `raw_balldontlie_payloads`
- `bdl_teams`
- `bdl_players`
- `bdl_games`

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

The FastAPI startup path initializes the PostgreSQL schema idempotently. The repository has both the FastAPI/Jinja dashboard served at `/dashboard` and the Next.js dashboard in `/frontend`; both consume the same FastAPI JSON endpoints. For a separate Railway frontend service, set `NEXT_PUBLIC_API_BASE_URL` to the backend URL and set `HAWKNETIC_FRONTEND_ORIGINS` on the backend if the frontend domain is not already allowed.

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


### Railway DB bootstrap and readiness checks

```bash
cd hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready
export HAWKNETIC_ENV=production
export DATABASE_URL=postgresql://...   # Railway connection string
python3 scripts/db_init.py
python3 scripts/db_readiness.py
```

`db_init.py` runs idempotent schema creation/upgrades/seeds and fails fast when `HAWKNETIC_ENV=production` and `DATABASE_URL` is missing.

`db_readiness.py` reports:
- engine type
- whether `DATABASE_URL` is present (without printing secrets)
- total discovered tables
- missing expected tables
- row counts for dashboard-critical tables (`historical_*`, `bdl_*`, `odds`, `props`, `simulations`, `parlays`, `parlay_legs`, `data_quality_reports`).

To confirm dashboard-required data is populated, run:

```bash
python3 scripts/db_readiness.py
```

Then verify non-zero row counts where expected, especially:
- `historical_games`, `historical_player_game_stats`, `historical_team_game_stats`
- `bdl_teams`, `bdl_players`, `bdl_games`, `bdl_ingestion_logs`
- `props`, `odds`, `simulations`

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
- `GET /api/database/readiness`
- `GET /api/debug/table-counts`
- `GET /api/database/coverage`
- `GET /api/teams`, `GET /api/players`, `GET /api/games`
- `GET /api/props`, `GET /api/odds`, `GET /api/simulations`
- `POST /api/simulations/run`
- `GET /api/parlays`, `POST /api/parlays/build`, `POST /api/parlays/reorder`
- `POST /api/historical/rebuild`, `POST /api/historical/backfill`, `GET /api/historical/coverage`
- `POST /api/bdl/sync/teams`, `POST /api/bdl/sync/players`, `POST /api/bdl/sync/games`, `GET /api/bdl/status`, `GET /api/bdl/logs`

### Historical rebuild/backfill

`POST /api/historical/rebuild` verifies seasons 1996-2026 against the historical tables and writes coverage rows into `data_quality_reports`. Without a configured historical source file/API, missing seasons are reported as `incomplete` rather than faked as complete. A real historical loader can safely upsert into the `historical_*` tables and rerun coverage.

Railway-safe CLI backfill:

```bash
python3 scripts/historical_backfill.py --season 2024 --skip-existing --sleep-seconds 12
python3 scripts/historical_backfill.py --start-season 1996 --end-season 2026 --skip-existing --sleep-seconds 12
python3 scripts/historical_backfill.py --season 2024 --dry-run
python3 scripts/historical_backfill.py --season 2024 --scrape-only
python3 scripts/historical_backfill.py --season 2024 --import-only
```

The command uses the same `DATABASE_URL` connection as FastAPI, stores raw files in `raw_historical_payloads`, upserts cleaned records into `historical_*` tables, updates `raw_import_jobs`, and logs failed rows in `raw_import_errors`.

### Ball Don't Lie ingestion

Use:

```bash
curl -X POST http://127.0.0.1:8000/api/bdl/sync/teams
curl -X POST 'http://127.0.0.1:8000/api/bdl/sync/players?search=lebron'
curl -X POST 'http://127.0.0.1:8000/api/bdl/sync/games?date=2026-01-27'
```

Each sync writes normalized provider records to `bdl_*` tables and records status/errors in `bdl_ingestion_logs`.

Railway-safe CLI sync:

```bash
python3 scripts/bdl_sync.py --teams
python3 scripts/bdl_sync.py --players --search lebron
python3 scripts/bdl_sync.py --games --season 2024
python3 scripts/bdl_sync.py --games --start-date 2026-01-01 --end-date 2026-01-07
python3 scripts/bdl_sync.py --teams --players --games --season 2024 --dry-run
```

The command stores raw provider responses in `raw_balldontlie_payloads`, upserts cleaned rows into `bdl_*` tables, updates `bdl_ingestion_logs` and `raw_import_jobs`, and keeps BDL data separate from historical 1996-2026 tables.

### Test path proving frontend -> backend -> database

```bash
python3 -m pytest
```

Coverage includes dashboard rendering, core `/api/*` endpoints, database health/coverage, simulation creation, parlay creation, BDL storage, and account flows.


## Next.js / React dashboard

A real React dashboard now lives in `/frontend`. It is separate from the legacy FastAPI/Jinja pages and consumes FastAPI endpoints through `NEXT_PUBLIC_API_BASE_URL`.

```bash
# terminal 1
cd hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready
export DATABASE_URL=postgresql://...   # Railway in production
python3 run_local.py

# terminal 2
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

The React dashboard includes reusable components for Sidebar, DashboardLayout, GameCard, PlayerSearch, PropTable, ParlaySlip, SimulationCard, EVTable, DatabaseStatusPanel, HistoricalCoveragePanel, LiveApiStatusPanel, IngestionStatusPanel, and DataStatusBadge.


## Basketball-Reference historical scraper and importer

The raw historical NBA pipeline is implemented in the backend repo and does not use uploaded ZIP/Excel files.

Raw files are generated under:

```text
raw/historical/
  teams.csv
  players.csv
  1996/
    schedule.csv
    player_team_history.csv
    player_season_per_game.csv
    player_season_totals.csv
    player_advanced.csv
    team_season_stats.csv
    team_game_stats.csv
    player_game_stats.csv
    player_game_advanced.csv
    playoffs_schedule.csv
    playoffs_player_stats.csv
    playoffs_team_stats.csv
    coverage_report.json
    scrape_errors.csv
  ...
  2026/
```

The default raw path can be overridden with `HAWKNETIC_HISTORICAL_RAW_DIR`.

### Scrape Basketball-Reference

```bash
# one season, optional box score cap for testing
curl -X POST 'http://127.0.0.1:8000/api/historical/scrape/1996?max_box_scores=2'

# full range; this can take a long time and should be run as a controlled job
curl -X POST 'http://127.0.0.1:8000/api/historical/scrape?start_season=1996&end_season=2026'
```

Source URL patterns:

- `https://www.basketball-reference.com/leagues/NBA_{season}_games.html`
- `https://www.basketball-reference.com/leagues/NBA_{season}_per_game.html`
- `https://www.basketball-reference.com/leagues/NBA_{season}_totals.html`
- `https://www.basketball-reference.com/leagues/NBA_{season}_advanced.html`
- `https://www.basketball-reference.com/leagues/NBA_{season}.html`
- `https://www.basketball-reference.com/playoffs/NBA_{season}.html`

The scraper writes CSVs, `coverage_report.json`, and `scrape_errors.csv` for each season. It can resume safely because each run overwrites the raw season files for that season and import uses PostgreSQL upserts.

### Import raw files into Railway PostgreSQL

```bash
curl -X POST 'http://127.0.0.1:8000/api/historical/import/1996'
curl -X POST 'http://127.0.0.1:8000/api/historical/import?start_season=1996&end_season=2026'
```

The importer reads the raw CSVs, upserts into the `historical_*` tables, avoids duplicate rows through stable keys, and updates `data_quality_reports` with games, player-game rows, team-game rows, missing box scores, failed URLs, scrape time, import time, and season coverage status.

### Coverage and operational status

```bash
curl http://127.0.0.1:8000/api/historical/seasons
curl http://127.0.0.1:8000/api/historical/seasons/1996
curl http://127.0.0.1:8000/api/database/coverage
```

The React dashboard displays oldest/newest scraped season, total games stored, player/team stat rows, missing seasons, missing box scores, failed URLs, last scrape time, last import time, and coverage by season from these endpoints.
