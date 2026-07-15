# Competitive Platform Architecture

Status: Phase 0 target architecture. This extends the existing repository; it does not define a replacement platform.

## Technical summary

The correct architecture is one application with explicit boundaries, not a network of speculative microservices. SQLite remains a supported local runtime. PostgreSQL becomes the hosted source of truth only after one business-store contract serves web, workers, reporting, auth, crypto, sports, and settlement paths. Railway hosts staging and production processes; it does not own business logic.

```text
Approved source providers
        |
        v
Source adapters and immutable evidence
        |
        v
Validation, identity mapping, and freshness
        |
        v
Canonical events, markets, selections, and quotes
        |
        v
Probability and opportunity engines
        |
        v
Reporting/API contract
        |
        v
Existing responsive frontend
```

## Existing boundaries to preserve

- `paper_server.py`: current HTTP and server-rendered frontend.
- `worker_services.py` and `worker_runtime.py`: isolated deterministic jobs.
- `connectors/`: source-specific retrieval and lifecycle helpers.
- `storage.py`: current SQLite business store.
- `database.py`, `db_migrations.py`, and `postgres_migration.py`: database configuration, migration, and compatibility transfer.
- `evaluation/`: prediction, settlement, metrics, validation, and audit logic.
- `slip_safety.py`, `combo_safety.py`, and `review_packet.py`: manual-review integrity.
- `auth.py`: roles, sessions, CSRF, lockout, and audit.

## Application boundary

Use one explicit store interface with SQLite and PostgreSQL implementations. Application services receive that interface; routes and workers do not instantiate a concrete database directly.

```text
HTTP routes / CLI / worker runtime
             |
             v
Application services and domain policies
             |
             v
BusinessStore contract
        /             \
SQLiteBusinessStore   PostgresBusinessStore
```

The contract must cover current business behavior before adding new competitive tables. It must use exact transactions, explicit rollback, bounded pools, timeouts, deterministic identifiers, idempotent writes, and stable error codes.

## Data model

Hosted PostgreSQL keeps these schemas:

| Schema | Responsibility |
|---|---|
| `raw` | ingestion batches, immutable payloads, retained rejects |
| `core` | canonical sports/league/team/player/event/market/selection identities, provider mappings, quotes, scores, settlements |
| `research` | model versions, frozen features, predictions, outcomes, opportunities, simulations, correlation, exposures, metrics |
| `ops` | worker runs, source health, checkpoints, backfills, quality, audit, report refreshes |
| `reporting` | controlled read models that repeat metric exclusions at the database layer |
| `auth` | hosted users, sessions, roles, and entitlements after reviewed migration |

Use `TIMESTAMPTZ` and exact `NUMERIC`. Keep identity and append-only history relational. JSON is limited to raw payloads, frozen vectors, provider metadata, and versioned calculation configuration.

## Source registry and mapping

Every source record uses one controlled status:

```text
official_api
licensed_aggregator
permitted_public_endpoint
permitted_html
operator_supplied
optional
disabled
blocked_terms
blocked_authentication
blocked_technical
deprecated
```

No provider row is considered approved merely because a connector works.

Explicit mappings are required for provider event, team, player, market, and selection identities. Each mapping stores status, confidence, method, timestamps, evidence, reviewer, and rejection reason. Low-confidence or unresolved mappings cannot enter best-line, EV, arbitrage, prediction, or combo calculations.

## Worker topology

Start with grouped processes, not one Railway service per task:

| Process group | Jobs | Initial cadence |
|---|---|---|
| Web/API | authenticated pages, read APIs, SSE later | continuous |
| Market ingestion | Kalshi and licensed sportsbook odds | source-specific; measured |
| Context ingestion | schedules, scores, injuries, lineups, weather | 5-60 minutes by source |
| Research processing | normalization, fair price, opportunities, combo candidates | event-driven or bounded polling |
| Settlement/reporting | outcomes, closing lines, metrics, reports | 15 minutes to 6 hours |
| Browser collection | permitted public pages only | isolated, low rate, optional |

Every run records worker version, deployment commit, source, sport/league, source and receipt times, counts, checkpoints, freshness, error code, and duration. Checkpoints advance only in the transaction that commits accepted records.

## API and real-time delivery

Preserve the existing routes while introducing versioned JSON endpoints behind the contract in `docs/backend-api-contract.md`. Prefer server-sent events for one-way quote/opportunity updates. Do not hold database transactions open for streams. Every event includes an ID, source cutoff, generated time, hard expiry, and calculation version.

## Cache policy

Do not add Redis until a measured hot path justifies it. When added, use it only for latest odds, best-line lookup, active opportunities, short-lived summaries, request rate limiting/deduplication, stream fanout, and alert suppression. PostgreSQL remains authoritative. Every cache entry has a version, source cutoff, generated time, hard expiry, and freshness state.

## Frontend boundary

Keep the existing frontend and progressively separate templates, styles, and scripts only when a tested change needs it. The customer surface exposes live odds, opportunities, predictions, combos, tracker, alerts, and research. Operator quality, worker, connector, migration, and diagnostic detail stays under authenticated operator routes.

Desktop uses dense tables and persistent filters. Mobile uses purpose-built rows/cards with the same evidence and status semantics. Current, loading, stale, blocked, empty, and error states are explicit.

## Security boundary

- Server-side authentication, role, entitlement, and CSRF enforcement.
- Secure hosted cookies, expiry, lockout, disabled accounts, and audit.
- Least-privilege database roles and private PostgreSQL/Redis networking.
- No secrets, URLs with credentials, auth headers, cookies, or raw private payloads in logs.
- No sportsbook credentials or wagering account access.
- No live execution, order creation, staging, upload, or auto-trading.

## Railway staging and production

Railway staging is the only deployment target during this program. The staging web service may watch `codex/competitive-sports-intelligence` after OAuth authorization and branch publication. Production continues to watch `Master` and remains unchanged.

No independent hosted workers start until PostgreSQL business-runtime parity passes. No production cutover occurs until backup/restore evidence, credential rotation, hosted auth, provider rights, load/security tests, and reviewed PR gates pass.

## Failure behavior

- Optional provider outage: affected data becomes stale, blocked, or unavailable.
- Required provider outage: relevant workflow readiness fails; unrelated workflows continue.
- PostgreSQL unavailable: hosted readiness fails; no silent SQLite fallback.
- Redis unavailable: bypass cache or degrade noncritical delivery; never lose source-of-truth data.
- Mapping uncertain: reject with evidence; never force the join.
- Quote expired: invalidate the opportunity and remove it from live review.

## Next implementation boundary

Implement the business-store contract and PostgreSQL query parity before adding competitive product modules. That is the smallest change that unlocks safe Railway workers, normalized reporting, and later odds history without creating dual-write ambiguity.

