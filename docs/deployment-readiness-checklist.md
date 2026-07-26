# Deployment Readiness Checklist

## Required before any hosted database cutover

- [x] Local full test suite passes: 277 tests.
- [x] Empty PostgreSQL migration and repeat migration pass.
- [x] Concurrent migration lock test passes.
- [x] The staging-deployed `0006` checksum upgrades cleanly through `0007`-`0012`.
- [x] Exact numeric, JSONB, schema-isolation, and atomic-transition tests pass.
- [x] Staging has a separate PostgreSQL service and separate credentials.
- [ ] Staging migration, readiness, worker smoke, and neutral-import parity pass.
- [ ] Hosted backup exists and restoration is verified outside production.
- [ ] Production volume capacity and authoritative-data retention are audited.
- [ ] Research-only flags are verified in the target environment.
- [ ] Required authentication configuration is verified.
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
