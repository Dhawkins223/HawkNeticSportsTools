# Cloud source data

Hawknetic's source data belongs in Railway PostgreSQL. GitHub stores code and
migrations; Railway services fetch public data; PostgreSQL stores raw lineage,
normalized rows, freshness, and refresh status. A laptop is not part of the
runtime.

## Free source plan

| Source | Data used | Normal cadence | Pregame behavior |
| --- | --- | ---: | --- |
| Kalshi public market API | Current contracts and quotes | 5 minutes | Refreshed again by a queued pregame request |
| Kalshi targets, milestones, live data | Players, source stats, event links, current player stats, source image URLs | 6 hours | Current milestones are refreshed by a queued request |
| Polymarket Gamma API | Sports, teams, team logos, active markets, prices, liquidity, market images | 1 hour | Refreshed at approximately T-65, T-20, and T-5 |
| Official/public league feeds already in `sports-research` | Schedule, results, odds where the source exposes them | 1 hour | Refreshed with the pregame request |

Public availability does not mean unlimited use. The collectors keep bounded
pages, retain source timestamps, deduplicate unchanged snapshots, and back off
through the existing worker runtime. A cached or stale HTTP response is never
labeled current.

## Railway services

Use the repository's worker configuration (`railway.worker.json`) so worker
deployments do not apply migrations. The web service owns the forward-only
migration gate.

1. `KalshiMarketIngestion`
   - Existing start command: `HAWKNETIC_SERVICE=kalshi-market-ingestion python -m kalshi_research_bot service-start`
   - Persistent worker; default cadence is five minutes.
2. `SportsResearch`
   - Existing start command: `HAWKNETIC_SERVICE=sports-research python -m kalshi_research_bot service-start`
   - Persistent worker; default cadence is one hour.
3. `PolymarketCatalog`
   - Start command: `python -m kalshi_research_bot.source_catalog_worker --source polymarket --once`
   - Railway cron: `0 * * * *` (UTC).
4. `KalshiReferenceCatalog`
   - Start command: `python -m kalshi_research_bot.source_catalog_worker --source kalshi --once`
   - Railway cron: `17 */6 * * *` (UTC).
5. `SourceRefreshCoordinator`
   - Start command: `python -m kalshi_research_bot.source_refresh_worker`
   - Railway cron: `*/5 * * * *` (UTC).
   - Plans pregame refreshes, claims PostgreSQL requests, updates sources, and exits.

All five services share the same Railway `DATABASE_URL`. Catalog and refresh
services use no persistent disk. Source image URLs are stored as evidence; the
workers do not download image files onto a machine.

Railway cron has a five-minute minimum and skips a new run while the prior run
is still active. Every one-shot command above closes PostgreSQL pools and exits.

## Platform contract

Authenticated readers can use:

- `GET /api/v1/source-data` — counts, source freshness, and queue status.
- `GET /api/v1/source-data/entities` — players and teams, with filters for
  source, type, competition, and search.
- `GET /api/v1/source-data/markets` — current Polymarket markets with latest
  observations and outcomes.
- `GET /api/v1/source-data/live` — current Kalshi milestone/player data.
- `GET /api/v1/source-data/refresh/{request_id}` — refresh progress.

An administrator can use `POST /api/v1/source-data/refresh`. The endpoint only
queues work in PostgreSQL and returns `202`; it never performs source requests
inside the web process. It requires the normal authenticated session, CSRF
token, JSON content type, and `X-Research-Action: queue-source-refresh`.

Every read route enforces a maximum source age. Empty or stale collections are
reported as empty instead of being presented as current.

## Deployment gate

Do not activate these services until the normal database gate passes:

1. Confirm the Railway PostgreSQL volume has safe headroom and a restorable backup.
2. Apply migration `0016_cloud_source_refresh.sql` through the web migration owner.
3. Verify staging `/readyz` and run each collector once with bounded pages.
4. Confirm `ops.source_refresh_requests`, `ops.worker_status`, and source-health rows advance.
5. Verify the source-data panel shows fresh rows and stale rows disappear when the age gate is exceeded.
6. Keep rollback to the prior web release available. The migration is additive;
   rollback disables the new services and routes without deleting collected data.

This remains research-only. The refresh queue cannot place orders, upload slips,
promote a model, or connect a betting account.
