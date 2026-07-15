# Backend Architecture Audit

Audit date: 2026-07-13. Scope: existing repository only.

## Technical summary

The backend is a compact Python application with a standard-library threaded HTTP server, CLI commands, deterministic workers, SQLite research storage, additive PostgreSQL migrations, source connectors, and evaluation modules. The architecture is workable for the current private system. Its main constraint is not framework choice; it is concrete SQLite coupling and the concentration of rendering, routing, refresh behavior, and embedded frontend assets in `paper_server.py`.

A backend rewrite is not justified. Introduce interfaces at the database, application-service, and API response boundaries, then move behavior incrementally with tests.

## Current structure

| Layer | Existing modules | Assessment |
|---|---|---|
| HTTP and rendering | `paper_server.py` | Functional, authenticated, and health-aware; too many responsibilities in one file |
| CLI | `cli.py`, `__main__.py` | Broad operator surface; useful and should remain the automation contract |
| Worker orchestration | `worker_services.py`, `worker_runtime.py`, `daemon.py` | Good cadence/idempotency/retry/graceful-shutdown base |
| Source adapters | `connectors/`, `agents/scrape_bot.py`, `today.py` | Clear safety direction; source-specific normalization still leaks into research modules |
| Domain safety | `slip_safety.py`, `combo_safety.py`, `review_packet.py` | Strong fail-closed Kalshi combinability boundary |
| Research logic | `crypto_research.py`, `sports_research.py`, `private_research.py`, `evaluation/` | Rich behavior but large modules mix schema, SQL, validation, settlement, reporting, and export |
| Storage | `storage.py`, direct SQLite connections, `database.py` | Main architectural blocker; PostgreSQL pool is not the business store |
| Authentication | `auth.py`, route checks in `paper_server.py` | Good local controls; hosted persistence/recovery needs completion |
| Operations | `monitoring.py`, `source_quality.py`, connectors lifecycle | Strong separation of quality, source health, and deployment readiness |

## Strengths to preserve

- one repository and one backend;
- explicit CLI commands used by scripts and workers;
- deterministic hashes and idempotency keys;
- strict stale-source behavior;
- structured rejection reasons;
- settlement and outcome separation in the target PostgreSQL model;
- local roles, sessions, CSRF, lockout, and audit;
- `/healthz` and `/readyz` separation;
- research-only flags and no-execution controls;
- failure isolation across worker services;
- manual-review exact-combo integrity.

## Architectural risks

### SQLite coupling blocks hosted scale

Routes, workers, reporting, auth, monitoring, sports, crypto, and settlement access SQLite directly or through `ResearchStore`. Multiple Railway replicas or worker services cannot safely share that local database.

### `paper_server.py` is an integration bottleneck

The module owns authentication routes, operator routes, public routes, payload loading, refresh coordination, prediction logging, readiness, HTML rendering, CSS, and JavaScript. Changes are testable today, but feature growth will increase regression risk.

### Research modules own too many layers

`sports_research.py` and `crypto_research.py` contain collection, schema management, normalization, validation, persistence, settlement, reporting, and export behavior. This makes provider and store changes harder to isolate.

### API responses are not versioned

Current JSON endpoints work for the dashboard and operator tools, but there is no customer-facing versioned contract for odds, opportunities, predictions, combos, alerts, or tracking.

### Hosted collection is not separated yet

The target architecture says the web process must not run collection workers. Current Railway start behavior can refresh the paper payload in the web process. Separate workers remain blocked until PostgreSQL runtime parity passes.

## Target boundaries

```text
HTTP handler / CLI adapter / worker adapter
                  |
                  v
Application services
                  |
                  v
Domain policies and calculations
                  |
          +-------+-------+
          |               |
    Business stores   Source adapters
```

Routes parse and authorize requests, call application services, and serialize stable responses. They do not contain SQL, scraping, model calculations, or database commits.

Application services coordinate store operations, domain policies, adapters, and transactions. They return typed results with stable error codes.

Domain modules own freshness, mapping confidence, market comparability, no-vig, opportunity, correlation, settlement, and metric-exclusion rules.

## Incremental refactor sequence

1. Add store protocols/factory without changing behavior.
2. Add application services for status, report reads, refresh coordination, and review packets.
3. Extract response serializers and stable errors from route code.
4. Split templates/styles/scripts only when the live-odds screen needs independent evolution.
5. Move sports/crypto schema and SQL behind stores while preserving normalization and settlement functions.
6. Add versioned customer API routes after PostgreSQL parity.
7. Add SSE only after latency and polling load are measured.

## Error contract

Application-facing failures use stable machine codes such as:

```text
source_unavailable
source_blocked
stale_source
parse_failed
low_confidence_event_match
market_definition_mismatch
incomplete_outcome_set
opportunity_expired
database_unavailable
migration_not_ready
authentication_required
forbidden
entitlement_required
research_only
```

Logs may include an internal request/run ID and safe detail. Responses never include stack traces, database URLs, raw SQL, secrets, cookies, auth headers, private service addresses, or raw private payloads.

## Testing implications

- Keep current unit tests as behavior locks.
- Add store contract tests shared by SQLite and PostgreSQL.
- Add route tests for status/error/auth contracts.
- Add worker restart, rollback, checkpoint, and provider outage tests.
- Add browser fixtures for loading, stale, blocked, empty, and error states.
- Do not reduce existing coverage or loosen freshness/metric guards.

## Decision

Preserve the backend framework. The next backend change is the business-store boundary, followed by thin application services. Do not create a second API service or frontend.

