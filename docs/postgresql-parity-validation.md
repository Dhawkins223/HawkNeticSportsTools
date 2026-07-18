# PostgreSQL Parity Validation

Validation timestamp: 2026-07-13T05:43:00Z.

## Current result

| Gate | Result | Evidence |
|---|---|---|
| Empty PostgreSQL creation | PASS | Railway staging PostgreSQL 18; migrations `0001` through `0004` applied in order |
| Migration repeat safety | PASS | second migration run reported no newly applied versions |
| PostgreSQL structure | PASS | schemas `raw`, `core`, `research`, `ops`, `reporting`, and `auth`; 6 reporting views |
| SQLite export | PASS | export id `sha256:2e50f51a0db430fff302387be8e54fb44059f0694a40da9338cd1c89974dab1d` |
| Export validation | PASS | 17 tables; zero validation errors; source SHA-256 `5afe810785592e05685d958dd77d990f6e4bec4d30f58134c34b842ffb9eabaa` |
| PostgreSQL compatibility import | PASS | all 17 legacy compatibility tables imported transactionally |
| Destination row-count parity | PASS | all source and destination table counts match |
| Null/status/timestamp/hash parity | PASS | no mismatches in the compatibility-table comparison |
| Critical aggregate parity | PASS | no differences outside the documented `1e-9` legacy-float tolerance |
| Duplicate import safety | PASS | second import status `already_imported`; zero rows reinserted and zero unintended duplicates |
| Staging migration readiness | PASS | `/healthz` 200 and `/readyz` 200 with PostgreSQL configured healthy and no pending versions |
| Normalized runtime/report parity | BLOCKED | worker and reporting business paths still instantiate SQLite `ResearchStore`; normalized reporting views are not populated by the compatibility import |

The schema, migration, export, compatibility import, and repeat-import gates pass. Full application cutover does not pass because PostgreSQL is not yet the business-query runtime.

## Staging target

- Environment: `staging` (`14f937a9-34e4-4720-afc4-509e910c64dc`).
- PostgreSQL service: `Postgres` (`1de1d0fc-ae04-4fae-820d-29ce7379b3d0`).
- Image/version: Railway PostgreSQL SSL image, PostgreSQL 18.
- Persistent volume: `postgres-volume` (`5405c9c5-c429-4caf-b6f1-aa0425313b50`), mounted at `/var/lib/postgresql/data`.
- Application connection: Railway private service reference. The temporary public TCP proxy used for migration validation was removed after validation.

## Observed compatibility counts

| Table | Rows |
|---|---:|
| `connector_health` | 0 |
| `crypto_prediction_logs` | 3,204 |
| `crypto_prediction_rejections` | 16 |
| `edge_results` | 0 |
| `exposure_decisions` | 0 |
| `model_evaluation_predictions` | 7,022 |
| `model_evaluations` | 10 |
| `paper_test_runs` | 1 |
| `prediction_logs` | 9,200 |
| `prediction_rejections` | 13,819 |
| `settlement_audit` | 17,546 |
| `simulated_executions` | 0 |
| `source_records` | 0 |
| `sports_prediction_logs` | 11,533 |
| `sports_prediction_rejections` | 1,330 |
| `worker_runs` | 14 |
| `worker_status` | 5 |

## Critical aggregates

- Kalshi: 9,200 rows; 6,901 wins; 1,281 losses; legacy P/L sum 4,768 cents.
- Crypto: 3,204 rows; 3,176 settled/push rows; legacy return sum -1,642.948057 bps.
- Sports: 11,533 rows; 3,338 settled/push/void rows.
- Rejected records retained: 15,165.
- Unresolved records retained: 9,241.
- Duplicate Kalshi business-key groups: 0.

These are migration checks, not profitability evidence.

## Duplicate-import result

The first failed ordering attempt rolled back cleanly and left destination counts at zero. The importer was corrected to use dependency-safe table order. The successful import was then repeated:

- import status: `already_imported`
- inserted rows on repeat: 0
- destination counts changed: no
- aggregate differences: none
- unintended duplicate normalized compatibility records: 0
- immutable history preserved: yes

## Remaining parity blocker

The additive PostgreSQL ledger is not yet the active repository boundary. `paper_server.py`, `worker_services.py`, authentication, monitoring, reporting, crypto, sports, and settlement paths still instantiate the SQLite-only `ResearchStore`. Therefore:

- staging web migration/readiness is valid;
- compatibility-table import parity is valid;
- staging startup collection is only a web/SQLite smoke test;
- independent PostgreSQL workers and normalized report parity remain blocked;
- production PostgreSQL cutover remains prohibited.
