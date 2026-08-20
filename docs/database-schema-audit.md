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
- Migration `0006` preserves the checksum already deployed to staging and converts legacy runtime numerics exactly. Migration `0007` moves legacy PostgreSQL collection-ledger tables out of `public` into `archive`; normalized `raw` and `ops` relations are authoritative.
- Unique constraints and state-conditioned updates, not advisory locks alone, enforce idempotency and ownership.
- Rejected, blocked, unresolved, stale, and duplicate rows remain auditable but are excluded from performance denominators.

## Measured index and read-path findings

Measured on PostgreSQL against `app.sports_prediction_logs` loaded with 400,000
rows, 60,000 of them unresolved and belonging to 60 upcoming events — roughly a
day of collection at the rate a moving multi-book slate produces.

| Finding | Measurement | Status |
| --- | --- | --- |
| Migrations `0001` and `0007` each created the same three indexes | Identical btrees on `app.prediction_logs`, `app.crypto_prediction_logs`, `app.sports_prediction_logs`; every insert maintained both copies | Fixed in migration `0013`; `test_no_table_carries_two_identical_indexes` keeps it fixed |
| Every table carries a primary key; no money or probability column is a binary float | 0 tables without a primary key, 0 `double precision`/`real` columns | Holds |
| The sports board reads the full snapshot history of every upcoming event | 491 ms, sorting 60,000 rows through a 10.8 MB external merge to return 120 | Open — see below |

### The board read scales with collection history, not with the slate

`sports_board._rows_for_board` takes `DISTINCT ON (event_id, market_type,
selection, line, bookmaker)` over every unresolved row of the upcoming events.
The rows it discards are the earlier snapshots of the same quote, so the work
grows with how long a game has been collected and how often its price moved,
while the answer stays the size of the slate.

A partial index on the `DISTINCT ON` key and a `LATERAL` rewrite were both
measured and neither helped: the planner keeps the bitmap scan and the sort
(566 ms and 523 ms respectively). The shape, not the access path, is the cost.

Removing it needs a current-quote projection — one row per
`(event_id, market_type, selection, line, bookmaker)` holding its latest
observation, maintained as rows are written and verified against the
`DISTINCT ON` result. That is a schema and write-path change, recorded here with
its measurement rather than guessed at.
