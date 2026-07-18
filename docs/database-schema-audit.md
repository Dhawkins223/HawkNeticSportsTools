# Database Schema Audit

## Authoritative model

PostgreSQL is the sole application persistence engine. Migrations are forward-only files in `migrations/postgres/`, serialized by a transaction-scoped advisory lock and recorded in `ops.schema_migrations`.

| Schema | Purpose | Writer boundary | Mutability |
| --- | --- | --- | --- |
| `app` | current research, prediction, simulation, and dashboard records | application workers | controlled updates with state predicates |
| `raw` | ingestion batches, source payload evidence, rejections | collectors | append-only except batch completion |
| `core` | series, events, markets, observations, trades, order books, settlements | collectors and settlement worker | identity updates plus append-only observations |
| `research` | feature snapshots, model versions, prediction lineage, outcomes | research/evaluation jobs | append-only lineage |
| `ops` | worker ownership, source health, checkpoints, quality, private messages | operations workers | atomic state transitions |
| `reporting` | query views | reporting refresher | read-only objects |
| `auth` | users, sessions, login audit | authentication service | auditable controlled writes |
| `archive` | immutable pre-cutover PostgreSQL ledger evidence | migration only | no runtime reads or writes |

## Contracts

- Monetary values, prices, fees, returns, probabilities, and aggregates use exact `NUMERIC` values. API, CLI JSON, and report JSON serialize decimal values as fixed-point strings only at their external boundary.
- Timestamps are timezone-aware `TIMESTAMPTZ`, stored in UTC. Reporting day grouping uses `America/New_York` explicitly where product reporting requires a calendar day.
- Structured payloads use `JSONB`; falsey JSON values remain distinct from an empty object.
- Runtime search path is `app, pg_catalog`. Statements touching another domain qualify that schema.
- Legacy PostgreSQL collection-ledger tables are moved out of `public` into `archive` during migration `0006`; normalized `raw` and `ops` relations are authoritative.
- Unique constraints and state-conditioned updates, not advisory locks alone, enforce idempotency and ownership.
- Rejected, blocked, unresolved, stale, and duplicate rows remain auditable but are excluded from performance denominators.
