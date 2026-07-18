# Deployment Readiness Checklist

## Required before any hosted database cutover

- [ ] Local full test suite passes.
- [ ] Empty PostgreSQL migration and repeat migration pass.
- [ ] Concurrent migration lock test passes.
- [ ] Exact numeric, JSONB, schema-isolation, and atomic-transition tests pass.
- [ ] Staging has a separate PostgreSQL service and separate credentials.
- [ ] Staging migration, readiness, worker smoke, and neutral-import parity pass.
- [ ] Hosted backup exists and restoration is verified outside production.
- [ ] Production volume capacity and authoritative-data retention are audited.
- [ ] Research-only flags are verified in the target environment.
- [ ] Required authentication configuration is verified.
- [ ] No secret appears in a diff, log, report, or build output.
- [ ] Railway deployment trigger policy is reviewed and restricted.

## Hard stops

Do not change production if a migration fails, a content hash conflicts, a backup or restore is unverified, readiness is false, data is stale, safety flags are disabled, or an external source failure has been misrepresented as healthy.
