# PostgreSQL-Only Conversion Report

This branch removes retired local database implementation paths and standardizes local and test persistence on PostgreSQL. The conversion preserves research-only controls, source freshness gating, rejection retention, and manual review boundaries.

Local historical data is now reconciled into the Docker-managed PostgreSQL
service with a zero-conflict, zero-duplicate replay result. The final complete
suite passed 277 tests, and `./scripts/local.sh verify` completed successfully
with migrations `0001` through `0012` current. Hosted staging still runs an
older reviewed branch, and production still runs the rollback commit without a
production PostgreSQL service. Those hosted cutover gates are not implied by
the local result.

The checksum already recorded for staging migration `0006` is preserved
byte-for-byte. The PostgreSQL-only schema move is versioned as `0007`, and a
clean staging-history upgrade regression verifies that the current migration
head applies without a checksum mismatch.
