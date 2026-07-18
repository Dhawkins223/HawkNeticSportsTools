# Local Historical Data Cutover Validation

## Scope and safety boundary

The retired local research ledgers were assessed before the PostgreSQL-only
cutover. Valuable research, prediction, settlement, collection, monitoring,
and model-evaluation history was imported into the Docker-managed local
PostgreSQL service only. No local history was sent to Railway, staging, or
production.

| Source | Classification | Backup | Import result |
| --- | --- | --- | --- |
| evaluation ledger | authoritative local research history | `/home/dahaw/data-cutover-backups/hawknetic-20260718/` | imported and reconciled |
| research ledger | authoritative model-edge history | `/home/dahaw/data-cutover-backups/hawknetic-20260718/` | imported and reconciled |
| older snapshots, browser fixtures, and routine-validation artifacts | duplicate, test-only, or reconstructable | preserved outside Git; not imported | excluded deliberately |
| unrelated Goose session data | unrelated application data | untouched | excluded deliberately |

The two authoritative source hashes were:

- evaluation ledger: `fa1cc3b7e88d51c18dccdc0c876ebff5796788b722bb40a27909991461d6d8fd`
- research ledger: `60677b37aaaf49a4d19b3af2a62aedf578ee4f9b023d52c8338241f06f90e7f3`

The neutral export contained no malformed structured-data values. Source
timestamps were converted to timezone-aware UTC values, nullable fields stayed
nullable, and financial/probability fields were quantized only to the declared
PostgreSQL scale (12 or 16 decimal places, depending on the column).

## Reconciled records

The first complete import reconciled 77,414 historical records. The repeated
import added **zero** records, reported 77,414 identical duplicates, and found
zero content conflicts.

| Target relation | Rows | Content hash |
| --- | ---: | --- |
| `app.prediction_logs` | 12,597 | `8c234e394b6369e441a18864ebb05f808f4fc8d76f56f5526266692cdeb260fb` |
| `app.prediction_rejections` | 19,740 | `f9b936fc30e0582855e92c4c039a03c5d1cb762ebb597df21ef987f4a3927043` |
| `app.settlement_audit` | 20,338 | `c56b85db266cba33c3833439d3ddad178f1a478e65073afe5e43849bea1e3a39` |
| `app.crypto_prediction_logs` | 4,370 | `d68060cbc69923c8df7a5f092ec16c4479808a28f638753309563b79f5eae568` |
| `app.crypto_prediction_rejections` | 22 | `fc089c303c83f8727e3567fd1c1a4fcea4c04ebf90d9e4b67132bb67407fa253` |
| `app.sports_prediction_logs` | 11,737 | `c918e7d58680377c6a3d9507117a3a51ff536f1baed6fadd8a58b2f3c5350988` |
| `app.sports_prediction_rejections` | 1,367 | `9e8b4853a3d2c00f5fd8df93f5c51b30d822183a81925dcf6cacfc5bf41f7016` |
| `app.model_evaluations` | 10 | `7cbcaeb60425d14ff8d6b4b03aba12d5da4689dbfd1f9fd22f7c66935593520f` |
| `app.model_evaluation_predictions` | 7,022 | `ee8fb878b15d5181410b27221697720470110658eca7a689f94a7118d022cc73` |
| `app.paper_test_runs` | 1 | `f2dc49eddc0896855514d1316ed651d16d7041f52272d4e7f96ae02624cf1f91` |
| `app.edge_results` | 2 | `c8815029010fcdc3b539184d726fdd2f95e3de7d0bda00eb6d395e8ff07f6b60` |
| `raw.ingestion_batches` | 39 | `e68d2c221bd52727fb84a0a2c927fc1eaf7f57da9603c86313a2b9aae852feb1` |
| `raw.source_payloads` | 74 | `d8c6264f959c65ce1bf93ffb4ff01fe80a3669ad90b594243bb7cc1f8a17c04b` |
| `raw.rejected_records` | 39 | `82dc6cc0fcd5be74534718a4b4f1a43867dc6657ad83d70b820116f1f95651d7` |
| operational health, checkpoints, runs, reports, and audit records | 95 | individually content-verified |

Business-key uniqueness, status distributions, null preservation, and minimum/
maximum timestamps were checked by the neutral manifest. A different row
content hash is a hard import conflict even when row counts match.

## Numeric aggregate reconciliation

| Relation | Verified aggregate values |
| --- | --- |
| `app.prediction_logs` | profit/loss `6207.000000000000`; entry prices `1050511.000000000000`; implied probability `10191.680497000000` |
| `app.settlement_audit` | new profit/loss `5095.000000000000`; previous profit/loss `-1112.000000000000` |
| `app.crypto_prediction_logs` | entry price `142474926.800000000000`; settlement price `141556421.120000000000`; return basis points `1336.170204000000` |
| `app.sports_prediction_logs` | odds `-608314.000000000000`; line `33368.500000000000`; confidence `6369.410038000000` |
| `app.model_evaluation_predictions` | model probability `2342.0070630000000000`; market-implied probability `4184.2556430000000000`; probability difference `13.5070629999999864` |
| `app.edge_results` | expected value `3.980000000000`; entry price `90.000000000000`; fair price `93.980000000000` |

## Import contract

`src/kalshi_research_bot/postgres_import.py` accepts canonical neutral rows.
It serializes each target table with one transaction-scoped advisory lock,
compares deterministic content hashes for every business key, and treats
identical records separately from conflicts. Generated identifiers are recorded
in `ops.import_lineage`, so restart/replay behavior remains content-validated.

Temporary source-reader scripts and neutral files live outside the repository.
Only the PostgreSQL-native importer and its regression tests remain in the
project tree.
