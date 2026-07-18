# Database and Collection Handoff

## Current architecture

- Local development: Docker-managed PostgreSQL only.
- Tests: isolated PostgreSQL database with the same migrations.
- Staging: separate hosted PostgreSQL service when provisioned.
- Production: separate hosted PostgreSQL service; unchanged until readiness gates pass.

## Collection lifecycle

1. Create an immutable ingestion batch.
2. Acquire the worker’s coarse ownership boundary.
3. Request fresh data with bounded retries and backoff.
4. Store raw evidence and its deterministic hash.
5. Validate and normalize records transactionally.
6. Retain rejected records with an exact reason.
7. Advance a checkpoint only after the writes commit.
8. Update source health and worker status.

Fresh, stale, historical, blocked, failed, and missing are explicit states. A stale cache is never current data. The pipeline retains evidence and rejects malformed content; it does not fabricate data.

## Integrity rules

- Prediction features, model versions, and outcomes remain separate and traceable.
- Exact prices and probabilities retain decimal precision in storage.
- Performance queries exclude rejected, unresolved, blocked, invalid-settlement, stale-source, test-fixture, and duplicate rows.
- Raw prediction records are preserved; exposure-adjusted portfolio accounting is explicit.
