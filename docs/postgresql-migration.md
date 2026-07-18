# SQLite to PostgreSQL Migration

SQLite remains supported for local development. PostgreSQL is prepared for hosted multi-worker research, but it is not activated automatically.

## Schema and Migrations

- SQLite additive migration: `migrations/sqlite/0001_research_hardening.sql`.
- PostgreSQL full schema: `migrations/postgres/0001_research_schema.sql`.
- Applied migration versions and hashes are stored in `schema_migrations`.
- Editing an already-applied migration causes a hard hash mismatch instead of silently changing history.
- Prediction, settlement, market, timestamp, model-version, worker, session, crypto, and sports query indexes are defined.
- Unique constraints protect prediction, settlement, execution, evaluation, exposure, worker-run, and import idempotency.

Install the optional PostgreSQL runtime only when PostgreSQL is intentionally enabled:

```powershell
python -m pip install -e ".[postgres]"
```

## Safe Local Migration Sequence

1. Stop writers or place workers in maintenance mode.
2. Back up SQLite and its WAL/SHM files together.
3. Apply local migrations.
4. Export immutable history to JSONL plus a hashed manifest.
5. Validate source counts, file hashes, and critical aggregates.
6. Create an empty PostgreSQL database and apply its migrations.
7. Import only after reviewing the manifest and setting `DATABASE_URL` outside Git.
8. Compare destination row counts and critical aggregates.
9. Keep the SQLite backup until a full read/write/settlement cycle is verified.

Commands:

```powershell
$env:PYTHONPATH='src'
python -m kalshi_research_bot database-migrate --backend sqlite
python -m kalshi_research_bot database-export-sqlite --output data/postgres_export
python -m kalshi_research_bot database-validate-export --input data/postgres_export

# Review data/postgres_export/manifest.json before continuing.
$env:DATABASE_URL='<set outside Git>'
python -m kalshi_research_bot database-migrate --backend postgres
python -m kalshi_research_bot database-import-postgres --input data/postgres_export --confirm IMPORT_RESEARCH_HISTORY
```

The import writes an `export_id` into `migration_imports`; rerunning the same export returns `already_imported`. Authentication tables are intentionally excluded from exports because they contain password/session hashes and should be provisioned independently.

## Backup and Restore

SQLite backup while writers are stopped:

```powershell
Copy-Item data/evaluation.sqlite data/backups/evaluation-$(Get-Date -Format yyyyMMdd-HHmmss).sqlite
```

For a live SQLite backup, use SQLite's backup API rather than copying one file while WAL writes are active.

PostgreSQL backup and restore (run with credentials supplied outside shell history where possible):

```text
pg_dump --format=custom --no-owner --file research.dump "$DATABASE_URL"
pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" research.dump
```

Railway backups should also use the platform's supported backup/snapshot controls. A restore drill is required before relying on those backups.

## Rollback

Schema migrations are forward-only. Do not drop new tables during an incident.

1. Stop PostgreSQL workers.
2. Point `DATABASE_BACKEND` back to `sqlite`.
3. Restore or reopen the verified SQLite file.
4. Run `database-status` and the full test suite.
5. Investigate PostgreSQL separately.

The current business loops still use SQLite query paths. PostgreSQL schema/import/pooling are ready, but switching every live loop to PostgreSQL remains a deployment blocker and must not be inferred from the presence of `DATABASE_URL`.
