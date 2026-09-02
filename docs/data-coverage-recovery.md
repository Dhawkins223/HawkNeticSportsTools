# Data Coverage Recovery

## Verified state on 2026-08-20

The production database is healthy and collection is active. A read-only audit
at 18:50 UTC measured:

| Layer | Rows | Latest data |
| --- | ---: | --- |
| Raw source payloads | 4,660 | 2026-08-20 18:45 UTC |
| Core events | 494,954 | 2026-08-20 18:43 UTC |
| Core markets | 590,291 | 2026-08-20 18:43 UTC |
| Core market observations | 591,129 | 2026-08-20 18:43 UTC |
| Sports prediction rows | 6,280 | 2026-08-20 18:29 UTC |
| Crypto prediction rows | 0 | never |
| Research model versions | 0 | never |
| Research prediction runs | 0 | never |
| Research predictions | 0 | never |
| Research metric results | 0 | never |

Kalshi ingestion, sports research, settlement, and raw retention all had fresh,
healthy worker heartbeats with zero consecutive failures. The web and database
were ready, authentication was configured, and every research-only safety flag
passed.

The platform therefore has two different states that must not be conflated:
raw/core collection is healthy, while crypto and normalized model output have
never been hosted.

## Recovery order

1. Deploy research-model-refresh to staging and verify that one cycle creates a
   baseline-only model version, feature snapshots, a completed prediction run,
   zero-edge predictions, and a sample-size coverage metric.
2. Repeat the cycle and prove the dataset hash makes it a no-op.
3. Confirm stale Kalshi source health blocks the worker rather than creating
   current rows.
4. After review and a backup/rollback gate, deploy the same reviewed commit to
   production.
5. Deploy crypto-research to staging as an independent source workflow. Do not
   make normalized research readiness depend on crypto availability.
6. Configure a licensed multi-book sports source only after the existing
   single-book data and normalized research output are visible.

## Staging readiness gate

The recovered staging services point to Postgres-GDG0, not the obsolete full
Postgres volume. At the time of this audit:

- Postgres-GDG0 used about 1.95 GB of 5 GB;
- the staging web readiness endpoint returned 200 and fresh_data_ready;
- staging had no pending migrations;
- hosted authentication was configured;
- all research-only controls passed; and
- the local PostgreSQL suite passed 470 tests.

The obsolete staging Postgres service still uses about 4.995 GB of 5 GB. It is
not an acceptable target for new workers and should not be deleted until its
ownership and recovery value are confirmed.

## Production gate

Do not create or deploy the production research worker until:

- the staging write counts and idempotent repeat are recorded;
- the exact reviewed commit is identified;
- a current production backup and tested restore are recorded;
- the production database headroom remains above the retention alert threshold;
- every hosted safety flag is still correct; and
- no secret appears in a build log, diff, or report.
