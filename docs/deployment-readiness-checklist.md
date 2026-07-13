# Deployment Readiness Checklist

Current state: **research_operational**, not deployment-ready or production-ready.

## Git

- [x] Local active branch inspected and isolated as `codex/postgres-collector-railway-hardening` from `main`.
- [x] Remote default branch inspected: `Master`.
- [x] `origin/main` and `origin/Master` currently resolve to the same commit.
- [x] Confirm Railway's actual watched branch in the Railway dashboard: production watches `Master`.
- [ ] Resolve the `main` versus `Master` policy without blind renaming.
- [x] Existing documentation changes were reviewed and preserved as task-relevant work.
- [x] Commit only reviewed task diffs on the isolated branch.
- [x] Push the feature branch and keep draft PR #52 open without merging.

## Database

- [x] Additive SQLite migrations and hash checks exist.
- [x] PostgreSQL raw/core/research/ops/reporting schemas, exact numerics, lineage constraints, indexes, and pooling configuration exist.
- [x] SQLite export manifest validates row counts, hashes, and critical aggregates.
- [x] Quality reporting separates mandatory core checks, workflow readiness, optional capability status, and deployment readiness.
- [x] Firecrawl defaults to optional and no longer lowers the mandatory core-quality score when unconfigured.
- [x] Sports uses a configured local-first plan: official API, public structured HTTP, then optional Firecrawl.
- [x] PostgreSQL import is idempotent and requires explicit confirmation text.
- [x] Run a real PostgreSQL migration against an isolated non-production database.
- [ ] Switch business query paths from SQLite before enabling independent PostgreSQL workers.
- [ ] Complete backup and restore drill; Railway Hobby has no volume Backups/PITR.
- [ ] Map the new local collection-ledger export into authoritative PostgreSQL schemas.
- [ ] Demonstrate report/evaluation/return parity; export validation alone is insufficient.

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
git switch codex/postgres-collector-railway-hardening
git add <reviewed files only>
git commit -m "Harden research validation and operations"
git push -u origin codex/research-platform-hardening
# Open a reviewed PR into the confirmed deployment branch.
```

Database and Railway service commands are intentionally omitted from this sequence until a non-production PostgreSQL migration succeeds and the watched branch is confirmed.

## PostgreSQL staging gates added in this phase

- [x] Forward-only migration `0003` adds normalized research-ledger schemas without changing legacy tables.
- [x] SQLite migration `0003` adds idempotent batches, raw payload hashes, rejected records, transactional checkpoints, and explicit source freshness.
- [x] `/readyz` includes database migration state and hosted research-safety flags.
- [x] Railway config contains a migration-only pre-deploy command.
- [x] Rollback procedure exists in `docs/railway-postgresql-deployment-and-rollback.md`.
- [x] Railway CLI authentication and project link verified.
- [x] Staging environment, service source branch, and PostgreSQL persistence verified.
- [x] Empty PostgreSQL migration passed through revision `0004`.
- [x] Staging compatibility import, row/hash parity, and duplicate-import safety passed.
- [ ] Full normalized report/runtime parity passed; business query paths still use SQLite.
- [ ] Repeated staging collector pass proved idempotent.
- [ ] Production backup and rollback evidence recorded.
- [x] Re-audit the production Railway volume: 625.287 MB used of 5,000 MB; prior full signal is resolved.
- [x] Create an isolated staging environment and one PostgreSQL service.
- [x] Keep staging on the existing Hobby project without adding paid features.

## Current validation evidence

- Full suite: 234/234 passed.
- Core platform quality: 100/100.
- Kalshi workflow: 100/100 and ready.
- Crypto workflow: 100/100 and ready.
- Sports workflow: 55/100 and blocked because the fresh ESPN scoreboard contained no scheduled events; the blocked row remains excluded from metrics.
- SQLite export: 17 tables, zero validation errors, export id `sha256:2e50f51a0db430fff302387be8e54fb44059f0694a40da9338cd1c89974dab1d`.
- PostgreSQL staging migration, compatibility import, repeat import, `/healthz`, and `/readyz` pass.
- Production remains blocked by unavailable Hobby-plan backups/PITR, no restoration drill, incomplete PostgreSQL business query paths, and required credential rotation.
