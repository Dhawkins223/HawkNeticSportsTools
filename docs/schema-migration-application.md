# How a Merged Migration Reaches the Database

## The gap

Merging a migration does not apply it. Migration `0013` sat in `Master` for days
while every worker running `DATABASE_MIGRATION_MODE=check` crash-looped on
`postgres_database_not_ready:['0013']`. It was applied by hand, not by a
deployment.

`docs/railway-worker-services.md` used to say the repository-root `railway.json`
"carries the web service's pre-deploy migration". That is what the file
declares. It is not what production does.

## What production actually shows

Reading the production service configuration in the `jubilant-liberation`
project, the web service and the workers differ in a way that matters:

| | Web service | Worker services |
| --- | --- | --- |
| `source` block | **absent** | `repo` + `branch` |
| `configFile` | **absent** | `railway.worker.json` |
| `preDeployCommand` | **absent** | `[]` |
| Start command | `paper --refresh-seconds 300` | from the config file |

A Railway service with no `source` has no repository to build from on merge and
no repository file to resolve config-as-code against. Both consequences follow
from the same missing block:

1. **Merges do not deploy the web service.** Its last deployment carrying commit
   metadata was 2026-07-18. Later deployments record `reason: deploy` with no
   commit, hash, or branch — uploads of a local directory, not builds of a merge.
2. **The pre-deploy migration never runs.** The live start command
   (`paper --refresh-seconds 300`) is not the one root `railway.json` declares
   (`service-start`), which is direct evidence the file is not being applied.
   The workers use `railway.worker.json`, which has no pre-deploy command by
   design. So no service in production runs `database-migrate` on deploy.

Nothing applies migrations. That is the defect, and it is a configuration
defect rather than a code one.

## Why `service-start` was not a drop-in replacement

The obvious fix — connect the web service to the repository and let root
`railway.json` take over — would have degraded the dashboard, because the two
start commands did not mean the same thing.

`run_hosted_service` hardcoded `refresh_seconds=0` for the web role. Zero
disables the startup refresh, the background refresh thread, and the page's
meta-refresh alike. Production runs `--refresh-seconds 300`, and `/readyz`
reports `data_gate: fresh_data_ready` only while those refreshes keep happening.
Adopting config-as-code unchanged would have stopped them silently.

The cadence now comes from `DASHBOARD_REFRESH_SECONDS` and defaults to 300,
matching what the hosted dashboard already runs, so the repository's declared
start command and the deployed one finally mean the same thing. Zero is still
accepted for a deployment whose data comes only from collector workers.

## Applying this

Reconnecting the web service to the repository fixes both halves at once —
merges build it, and its pre-deploy command applies migrations. Do it in this
order, because the second step is only safe after the first:

1. Land the start-command equivalence above so config-as-code is not a
   behavioural change.
2. Connect the web service to `Dhawkins223/HawkNeticSportsTools` on `Master`
   with config path `railway.json`.
3. Confirm on the next deployment that the pre-deploy `database-migrate` ran,
   that `/readyz` still reports `data_gate: fresh_data_ready`, and that
   `database.pending_versions` is empty.

Until step 2 is done, a merged migration still has to be applied deliberately.
Treat `postgres_database_not_ready` in a worker's logs as the symptom of an
unapplied migration, not of an unhealthy database.

## Why not verify the workers' way instead

Workers verify rather than apply, and that separation is deliberate: a worker
that applies schema changes couples every collector's deployment to database
availability and lets any of them race the others. The fix is to give the
applying role a working trigger, not to spread the applying role around.
