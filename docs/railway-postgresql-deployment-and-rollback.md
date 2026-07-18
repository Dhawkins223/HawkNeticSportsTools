# Railway PostgreSQL Deployment and Rollback

## Environment separation

Use different hosted PostgreSQL services and credentials for staging and production. Keep databases private to Railway networking. Feature branches must not target a shared staging service automatically; production must not advance from an unreviewed branch or failing checks.

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
