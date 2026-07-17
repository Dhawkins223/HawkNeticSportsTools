# Private Research Platform Operator Runbook

Status: **research operational**. This is a private research and manual-review system. It does not place, stage, upload, or submit orders.

Database and deployment references:

- `docs/database-schema-audit.md`
- `docs/sqlite-postgresql-migration-map.md`
- `docs/postgresql-parity-validation.md`
- `docs/railway-postgresql-deployment-and-rollback.md`

## What Moved Into the New Routine

The hardened code keeps the existing data collectors and reports, but exposes each responsibility as an isolated worker. This lets one source fail without stopping the others.

| Existing job | New isolated routine | Cadence |
|---|---|---:|
| live Kalshi dashboard refresh | `kalshi-market-ingestion` | 5 minutes |
| optional configured public sources | `external-source-ingestion` | 15 minutes |
| Coinbase/Kraken research | `crypto-research` | 15 minutes |
| public sports research | `sports-research` | 60 minutes |
| official Kalshi settlement import | `settlement-worker` | 60 minutes |
| reports, return audit, and monitoring | `reporting-evaluation` | 6 hours |
| dashboard | `paper` web process | continuous |

The existing Windows scheduled tasks still work. They were not deleted or silently replaced. The new worker commands are the migration target for independent Railway services after PostgreSQL and the deployment branch are verified.

Daily QA, feature exports, diagnostics, optional archive, and local company briefs remain explicit auxiliary scripts. They do not train a model or change live rules.

## First Local Start

Open PowerShell:

```powershell
cd C:\Users\dahaw\OneDrive\Documents\Playground\kalshi-research-bot
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_postgres_runtime.ps1
cmd /c scripts\test.cmd
cmd /c scripts\live.cmd --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The public review dashboard remains separate from the private operations page.

## Slip Integrity Gate

Every visible `BUILD_SLIP` must reproduce the complete `mve_selected_legs` set of one current, active, quoted Kalshi `KXMVE` market. The parent combo ticker, live YES ask, fetch timestamp, snapshot hash, exact leg count, and deterministic selected-leg signature travel with the slip. Legs from separate combo markets are never merged, and a subset of a listed combo is never presented as enterable.

If that evidence is absent or inconsistent, the dashboard, review packet, and prediction logger fail closed to `NO_SLIP`. An operator must still confirm the parent KXMVE ticker and each underlying ticker in Kalshi before manual review; the platform never creates, stages, uploads, or submits an order.

## Run the Research Routine

Show workers, connectors, and queued operator messages without collecting anything:

```powershell
cmd /c scripts\research_routine.cmd -Action status
```

Run one failure-isolated pass of Kalshi, crypto, sports, settlement, and reporting:

```powershell
cmd /c scripts\research_routine.cmd -Action once
```

The routine continues to later services if one source is blocked. It never fabricates data. A no-material-change result is healthy when sources are fresh but unchanged.

Run one worker for a smoke check:

```powershell
$env:PYTHONPATH = "src"
python -m kalshi_research_bot worker --service crypto-research --once
```

Run one worker continuously:

```powershell
$env:PYTHONPATH = "src"
python -m kalshi_research_bot worker --service crypto-research
```

Use one process or Railway service per continuous worker. All runtime workers use PostgreSQL and retain transactional checkpoint and idempotency protection. Do not configure a SQLite writer or fallback in any environment.

## Where To Put Messages For Codex

### Dashboard inbox

1. Sign in as an `admin`.
2. Open [http://127.0.0.1:8765/ops](http://127.0.0.1:8765/ops).
3. Enter a title, priority, target, and full instruction.
4. Select **Queue for review**.

The message is stored in the active PostgreSQL `operator_messages` table. It is not sent to a shell, AI model, GitHub, Railway, Kalshi, or any external service. It remains queued until a human or an explicitly started Codex task reviews it.

Do not put API keys, passwords, private keys, personal data, or trading credentials in the inbox.

### File-based CLI inbox

Put the instruction in an ignored local UTF-8 text or Markdown file under `data\operator_messages\`. Reading the body from a file keeps long prompts out of shell history and the ignored `data\` path prevents accidental Git staging:

```powershell
$env:PYTHONPATH = "src"
New-Item -ItemType Directory -Force data\operator_messages | Out-Null
python -m kalshi_research_bot operator-message-add `
  --title "Review sports source quality" `
  --file .\data\operator_messages\private-task.md `
  --priority high `
  --target codex
```

List queued work:

```powershell
python -m kalshi_research_bot operator-message-list --status queued
```

Codex or another reviewed local agent claims the message before work:

```powershell
python -m kalshi_research_bot operator-message-claim --message-id <message-id> --agent codex
```

After review and testing, put the result summary in a file and close the queue item:

```powershell
python -m kalshi_research_bot operator-message-complete `
  --message-id <message-id> `
  --agent codex `
  --summary-file .\data\operator_messages\private-result.md
```

Every inbox row is permanently marked `requires_approval=true` and `execution_allowed=false`. Queueing a prompt does not authorize deployment, Git pushes, account access, order upload, or trading.

### Codex app versus the platform inbox

- Use the Codex app conversation for immediate interactive work.
- Use `/ops` when you want a durable backlog visible from the private platform.
- Use GitHub Issues or pull requests for tasks that multiple AI coding tools need to share. Never let multiple models push directly to the deployment branch.
- The platform does not autonomously wake Codex or run queued instructions. That boundary is intentional.

## First Admin Account

Account creation is disabled by default. Create an owner account locally without putting the password on the command line:

```powershell
cd C:\Users\dahaw\OneDrive\Documents\Playground\kalshi-research-bot
$env:PYTHONPATH = "src"
$env:AUTH_REGISTRATION_ENABLED = "true"
$env:AUTH_NEW_USER_PASSWORD = Read-Host "New password"
python -m kalshi_research_bot auth-create-user --username owner --role admin
Remove-Item Env:AUTH_NEW_USER_PASSWORD
Remove-Item Env:AUTH_REGISTRATION_ENABLED
```

Then set `DASHBOARD_USER_AUTH_ENABLED=true`. Hosted environments must use HTTPS and Railway Variables; never commit passwords.

## Routine Status And Reports

```powershell
$env:PYTHONPATH = "src"
python -m kalshi_research_bot worker-status
python -m kalshi_research_bot connectors-status
python -m kalshi_research_bot data-quality
python -m kalshi_research_bot model-evaluate
python -m kalshi_research_bot kalshi-return-audit --run-id stage3a_20260703_170707
```

The quality report separates three different questions:

- **Core quality**: database audit availability, metric-denominator guards, and research-only safety controls.
- **Workflow quality**: Kalshi, crypto, and sports are evaluated independently; one blocked source does not downgrade unrelated workflows.
- **Deployment readiness**: PostgreSQL parity, staging validation, backup verification, and production-volume health remain independent infrastructure gates.

Data quality is not source availability, and neither is deployment readiness. Firecrawl defaults to `FIRECRAWL_MODE=optional`; its absence is visible as `unavailable_optional` but does not lower core quality. Sports remains blocked whenever its own configured source plan cannot produce fresh validated rows.

Sports retrieval is local-first and explicitly configured with `SPORTS_RETRIEVAL_PLAN`. The default controlled order is `official_api,http_json,firecrawl`: a configured official API is used first, ESPN public JSON is the free structured fallback, and Firecrawl is attempted only when configured. Playwright is not installed in the web runtime because the current source exposes structured JSON.

Important paths:

- live dashboard payload: `data\today_paper_view.json`
- research database: PostgreSQL configured through `DATABASE_URL`; the legacy SQLite archive is not a runtime database
- worker logs and local status: `data\daemon\`
- Kalshi reports: `data\paper_runs\`
- crypto reports: `data\crypto_runs\`
- sports reports: `data\sports_runs\`
- model audit: `data\model_validation_audit.txt`
- operator messages: private database table only

For a compact shareable summary of the database and data-collection setup, use:

- `docs/platform-handoff-database-and-collection.md`

## Hosted/Railway Boundary

Do not deploy the independent worker topology yet. Remaining blockers are:

1. rotate previously exposed credentials;
2. validate this PostgreSQL-only runtime branch against isolated Railway staging;
3. populate and validate normalized reporting views with a fresh staging import;
4. obtain a verified production backup method and test restoration outside production;
5. verify hosted session login over HTTPS;
6. run one complete hosted ingestion, settlement, and reporting cycle using PostgreSQL.

The normalized PostgreSQL research ledger is now the only runtime boundary. A valid archived-SQLite export is still only a parity artifact; it does not permit a fallback to SQLite. The current branch must pass fresh staging import and report comparisons before production can change.

Previous Railway staging evidence belongs to an earlier runtime branch and must be revalidated before cutover. Production watches `Master`, remains unchanged, and still requires a verified backup/restore path. Do not treat a past staging import or a resolved volume alert as authorization to deploy this branch.

Before the final database export/import, pause local writers, create and validate a fresh snapshot, import that exact snapshot, compare counts/aggregates, and only then resume collection.

The web service can continue using the existing workflow while those blockers are resolved. The operator inbox is deliberately excluded from research-history exports because prompts may contain private operating context.

## Shutdown

- Dashboard: press `Ctrl+C` in its terminal.
- Continuous worker: press `Ctrl+C`; it records graceful shutdown intent.
- Windows scheduled tasks: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall_tasks.ps1`.
- Railway: stop only the individual service in Railway after deployment is explicitly authorized.

No shutdown step should delete PostgreSQL data, the legacy SQLite archive, or report directories.

## Reproducible Browser States

The browser fixture server never refreshes live sources or writes prediction rows. Use it only for local visual QA:

```powershell
$env:PYTHONPATH = "src"
python scripts\browser_validation_server.py --state empty --port 8780
python scripts\browser_validation_server.py --state stale --port 8781
python scripts\browser_validation_server.py --state error --port 8782
python scripts\browser_validation_server.py --state loading --port 8783
```

Open the matching local URL and verify the empty, blocked-stale, source-error, and loading presentations. Stop each fixture with `Ctrl+C`.
