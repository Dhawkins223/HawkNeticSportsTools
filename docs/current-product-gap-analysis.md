# Current Product Gap Analysis

Status: Phase 0 baseline captured 2026-07-13.

## Technical summary

The platform is a functioning private Kalshi/crypto/sports research system, not yet a multi-sportsbook product. Local core quality is healthy. A full isolated routine pass refreshed the Kalshi, crypto, settlement, and reporting heartbeats; overall operations remain degraded because the sports source is blocked and settlement backlogs remain. PostgreSQL migration and compatibility import pass in isolated Railway staging; the active business code still uses SQLite, which blocks independent hosted workers and normalized hosted reporting.

No model qualifies for promotion. No edge, profitability, or production-readiness claim is supported.

## Verified baseline

| Area | Current evidence | Interpretation |
|---|---|---|
| Core quality | 100/100 | Metric-denominator guards and research-only controls pass |
| Kalshi workflow | 100/100 | Current local source/data checks pass |
| Crypto workflow | 100/100 | Current local source/data checks pass; model state includes failed validation |
| Sports workflow | 55/100, blocked | Latest public source attempt produced no scheduled events or usable odds rows |
| Dashboard | Fresh with visible slip tiers during the audit | The review surface works locally, but this is not hosted-runtime proof |
| Database | SQLite configured healthy | Local source of truth only |
| Railway PostgreSQL | Migrations and compatibility import pass through revision `0004` | Schema/import readiness only; not business-runtime parity |
| Workers | Commands and retry/idempotency controls exist | One full routine pass refreshed active heartbeats; sports recorded its third consecutive `blocked_no_scheduled_events` failure; hosted workers remain blocked |
| Models | Baseline-only, insufficient-sample, and failed-validation states | No production model or public performance claim |

Evidence comes from `database-status`, `data-quality`, `research_routine -Action status`, the current migration reports, and the code paths listed in `docs/runtime-store-boundary-audit.md`.

## Product gaps by surface

| Target surface | Implemented now | Missing before credible release | Gate |
|---|---|---|---|
| Overview | Kalshi review dashboard, quality status, research record | Unified customer-oriented summary, saved preferences, clear stale/blocked state | Hosted auth and PostgreSQL reads |
| Live Odds | Kalshi public quotes and limited sports ingestion | Canonical books/events/markets, best prices, filters, history, efficient updates | Licensed provider + Phase 2 schema |
| Positive EV | Kalshi edge research and model validation controls | Multi-book consensus, no-vig policy, uncertainty, expiry, calculation lineage | Phase 4 |
| Arbitrage | None | Complete outcome matching, rule parity, fee/rounding checks | Phase 4 |
| Low Hold | None | Complete outcome set, hold calculation, history | Phase 4 |
| Market Signals | Public intel and line-related research concepts | Canonical line movement, injury/lineup/weather annotations, false-signal controls | Phase 5 |
| Predictions | Baseline models and audit reports | Approved model registry, strict training/holdout boundaries, customer-safe explanation | Phase 5; no ML now |
| Combo Lab | Exact-listed Kalshi combo integrity and overlap guards | Sportsbook-specific combinability, payouts, correlations, alternatives | Phase 6 |
| Tracker | Prediction and settlement ledgers | User-entered decision records, CLV, provenance labels, notes/tags | Phase 7 |
| Alerts | Operational Slack helper | User rules, in-app delivery, expiry, entitlement, quiet hours | Phase 7 |
| Research | Reports and feature exports | Unified historical exploration without exposing operator internals | PostgreSQL reporting views |
| Entitlements | None | Server-side plan/feature/usage model | Phase 8; billing excluded |

## Data gaps

1. No activated licensed multi-book odds provider.
2. No canonical sportsbook, player, provider-event, provider-market, or provider-selection mapping tables in active runtime.
3. No complete sportsbook odds history or closing-line capture.
4. No reliable player-prop and alternate-line feed.
5. Sports source attempts can return valid schedules but no usable odds; those failures correctly block rather than fabricate rows.
6. Current hosted compatibility import does not populate normalized reporting views.

## Runtime and operations gaps

- `ResearchStore` is SQLite-specific and instantiated by the web server, workers, authentication, monitoring, reporting, crypto, sports, and settlement paths.
- The web process still performs local refresh behavior; the target hosted design requires collectors to run separately.
- Railway staging has a PostgreSQL service, but independent workers cannot safely use it until the business store contract is implemented.
- Production has no verified off-platform backup/restore drill. Railway Hobby volume Backups/PITR are unavailable.
- Previously exposed credentials must be rotated before any production change.
- Hosted session authentication still needs end-to-end verification over HTTPS.

## Frontend gaps

The frontend is one server-rendered Python module with embedded CSS and JavaScript. That keeps deployment simple, but it makes the screen hard to evolve and has already accumulated operator-oriented text in customer-facing areas. The next frontend phase should preserve the server and data contracts while separating:

- customer navigation from operator diagnostics;
- compact primary metrics from detailed methodology;
- mobile cards from desktop tables;
- current, stale, blocked, loading, and empty states;
- live odds from research/model outputs.

No disconnected frontend rewrite is justified.

## Security and compliance gaps

- Provider display/redistribution rights are not yet approved.
- Production credential rotation is incomplete.
- Entitlements do not exist.
- Account recovery and password rotation procedures are incomplete.
- The product must continue to block order creation, order staging, auto-upload, auto-trading, and sportsbook credential storage.

## What is strong enough to preserve

- deterministic source hashes and timestamp proof;
- stale-source rejection;
- retained raw evidence and rejection reasons;
- settlement-only labels and leakage-guarded feature exports;
- de-duplicated settled metrics;
- exact Kalshi listed-combo validation;
- manual review packets;
- research-only safety flags and readiness checks;
- isolated worker commands and structured failures.

## Decision

Do not tune prediction logic or start model training. Finish the PostgreSQL runtime boundary first. In parallel, run a no-cost provider evaluation using free trials or public documentation only; do not activate a paid plan without explicit approval. More data is required before any model change or customer performance claim.
