# Repository Operating Rules

- The canonical local checkout is the native WSL repository at `/home/dahaw/projects/HawkNeticSportsTools`; do not edit it and the OneDrive copies in parallel.
- GitHub is the version-control source of truth. One writer owns each branch or worktree; never commit directly to `Master`.
- PostgreSQL is the only supported application runtime database. Docker Compose manages the local database; SQLite is archive/import evidence only.
- Schema changes require versioned PostgreSQL migrations. Never add a runtime fallback to SQLite.
- Do not access Railway or production without explicit authorization. This local workflow must not use hosted database URLs.
- Never commit secrets, `.env` files, private keys, or database URLs with credentials.
- Do not change prediction, settlement, financial, scraping, safety, live-execution, automatic-trading, or slip-upload logic during infrastructure work.
- After code changes run `./scripts/local.sh verify` from the repository root and report changed, unchanged, blocked, and next-step items.
