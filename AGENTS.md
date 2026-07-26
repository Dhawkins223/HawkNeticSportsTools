# Repository Rules

- Start with `git status`, identify the branch, and read `docs/operator-runbook.md` before changing runtime, data, or deployment behavior.
- The canonical local checkout is `/home/dahaw/projects/HawkNeticSportsTools`; do not edit a parallel Windows or OneDrive copy.
- PostgreSQL is the only supported database. Docker owns the local service, and every schema change requires a forward-only migration.
- Use `./scripts/local.sh test` after code changes. Keep test state isolated from local development state.
- Require fresh, timestamped sources. Do not label cached, blocked, failed, historical, rejected, unresolved, or duplicate rows as current or include them in performance metrics.
- Preserve research-only controls: no live orders, automatic trading, slip uploads, model promotion, or unsupported profitability claims.
- Never expose or commit credentials, private keys, database URLs, tokens, or local environment files.
- Use feature branches and pull requests. Do not push directly to `Master`, deploy, or alter hosted services without a documented readiness gate.
- Database architecture, data cutover evidence, and rollback gates are documented in `docs/`.
