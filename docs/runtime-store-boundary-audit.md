# Runtime Store Boundary Audit

Audit date: 2026-07-13. Result: PostgreSQL schema/import parity passes; application business-runtime parity is blocked.

## Technical summary

The repository has two database concepts but only one active business store. `DatabaseSettings` and `PostgresConnectionPool` can configure and check PostgreSQL, while `ResearchStore` implements the business operations directly with SQLite. Most application paths construct `ResearchStore` themselves, so setting `DATABASE_BACKEND=postgres` does not move those paths to PostgreSQL.

The safe fix is an explicit business-store protocol with SQLite and PostgreSQL implementations. Do not add hidden dual writes or a fallback that silently returns to SQLite in hosted environments.

## Current database components

| Component | Current responsibility | Limitation |
|---|---|---|
| `database.py` | Environment parsing, PostgreSQL pool wrapper, migration/readiness status, production safety flags | No business queries |
| `storage.py` | SQLite schema initialization and core Kalshi source/edge/prediction/run/rejection writes | Concrete SQLite implementation, not a shared contract |
| `sports_research.py` | Sports schema, writes, settlement, reports, feature exports | Opens SQLite directly and owns SQL locally |
| `crypto_research.py` | Crypto collection, prediction, settlement, reports, diagnostics, feature exports | SQLite-specific paths |
| `auth.py` | Local users, sessions, lockout, CSRF support, login audit | SQLite-specific store |
| `collection_ledger.py` | Raw evidence, batches, checkpoints, source health | Initializes SQLite `ResearchStore` |
| `monitoring.py` | Worker and connector health | SQLite-specific reads |
| `db_migrations.py` | Versioned SQLite/PostgreSQL migration discovery and application | Correctly separated from business runtime |
| `postgres_migration.py` | Deterministic SQLite export, validation, compatibility import, parity checks | Compatibility import does not populate normalized business views |

## Concrete coupling points

The following active paths instantiate or depend on SQLite `ResearchStore`:

- `paper_server.py`: refresh prediction logging and service readiness.
- `worker_services.py`: external source, settlement, and reporting workers.
- `cli.py`: database-backed CLI operations and reports.
- `evaluation/logging.py`: prediction logging.
- `evaluation/model_validation.py` and `evaluation/model_audit.py`: evaluation reads/writes.
- `auth.py`: local authentication store.
- `operator_inbox.py`: private operator messages.
- `monitoring.py`: health/status reporting.
- `collection_ledger.py`: local collection ledger.

`sports_research.py` and `crypto_research.py` also manage SQLite connections and schemas directly. A store protocol that wraps only `storage.py` would therefore be incomplete.

## Why the current Railway result is not runtime parity

Railway staging proves:

- PostgreSQL connectivity and migration revision through `0004`;
- repeat migration safety;
- compatibility import of 17 SQLite tables;
- row count, null/status/timestamp/hash, aggregate, and duplicate-import parity;
- `/healthz` and `/readyz` under configured PostgreSQL migration checks.

It does not prove:

- web reads from PostgreSQL;
- worker writes to PostgreSQL;
- normalized `raw`, `core`, `research`, `ops`, and `reporting` data population;
- authentication or operator-message persistence in PostgreSQL;
- PostgreSQL-based report, return, settlement, crypto, or sports parity;
- safe independent hosted workers.

## Required business-store contract

Define protocols around application behavior rather than generic CRUD. Initial capability groups:

1. **Kalshi research**: runs, predictions, rejections, settlement revisions, de-duplicated report reads.
2. **Crypto research**: predictions, rejections, candle/settlement updates, diagnostics/report reads.
3. **Sports research**: source evidence, event/odds rows, mapping rejects, settlement updates, report reads.
4. **Collection operations**: ingestion batches, immutable payloads, rejected rows, checkpoints, source health.
5. **Workers and monitoring**: attempts, completion, counters, heartbeat, errors, pending settlement state.
6. **Authentication and operations**: users, sessions, login audit, operator messages.
7. **Model evaluation**: model versions, feature snapshots, predictions/outcomes, evaluation detail, metrics.

Prefer several cohesive protocols or repositories behind one factory over one giant interface.

## Store selection policy

```text
local default:
    DATABASE_BACKEND=sqlite
    EVALUATION_DB_PATH=data/evaluation.sqlite

hosted staging/production:
    DATABASE_BACKEND=postgres
    DATABASE_URL=<private Railway reference>
```

Rules:

- Hosted PostgreSQL selection is explicit and mandatory.
- Missing or unhealthy PostgreSQL fails readiness and worker startup.
- No hosted SQLite fallback.
- Local SQLite remains supported until all parity tests pass.
- A process receives one store factory; modules do not independently reinterpret environment variables.

## Transaction and numeric requirements

- Explicit transaction scope and rollback.
- Bounded pool, connection timeout, and statement timeout.
- Checkpoint advance in the same commit as accepted rows.
- Database-enforced uniqueness and deterministic IDs.
- Append-only source, quote, and settlement history.
- Exact `NUMERIC` for prices, probabilities, returns, fees, lines, and money.
- UTC timezone-aware timestamps.
- Separate immutable prediction features from later outcomes.

## Incremental conversion plan

1. Add store protocols, factory, and a SQLite adapter around current behavior with no output change.
2. Move worker runtime/status and collection-ledger operations first; they have clear idempotency boundaries.
3. Move Kalshi prediction/report/settlement behavior and compare controlled fixture outputs.
4. Move crypto and sports operations without changing candidate or settlement logic.
5. Move model evaluation and monitoring.
6. Move authentication/operator messages under a separately reviewed schema change.
7. Populate normalized reporting views and compare counts, exclusions, aggregates, and rendered reports.
8. Run one complete Railway staging cycle, restart workers, and verify checkpoint safety.

Every step keeps SQLite tests passing and adds PostgreSQL integration tests. Do not delete compatibility tables during conversion.

## Parity tests required

- Identical accepted/rejected counts for controlled inputs.
- Identical exact duplicate behavior.
- Identical unresolved/settled/push/void classifications.
- Identical de-duplicated metric denominators.
- Identical daily and Stage 3B report aggregates within only documented legacy-float tolerance.
- Transaction rollback on injected failure.
- Restart/idempotency with unchanged snapshots.
- Checkpoint does not advance after rollback.
- Hosted process refuses to start when PostgreSQL is missing or behind migrations.
- No rejected, stale, blocked, unresolved, or duplicate row enters performance metrics.

## Current blockers

- Normalized PostgreSQL write/read implementation is incomplete.
- Auth schema/runtime migration is not reviewed.
- Off-platform backup and restoration are not verified.
- Independent hosted workers remain prohibited.
- Previously exposed credentials require rotation before production.

## Decision

Begin Phase 1 with the store protocols and factory while preserving every existing SQLite behavior. No competitive product module should add new direct SQLite queries.

