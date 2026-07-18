# Railway PostgreSQL Deployment and Rollback

Status: **Railway staging migration/import validated; PostgreSQL business-runtime cutover and production remain blocked**.

## Deployment boundary

Railway must use staging first. The repository `railway.json` runs only the versioned migration command in pre-deploy and starts only the web process. Worker services retain their independent commands from `docs/railway-worker-services.md`.

Pre-deploy command:

```text
PYTHONPATH=src python -m kalshi_research_bot database-migrate --backend postgres
```

This command does not seed, import SQLite, start collectors, train models, delete rows, or reset a database.

## Required safety variables

Values belong in Railway Variables and must not be committed:

```text
APP_ENV=staging|production
DATABASE_BACKEND=postgres
DATABASE_URL=<Railway private reference>
DATABASE_POOL_MIN_SIZE=1
DATABASE_POOL_MAX_SIZE=5
DATABASE_CONNECT_TIMEOUT=5
DATABASE_STATEMENT_TIMEOUT=30000
DATABASE_MIGRATION_MODE=check
MIGRATION_CHECK_ENABLED=true
RESEARCH_ONLY=true
LIVE_EXECUTION_ENABLED=false
AUTO_UPLOAD_ENABLED=false
AUTO_TRADE_ENABLED=false
KALSHI_ORDER_UPLOAD_ENABLED=false
MODEL_PROMOTION_ENABLED=false
STALE_CACHE_AS_FRESH=false
DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED=true
```

## Staging evidence

1. Environment `staging` was created without copying production services, credentials, schedules, domains, volumes, or database references.
2. PostgreSQL service `Postgres` runs PostgreSQL 18 with persistent volume `postgres-volume`.
3. Application service `HawkNeticResearchStaging` watches only `codex/postgres-collector-railway-hardening`.
4. First successful code-bearing staging commit: `65b15889b371b7694112a98eef3b90806dd07416`; later documentation-only branch commits redeploy the same runtime code.
5. Migration revision: `0004`; repeat migration applied nothing.
6. `/healthz` and `/readyz` both return 200.
7. Stable SQLite export and repeated compatibility import pass; see `docs/postgresql-parity-validation.md`.
8. The temporary public PostgreSQL TCP proxy was removed after validation; the application retains a private Railway reference.
9. Startup Kalshi refresh produced 12 slip legs with no refresh error.
10. Independent hosted worker smoke tests remain blocked because business paths still use SQLite `ResearchStore`.

## Production gate

Production requires all checklist items in `docs/deployment-readiness-checklist.md`, including a verified backup, full normalized runtime parity, reviewed branch, clean task diff, research-only flags, and rollback evidence. A pre-deploy failure must prevent traffic from reaching new code.

## Rollback record

| Item | Current evidence |
|---|---|
| Previous application deployment | production deployment `2a315542-b979-477e-b614-20755c32c9f6` remains online |
| Previous commit | `aec3886c791e2a733fd1bfbeeb59a4298f40cb67` |
| Previous migration revision | not applicable; production remains SQLite and has no PostgreSQL service |
| New migration revision | staging `0004`; not deployed to production |
| Backup timestamp | unavailable; no backup exists |
| Backup volume/database | Railway Hobby volume backup unavailable |
| Point-in-time recovery | unavailable on current Hobby plan |
| Code rollback tested | no |
| Restoration tested outside production | no |

## Rollback triggers

- migration failure or unexpected revision
- `/readyz` failure after deployment
- parity mismatch
- duplicate normalized records
- stale data represented as fresh
- rejected/unresolved records entering metrics
- authentication or research-only flag failure
- secret exposure in logs
- worker corruption or checkpoint advancement after rollback

## Code rollback

Redeploy the previously verified Railway deployment or revert the reviewed merge through GitHub. Re-check `/healthz`, `/readyz`, migration revision, authentication, and all research-only flags.

## Database recovery

Prefer forward repair for additive migration defects. If restoration is required, restore a verified backup into a separate staging service first, validate the revision and critical aggregates, then follow Railway's reviewed recovery process. Account for writes after the backup timestamp; never overwrite production blindly. Destructive restoration must not be tested against production.

## Current Railway discovery

- Project: `jubilant-liberation`; authenticated through Railway's secure browserless one-time login.
- Environments: `production` and isolated `staging`.
- Production web service: `HawkNeticSportsTools`; production watches `Master` and remains at `aec3886c791e2a733fd1bfbeeb59a4298f40cb67`.
- Staging web service: `HawkNeticResearchStaging`; staging watches `codex/postgres-collector-railway-hardening`. The first successful code-bearing deployment was `65b15889b371b7694112a98eef3b90806dd07416`.
- Staging PostgreSQL: private-reference connection, migration `0004`, compatibility import complete.
- Production volume: 625.287 MB used of 5,000 MB; it is not currently full.
- Production Backups page: no backups; Backups/PITR require Pro.
- Production database and deployment were not modified.

The production gate remains blocked by missing backup capability and the incomplete PostgreSQL business-query boundary. A dashboard credential exposed during infrastructure discovery must also be rotated before any production deployment.
