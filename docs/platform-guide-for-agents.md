# Platform Guide For Agents

This repository is a private research platform for Kalshi, crypto, and sports research.
It is research-only and manual-review only. It does not place, stage, upload, or submit
real-money orders.

## What This Platform Is

- Local development lives in this repo and remains the source of truth during day-to-day work.
- SQLite is the active local business store today.
- PostgreSQL is staged and validated in isolation, but the hosted runtime still has cutover blockers.
- Railway is the hosted runtime target, not the place where the core workflow is defined.
- GitHub is the collaboration boundary for feature branches, review, and shared model work.
- Optional connectors fail closed instead of faking data or breaking the pipeline.

## Where To Look First

1. `README.md` for the fastest overview, quick-start commands, and the local dashboard entry points.
2. `docs/operator-runbook.md` for the private operator routine, worker cadence, and manual inbox rules.
3. `docs/platform-handoff-database-and-collection.md` for database boundaries and collection-loop design.
4. `docs/github-railway-firecrawl-workflow.md` for the GitHub / Railway / Firecrawl operating model.
5. `docs/railway-postgresql-deployment-and-rollback.md` for hosted deployment and rollback constraints.
6. `docs/deployment-readiness-checklist.md` and `docs/near-production-readiness.md` for launch gates.
7. `src/kalshi_research_bot/cli.py` for the actual command surface.
8. `src/kalshi_research_bot/connectors/` for optional integrations and their fail-closed behavior.
9. `data/` for the live reports, payloads, ledgers, and local evaluation database.

## Current Process

- Start by checking `git status`.
- Read the operator and handoff docs before changing runtime, collection, or deployment behavior.
- Use the existing CLI and worker commands instead of inventing a parallel orchestration layer.
- Keep fresh timestamped source data separate from stale cache, blocked fetches, and rejected rows.
- Exclude rejected, unresolved, stale-source, duplicate, and invalid-settlement rows from metrics.
- Keep all workflows research-only: no live orders, no automatic trading, no model promotion, no profitability claims.
- Run `cmd /c scripts\test.cmd` after code changes.
- Update docs whenever the workflow, data contract, connector status, or deployment path changes.

## How To Contribute

- Work on a small feature branch.
- Keep changes focused on one workflow boundary, connector, or report family at a time.
- Prefer existing helper commands under `scripts/` over new one-off entry points.
- Update or add tests when behavior changes.
- Update `.env.example` when new configuration is required.
- Keep secrets out of GitHub, local commits, and report artifacts.
- Keep any Railway change behind verified staging work first.

## Commands That Define The Workflow

```powershell
$env:PYTHONPATH = "src"
python -m kalshi_research_bot connectors-status
cmd /c scripts\research_routine.cmd -Action status
cmd /c scripts\research_routine.cmd -Action once
cmd /c scripts\test.cmd
cmd /c scripts\live.cmd --port 8765
cmd /c scripts\paper.cmd --port 8765
cmd /c scripts\today.cmd --date 20260702
```

## Contribution Rules

- Do not commit `.env`, private keys, Railway local state, SQLite files, or runtime reports.
- Do not push directly to an unverified deployment branch.
- Do not change live-order, auto-bet, or model-promotion boundaries without a separate safety review.
- Do not treat stale fallback data as fresh data.
- Do not merge unrelated connector changes into a workflow fix.

## For Other Models

When another model picks up this repo, it should read this guide first, then the operator runbook,
then the specific source file or worker command relevant to the task. The safest handoff path is:

1. Read the docs above.
2. Inspect `src/kalshi_research_bot/cli.py` for the command entry points.
3. Use the repository commands and existing worker services.
4. Keep changes narrow and test them locally.
5. Push only reviewed branch work, never direct to the deployment branch.

## What To Avoid

- Replacing the existing frontend, backend, or database with a new architecture.
- Treating MCP or any other connector layer as the platform itself.
- Introducing fake data to make a report look healthy.
- Broad refactors that are not tied to the requested change.
- Production deployment before the readiness checklist passes.
