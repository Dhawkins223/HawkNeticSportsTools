# Research Platform Implementation Report

Date: 2026-07-12
Research status: **research_operational**
Deployment status: **not deployment ready**
Trading status: **manual review only; no order upload or automatic trading**

## Outcome

The existing platform was hardened without replacing its dashboard, collection logic, or research-only controls. It now has category-specific probability evaluation, realistic paper execution, explicit exposure accounting, versioned SQLite/PostgreSQL migrations, isolated worker commands, internal monitoring, role-based local authentication, deterministic browser fixtures, and a private non-executing operator/Codex inbox.

The code was not committed, pushed, or deployed. Live prediction rules were not changed. No ML training was started. No model was promoted.

## Files Changed

Every current working-tree change is listed below.

### Root and deployment configuration

- `.env.example` — database, authentication, worker, freshness, and private operator-inbox placeholders; stale fallback disabled.
- `Procfile` — hosted web command retains the existing app and disables stale-on-error payload reuse.
- `README.md` — current guardrails, hardening docs, isolated routine, and `/ops` instructions.
- `nixpacks.toml` — existing start command retained with stale fallback disabled.
- `pyproject.toml` — optional PostgreSQL driver and pool dependencies.
- `railway.json` — existing web service retained, stale fallback disabled, `/healthz` configured.

### Documentation

- `docs/github-railway-firecrawl-workflow.md` — branch ambiguity, fail-closed data, and PostgreSQL boundary corrected.
- `docs/deployment-readiness-checklist.md` — explicit Git, database, auth, operations, and credential-rotation gates.
- `docs/implementation-report-2026-07-12.md` — this evidence-backed handoff.
- `docs/near-production-readiness.md` — current hardened architecture and remaining blockers.
- `docs/operator-runbook.md` — exact local routine, worker, admin, prompt-inbox, browser-fixture, and shutdown commands.
- `docs/postgresql-migration.md` — export/import/validation, rollback, backup, and remaining query-path work.
- `docs/railway-worker-services.md` — independent service commands, variables, dependency order, and failure isolation.
- `docs/research-platform-hardening.md` — model, execution, exposure, and evidence guardrails.

### Migrations

- `migrations/sqlite/0001_research_hardening.sql` — additive model, execution, exposure, worker, connector, and auth schema.
- `migrations/sqlite/0002_operator_messages.sql` — non-executing private instruction queue.
- `migrations/postgres/0001_research_schema.sql` — PostgreSQL-compatible research schema, constraints, and indexes.
- `migrations/postgres/0002_operator_messages.sql` — PostgreSQL queue schema with execution permanently disabled.

### Scripts

- `scripts/browser_validation_server.py` — deterministic live/empty/stale/error/loading visual fixtures without live refresh or prediction writes.
- `scripts/research_routine.cmd` — Windows entry point for the consolidated routine.
- `scripts/research_routine.ps1` — status and one-pass failure-isolated worker orchestration.
- `scripts/test.cmd` — changes to the repository before discovery so Task Scheduler can run QA from any working directory.
- `scripts/test.ps1` — PowerShell QA wrapper now applies the same repository-working-directory guarantee.

### Application code

- `src/kalshi_research_bot/auth.py` — scrypt accounts, roles, sessions, CSRF, lockout, audit, and disabling.
- `src/kalshi_research_bot/browser_fixtures.py` — deterministic browser-state fixture transformations.
- `src/kalshi_research_bot/cli.py` — database, auth, worker, model, return-audit, and operator-inbox commands.
- `src/kalshi_research_bot/connectors/airtable_status.py` — robust mapping/list rejection summaries so an optional disabled connector cannot crash scheduled status generation.
- `src/kalshi_research_bot/connectors/status.py` — explicit configured/degraded/failed/unconfigured/missing-required states.
- `src/kalshi_research_bot/database.py` — redacted database settings, optional pooling, and startup readiness.
- `src/kalshi_research_bot/db_migrations.py` — ordered migrations, immutable hashes, status checks, and transactions.
- `src/kalshi_research_bot/evaluation/__init__.py` — exports for the new evaluation components.
- `src/kalshi_research_bot/evaluation/execution.py` — market/limit paper execution, depth, partial/no fill, slippage, fees, limits, and settlement.
- `src/kalshi_research_bot/evaluation/exposure.py` — event/category/underlying/correlation/capital limits while preserving raw records.
- `src/kalshi_research_bot/evaluation/kalshi_decomposition.py` — cost and correlated-exposure return decomposition.
- `src/kalshi_research_bot/evaluation/model_audit.py` — separate Kalshi/crypto/sports dataset evaluation.
- `src/kalshi_research_bot/evaluation/model_validation.py` — time-aware splits, walk-forward support, leakage guards, baselines, calibration, ensembles, metrics, and states.
- `src/kalshi_research_bot/monitoring.py` — worker/database/model/source/backlog health and actionable alerts.
- `src/kalshi_research_bot/operator_inbox.py` — durable manual-review instruction queue that cannot execute content.
- `src/kalshi_research_bot/paper_server.py` — protected internal status, session login, role boundaries, fail-closed public payload, `/ops`, and responsive cleanup.
- `src/kalshi_research_bot/postgres_migration.py` — deterministic JSONL export, sensitive-table exclusions, correct settlement aggregates, idempotent import, and validation.
- `src/kalshi_research_bot/review_packet.py` — stale/failed payload blocking and safe manual packet fields.
- `src/kalshi_research_bot/slip_safety.py` — centralized stale/error/source gate for slips and public JSON.
- `src/kalshi_research_bot/sports_research.py` — source timestamp ordering fix and future-source rejection.
- `src/kalshi_research_bot/storage.py` — additive migration application during store initialization.
- `src/kalshi_research_bot/today.py` — fail-closed refresh behavior and research ledger integration.
- `src/kalshi_research_bot/worker_runtime.py` — idempotency, retries, backoff, structured logs, and graceful shutdown.
- `src/kalshi_research_bot/worker_services.py` — isolated Kalshi, external, crypto, sports, settlement, and reporting operations.

### Tests

- `tests/test_auth_roles.py` — role, password, session, lockout, CSRF, and disable behavior.
- `tests/test_browser_fixtures.py` — deterministic empty/stale/error/loading fixtures.
- `tests/test_connectors.py` — explicit connector states and environment documentation.
- `tests/test_database_migrations.py` — migration immutability, export/import guards, redaction, indexes, and correct settlement aggregates.
- `tests/test_daemon.py` — scheduled-script inventory plus working-directory-safe QA assertions.
- `tests/test_execution_exposure.py` — fee math, market/limit fills, partial/no fills, correlations, and limits.
- `tests/test_internal_endpoint.py` — public health with admin-only internal monitoring.
- `tests/test_kalshi_decomposition.py` — high-accuracy/negative-return decomposition and bucket reporting.
- `tests/test_model_audit.py` — separate category data and leakage handling.
- `tests/test_model_validation.py` — splits, metrics, calibration, baseline comparison, leakage, persistence, and states.
- `tests/test_operator_inbox.py` — queue idempotency, transitions, authorization, and permanent no-execution boundary.
- `tests/test_paper_server_auth.py` — hosted defaults, Basic fallback roles, sessions, cookies, login, and headers.
- `tests/test_quality.py` — contamination and fail-closed quality rules.
- `tests/test_review_packet.py` — manual packet safety and stale/error blocking.
- `tests/test_slip_safety.py` — public payload redaction and stale/source failure gates.
- `tests/test_sports_research.py` — source timing, scraper validation, and feature leakage prevention.
- `tests/test_worker_runtime.py` — idempotency, failure isolation, retries, no-material-change, and log redaction.

## Database

### Schema and local compatibility

- SQLite remains the active local source of truth.
- Applied SQLite migration versions: `0001`, `0002`.
- Pending SQLite migrations: none.
- Migration hashes are checked; modifying an applied migration is blocked.
- Existing SQLite research data was not destroyed.

### PostgreSQL readiness

- PostgreSQL schema, unique/idempotency constraints, query indexes, migration tracking, and optional connection pooling exist.
- The validated export snapshot created at `2026-07-12T16:52:15Z` contains 17 research tables and had zero validation errors at capture time.
- Export ID: `sha256:071c21ce69b227b25acbf4dda402c54f9e5511a1e4f3c7f8cc39c6298b2028d4`.
- Snapshot aggregates: 6,622 Kalshi prediction rows, 3,398 wins, 694 losses; 2,994 crypto rows with 2,968 resolved; 11,425 sports rows with 1,750 resolved.
- Authentication, login audit, and operator messages are deliberately excluded from research-history exports.
- A real PostgreSQL import was not run because Railway CLI is unauthenticated and no reviewed non-production target was authorized.
- Hosted business read/write paths are still SQLite-specific. PostgreSQL is schema/import ready, not active-runtime ready.
- Because local collectors remain live, pause SQLite writers and create a fresh export immediately before a real import; later source rows intentionally make an older snapshot differ from the active database.

## Model Validation

Baseline: market-implied probability. Split policy: chronological 60/20/20 with an untouched test set. Walk-forward support is implemented. No model is usable for promotion.

### Kalshi sports market baseline

- State: `baseline_only`.
- Reason: no independent category-model probabilities exist.
- Full sample: 1,237; train 742; validation 247; test 248.
- Train: 2026-07-04T00:04:14Z through 2026-07-11T21:16:22Z.
- Validation: 2026-07-11T21:16:22Z through 2026-07-12T00:13:06Z.
- Test: 2026-07-12T00:13:06Z through 2026-07-12T13:09:53Z.
- Test Brier: 0.112648869.
- Test log loss: 0.380517721.
- Test calibration error: 0.049855597.
- Test accuracy: 0.866935484; 95% CI 0.819017921–0.903658555.

### Crypto challenger

- State: `failed_validation`.
- Reason: challenger did not beat the market/neutral baseline.
- Selected diagnostic candidate: training-only calibrated category model.
- Full sample: 2,392; train 1,435; validation 478; test 479.
- Test: 2026-07-10T19:53:07Z through 2026-07-12T16:08:02Z.
- Test Brier: 0.250651442.
- Test log loss: 0.694450475.
- Test calibration error: 0.029943334.
- Test accuracy: 0.484342380; 95% CI 0.439889797–0.529044114.

### Standalone sports challenger

- State: `failed_validation`.
- Reason: legacy feature/source timestamps contain future-data leakage.
- New collection timestamp ordering is fixed; immutable contaminated history remains excluded.

Other Kalshi categories remain `insufficient_sample`. Usable research models: none. Live logic unchanged.

## Kalshi Return Decomposition

- Raw settled rows: 4,092.
- Market de-duplicated exposures: 1,304.
- Event-adjusted/portfolio-limited exposures: 528.
- Repeated snapshot/strategy rows removed from portfolio accounting: 2,788.
- Additional correlated event markets excluded: 776.
- Market-level fills: 1,293; no-fill/rejected: 11.
- Winners/losses: 1,062/231.
- Directional accuracy: 82.1346%.
- Average/median entry: 84.5437c/82c.
- Average winning gross payout: +14.9426c.
- Average losing amount: -82.1818c.
- Gross simulated return: -3,115c.
- Fees: -1,959c.
- Adverse movement/slippage: -1,293c.
- Net simulated return: -5,074c; -4.6416% of simulated capital at risk.
- Average-price break-even accuracy before costs: 84.5437%, above observed accuracy.

All price buckets remain negative after modeled costs: 70–79c -5.73%, 80–89c -5.05%, and 90–100c -2.88%. The high accuracy came from expensive favorites: a win earns only `100 - entry`, while a loss forfeits the full entry price. Fees and adverse movement raise break-even further. This is not proof of tradable profitability.

## Simulated Execution

- Conservative market orders and limit orders are supported.
- Full, partial, no-fill, rejected, closed, and expired outcomes are represented.
- Every simulation stores signal/order/snapshot timestamps, intended/fill price, quantity, fees, slippage, payout, gross return, and net return.
- Historical audit assumption: one contract at top of book, 1c adverse signal-to-order movement, 2c slippage ceiling.
- Historical depth is unavailable, so the audit does not invent partial depth.
- Fee schedule version: `kalshi_general_2026-02-05`; special-product fees still require separate validation.

## Exposure Controls

- Raw records are preserved.
- Event, category, underlying, correlation-group, position, and total-capital limits exist.
- Repeated snapshots, same-event markets, opposing positions, and overlapping markets are explicit decisions rather than silent deletion.
- Current market de-duplicated result: -4.64% after modeled costs.
- Current event-adjusted result: 420 wins/106 losses, 79.85% accuracy, -3,019c net, -6.83% of risk.
- Maximum simulated capital at risk is configurable; historical event-adjusted audit risk was 44,211c.

## Workers and Monitoring

Prepared services:

- web dashboard;
- Kalshi market ingestion;
- external-source ingestion;
- crypto research;
- sports research;
- settlement;
- reporting/evaluation.

Each worker has a startup command, cadence, idempotency key, retries/backoff, structured secret-redacted logging, graceful shutdown, last attempt/success, consecutive failure state, and database-backed heartbeat. Failure-isolation tests pass. No independent hosted workers are currently running; the local worker-status tables contain zero rows because the existing scheduled workflow was preserved rather than silently replaced.

The existing Windows Task Scheduler automation is enabled. QA previously failed because Task Scheduler launched `test.cmd` outside the repository, and status sync previously failed while formatting list-shaped Kalshi rejection reasons. Both root causes are fixed; the entire suite passes when invoked from `C:\Windows\System32`, and unavailable Airtable now returns a clean nonblocking skip. Both `QualityAuditDaily` and `StatusSyncHourly` were rerun through Task Scheduler and now report `Ready` with result `0`.

Internal monitoring is admin-only at `/internal/status.json`. Current actionable backlog signals exist for unresolved Kalshi, crypto, and sports settlements; these are research backlog alerts, not counted as losses.

## Authentication and Operator Messages

- Hosted authentication remains required by default.
- Basic authentication is retained as an emergency owner fallback.
- Local account roles: `admin`, `researcher`, `read_only`.
- Session expiry, secure hashing, CSRF, login audit, failed-login lockout, and account disabling exist.
- No persistent local user has been created yet; first-admin setup remains manual.
- `/ops` and operator-message JSON endpoints require admin.
- Every operator message is `requires_approval=true` and `execution_allowed=false`.
- Operator messages never become worker input and cannot run code, deploy, access accounts, or trade.

## Browser Validation

Automated browser results:

- Phone 390×845: no horizontal overflow; navigation scrolls; minimum button height 44px; 76 slip rows; zero clipped slip cards.
- Tablet 768×1025: no horizontal overflow; minimum button height 44px; 76 slip rows; zero clipped slip cards.
- Desktop 1506×847: no horizontal overflow; zero long-text overflow; event start times visible; 76 slip rows.
- Login: protected `/ops` redirected to login; unique username/password/button controls; valid test login returned to the dashboard.
- Operator inbox: admin submission stored a message, cleared the form, refreshed the queue, and exposed no run/deploy/trade/order control.
- Empty fixture: zero slip rows and four explicit `No Slip` cards.
- Stale fixture: zero slip rows; all tiers say fresh data is required.
- Error fixture: zero slip rows; refresh failure and exact fixture error are visible.
- Loading fixture: refresh button is disabled and labeled `Refreshing…`; status is `Updating`.

Desktop and operator screenshots are stored under ignored `data/browser_validation/`. The Chrome phone screenshot capture produced a scaling artifact, so phone readiness is supported by automated dimensions/overflow/touch-target metrics rather than a clean committed screenshot. Repeat mobile screenshots after the Chrome plugin reconnects.

## Connector State

- Firecrawl: `missing_required` locally because no safe active key is configured.
- Google Drive: `unconfigured_optional`.
- Airtable: `unconfigured_optional`.
- Slack: `unconfigured_optional`.
- Optional connector absence does not block core collection, settlement, reports, or the dashboard.
- Vercel, PostHog, Stripe remain disabled; Kit and Clay remain later-only.

No previously pasted credential was reused. Credentials exposed in chat/screenshots must be rotated before deployment: Firecrawl key, Kalshi key identifier/private key, and any exposed dashboard/Railway credential.

## Tests and Quality

- Full tests: 213.
- Passed: 213.
- Failed: 0.
- Skipped: 0.
- Data-quality score: 100/100.
- Data-quality major issues: none.
- Data-quality minor issues: none.
- Secret scan: 153 tracked/untracked non-ignored files; zero private-key/token/non-empty-secret findings.
- `.env`, `.env.local`, and `data/evaluation.sqlite` are ignored.
- `git diff --check`: passed.

## Git and Deployment

- Active local branch: `main`.
- Remote default branch: `Master`.
- `origin/main` and `origin/Master` currently point to `def0dc722a104982d4707d3994d1a850dcfa0669`.
- Working tree: dirty with all changes above; nothing staged, committed, pushed, or deployed.
- Railway CLI: installed but unauthenticated (`railway login` required).
- Railway's actual watched branch still needs confirmation in the dashboard.
- The local dashboard was restarted on `127.0.0.1:8765`; `/healthz`, `/readyz`, and `/ops` all returned 200 after a successful fresh-source startup refresh.

Safe next sequence after explicit authorization:

```powershell
git status --short
git branch --show-current
git diff --check
cmd /c scripts\test.cmd

# Confirm Railway's watched branch first.
git switch -c codex/research-platform-hardening
git add <reviewed files only>
git commit -m "Harden research validation and operations"
git push -u origin codex/research-platform-hardening
# Open a reviewed pull request into the confirmed branch.
```

Before creating Railway worker services, run the PostgreSQL schema/import against a non-production database, verify all counts and aggregates, finish PostgreSQL business query paths, rotate credentials, and validate hosted session auth over HTTPS.

## Final Research Decision

State: **research_operational**.

- Do not promote a model.
- Do not start ML training.
- Do not change live rules based on current evidence.
- Continue clean collection and settlement.
- Continue only controlled challenger research.
- Do not claim edge or profitability.
