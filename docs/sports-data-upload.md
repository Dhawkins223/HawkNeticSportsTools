# Sports Data Upload

## Current gap

Production runs two services in the `jubilant-liberation` project: the web
dashboard (`HAWKNETIC_SERVICE=web`) and Kalshi collection
(`HAWKNETIC_SERVICE=kalshi-market-ingestion`). Kalshi collection is healthy and
uploads roughly 200-240 market observations every five minutes.

No sports worker runs there. `sports-research` is a supported worker role and
its pipeline is complete locally, but because it is not deployed,
`app.sports_prediction_logs` receives nothing in the hosted database. Crypto,
settlement, external-source, and reporting workers are in the same position.

The consequence is narrow and specific: the hosted dashboard cannot show sports
because no sports rows have ever been uploaded to it.

## What the read side now expects

`src/kalshi_research_bot/sports_board.py` reads what the worker uploads:

- Rows come from `app.sports_prediction_logs` where `validation_status = 'valid'`
  and `settlement_state = 'unresolved'`, restricted to games that have not
  started.
- `DISTINCT ON (event_id, market_type, selection, line, bookmaker)` keeps the
  most recent snapshot of each posted price, so re-collecting the same market
  every cycle contributes one current row rather than one row per cycle.
- Freshness is judged on `MAX(api_fetched_at)` across all valid sports rows and
  on `ops.source_health` for the sports sources. The board reports exactly one
  of `fresh`, `stale`, `blocked`, `empty`, or `unavailable`, and withholds rows
  in every state except `fresh`.
- Prices stay `NUMERIC` in storage and are serialized as fixed-point decimal
  strings, never binary floats.

The derived numbers are market observations only. No-vig probabilities and best
posted prices carry `model_state = baseline_only` and
`decision_status = track_only`, matching `docs/probability-and-decision-policy.md`.
They are not a validated model edge and never a betting recommendation.

## Deploying the sports worker

This is a hosted change and requires the readiness gate in
`docs/deployment-readiness-checklist.md`. Do not create the service as a side
effect of a code change.

1. Verify staging first. Create the worker in the `staging` environment of
   `jubilant-liberation` against the staging PostgreSQL service, never
   production credentials.
2. Create a service from this repository with the start command:

   ```text
   HAWKNETIC_SERVICE=sports-research PYTHONPATH=src python -m kalshi_research_bot service-start
   ```

3. Set the worker's variables. It needs database access and the research-only
   controls, and nothing else the web service holds:

   ```text
   HAWKNETIC_SERVICE=sports-research
   DATABASE_URL=<the same PostgreSQL service the web app reads>
   DATABASE_MIGRATION_MODE=check
   SPORTS_SOURCE_MODE=scraper
   SPORTS_SCRAPER_ENABLED=true
   SPORTS_RETRIEVAL_PLAN=official_api,http_json,firecrawl
   SPORTS_RUN_ID=<a stable run identifier>
   RESEARCH_ONLY=true
   LIVE_EXECUTION_ENABLED=false
   AUTO_TRADE_ENABLED=false
   AUTO_UPLOAD_ENABLED=false
   KALSHI_ORDER_UPLOAD_ENABLED=false
   MODEL_PROMOTION_ENABLED=false
   STALE_CACHE_AS_FRESH=false
   ```

   `THE_ODDS_API_KEY` is optional. Without it the retrieval plan falls back to
   the public ESPN scoreboard and summary endpoints.

4. Do not give the worker a migration pre-deploy command. Migrations belong to
   the web service, and the worker runs with `DATABASE_MIGRATION_MODE=check`.
5. Confirm the worker writes before pointing anyone at the dashboard:

   ```sql
   SELECT COUNT(*), MAX(api_fetched_at)
   FROM app.sports_prediction_logs
   WHERE validation_status = 'valid';

   SELECT source, freshness_state, last_successful_at, last_error
   FROM ops.source_health
   WHERE source IN ('espn_scoreboard', 'the_odds_api', 'sports_source');

   SELECT worker_name, status, consecutive_failures, last_error_code, heartbeat_at
   FROM ops.worker_status
   WHERE worker_name = 'sports-research';
   ```

6. Check the board from the web service. `GET /sports.json` returns the full
   board and `GET /sports.json?detail=summary` returns counters only. Both
   require an authenticated session.

## Expected states while the worker settles

A newly deployed worker does not produce a `fresh` board immediately, and each
non-fresh state has a specific meaning:

| `board_state` | Meaning | Action |
| --- | --- | --- |
| `unavailable` | No valid sports rows exist in this database. | Confirm the worker is deployed and pointed at the right `DATABASE_URL`. |
| `blocked` | A sports source reported `blocked` or `failed` health. | Read `last_error` in `ops.source_health`; a blocked public source is not a code defect. |
| `stale` | The newest upload is older than the one-hour window. | Check the worker heartbeat and `consecutive_failures`. |
| `empty` | The collector is fresh but no upcoming game has usable odds. | Normal off-hours and between slates. |
| `fresh` | Rows are current and shown. | None. |

A blocked or empty sports source must not affect Kalshi or crypto metrics, and
never fabricates rows.

## Remaining installments

The sports worker is the first of the missing collectors. `crypto-research`,
`settlement-worker`, `external-source-ingestion`, and `reporting-evaluation`
follow the same deployment shape, each behind its own readiness gate.
