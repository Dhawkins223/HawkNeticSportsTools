# Competitive Platform Roadmap

Status: controlled research roadmap. No phase authorizes production, billing, wagering, or model promotion.

## Technical summary

The program must move in dependency order. The immediate gate is PostgreSQL business-runtime completion. Building a live odds screen, EV engine, or additional workers before that boundary would create more SQLite coupling and unreliable hosted state.

Each phase uses a separate reviewed branch or a small series of commits on `codex/competitive-sports-intelligence`. Railway staging can show completed, tested phases after OAuth authorization. Production remains unchanged until the production gate passes.

## Phase 0 - Audit and architecture

Deliverables:

- `docs/competitive-capability-analysis.md`
- `docs/current-product-gap-analysis.md`
- `docs/odds-provider-evaluation.md`
- `docs/competitive-platform-architecture.md`
- `docs/competitive-platform-roadmap.md`
- `docs/runtime-store-boundary-audit.md`
- `docs/backend-architecture-audit.md`
- `docs/backend-api-contract.md`

Exit gate:

- current capabilities and gaps are evidence-backed;
- no competitor performance claim is treated as verified;
- provider rights and cost are explicit blockers;
- the next code boundary is unambiguous;
- full tests pass with no prediction-logic change.

## Phase 1 - PostgreSQL runtime completion

Implement:

- one business-store protocol;
- SQLite and PostgreSQL implementations for active web/worker/report/auth paths;
- no hosted fallback from PostgreSQL to SQLite;
- normalized ledger writes and reporting reads;
- transaction, timeout, pooling, migration, and readiness controls;
- staging import/report parity and restart/idempotency tests;
- off-platform backup and restore procedure suitable for the current plan.

Exit gate:

- web, workers, reporting, crypto, sports, settlement, monitoring, and auth use the selected store;
- SQLite local tests and PostgreSQL staging tests agree on controlled fixtures and aggregates;
- one complete hosted ingestion/settlement/report cycle passes;
- no dual-write ambiguity;
- production remains unchanged.

## Phase 2 - Canonical odds foundation

Implement:

- supported-source and sportsbook registries;
- canonical sport/league/season/team/player/event/market/selection identities;
- provider mapping evidence and confidence;
- immutable odds/line history, source freshness, corrections, and closing lines;
- controlled provider bakeoff and cost telemetry;
- best-line calculation from complete comparable outcomes.

Exit gate:

- one in-season league has measured, licensed coverage;
- mapping and duplicate rates meet the documented bakeoff gate;
- blocked/stale/quota failures fail closed;
- no paid provider is activated without explicit approval.

## Phase 3 - Live Odds frontend

Implement:

- compact odds workstation using the existing backend/frontend;
- filters, saved views, best prices, timestamps, source age, line movement, and market state;
- desktop table and mobile-specific layout;
- keyboard and accessibility validation;
- efficient polling or SSE after measured need.

Exit gate:

- current/loading/stale/blocked/empty/error states pass visual tests;
- source-to-screen latency is measured, not claimed;
- operator diagnostics remain private;
- Railway staging screenshots and mobile checks pass.

## Phase 4 - Opportunity engine

Implement:

- multiplicative, additive, power, and justified market-specific no-vig methods;
- consensus inputs and explicit book inclusion/exclusion;
- positive-EV, arbitrage, and low-hold calculations;
- opportunity lineage, uncertainty, expiry, invalidation, fees, and rounding.

Exit gate:

- exact numeric tests pass;
- stale, incomplete, mismatched, or unsupported markets cannot produce opportunities;
- outputs remain research-only and make no profitability claim.

## Phase 5 - Predictions and market signals

Implement:

- approved model registry and reproducible feature cutoffs;
- calibration, Brier score, log loss, holdout comparisons, and confidence intervals;
- market baseline, closing-line baseline, and simple historical baseline;
- injury, lineup, weather, and line-movement annotations;
- model-market disagreement without automatic promotion.

Exit gate:

- leakage and source-coverage checks pass;
- no model is promoted unless it beats a simpler baseline on untouched data;
- negative periods and failed models remain visible.

## Phase 6 - Combo Lab

Implement:

- exact sportsbook-specific availability and payout evidence;
- incompatible-leg and duplicate-outcome detection;
- pairwise dependency rules, correlation status, simulation, and joint probability;
- scenario analysis, alternatives, expiry, and downgrade/block rules.

Exit gate:

- marginal probabilities are never multiplied naively for related legs;
- `insufficient_evidence` blocks or downgrades unsupported combinations;
- every visible combination is actually available from the identified source.

## Phase 7 - Alerts and tracker

Implement:

- saved filters and in-app alerts;
- deduplication, rate limits, quiet hours, expiry, revocation, and audit;
- manual decision tracking, source snapshot, closing line, CLV, outcome, notes, and provenance labels;
- email only after a valid provider is configured.

Exit gate:

- alerts fire only on state changes and remain freshness-aware;
- user-entered, provider-verified, system-calculated, and unverified values are distinct.

## Phase 8 - Entitlements

Implement server-side plans, entitlements, user overrides, trials, usage limits, and expiration. Do not add Stripe, checkout, pricing, marketing, or billing without a separate explicit authorization.

## Phase 9 - Load, security, and failure testing

Validate representative odds volume, stream connections, PostgreSQL/Redis restarts, provider outage, stale-data enforcement, worker overlap, backup/restore, access controls, and rollback.

## Production gate

Production stays blocked until all of the following are directly evidenced:

- PostgreSQL business-runtime and normalized parity;
- restorable off-platform backup;
- approved provider rights and cost;
- credential rotation;
- hosted authentication and entitlement enforcement;
- staging worker, load, security, failure, frontend, and accessibility tests;
- reviewed PR and verified rollback;
- research-only and no-execution controls.

## One next phase

Phase 1: implement and validate the PostgreSQL business-store boundary. Do not start feature expansion or model training before that gate.

