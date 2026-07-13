# Deployment Readiness Checklist

Current state: **research_operational**, not deployment-ready or production-ready.

## Git

- [x] Local active branch inspected: `main`.
- [x] Remote default branch inspected: `Master`.
- [x] `origin/main` and `origin/Master` currently resolve to the same commit.
- [ ] Confirm Railway's actual watched branch in the Railway dashboard.
- [ ] Resolve the `main` versus `Master` policy without blind renaming.
- [ ] Review all existing dirty changes; none have been committed by this phase.
- [ ] Commit on a reviewed `codex/...` branch only after authorization.
- [ ] Push only after explicit authorization.

## Database

- [x] Additive SQLite migrations and hash checks exist.
- [x] PostgreSQL schema, indexes, constraints, and pooling configuration exist.
- [x] SQLite export manifest validates row counts, hashes, and critical aggregates.
- [x] PostgreSQL import is idempotent and requires explicit confirmation text.
- [ ] Run a real PostgreSQL migration against a non-production database.
- [ ] Switch business query paths from SQLite before enabling independent PostgreSQL workers.
- [ ] Complete backup and restore drill.

## Authentication

- [x] Hosted auth remains required by default.
- [x] Basic auth remains an emergency owner fallback.
- [x] Local scrypt accounts, admin/researcher/read-only roles, session expiry, CSRF, lockout, audit, and disabling exist.
- [x] Refresh and internal status require admin role.
- [x] The operator/Codex inbox is admin-only, CSRF-protected for sessions, and non-executing.
- [ ] Create the first admin through the environment-gated local CLI.
- [ ] Verify hosted session login flow over HTTPS.
- [ ] Establish account recovery and password rotation procedure.
- [ ] Decide whether hosted operator messages remain local-only or move through a separately reviewed private storage path; they are excluded from research-history exports.

## Research Evidence

- [x] Time-aware probability validation and leakage gates exist.
- [x] Market baseline, base rate, calibration, ensemble, and walk-forward support exist.
- [x] Cost-aware fill and event-exposure audits exist.
- [ ] No model currently qualifies for promotion.
- [ ] Accumulate clean sports rows after the timestamp fix.
- [ ] Validate any challenger on untouched data and portfolio return after costs.

## Operations

- [x] Independent worker commands, retries, backoff, idempotency, and graceful shutdown exist.
- [x] Admin-only status and optional deduplicated Slack alerts exist.
- [ ] Create independent Railway services only after database and branch confirmation.
- [ ] Verify one complete hosted ingestion/settlement/report cycle per service.
- [ ] Configure external uptime checks without exposing internal status.

## Security Rotation

Credentials previously pasted into chat or visible screenshots must be treated as compromised and rotated before deployment:

- Firecrawl API key;
- Kalshi API key identifier and associated private key;
- any dashboard password or Railway credential ever exposed in terminal/chat output.

Never commit replacements. Store them only in local `.env` (ignored) or Railway Variables. Review logs before deployment to confirm no credential values appear.

## Exact Safe Sequence After Authorization

```powershell
git status --short
git branch --show-current
git diff --check
cmd /c scripts\test.cmd

# Confirm Railway watched branch in the dashboard before continuing.
git switch -c codex/research-platform-hardening
git add <reviewed files only>
git commit -m "Harden research validation and operations"
git push -u origin codex/research-platform-hardening
# Open a reviewed PR into the confirmed deployment branch.
```

Database and Railway service commands are intentionally omitted from this sequence until a non-production PostgreSQL migration succeeds and the watched branch is confirmed.
