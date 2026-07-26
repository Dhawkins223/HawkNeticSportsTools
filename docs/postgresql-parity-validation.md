# PostgreSQL Validation

## Local evidence

The local Docker PostgreSQL service is validated through `./scripts/local.sh`.

| Gate | Required result |
| --- | --- |
| Empty database migration | all versioned migrations apply |
| Repeat migration | no pending work and no duplicate schema state |
| Import conflict check | identical duplicates reported; different content fails |
| Numeric round-trip | `9999999999.12345678` remains exact |
| JSONB round-trip | null, booleans, numeric zeroes, strings, arrays, and objects remain distinct |
| Concurrent migration | advisory lock serializes two migrators |
| Transaction claims | only one claimant can own an inbox item, batch completion, or worker transition |
| Reporting boundary | calendar-day behavior is stable around offset boundaries |

## Observed local result

On 2026-07-18, a fresh neutral-format export of the authoritative local
history was imported into the Docker-managed PostgreSQL service after applying
migrations `0001` through `0011`. Migration `0012` was subsequently applied to
record active worker ownership without changing imported research rows.
Migrations `0005` and `0006` remain hash-identical to the restored staging
history. Migration `0006` is the exact-numeric compatibility migration already
recorded in staging; migration `0007` moves former `public` tables into the
non-runtime `archive` schema and copies their active records into the
authoritative normalized relations.

| Check | Observed result |
| --- | --- |
| Migration from current local schema | ready; no pending versions |
| Historical records reconciled | 77,414 |
| Structured-data parse failures | 0 |
| Content conflicts | 0 |
| Repeated import inserts | 0 |
| Repeated import identical duplicates | 77,414 |
| Content-hash parity relations | 20 |
| Content-hash parity result | all matched |
| Data sent to hosted services | none |

The detailed source hashes, table counts, null/timestamp checks, numeric
aggregates, and target content hashes are recorded in
`docs/data-cutover-validation.md`.

## Hosted parity

No local development data is sent to staging or production. Railway staging
has an isolated PostgreSQL service, but it currently runs commit `1bfe8d4` from
`codex/finish-postgres-only-runtime`, not this branch. Validation of the final
migration set, a verified backup, a restore drill, and controlled hosted parity
remain pending. A mismatch in content hashes, business keys, numeric totals,
timestamps, status distributions, reports, or freshness output is a hard
failure.
