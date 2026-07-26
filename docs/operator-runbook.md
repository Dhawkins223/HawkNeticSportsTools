# Operator Runbook

## Start locally

```bash
cd /home/dahaw/projects/HawkNeticSportsTools
./scripts/local.sh db-start
./scripts/local.sh migrate
./scripts/local.sh dev
```

The dashboard remains research-only. `/healthz` reports process liveness; `/readyz` verifies database access, migration state, required schema, authentication configuration, and safety flags.

## Validate before changes leave local development

```bash
./scripts/local.sh test
./scripts/local.sh test-integration
./scripts/local.sh smoke
./scripts/local.sh verify
```

Run a routine status check without changing model logic:

```bash
cmd /c scripts\research_routine.cmd -Action status
cmd /c scripts\research_routine.cmd -Action once
```

## Worker rules

- Run one configured worker per responsibility.
- Workers claim ownership atomically, use idempotency keys, retain failures/rejections, and do not advance checkpoints until their transaction commits.
- Treat an unchanged fresh crypto heartbeat as `no_material_change`, not a failure.
- Do not force sports rows when a public source has no valid scheduled events.
- Optional connectors may degrade independently; they do not make a healthy core database appear unavailable.

## Operator inbox and authentication

Private operator messages are durable records in `ops.operator_messages`; they require manual review and never execute a command, deployment, or trade. Authentication state and audit history are retained in `auth` tables. Protected operational routes require the configured role and CSRF checks.

## Hosted safety

Never use local credentials for hosted services. Before staging or production work, follow `docs/railway-postgresql-deployment-and-rollback.md` and `docs/deployment-readiness-checklist.md`.
