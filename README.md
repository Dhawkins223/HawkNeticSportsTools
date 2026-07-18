# HawkNeticSportsTools

Private, research-only decision support for Kalshi, crypto, and sports workflows. It never places orders, uploads slips, enables automatic trading, or promotes models.

## Local workflow

The canonical local checkout is the native WSL repository at:

```text
/home/dahaw/projects/HawkNeticSportsTools
```

Do not edit a parallel Windows or OneDrive checkout at the same time. GitHub is the version-control source of truth.

### Prerequisites

- Docker Desktop with WSL integration
- Docker Compose
- Python 3.12 or newer
- A local `.env` copied from `.env.example`

PostgreSQL is the only supported database engine. Docker Compose starts exactly one local service; credentials remain in the untracked `.env` file.

```bash
cd /home/dahaw/projects/HawkNeticSportsTools
cp .env.example .env
./scripts/local.sh setup
./scripts/local.sh migrate
./scripts/local.sh dev
```

Useful commands:

```bash
./scripts/local.sh db-start
./scripts/local.sh db-status
./scripts/local.sh migration-status
./scripts/local.sh test
./scripts/local.sh test-integration
./scripts/local.sh smoke
./scripts/local.sh verify
./scripts/local.sh stop
```

`db-reset` destroys only the local Docker volume and requires the explicit `RESET` confirmation. It never contacts Railway.

## Database contract

All application state uses PostgreSQL and versioned migrations in `migrations/postgres/`.

- `app`: active research, prediction, simulation, and dashboard writes.
- `raw`: immutable collection batches, payload evidence, and rejection records.
- `core`: source market identity and observations.
- `research`: model and feature lineage.
- `ops`: worker state, source health, quality results, and private operator messages.
- `reporting`: read-only reporting views.
- `auth`: users, sessions, and login audits.

Runtime connections use the deterministic search path `app, pg_catalog`; cross-domain statements use explicitly qualified schema names. Exact financial and probability values remain `NUMERIC` until an API or UI serialization boundary, where fixed-point decimal strings preserve their scale without binary-float loss.

## Safety controls

The application starts in research-only mode. Keep these values in `.env` and hosted variables:

```text
RESEARCH_ONLY=true
LIVE_EXECUTION_ENABLED=false
AUTO_TRADE_ENABLED=false
AUTO_UPLOAD_ENABLED=false
MODEL_PROMOTION_ENABLED=false
STALE_CACHE_AS_FRESH=false
```

Freshness, source evidence, rejection, unresolved-state, and duplicate-exposure gates remain enforced. A blocked sports source does not fabricate rows or affect Kalshi or crypto metrics.

## Hosted workflow

Hosted staging and production are separate from local development and must use distinct PostgreSQL services, credentials, and data. A production cutover requires successful migration, parity, backup, restore, readiness, and research-only safety checks. See:

- `docs/operator-runbook.md`
- `docs/database-schema-audit.md`
- `docs/data-cutover-validation.md`
- `docs/postgresql-parity-validation.md`
- `docs/railway-postgresql-deployment-and-rollback.md`
- `docs/deployment-readiness-checklist.md`

Do not use the deployment environment as proof of model validity, edge, or profitability.
