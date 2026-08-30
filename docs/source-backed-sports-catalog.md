# Source-backed sports catalog

This pipeline fills the platform's reference-data and external-market gaps in
Railway PostgreSQL. It is read-only with respect to every upstream source and
does not submit orders, upload slips, or promote models.

## Data flow

```text
Kalshi public API                       Polymarket Gamma API
  structured targets                     sports directory
  player/series stats                     sports markets and outcomes
  sports milestones                      market/sport image URLs
  event/market image URLs
            \                              /
             raw.ingestion_batches + raw.source_payloads
                              |
                              v
                    normalized core tables
                              |
                              v
                 dashboard/model queries (separate PR)
```

The collectors retain each source response before writing normalized rows.
Malformed or stale responses are recorded as rejected/blocked evidence, never
as fresh data. Provider identities remain separate; no player, team, event, or
market is matched across providers by name alone.

Player records keep Kalshi's complete `details` object, including
`player_stats` and `series_stats` when the source provides them. Changes are
stored in `core.source_entity_snapshots`. Polymarket price changes are stored in
`core.external_market_observations` and their outcomes in
`core.external_market_outcomes`; an unchanged quoted state is not duplicated on
every poll.

Image files are not copied into PostgreSQL, the repository, or a laptop.
`core.source_assets` stores the source URL, owner, observation time, and raw
payload lineage so the front end can render source-hosted assets with explicit
provenance.

## Railway services

Create two isolated worker services from the GitHub repository after the normal
backup, migration, staging, capacity, and rollback gates pass. Both services
use the Railway PostgreSQL `DATABASE_URL`; neither requires a persistent volume.

Polymarket market observations:

```sh
PYTHONPATH=src python -m kalshi_research_bot.source_catalog_worker --source polymarket
```

Kalshi reference data:

```sh
PYTHONPATH=src python -m kalshi_research_bot.source_catalog_worker --source kalshi
```

Recommended safety variables remain mandatory:

```text
RESEARCH_ONLY=true
LIVE_EXECUTION_ENABLED=false
AUTO_UPLOAD_ENABLED=false
AUTO_TRADE_ENABLED=false
KALSHI_ORDER_UPLOAD_ENABLED=false
MODEL_PROMOTION_ENABLED=false
STALE_CACHE_AS_FRESH=false
DATABASE_MIGRATION_MODE=check
```

The deployment pre-command must apply migration `0015` once before switching
the services back to `DATABASE_MIGRATION_MODE=check`.

## Bounded collection defaults

- Polymarket: two pages of 250 recently updated sports markets, hourly.
- Kalshi structured targets: one cursor page per configured player type every
  six hours; default types are basketball, football, baseball, hockey, and
  soccer players.
- Kalshi milestones: one cursor page every six hours.
- Kalshi event metadata: at most 25 event documents per cycle.
- Raw payload bodies remain governed by the existing 30-day retention worker.

The limits can be changed with `POLYMARKET_SPORTS_PAGES`,
`POLYMARKET_SPORTS_PAGE_SIZE`, `POLYMARKET_COLLECTION_CADENCE_SECONDS`,
`KALSHI_PLAYER_TARGET_TYPES`, `KALSHI_PLAYER_PAGE_SIZE`,
`KALSHI_MILESTONE_PAGE_SIZE`, `KALSHI_EVENT_METADATA_LIMIT`, and
`KALSHI_REFERENCE_CADENCE_SECONDS`. Increase them only after checking the
Railway volume and database relation census.

## What this does not claim

This foundation makes the missing data collectable and queryable. It does not
claim that a source image can be mirrored, that two source entities are the same
person, or that collected market/player data is already a validated prediction
model. Front-end panels should remain withheld until their query has fresh rows
for the requested category.
