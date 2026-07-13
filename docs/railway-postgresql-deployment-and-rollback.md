# Railway PostgreSQL Deployment and Rollback

Status: **repository configuration prepared; Railway staging absent and production unchanged**.

## Deployment boundary

Railway must use staging first. The repository `railway.json` runs only the versioned migration command in pre-deploy and starts only the web process. Worker services retain their existing independent commands from `docs/railway-worker-services.md`.

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

## Staging sequence

1. Verify Railway account, linked project, environment, services, GitHub source, watched branch, root directory, and private database reference.
2. Verify an isolated staging PostgreSQL service; do not duplicate an existing one.
3. Verify persistence and backup configuration.
4. Record current staging deployment commit and migration revision.
5. Deploy the reviewed feature branch or PR environment.
6. Confirm pre-deploy migration success, `/healthz` 200, and `/readyz` 200.
7. Import the stable SQLite snapshot only through the explicit import command.
8. Complete `docs/postgresql-parity-validation.md` with destination evidence.
9. Run one isolated collector pass, then repeat it to prove idempotency.
10. Inspect worker heartbeats, source freshness, rejections, logs, and secret redaction.

## Production gate

Production requires all checklist items in `docs/deployment-readiness-checklist.md`, including a verified backup, staging parity, reviewed branch, clean task diff, research-only flags, and rollback evidence. A pre-deploy failure must prevent traffic from reaching the new code.

## Rollback record

These fields must be filled from Railway immediately before production mutation:

| Item | Current evidence |
|---|---|
| Previous application deployment | production web service currently online; deployment id unverified |
| Previous commit | `aec3886c791e2a733fd1bfbeeb59a4298f40cb67` shown by Railway config links |
| Previous migration revision | unverified |
| New migration revision | `0004` repository target; not deployed |
| Backup timestamp | unverified |
| Backup volume/database | unverified |
| Point-in-time recovery | unverified |
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

Prefer forward repair for additive migration defects. If restoration is required, restore a verified backup into a separate staging service first, validate the revision and critical aggregates, then follow Railway’s reviewed recovery process. Account for any writes after the backup timestamp; never overwrite production blindly. Destructive restoration must not be tested against production.

## Current Railway discovery

- Project: `jubilant-liberation`.
- Only visible environment: `production`.
- Web service: `HawkNeticSportsTools`.
- GitHub source: `Dhawkins223/HawkNeticSportsTools`.
- Production watched branch: `Master`, with automatic deploys enabled.
- Public health path: `/healthz` from `railway.json`.
- Attached volume: `hawkneticsportstools-volume`; Railway reports the volume is full. The non-destructive audit procedure and deletion boundary are recorded in `docs/railway-volume-storage-audit.md`.
- No PostgreSQL service is visible.
- No `DATABASE_URL`, `DATABASE_BACKEND`, migration-check, or full research-safety variable set is configured on the web service.
- Backup page exposed no verifiable backup or point-in-time-recovery state.
- Railway CLI `5.23.3` is installed, but `railway status` and `railway whoami` are unauthenticated.

No Railway environment, service, variable, backup, branch, deployment, or database was changed. The local SQLite export for staging has been validated, but it has not been imported into PostgreSQL. Creating staging and PostgreSQL may consume Railway credits and must not proceed until interactive authentication succeeds and the full volume and budget constraints are resolved.
