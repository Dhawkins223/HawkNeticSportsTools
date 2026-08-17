# Sports Data Upload

## The gap this closed

Production used to run two services in the `jubilant-liberation` project: the web
dashboard (`HAWKNETIC_SERVICE=web`) and Kalshi collection
(`HAWKNETIC_SERVICE=kalshi-market-ingestion`). No sports worker ran there, so
`app.sports_prediction_logs` received nothing in the hosted database and the
dashboard could not show sports at all.

`SportsResearchProduction` and `RawRetentionProduction` now run alongside them,
and sports rows are arriving hourly. See "Production status" below for the
measured cycles.

`crypto-research`, `settlement-worker`, and `external-source-ingestion` remain
undeployed and are in the position sports was: supported worker roles whose
tables receive nothing hosted. They follow the same deployment shape, each behind
its own readiness gate.

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

## Closing line value

`app.sports_prediction_logs` has carried `closing_line` and `clv` columns since
the first migration, and nothing wrote them.
`src/kalshi_research_bot/sports_clv.py` now does.

Once a game starts, the last price posted before kickoff becomes that market's
close. Every earlier row in the same `(event_id, market_type, selection, line)`
series is graded against it, so the comparison never borrows another market's
number. Rows quoted after kickoff are excluded — a live price is not a closing
line.

CLV is stated in probability points and is positive when the taken price implied
*less* probability than the close, meaning the market moved toward that side
after the row was recorded. The capture is idempotent: a repeat run recomputes
the same values and updates nothing, and a quote collected closer to kickoff
supersedes an earlier close.

The sports-research worker runs the capture every cycle and reports
`closing_lines_recorded` and `markets_closed` in its worker metrics. Operators
can also run it directly:

```bash
PYTHONPATH=src python -m kalshi_research_bot sports-clv --run-id <run>
PYTHONPATH=src python -m kalshi_research_bot sports-clv --report-only
```

`GET /sports-clv.json` returns the same report, and the dashboard's sports panel
shows graded rows, beat/lost/matched counts, beat rate, and average CLV broken
down by market and book.

This is a price comparison and nothing more. It needs no settled outcome, so it
stays inside the research-only contract, and it is not profit, not a settled
result, and not evidence that a model is validated or profitable.

## Deploying a collector worker

This is the shape every remaining collector follows. It is a hosted change and
requires the readiness gate in `docs/deployment-readiness-checklist.md`. Do not
create the service as a side effect of a code change.

1. Verify in `staging` first where that environment is usable, against the
   staging PostgreSQL service, never production credentials.
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

4. Set the service's config-as-code path to `railway.worker.json`. The
   repository-root `railway.json` carries the web service's pre-deploy migration
   and Railway applies it to every service built from the repository; a worker
   inheriting it runs migrations on each deploy and cannot deploy at all while
   the database is unavailable. Migrations belong to the web service, and the
   worker runs with `DATABASE_MIGRATION_MODE=check`.
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

   SELECT COUNT(*) FILTER (WHERE clv IS NOT NULL) AS graded,
          COUNT(*) FILTER (WHERE clv IS NULL) AS awaiting_close
   FROM app.sports_prediction_logs
   WHERE validation_status = 'valid';
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

## Source identification

Collection identifies itself with `connectors.http.DEFAULT_USER_AGENT`, which
names the project and carries a contact URL. Do not replace it with a browser
string: ESPN reproducibly returns 403 to the spoofed agent and 200 to the honest
one, and the robots handling in `connectors/` assumes the client identifies
itself truthfully.

The ESPN summary endpoint exposes a single bookmaker, so no-vig figures are
available but cross-book line shopping is not. Set `THE_ODDS_API_KEY` for
multi-book quotes; it is already first in `SPORTS_RETRIEVAL_PLAN`.

## Staging status

`SportsResearchStaging` is deployed but cannot write: the staging PostgreSQL
volume is full and the server is refusing connections. It needs a volume resize
before it is usable again. See `docs/staging-sports-worker-verification.md`.

## Production status: data is flowing

`SportsResearchProduction` and `RawRetentionProduction` are deployed in the
production environment, both on `railway.worker.json`, both research-only.

Five consecutive hourly cycles from 2026-08-16 21:08Z:

| Cycle | Logged | Rejected | Closing lines | Settled | Pending |
| --- | ---: | ---: | ---: | ---: | ---: |
| 21:08 | 6 | 84 | 12 | 0 | 48 |
| 22:08 | 6 | 84 | 0 | 0 | 54 |
| 23:08 | 6 | 84 | 0 | 24 | 36 |
| 00:09 | 38 | 0 | 30 | 0 | 74 |
| 01:09 | 46 | 0 | 0 | 0 | 120 |

Collection, validation, storage, settlement, and closing-line grading are all
live. `closing_line` and `clv`, unwritten since the first migration, now carry
values.

The early cycles rejecting 84 of 90 rows is the pre-game gate doing its job:
those cycles landed after that evening's games had started, so their prices were
no longer pre-game. The later cycles picked up the next unstarted slate and
rejected nothing.

One known gap: `data_fresh_at` and `source_fresh_at` log as null for sports, so
`ops.worker_status` does not show source freshness for this worker. The board
computes freshness from the rows themselves, so nothing is misreported, but the
worker-status view is missing a signal it shows for other collectors.
