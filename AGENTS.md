# Repository Rules

- Start with `git status`, identify the branch, and read `docs/operator-runbook.md` before changing runtime, data, or deployment behavior.
- GitHub Codespaces is the canonical development environment and GitHub is the source of truth. Do not require a Windows, WSL, OneDrive, or Docker Desktop checkout for development.
- PostgreSQL is the only supported database. Docker-in-Docker owns the Codespace dev/test service, Railway owns hosted databases, and every schema change requires a forward-only migration.
- Use `./scripts/local.sh test` after code changes. Keep Codespace test state isolated from development and never point it at Railway.
- Require fresh, timestamped sources. Do not label cached, blocked, failed, historical, rejected, unresolved, or duplicate rows as current or include them in performance metrics.
- Preserve research-only controls: no live orders, automatic trading, slip uploads, model promotion, or unsupported profitability claims.
- Never expose or commit credentials, private keys, database URLs, tokens, or local environment files.
- Use feature branches and pull requests. Do not push directly to `Master`, deploy, or alter hosted services without a documented readiness gate.
- Database architecture, data cutover evidence, and rollback gates are documented in `docs/`.
