# Hosted Worker Services

The web service runs the dashboard only. Configure existing worker entry points independently for Kalshi ingestion, external sources, crypto research, sports research, settlement, and reporting as reliability needs require.

Every worker uses PostgreSQL-backed idempotency, heartbeat, failure counts, source freshness, bounded retry/backoff, structured logs, graceful shutdown, and transactional checkpoints. A failure in one worker must not alter records owned by another worker or stop the web service.

Do not start workers from a migration pre-deploy command. Optional connector failures appear in worker status and block only their dependent workflow.
