# Staging Sports Worker Verification

Record of the first `sports-research` deployment, run in staging only. Production
was not changed.

## What was deployed

| Field | Value |
| --- | --- |
| Project | `jubilant-liberation` |
| Environment | `staging` |
| Service | `SportsResearchStaging` |
| Source | `Dhawkins223/HawkNeticSportsTools`, branch `claude/data-upload-gstack-xu2lgq` |
| Start command | `PYTHONPATH=src python -m kalshi_research_bot service-start` |
| `HAWKNETIC_SERVICE` | `sports-research` |
| Database | staging `Postgres` service reference, not production |
| Restart policy | `ON_FAILURE`, 10 retries |

Research-only controls were set explicitly on the service: `RESEARCH_ONLY=true`
and `LIVE_EXECUTION_ENABLED`, `AUTO_TRADE_ENABLED`, `AUTO_UPLOAD_ENABLED`,
`KALSHI_ORDER_UPLOAD_ENABLED`, `MODEL_PROMOTION_ENABLED`, `STALE_CACHE_AS_FRESH`
all false.

The deployment succeeded, migrations reported `ready: true` with no pending
versions, and the worker started on its 3600s cadence.

## Blocking finding: the staging database volume is full

The first collection cycle failed while writing:

```text
DiskFull: could not extend file "base/16384/16996": No space left on device
HINT:  Check free disk space.
```

Staging `Postgres` disk usage has been flat at its ceiling for at least 24
hours — minimum 4.966 GB, maximum 4.9948 GB, current 4.9948 GB. The volume is
full, not filling.

This also explains `KalshiIngestionStaging`, which has been `CRASHED` since
2026-08-14 with `psycopg.OperationalError: the connection is lost`. That is what
a full-disk PostgreSQL looks like from the client side. It was not a transient
network blip.

**No sports rows can be written to staging until the volume has free space.**
Verification of the upload path is blocked on that, and only on that.

## Production is on the same trajectory

Production `Postgres-gxQB` disk usage over the last seven days:

| Measure | Value |
| --- | --- |
| Seven days ago | 1.128 GB |
| Current | 2.755 GB |
| Growth | roughly 230 MB per day |

If the production volume is the same size as staging, it has on the order of ten
days before it reaches the same ceiling. When it does, Kalshi ingestion stops the
same way staging did, and that is currently the platform's only working feed.

This needs an owner decision — raise the volume, or add retention for the
highest-volume relations. `raw.source_payloads` holds a full payload per
collection cycle and Kalshi ingestion runs every five minutes, so it is the
first place to look.

## Secondary finding: retry after a partially written batch

With the disk full, the first attempt failed mid-write after the ingestion batch
row already existed. The two retries then failed with:

```text
RuntimeError: ingestion_batch_content_conflict
```

The batch's idempotency key was already taken, and the recollected payload
hashed differently, so the retry could not proceed. Under a healthy disk this
path is not exercised, and the conflict is the ledger correctly refusing to
overwrite recorded evidence rather than a data-integrity failure. It is worth
revisiting so a retry after a partial write can resume rather than conflict.

## What the fix under test did do

The worker did not die. It recorded `worker_failed` with
`consecutive_failures: 2`, kept its process alive, and stayed scheduled for the
next cycle — which is the behaviour the crashed staging Kalshi worker lacked.

## Next steps

1. Free space on the staging volume, or raise it.
2. Let one sports cycle complete and confirm `app.sports_prediction_logs`
   receives rows and `ops.source_health` reports a real state for
   `espn_scoreboard`.
3. Confirm the board reports `fresh` rather than `unavailable`.
4. Only then consider the production worker, per
   `docs/deployment-readiness-checklist.md`.

Whether ESPN serves Railway's egress is still unverified — the cycle never got
far enough to record source health. From the development sandbox ESPN returns
403 to repeated requests, including for `robots.txt`, which reads as egress-level
throttling rather than a user-agent rule. If Railway is throttled the same way,
the supported alternative is already first in `SPORTS_RETRIEVAL_PLAN`: set
`THE_ODDS_API_KEY` and the official API path is used before any scraping.
