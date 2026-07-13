# PostgreSQL Parity Validation

Validation timestamp: 2026-07-13T03:16:02Z.

## Current result

| Gate | Result | Evidence |
|---|---|---|
| SQLite migration status | PASS | versions `0001` through `0004`; no pending migration |
| SQLite export | PASS | export id `sha256:03ad879bc55a26f4b29f1695472eb159cd5f5df1a196024121bb502b4eebaaf0` |
| Export row/hash validation | PASS | 17 tables; zero validation errors |
| Critical aggregate capture | PASS | Kalshi, crypto, and sports aggregates recorded in manifest |
| Empty PostgreSQL creation | NOT RUN | authenticated staging PostgreSQL unavailable |
| PostgreSQL import | NOT RUN | authenticated staging PostgreSQL unavailable |
| Destination row-count parity | NOT RUN | requires staging import |
| Destination hash/status/numeric parity | NOT RUN | requires staging import |
| Dashboard/report/evaluation parity | NOT RUN | requires staging runtime query conversion |
| Full local test suite | PASS | 224/224 |
| Live data-quality gate | BLOCKED | 85.83/100; sports public source unavailable and Firecrawl unconfigured |

The export PASS is not a PostgreSQL parity PASS. PostgreSQL cutover remains blocked.

## Observed export counts

| Table | Rows |
|---|---:|
| `prediction_logs` | 8,831 |
| `prediction_rejections` | 13,182 |
| `settlement_audit` | 9,906 |
| `crypto_prediction_logs` | 3,162 |
| `crypto_prediction_rejections` | 10 |
| `sports_prediction_logs` | 11,533 |
| `sports_prediction_rejections` | 1,328 |
| `model_evaluations` | 10 |
| `model_evaluation_predictions` | 7,022 |
| `paper_test_runs` | 1 |

Other exported compatibility tables were empty at the snapshot time.

## Observed critical aggregates

- Kalshi: 8,831 rows; 6,820 wins; 1,266 losses; legacy P/L sum 5,093 cents.
- Crypto: 3,162 rows; 3,136 settled/push; legacy return sum 113.463427 bps.
- Sports: 11,533 rows; 3,338 settled/push/void.

These aggregates are migration checks, not profitability evidence. They include legacy semantics and must not be used as a model claim.

## Required staging parity procedure

1. Authenticate and link Railway CLI without exposing tokens.
2. Verify or create isolated `staging` environment and PostgreSQL service.
3. Apply migrations to an empty staging database.
4. Import `data/postgres_export_20260712` once.
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
