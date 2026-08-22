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
| The sports board read the full snapshot history of every upcoming event | 1.6 s per board load (491 ms of it SQL), sorting 60,000 rows through a 10.8 MB external merge to return 120 | Fixed in migration `0014`: 632 ms cold, 9 ms warm |

### The board read scaled with collection history, not with the slate

`sports_board._rows_for_board` took `DISTINCT ON (event_id, market_type,
selection, line, bookmaker)` over every unresolved row of the upcoming events.
The rows it discarded were the earlier snapshots of the same quote, so the work
grew with how long a game had been collected and how often its price moved,
while the answer stayed the size of the slate.

A partial index on the `DISTINCT ON` key and a `LATERAL` rewrite were both
measured first and neither helped: the planner kept the bitmap scan and the sort
(566 ms and 523 ms respectively). The shape, not the access path, was the cost.

Migration `0014` adds `app.sports_current_quotes`: one row per
`(event_id, market_type, selection, line, bookmaker)` holding its most recent
observation. A trigger maintains it, rather than the collector, because the
collector is not the only writer — imports and backfills reach these tables too —
and a projection that silently diverges from its source is worse than none.
`sports_board.verify_current_quotes()` re-derives the `DISTINCT ON` answer and
reports every row the projection disagrees about, by kind.

Keeping the projection equal to that answer takes more than removing rows as they
stop qualifying. When the row leaving is the newest snapshot of its key and an
older valid, unresolved snapshot survives, `DISTINCT ON` still returns the older
one, so the trigger promotes it; deleting alone would have removed a market the
board should still show. The promotion is guarded so it runs only for the
snapshot that actually owned the projection row — settlement updates every
snapshot of an event, and promoting on all of them rather than on the ten or so
that own quotes measured three times the cost for an identical result. On the
delete path the guard is the key's absence rather than the trigger's own delete,
because the foreign key cascades and usually removes the projection row first.

Profiling the result exposed a second cost that the SQL had been hiding. With the
query down to 4 ms, 955 ms of a 983 ms board build was Python, and 870 ms of that
was `method_disagreement` running all five de-vig methods on every market — 798 ms
in the power method's bisection alone. The solvers are pure functions of a price
vector returning frozen results, and a slate asks for the same vector dozens of
times: every book posts from the same short list of standard prices, the
disagreement figure runs five methods per market, and the consensus solves each
book separately. `math/devig.py` now memoizes them behind a bounded cache.

| Stage | Board load, 400,000 collected rows |
| --- | --- |
| Before | 1.6 s |
| Reading the projection instead of the history | 1.12 s |
| With the de-vig solvers memoized | 632 ms cold, **9 ms warm** |

The warm number is the one the hosted web service sees: it holds a process across
refreshes, so only the first board after a restart pays for the solves.
