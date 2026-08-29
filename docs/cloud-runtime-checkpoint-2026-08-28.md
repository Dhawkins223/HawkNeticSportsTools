# Cloud Runtime Checkpoint — 2026-08-28 ET

This is the latest verified hosted-runtime record for `Dhawkins223/HawkNeticSportsTools`.
It supersedes older hosted claims, not their historical research or design notes.
Re-run the checks below before any hosted change because GitHub and Railway can move independently.

## Evidence boundary

- GitHub and Railway were inspected read-only on 2026-08-28 ET / 2026-08-29 UTC.
- Production PostgreSQL was queried read-only through Railway.
- No service, variable, database row, schedule, or volume was changed.
- `HawkNetic Office` is outside this repository and outside this checkpoint.

## GitHub coordination

- `Master`: `0b1cd722a1d87209580741b9cb5e14a00db04aa1`
- Latest PostgreSQL validation: success, 815 tests.
- Open pull requests: none.
- The active Claude-named branches were all zero commits ahead of `Master` at inspection time.
- PRs 77-80 already contain the design-system dashboard rebuild and the correlation-aware slip engine. Do not recreate those changes in another branch.

## Railway production release matrix

Railway project: `jubilant-liberation` (`dfc58505-d45f-4093-8050-35f5371bbf37`).
The CLI enumerated one active environment, `production`.

| Service | Deployment source | Live revision | Drift from Master |
| --- | --- | --- | ---: |
| `SettlementWorkerProduction` | GitHub `Master` | `0b1cd722` | current |
| `SportsResearchProduction` | GitHub `claude/data-upload-gstack-xu2lgq` | `16bfe70e` | 30 commits behind |
| `RawRetentionProduction` | GitHub `claude/data-upload-gstack-xu2lgq` | `16bfe70e` | 30 commits behind |
| `HawkNeticSportsTools` web | manual CLI upload | `d82e0d0d` by deployment message | 54 commits behind |
| `KalshiIngestionProduction` | manual CLI upload | `62c32600` by deployment message | 86 commits behind |
| `Postgres-gxQB` | Railway PostgreSQL 18 image | managed image | not applicable |

The web service returned `200` for `/healthz` and `/readyz`. Readiness reported PostgreSQL healthy, no pending migrations, authentication required and configured, and every research-only safety control passing. Protected application routes returned `401` without credentials as expected.

## Worker scheduling and observed activity

These services do not use Railway cron schedules. They are always-on processes whose `WorkerSpec` cadence drives an internal loop.

| Worker | Intended cadence | Latest observed successful work |
| --- | ---: | --- |
| Kalshi ingestion | 5 minutes | 258 received and accepted; fresh at 2026-08-29 03:22:48 UTC |
| Sports research | 1 hour | 708 processed; fresh at 2026-08-29 02:58:15 UTC |
| Raw retention | 1 hour | 25 rows processed in the latest observed cycle |
| Settlement | worker cadence | successful after deploying current `Master`; zero rows required settlement |

A healthy heartbeat proves that a worker ran. It does not prove that every desired source or player category exists.

## PostgreSQL data reality

At inspection time:

- Logical database size: about 3,384 MB.
- Railway volume allocation: about 3,830 MB of 5,000 MB (roughly 77%).
- Largest relations: `raw.source_payloads` 1,553 MB, `core.markets` 829 MB, `core.events` 549 MB, and `core.market_observations` 192 MB.
- Retained raw sources were only `kalshi_public_api`, `espn_scoreboard`, and `espn_summary`.
- `app.source_records` had no rows.
- No table or column represented a canonical player/athlete, roster, injury, lineup, player image/photo, or Polymarket dataset.

Adding high-volume sources before proving restore capability and storage headroom would violate the deployment checklist.

## Polymarket and player-data gap

`connectors/polymarket.py` and its tests exist. The connector can fetch and normalize public Gamma market data, but production has no Polymarket collector, retained payload, normalized table, or cross-venue entity mapping. `cross_venue_gaps` deliberately requires an explicit match; backlog E-49 entity resolution remains unsolved.

`external-source-ingestion` also exists as a worker specification, but it is not deployed. Its example configuration contains Kalshi, RSS, and web-page examples rather than a Polymarket ingestion pipeline.

Player-facing screens cannot become source-backed until the platform has canonical teams, players, rosters, availability/injuries, statistics, source assets, and point-in-time identity mappings. Images must retain their source URL and usage/provenance evidence; an available URL is not automatically permission to mirror the file.

## Remaining hard gates

Before aligning or expanding production services:

1. Create and validate a real staging environment.
2. Record a current backup and prove restoration outside production.
3. Review volume capacity, retention, and the growth of `core.events` and `core.markets`.
4. Restrict deployment triggers and use reviewed release revisions with per-service configuration.
5. Run migration, readiness, worker-smoke, secret-scan, and research-safety gates in staging.
6. Promote the exact reviewed revision; do not rebuild or upload from a parallel Windows/OneDrive checkout.

## Coordination check before new work

Before opening a branch or changing a hosted service, record:

1. current `Master` SHA and latest CI result;
2. open pull requests and branches with commits ahead of `Master`;
3. the Railway revision and config path for every affected service;
4. the target database, migration state, backup/restore evidence, and volume headroom; and
5. the files already modified in the canonical Linux checkout.

If another branch or dirty worktree owns the same files or responsibility, preserve it and choose a non-overlapping workstream.
