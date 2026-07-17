# PostgreSQL Runtime and Legacy SQLite Archive

PostgreSQL is the only application runtime database locally and in approved hosted environments. SQLite is retained solely as a read-only archive/import and rollback artifact; no worker, web process, dashboard, authentication path, or report may fall back to it.

## Schema and Migrations

- Legacy SQLite archive migrations: `migrations/sqlite/` (archive fixture/validation only).
- PostgreSQL full runtime schema: `migrations/postgres/0001_research_schema.sql` through `0006_exact_numeric_runtime_compatibility.sql`.
- Applied migration versions and hashes are stored in `schema_migrations`.
- Editing an already-applied migration causes a hard hash mismatch instead of silently changing history.
- Prediction, settlement, market, timestamp, model-version, worker, session, crypto, and sports query indexes are defined.
- Unique constraints protect prediction, settlement, execution, evaluation, exposure, worker-run, and import idempotency.

Install the PostgreSQL runtime dependency:

```powershell
python -m pip install -e ".[postgres]"
```

## Safe Local Migration Sequence

1. Start the local PostgreSQL runtime and apply migrations.
2. Use PostgreSQL for all normal application, worker, and report commands.
3. When importing a historic ledger, stop writers, preserve the SQLite archive and its WAL/SHM evidence, then export immutable history to JSONL plus a hashed manifest.
4. Import only into a non-production PostgreSQL target with the migration role.
5. Compare destination row counts, hashes, and critical aggregates; repeat the import to prove idempotency.
6. Preserve the SQLite archive after parity; never configure it as a fallback.

Commands:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_postgres_runtime.ps1

# One-time archive import only; credentials belong outside Git.
$env:PYTHONPATH='src'
python -m kalshi_research_bot database-export-sqlite --sqlite-db <legacy-archive.sqlite> --output data/postgres_export
python -m kalshi_research_bot database-validate-export --sqlite-db <legacy-archive.sqlite> --input data/postgres_export
python -m kalshi_research_bot database-import-postgres --input data/postgres_export --confirm IMPORT_RESEARCH_HISTORY
```

The import writes an `export_id` into `migration_imports`; rerunning the same export returns `already_imported`. Authentication tables are intentionally excluded from exports because they contain password/session hashes and should be provisioned independently.

## Backup and Restore

Archive a SQLite file only while its legacy writers are stopped:

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
2. Preserve the current PostgreSQL database and deployment evidence.
3. Restore a verified PostgreSQL backup or forward-repair with a reviewed migration.
4. Use the SQLite archive only to rebuild an isolated PostgreSQL target; never point `DATABASE_BACKEND` back to SQLite.
5. Run `database-status` and the full test suite before restoring traffic.
