# Repository Operating Rules

- Begin every task with `git status` and identify the active branch and workflow.
- Read `docs/operator-runbook.md` and `docs/platform-handoff-database-and-collection.md` before changing runtime, database, collector, or deployment behavior.
- Use the existing CLI and worker commands; do not create a parallel orchestration system.
- Require fresh, timestamped source data. Never represent stale cache, blocked sources, failed fetches, or historical backfills as current data.
- Exclude rejected, unresolved, blocked, invalid-settlement, stale-source, test-fixture, and duplicate records from performance metrics.
- Preserve all research-only controls: no live orders, automatic trading, slip upload, model promotion, or profitability/edge claims.
- Keep SQLite available for local use until PostgreSQL migration and parity validation succeed against a non-production database.
- Run `cmd /c scripts\test.cmd` after code changes and report changed, unchanged, blocked, and next-step items.
- Never expose or commit credentials, `.env` files, private keys, database URLs, Railway tokens, or connector secrets.
- Use reviewed feature branches and pull requests. Do not push directly to an unverified Railway deployment branch.
- Deployment gates and rollback requirements are defined in `docs/deployment-readiness-checklist.md` and `docs/railway-postgresql-deployment-and-rollback.md`.
