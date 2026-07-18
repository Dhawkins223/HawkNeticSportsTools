# Railway PostgreSQL Deployment and Rollback

Status: **PostgreSQL-only local runtime validated; Railway staging must be revalidated for this branch and production remains blocked**.

Local validation on 2026-07-17 applied migrations through `0006`, imported a read-only legacy archive with repeat-import protection, passed 251/251 tests, and completed one Kalshi/crypto/sports/settlement/reporting worker pass. This is local evidence only; it is not a Railway deployment or production approval.

## Deployment boundary

Railway must use staging first. The repository `railway.json` runs only the versioned migration command in pre-deploy and starts only the web process. Worker services retain their independent commands from `docs/railway-worker-services.md`.

Pre-deploy command:

```text
PYTHONPATH=src python -m kalshi_research_bot database-migrate
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

## Historical staging evidence (pre-PostgreSQL-only runtime)

1. Environment `staging` was created without copying production services, credentials, schedules, domains, volumes, or database references.
2. PostgreSQL service `Postgres` runs PostgreSQL 18 with persistent volume `postgres-volume`.
3. This prior staging evidence was created before the current branch; direct discovery now shows `HawkNeticResearchStaging` sourcing `Master` and it must be repointed to the reviewed feature branch before validation.
4. First successful code-bearing staging commit: `65b15889b371b7694112a98eef3b90806dd07416`; later documentation-only branch commits redeploy the same runtime code.
5. Migration revision: `0004`; repeat migration applied nothing.
6. `/healthz` and `/readyz` both return 200.
7. Stable SQLite export and repeated compatibility import pass; see `docs/postgresql-parity-validation.md`.
8. The temporary public PostgreSQL TCP proxy was removed after validation; the application retains a private Railway reference.
9. Startup Kalshi refresh produced 12 slip legs with no refresh error.
10. This historical staging deployment predates the PostgreSQL-only runtime branch and is not evidence that its web or worker paths are currently validated.

## Production gate

Production requires all checklist items in `docs/deployment-readiness-checklist.md`, including a verified backup, fresh staging PostgreSQL runtime parity, reviewed branch, clean task diff, research-only flags, and rollback evidence. A pre-deploy failure must prevent traffic from reaching new code.

## Rollback record

| Item | Current evidence |
|---|---|
| Previous application deployment | production deployment `2a315542-b979-477e-b614-20755c32c9f6` remains online |
| Previous commit | `aec3886c791e2a733fd1bfbeeb59a4298f40cb67` |
| Previous migration revision | not applicable; production remains SQLite and has no PostgreSQL service |
| New migration revision | local `0006`; current-branch staging deployment not yet run |
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
- Production web service: `HawkNeticSportsTools`; production watches `Master`. Current Railway metadata references commit `091c7f75a38d5c956b7ee2ce8064249811310d80`; this task has not modified production.
- Staging web service: `HawkNeticResearchStaging`; current Railway discovery shows it also watches `Master`. It must be repointed to `codex/finish-postgres-only-runtime` only after the reviewed branch is pushed.
- Staging PostgreSQL: prior private-reference migration/import evidence exists at `0004`; revalidate current branch through `0006` before relying on it.
- Production volume: 625.287 MB used of 5,000 MB; it is not currently full.
- Production Backups page: no backups; Backups/PITR require Pro.
- Production database and deployment were not modified.

The production gate remains blocked by missing backup capability, missing current-branch staging validation, and required credential rotation. The PostgreSQL-only business-query boundary is complete locally but must be proven in Railway before any production deployment.
