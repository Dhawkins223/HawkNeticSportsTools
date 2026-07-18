# PostgreSQL-Only Conversion Report

This branch removes retired local database implementation paths and standardizes local and test persistence on PostgreSQL. The conversion preserves research-only controls, source freshness gating, rejection retention, and manual review boundaries.

Local historical data is now reconciled into the Docker-managed PostgreSQL
service with a zero-conflict, zero-duplicate replay result. The final complete
suite and clean-worktree verification must still be rerun before merge. Hosted
staging and production remain separate readiness gates and are not implied by
repository changes.
