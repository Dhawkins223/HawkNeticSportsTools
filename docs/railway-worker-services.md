# Hosted Worker Services

The web service runs the dashboard only. Configure existing worker entry points independently for Kalshi ingestion, external sources, crypto research, sports research, settlement, and reporting as reliability needs require.

Every worker uses PostgreSQL-backed idempotency, heartbeat, failure counts, source freshness, bounded retry/backoff, structured logs, graceful shutdown, and transactional checkpoints. A failure in one worker must not alter records owned by another worker or stop the web service.

Do not start workers from a migration pre-deploy command. Optional connector failures appear in worker status and block only their dependent workflow.

## Surviving a transient database error

A worker's per-cycle bookkeeping — claiming ownership and recording the outcome — runs outside the operation's own retry loop, so a PostgreSQL connection dropped there is not an operation failure and is not retried by the operation. Left unhandled it ends the process, which is how a momentary blip turns into a permanently stopped collector: `KalshiIngestionStaging` crashed exactly this way with `psycopg.OperationalError: the connection is lost`.

`run_worker_forever` now absorbs a crashed cycle, logs `worker_cycle_crashed` with the error code and the consecutive-crash count, and retries on the next tick. After three consecutive crashes the connection pool is dropped, because a pool holding broken connections keeps failing the same way. A cycle that completes clears the streak.

Backoff doubles from `initial_backoff_seconds` until it reaches the worker's own cadence, then holds there. A database that stays down is never retried faster than the worker would have run anyway:

| Worker | Cadence | Retry schedule (seconds) |
| --- | ---: | --- |
| `kalshi-market-ingestion` | 300 | 2, 4, 8, 16, 32, 64, 128, 256, then 300 |
| `sports-research` | 3600 | 2, 4, 8, …, 1024, 2048, then 3600 |
| `reporting-evaluation` | 21600 | 2, 4, 8, …, 8192, 16384, then 21600 |

The first version of this capped the *exponent* at four steps rather than clamping the delay, which pinned an hourly worker to a 16-second retry. Against a staging database stuck in recovery that produced over eleven hundred crash cycles. Clamp the delay by the cadence; bound the exponent only to keep the arithmetic sane.

This does not mask failures. An operation that fails is still recorded through the existing failure path, still increments `consecutive_failures`, and still alerts. Only the loop's survival changed.

Production currently runs only the web service and `kalshi-market-ingestion`. The sports, crypto, settlement, external-source, and reporting workers are not deployed, so their tables receive no hosted rows. `docs/sports-data-upload.md` documents the readiness-gated steps for the sports worker and the states its board reports while it settles.
