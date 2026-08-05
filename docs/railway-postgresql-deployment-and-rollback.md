# Railway PostgreSQL Deployment and Rollback

## Environment separation

Use different hosted PostgreSQL services and credentials for staging and production. Keep databases private to Railway networking. Feature branches must not target a shared staging service automatically; production must not advance from an unreviewed branch or failing checks.

Read-only discovery on 2026-08-03 found the PostgreSQL cutover merged to
`Master` at `b4c86b5`, while production remained on rollback commit `b687c7d`.
The production service had no active repository source and no PostgreSQL
binding, so it could not deploy the merged runtime safely or automatically.

## Railway service roles

Every service deploys the same reviewed image and selects one role through
`HAWKNETIC_SERVICE`:

- `web`: serves the redesigned dashboard and reads the latest completed Kalshi payload from `raw.source_payloads`.
- `kalshi-market-ingestion`: collects fresh public Kalshi evidence and persists the immutable payload plus normalized markets.
- Other values must match a worker in `worker_services.SERVICE_SPECS`.

The web role does not collect on a timer. This prevents duplicate collectors
and makes PostgreSQL the handoff boundary between agents and the Railway UI.
Missing, failed, or stale snapshots block contracts and slips rather than
falling back to a generated file.

## Deployment sequence

1. Validate the local branch and full test suite.
2. Verify the staging branch, service, and variables by name only.
3. Create and verify a staging backup.
4. Run the migration-only pre-deploy command.
5. Verify `/healthz`, `/readyz`, worker ownership, source freshness, and research-only controls.
6. Run a controlled neutral-format parity import only when needed.
7. Record the deployed commit and migration revision.

The pre-deploy command may run migrations only. It must not seed data, collect sources, start workers, train models, alter safety flags, or reset data.

## Rollback

Before production mutation, record the previous deployed commit, current migration revision, target revision, backup timestamp, and service identity. Code rollback may restore the previous service image; data restoration must be tested outside production first. Do not use an unverified restore as a recovery plan.
