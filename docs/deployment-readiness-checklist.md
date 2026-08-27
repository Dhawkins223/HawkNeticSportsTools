# Deployment Readiness Checklist

## Check the environment before reading this list

Four of the items below are properties of a running environment rather than of
the code, and they were left unticked for a while because confirming them meant
running several things and knowing how to read each. One read-only command now
reports them together:

```bash
DATABASE_URL=<target> PYTHONPATH=src python -m kalshi_research_bot preflight
```

It applies nothing and creates nothing, so it is safe to point at production. It
exits non-zero when a gate blocks, so it also works as a deployment guard. A
check that cannot run reports `unknown` and blocks: not knowing and being fine
are the two states it exists to keep apart.

It covers migration state, the research-only controls, the authentication
posture, and whether an account that can actually sign in exists. It does **not**
cover backups, volume capacity, secret scanning, or the deploy-trigger policy —
those still need a person.

## Required before any hosted database cutover

- [x] Local full test suite passes: 685 tests.
- [x] Empty PostgreSQL migration and repeat migration pass.
- [x] Concurrent migration lock test passes.
- [x] The staging-deployed `0006` checksum upgrades cleanly through `0007`-`0012`.
- [x] Migration execution has a separately configurable statement timeout.
- [x] Password-only Basic authentication remains available during the account cutover.
- [x] Exact numeric, JSONB, schema-isolation, and atomic-transition tests pass.
- [x] Staging has a separate PostgreSQL service and separate credentials.
- [ ] Staging migration, readiness, worker smoke, and neutral-import parity pass.
- [ ] Hosted backup exists and restoration is verified outside production.
- [ ] Production volume capacity and authoritative-data retention are audited.
- [ ] Research-only flags are verified in the target environment. *(`preflight`: `safety_controls`)*
- [ ] Required authentication configuration is verified. *(`preflight`: `auth_configuration`, `sign_in_possible`)*
- [ ] Every migration in the tree is applied to the target database. *(`preflight`: `migrations`)*
- [ ] No secret appears in a diff, log, report, or build output.
- [ ] Railway deployment trigger policy is reviewed and restricted.

## Hosted safety configuration

Hosted readiness requires explicit values for `RESEARCH_ONLY=true`,
`LIVE_EXECUTION_ENABLED=false`, `AUTO_UPLOAD_ENABLED=false`,
`AUTO_TRADE_ENABLED=false`, `KALSHI_ORDER_UPLOAD_ENABLED=false`,
`MODEL_PROMOTION_ENABLED=false`, `STALE_CACHE_AS_FRESH=false`, and
`DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED=true`. Missing hosted controls block
readiness rather than inheriting a local default.

## Hard stops

Do not change production if a migration fails, a content hash conflicts, a backup or restore is unverified, readiness is false, data is stale, safety flags are disabled, or an external source failure has been misrepresented as healthy.
