# SQLite to PostgreSQL Migration Map

Status: **export validated; destination import/parity pending staging PostgreSQL**.

## Migration discipline

The migration is forward-only and additive. Existing shared migrations are not rewritten. SQLite remains intact until a staging PostgreSQL import passes row, hash, aggregate, report, and research-result parity.

| SQLite source | Immediate PostgreSQL import | Authoritative destination | Conversion rule |
|---|---|---|---|
| `source_records` | `public.source_records` | `raw.source_payloads` plus normalized `core` records | retain original row during legacy parity; later replay through versioned parser |
| `prediction_logs` | `public.prediction_logs` | `research.prediction_runs`, `feature_snapshots`, `predictions`, `prediction_outcomes` | preserve IDs; split outcomes only through a reviewed backfill with cutoff evidence |
| `prediction_rejections` | `public.prediction_rejections` | `raw.rejected_records` | preserve raw JSON and rejection reason |
| `settlement_audit` | `public.settlement_audit` | `core.settlements` | preserve every revision; verified status requires source validation |
| crypto logs/rejections | matching legacy public tables | category-specific research/raw records | preserve source hash and candle cutoff; no generic model coercion |
| sports logs/rejections | matching legacy public tables | category-specific research/raw records | preserve odds time, game time, source hash, and rejection reason |
| model evaluation tables | matching legacy public tables | `research.model_versions`, predictions/outcomes, `metric_results` | preserve dataset/feature/model versions and split boundaries |
| simulation/exposure tables | matching legacy public tables | `research.simulation_runs`, orders, fills, correlations, exposures | convert cents to exact decimal; preserve no-fill/partial-fill state |
| worker/connector tables | matching legacy public tables | `ops.worker_runs`, `ops.source_health` | latest-state tables become operational projections over history |
| auth and operator tables | excluded from automated export | reviewed auth migration only | never export password/session material through research-data tooling |
| local collection ledger tables | not in export v1 | matching `raw`/`ops` schema tables | mapper required before PostgreSQL runtime cutover |

## Stable export

Command:

```powershell
$env:PYTHONPATH='src'
python -m kalshi_research_bot database-export-sqlite --db data\evaluation.sqlite --output data\postgres_export_20260712
```

The export records the source filename, UTC export time, table row counts, deterministic SHA-256 digests, critical aggregates, and one export identity. Sensitive auth/operator tables are excluded.

## Import order

1. Apply all PostgreSQL migrations to an empty, non-production database.
2. Import legacy compatibility tables transactionally using the reviewed export.
3. Record the export identity in `migration_imports`; a repeated import returns `already_imported`.
4. Validate compatibility-table parity.
5. Replay raw evidence into normalized schemas only with versioned parsers and explicit lineage.
6. Convert application reads one bounded query path at a time.
7. Keep SQLite available until dashboard, evaluation, return decomposition, freshness, and settlement reports match.

## Numeric and timestamp rules

- Legacy `REAL` values are preserved exactly for compatibility checks; new authoritative values are converted to exact `NUMERIC` using documented decimal scale.
- UTC timezone-bearing ISO strings become `TIMESTAMPTZ` without dropping the represented instant.
- Null, malformed, or naive timestamps fail import or are rejected; they are never silently assigned the current time.
- Aggregate comparison tolerance is zero for counts/statuses/hashes and `1e-9` only for legacy floating-point aggregate serialization.

## Rollback boundary

No application-level dual writes are introduced. Until cutover, SQLite remains the active source. A failed import can be discarded by dropping only the non-production staging database. Production database mutation is prohibited until backup and rollback evidence exists.
