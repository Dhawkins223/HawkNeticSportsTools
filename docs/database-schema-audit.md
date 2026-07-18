# Database Schema Audit

Audit date: 2026-07-12. Status: **research operational; PostgreSQL cutover blocked pending staging parity**.

## Scope and conventions

SQLite remains the local source of truth at `data/evaluation.sqlite`. PostgreSQL migrations `0001` and `0002` are legacy-compatible import tables. Migration `0003` adds the authoritative `raw`, `core`, `research`, `ops`, `reporting`, and `auth` schemas without deleting or rewriting legacy tables.

Timestamp semantics:

- `prediction_timestamp` and `feature_time`: when the research decision was made.
- `api_fetched_at` and `received_at`: when this system received source data.
- `source_updated_at` and `observed_at`: source-reported observation time.
- `created_at`: database insertion time.
- `source_cutoff_time` and `data_cutoff_time`: latest source time permitted for a reproducible prediction or evaluation.
- `settlement_updated_at` and `source_settled_at`: settlement observation time, not prediction time.

Legacy SQLite stores timestamps as timezone-bearing ISO text and numerics as `REAL`. The authoritative PostgreSQL ledger uses `TIMESTAMPTZ`, exact `NUMERIC`, foreign keys, checks, and controlled statuses.

## SQLite inventory

Abbreviations: PK = primary key; BK = business key; FK = foreign key; UQ = unique constraint; RO = append-only/read-only intent; RW = mutable operational state.

| Table | Class | PK / BK / integrity | Timestamp and numeric semantics | Mutability | Writer / reader | PostgreSQL destination and migration status | Known defect |
|---|---|---|---|---|---|---|---|
| `source_records` | raw source | PK `id`; no source BK or UQ | `collected_at`; text JSON | RO intent | `ScrapeBot` / research pipeline | legacy `public.source_records`; future `raw.source_payloads` | raw and normalized content combined; duplicates possible |
| `edge_results` | derived research | PK `id`; no run FK/UQ | `created_at`; probability and cents are `REAL` | RO | pipeline / reports | legacy `public.edge_results`; superseded by research predictions/metrics | floating point; no model/run lineage |
| `paper_test_runs` | configuration/run | PK `run_id`; UQ config hash absent | `started_at`; no money | RW status | paper CLI / reports | legacy `public.paper_test_runs`; future `research.prediction_runs` | JSON config; status not constrained in base table |
| `prediction_logs` | prediction + settlement | PK `id`; partial UQ run/strategy/event/market/side/time | prediction, source, event, close, settlement times; probabilities/money `REAL` | prediction should be RO but settlement fields mutate | paper logger and settlement importer / reports, audits | legacy `public.prediction_logs`; split into `research.predictions` + `research.prediction_outcomes` | combines prediction and future outcome; floats; JSON features; mutable history |
| `prediction_rejections` | rejected research | PK `id`; no rejection UQ | prediction and creation times | RO | paper logger / quality reports | legacy `public.prediction_rejections`; future `raw.rejected_records` | duplicate rejection pathway; raw JSON only |
| `settlement_audit` | settlement audit | PK `id`; FK by convention to prediction; UQ hash tuple | source fetch and creation times; P/L `REAL` | RO | settlement importer / audits | legacy `public.settlement_audit`; future `core.settlements` correction chain | FK not declared in SQLite base schema; floats |
| `crypto_prediction_logs` | prediction + settlement | PK `id`; exact-snapshot UQ | prediction, candle, fetch, settlement times; prices/returns `REAL` | mixed RO/RW | crypto cycle / crypto reports | legacy `public.crypto_prediction_logs`; future normalized research ledger | outcome mixed into prediction; floats; feature blob |
| `crypto_prediction_rejections` | rejected research | PK `id`; no UQ | prediction and creation times | RO | crypto cycle / quality reports | legacy public table; future `raw.rejected_records` | duplicates possible; raw JSON |
| `sports_prediction_logs` | prediction + settlement | PK `id`; exact-snapshot UQ | prediction, odds, game, fetch, settlement times; odds/line/CLV `REAL` | mixed RO/RW | sports cycle / sports reports | legacy public table; future normalized research ledger | outcome mixed into prediction; floats; feature blob |
| `sports_prediction_rejections` | rejected research | PK `id`; no UQ | prediction and creation times | RO | sports cycle / quality reports | legacy public table; future `raw.rejected_records` | duplicates possible; raw JSON |
| `model_evaluations` | reporting/evaluation | PK `id`; UQ `evaluation_id`; model-state check | split/evaluation times; metrics `REAL` | RO | model evaluator / internal status | legacy public table; future `research.metric_results` | evidence JSON; float metrics |
| `model_evaluation_predictions` | evaluation detail | PK `id`; FK evaluation; UQ evaluation/record/split | prediction time; probabilities/metrics `REAL` | RO | model evaluator / audit | legacy public table; future prediction/outcome/metric records | actual outcome stored beside evaluation prediction |
| `simulated_executions` | execution simulation | PK `id`; UQ `order_id` | signal/order/snapshot times; cents `REAL` | RW until settlement | execution evaluator / return audit | legacy public table; future simulation orders/fills | float money; snapshot JSON; no fill child table |
| `exposure_decisions` | execution/risk | PK `id`; UQ portfolio/prediction | creation time; capital `REAL` | RO | exposure evaluator / return audit | legacy public table; future correlation/exposure records | float money; event and prediction FKs absent |
| `worker_runs` | ops | PK `id`; UQ worker/idempotency | attempted/finished times | RW completion | worker runtime / internal status | legacy public table; future `ops.worker_runs` | counters incomplete; worker version absent |
| `worker_status` | ops | PK `worker_name` | attempt/success/freshness/heartbeat times | RW latest-state | monitor / internal status | legacy public table; future reporting view over `ops.worker_runs` | overwrites history by design; details JSON |
| `connector_health` | ops/config | composite PK connector/asset | attempt/success/failure times | RW latest-state | connectors / status | legacy public table; future `ops.source_health` | connector state differs from source freshness semantics |
| `app_users` | authentication | PK `id`; UQ username; role check | create/update/lock times | RW | auth store / auth middleware | legacy `public.app_users`; future `auth` migration not yet mapped | SQLite-only runtime; role schema acceptable |
| `app_sessions` | authentication | PK session hash; FK user | create/expiry/seen/revoked times | RW | auth store / auth middleware | legacy public table; future `auth` migration not yet mapped | SQLite-only runtime |
| `login_audit` | authentication audit | PK `id`; no UQ | attempted time | RO | auth store / admin audit | legacy public table; future `auth` migration not yet mapped | retention policy undocumented |
| `operator_messages` | ops/control | PK `message_id`; controlled priority/status/source; execution disabled by check | create/update/claim/complete times | RW workflow | operator inbox / admin-only `/ops` | legacy public table | intentionally manual; not an execution queue |
| `schema_migrations` | configuration | PK version; migration hash | applied time | RO | migration runner / readiness | `public.schema_migrations` | SQLite text timestamps; otherwise intentional |
| `ingestion_batches` | raw ops | PK batch; UQ idempotency; controlled status/mode | batch/window times; integer counts | RW until terminal | collection ledger / ops | `raw.ingestion_batches` | new; local compatibility uses text IDs |
| `raw_source_payloads` | raw evidence | PK payload; FK batch; UQ batch/source id/hash | observed/received/create times | append-only | collection ledger / parsers/audit | `raw.source_payloads` | new; export mapper not yet active |
| `rejected_records` | raw quality | PK rejection; FK batch/payload | reject/resolve times | append-only plus resolution | collection ledger / quality | `raw.rejected_records` | new |
| `collection_checkpoints` | ops | composite PK source/endpoint/scope; FK batch | window/item/update times | RW transactional | collection ledger / collectors | `ops.collection_checkpoints` | new; only advances with completed batch |
| `source_health` | ops | PK source; freshness-state check | attempt/success/deadline/update times | RW latest-state | collection ledger / readiness/status | `ops.source_health` | new |
| `data_quality_results` | ops quality | PK result; FK batch; status check | checked time | append-only | quality checks / status | `ops.data_quality_results` | new |
| `audit_events` | audit | PK event | create time | append-only | operators/workers / audits | `ops.audit_events` | new |
| `backfill_jobs` | ops | PK job; controlled status | requested window/create/update times | RW | backfill operator / status | `ops.backfill_jobs` | new |
| `report_refreshes` | reporting ops | PK refresh; controlled status | cutoff/start/complete times | RW terminal | reporting worker / status | `ops.report_refreshes` | new |

## PostgreSQL authoritative ledger

| Schema | Tables / views | Integrity design | Primary writers / readers |
|---|---|---|---|
| `raw` | `ingestion_batches`, `source_payloads`, `rejected_records` | idempotency key, deterministic hash, append-only payloads, retained rejects | collectors / parsers, audit |
| `core` | `series`, `events`, `markets`, `market_observations`, `trades`, `orderbook_snapshots`, `orderbook_levels`, `settlements` | stable source BKs, exact numerics, temporal observations, source trade UQ, settlement correction chain | normalized collectors / research feature builders |
| `research` | `model_versions`, `feature_snapshots`, `prediction_runs`, `predictions`, `prediction_outcomes`, simulation, fills, correlation, exposure, metrics | source cutoff checks, probability checks, outcome separation, no duplicate run/market prediction, exact money | research workers / reporting views |
| `ops` | `worker_runs`, `source_health`, `collection_checkpoints`, backfill, quality, audit, migration, report refresh | controlled states, transactional checkpoints, idempotent worker runs | workers / admin-only monitoring |
| `reporting` | latest market, freshness, worker health, unresolved issues, prediction evaluation, settlement backlog views | read-only projections; evaluation view excludes rejected, blocked, stale, duplicate, and unverified records | web read-only/reporting |
| `auth` | reserved for role-separated auth migration | no new auth tables until runtime mapping is reviewed | auth service only |

## Confirmed defects and disposition

1. Legacy SQLite and PostgreSQL public tables use binary floating point for prices, probabilities, fees, returns, and capital. They remain compatibility tables only; all new authoritative fields use exact PostgreSQL `NUMERIC`.
2. Legacy prediction rows combine contemporaneous model output with later settlements. New predictions and outcomes are separate tables linked to immutable feature snapshots and verified settlements.
3. Legacy source payloads are flattened into text/JSON without ingestion provenance. The new raw ledger retains batch, parser, receipt, observation, source identifier, and deterministic hash.
4. Legacy market identity and observations are not relationally represented. The new core hierarchy separates series/event/market identity from append-only observations, trades, books, and settlements.
5. Existing business loops are SQLite-specific. PostgreSQL must not become runtime source-of-truth until query-path conversion and staging parity are complete.
6. Legacy report queries remain guarded in application code. The new reporting evaluation view repeats the exclusions at the database layer.

## Volume and partition threshold

Current local volume is below a partitioning threshold. Do not partition yet. Re-evaluate monthly partitioning when an append-only table exceeds 10 million rows or sustained write volume exceeds 100 rows/second and query plans show time-range scans are a measurable bottleneck.
