# Railway Worker Service Plan

This document prepares independent services. It does not deploy or modify the current Railway service.

## Dependency Order

1. Confirm Git deployment branch and protected review flow.
2. Provision PostgreSQL and complete the validated import.
3. Configure the web service with hosted authentication.
4. Start Kalshi ingestion and settlement workers.
5. Start crypto and sports workers independently.
6. Start external-source ingestion only when its source config exists.
7. Start reporting/evaluation last.

A worker failure must not terminate any other service.

## Services

| Service | Startup command | Cadence | Primary responsibility |
|---|---|---:|---|
| Web | `python -m kalshi_research_bot paper --host 0.0.0.0 --port $PORT --refresh-seconds 0` | continuous | authenticated review dashboard only |
| Kalshi ingestion | `python -m kalshi_research_bot worker --service kalshi-market-ingestion` | 5 min | public market/schedule snapshots |
| External sources | `python -m kalshi_research_bot worker --service external-source-ingestion` | 15 min | configured public sources only |
| Crypto research | `python -m kalshi_research_bot worker --service crypto-research` | 15 min | Coinbase/Kraken collection, logging, settlement, reports |
| Sports research | `python -m kalshi_research_bot worker --service sports-research` | 60 min | scraper-first public odds/results research |
| Settlement | `python -m kalshi_research_bot worker --service settlement-worker` | 60 min | official Kalshi settlement imports |
| Reporting/evaluation | `python -m kalshi_research_bot worker --service reporting-evaluation` | 6 hours | reports, return decomposition, monitoring alerts |

Use `--once` for smoke tests. Each worker records an idempotency key, attempt/success timestamps, consecutive failures, retry/backoff results, processed rows, backlog, and heartbeat in the database. `SIGINT` and `SIGTERM` request graceful shutdown.

## Shared Required Variables

```text
PYTHONPATH=src
DATABASE_BACKEND=postgres
DATABASE_URL=<Railway reference variable>
DATABASE_POOL_MIN_SIZE=1
DATABASE_POOL_MAX_SIZE=5
DATABASE_MIGRATION_MODE=check
KALSHI_ORDER_UPLOAD_ENABLED=false
```

All application services use PostgreSQL. Do not configure a SQLite runtime volume or a SQLite fallback. The only SQLite path is the explicit read-only archive/import tooling.

## Per-Service Variables

- Web: `DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED=true`, one configured auth mode, `DASHBOARD_MAX_SLIP_AGE_SECONDS`.
- Kalshi/settlement: `KALSHI_RUN_ID`; public API safety variables.
- Crypto: `CRYPTO_RUN_ID`; no paid key is required for current public Coinbase/Kraken sources.
- Sports: `SPORTS_RUN_ID`, `SPORTS_SOURCE_MODE`, `SPORTS_SCRAPER_ENABLED`, and either a working public scraper source or an optional odds API key.
- External: `EXTERNAL_SOURCES_CONFIG`; absent config is `unconfigured_optional`.
- Alerts: `SLACK_ALERTS_ENABLED` and `SLACK_WEBHOOK_URL` are optional.

## Health and Monitoring

- Public liveness: `/healthz`.
- Web data readiness: `/readyz`.
- Admin-only operations view: `/internal/status.json`.
- Admin-only manual instruction inbox: `/ops` and `/internal/operator-messages.json`.
- CLI view: `python -m kalshi_research_bot worker-status`.
- Worker health is database-backed and includes last attempt, last success, heartbeat age, consecutive failures, stale data/source state, model state, and settlement backlog.
- Slack alerts are deduplicated and limited to actionable anomalies.

## Failure Isolation

- Idempotency prevents duplicate cadence runs.
- PostgreSQL transactions, row-level constraints, and unique keys protect multi-service claims.
- A source failure produces a failed worker state and does not mutate settled metrics.
- A zero-row run is a failure only when records were expected; explicit `no_material_change` remains healthy.
- Optional connector failures remain nonblocking.
- Operator messages are never worker inputs and cannot execute code, deployments, account actions, or trades.

## Do Not Deploy Yet

This branch must receive isolated staging validation before a worker service is deployed. Railway production watches `Master` and remains frozen until the current PostgreSQL runtime, backup, restore, and PR gates pass. Do not create or enable a SQLite worker service.
