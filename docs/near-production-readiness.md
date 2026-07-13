# Near-Production Readiness Audit

Audit date: 2026-07-11

## Current Architecture

- Frontend and backend: one responsive Python HTTP service in `paper_server.py`.
- Market collection: public Kalshi market endpoints plus public ESPN schedule data.
- Crypto research: Coinbase and Kraken source normalization, prediction logging, settlement, reports, and Stage 3B/4 diagnostics.
- Sports research: ESPN/public scraper-first schedule, odds, and official-result settlement flow.
- Database: SQLite research ledgers under `RESEARCH_DATA_DIR`; local files remain the source of truth.
- Workers: Windows Task Scheduler locally; the Railway web service refreshes the Kalshi dashboard every 15 minutes.
- Deployment: GitHub to Railway with a persistent `/data` volume expected for SQLite, reports, and cache.
- Execution boundary: research-only and manual review. Live orders, account writes, auto-betting, and order upload remain disabled.

## Hardening Completed In This Pass

- Stale public-source fallback can no longer produce visible slips, downloadable review packets, or newly logged Kalshi predictions.
- Failed refreshes hide the previous slip rows until fresh data returns.
- Payloads older than `DASHBOARD_MAX_SLIP_AGE_SECONDS` fail closed.
- Public `/data.json` output no longer includes internal research summaries, source-cache diagnostics, or guardrail internals.
- Hosted runtimes require dashboard authentication by default.
- The manual refresh endpoint requires a same-origin custom action header in addition to dashboard authentication.
- Responses include CSP, anti-framing, MIME-sniffing, referrer, permissions, and cross-origin isolation headers.
- Railway now has a `/healthz` deployment health check; `/readyz` reports data readiness separately.
- Frontend wording distinguishes market-implied prices from verified prediction accuracy.
- Internal rejection, connector, and metric-contamination detail remains in protected JSON/report paths instead of consumer cards.

## Database Status

The follow-up hardening phase adds versioned additive migrations, a PostgreSQL-compatible schema,
pool configuration, and an idempotent SQLite export/import validator. The existing SQLite schema includes:

- immutable run locks and model versions;
- prediction timestamps, source timestamps, and deterministic snapshot hashes;
- rejected-prediction records and exact rejection reasons;
- settlement audit records and duplicate-settlement prevention;
- separate crypto and sports prediction tables;
- de-duplicated reporting paths and feature/label separation.

SQLite remains compatible for local single-writer development. PostgreSQL schema/import support is
implemented but not activated; the existing business query paths remain SQLite-specific and are a
deployment blocker for multi-service hosting.

## Data-Source Status At Audit

- Kalshi public market data: active and refreshing locally.
- ESPN schedules/results/odds: active for current sports scraper mode.
- Coinbase/Kraken: active and fresh in the completed post-change quality audit.
- Firecrawl: unconfigured in the current local process.
- Google Drive, Airtable, and Slack: optional and currently unconfigured locally.
- Paid sports odds APIs: not required for the current scraper-first path.

No failed connector is allowed to create fake prediction rows or change settled metrics.

## Measured Research Performance Snapshot

These figures are descriptive research results, not proof of edge or profitability.

- Kalshi Stage 3B: 337 de-duplicated settled market exposures; 77.7448% directional accuracy; fee-excluded simulated return -7.7562%. The negative result and missing execution-cost model block any profitability claim.
- Crypto: 2,618 settled de-duplicated exposures; 51.0728% directional accuracy; average return +0.4634 bps before any fee/slippage model. ROI remains unavailable.
- Sports: 64 settled de-duplicated exposures; 32 wins and 32 losses; 50.0% win rate. The sample remains below the 100-exposure audit gate, with 630 repeated-snapshot groups excluded from the primary settled exposure count.

Unresolved, rejected, legacy, blocked, push/no-edge, and duplicate exposure rows are excluded according to each report's documented metric policy.

The post-change local data-quality audit completed at `2026-07-11T18:28:47Z` with status `OK`, score `100`, and no major or minor issues. That status is a point-in-time pipeline check, not a prediction-performance claim.

## Critical Launch Blockers

1. There is no independent, validated probability model for most public Kalshi tiers. The 80c/75c tiers are market-implied screens, not model success probabilities.
2. Real historical order-book depth is unavailable; cost-aware one-contract simulation is implemented but cannot prove historical fills.
3. Role/session authentication is implemented, but account recovery and hosted session validation remain incomplete.
4. PostgreSQL migrations exist, but production business queries remain SQLite-specific and no restore drill has passed.
5. Independent worker commands and monitoring exist, but Railway services have not been created or validated.
6. There is no error-tracking product, uptime monitor, or alert destination configured in the current local environment.
7. Accessibility and mobile layout are tested manually and with unit assertions, but no automated browser accessibility suite exists yet.
8. The public-source license/terms review is not recorded per source.

## Prediction-System Boundary

No model training or live-rule tuning was performed. Starting ML now would violate the controlled-research gate and would not repair the current launch blockers. The next model step must be a challenger-only, out-of-sample workflow with frozen baselines, leakage checks, calibration metrics, and no impact on live recommendations until it wins a predeclared evaluation.

## Exact Next Technical Priority

Run the complete test suite and a fresh local workflow, then deploy this hardening pass. After deployment, configure `DASHBOARD_AUTH_PASSWORD`, verify `/healthz` and `/readyz`, confirm the Railway volume persists `evaluation.sqlite`, and monitor one full refresh/settlement cycle. The next code project should be a formal database migration/backup layer or a controlled independent-probability challenger harness—not live execution.
