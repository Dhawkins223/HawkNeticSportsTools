# PostgreSQL Parity Validation

Validation timestamp: 2026-07-13T04:48:22Z.

## Current result

| Gate | Result | Evidence |
|---|---|---|
| SQLite migration status | PASS | versions `0001` through `0004`; no pending migration |
| SQLite export | PASS | export id `sha256:d74cf356d58c476c1af498dc535c8785d4b15445f482e779c1dda6f3ab7a7559` |
| Export row/hash validation | PASS | 17 tables; zero validation errors |
| Critical aggregate capture | PASS | Kalshi, crypto, and sports aggregates recorded in manifest |
| Empty PostgreSQL creation | NOT RUN | authenticated staging PostgreSQL unavailable |
| PostgreSQL import | NOT RUN | authenticated staging PostgreSQL unavailable |
| Destination row-count parity | NOT RUN | requires staging import |
| Destination hash/status/numeric parity | NOT RUN | requires staging import |
| Dashboard/report/evaluation parity | NOT RUN | requires staging runtime query conversion |
| Full local test suite | PASS | 232/232 |
| Core data-quality gate | PASS | 100/100; mandatory platform checks pass |
| Workflow quality | MIXED | Kalshi 100/100, crypto 100/100, sports 55/100 and blocked for no scheduled events |
| Deployment readiness | BLOCKED | PostgreSQL parity, staging, production backup, and production volume health remain unverified |

The export PASS is not a PostgreSQL parity PASS. PostgreSQL cutover remains blocked.

## Observed export counts

| Table | Rows |
|---|---:|
| `prediction_logs` | 9,079 |
| `prediction_rejections` | 13,609 |
| `settlement_audit` | 17,546 |
| `crypto_prediction_logs` | 3,192 |
| `crypto_prediction_rejections` | 16 |
| `sports_prediction_logs` | 11,533 |
| `sports_prediction_rejections` | 1,329 |
| `model_evaluations` | 10 |
| `model_evaluation_predictions` | 7,022 |
| `paper_test_runs` | 1 |

Other exported compatibility tables were empty at the snapshot time.

## Observed critical aggregates

- Kalshi: 9,079 rows; 6,901 wins; 1,281 losses; legacy P/L sum 4,768 cents.
- Crypto: 3,192 rows; 3,166 settled/push; legacy return sum -1,606.859206 bps.
- Sports: 11,533 rows; 3,338 settled/push/void.

These aggregates are migration checks, not profitability evidence. They include legacy semantics and must not be used as a model claim.

## Required staging parity procedure

1. Authenticate and link Railway CLI without exposing tokens.
2. Verify or create isolated `staging` environment and PostgreSQL service.
3. Apply migrations to an empty staging database.
4. Import `data/postgres_export_20260713` once.
5. Compare counts, min/max times, null counts, business-key uniqueness, duplicate counts, statuses, results, exact numeric aggregates, and deterministic hashes.
6. Compare dashboard payload, model evaluation, return decomposition, source freshness, rejected count, and unresolved count.
7. Run the same collector cycle twice and confirm no duplicate normalized records or checkpoint drift.
8. Update this document with actual destination values and deployed commit.

Any unexplained mismatch fails the migration gate.

## Local collector/settlement validation

- Retry amplification was removed: deterministic sports source blocks now stop after one worker attempt while transient HTTP failures retain bounded connector retries.
- Settlement fetching now selects unresolved markets only, caps each pass at 50 markets, uses an 8-second request timeout, and stops after three consecutive fetch failures.
- A direct settlement validation processed one 50-market batch in 7.6 seconds; a repeat completed with no material change and no missing-market contamination.
- Migration `0004` cleared 328 known false-positive `settlement_market_id_not_found` flags on unresolved rows and retained the prior settlement audit history.
- Reporting validation completed in 12 seconds and generated daily, Stage 3B, and return-decomposition reports.
