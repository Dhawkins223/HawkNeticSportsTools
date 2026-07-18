# Platform Handoff: Database And Data Collection

Status: research operational. This platform is private, research-only, and manual-review only. It does not place, stage, upload, or submit orders.

## What Is Already In Place

- Local dashboard on `127.0.0.1:8765`.
- Private operator inbox at `/ops`.
- Workerized collection loops for Kalshi, crypto, sports, external sources, settlement, and reporting.
- PostgreSQL is the active local application runtime for all workers, reports, authentication, and the dashboard.
- SQLite is retained only as a read-only legacy archive/import and rollback source; it is never an active business runtime or fallback.
- Optional connectors degrade gracefully instead of breaking the pipeline.
- Core quality, per-workflow source quality, optional capability status, and deployment readiness are reported independently.

## Database

### Current State

- Local development uses the PostgreSQL runtime launched by `scripts\start_postgres_runtime.ps1`.
- The active PostgreSQL boundary covers workers, reports, authentication, operations, and the dashboard.
- Existing SQLite history is preserved as read-only archive evidence for the explicit export/import tool only.
- Earlier staging evidence must be rerun against this branch before production changes.

### What To Use

- Local development and research: PostgreSQL only.
- Hosted deployment target: PostgreSQL after isolated staging parity, worker smoke tests, backup/restoration evidence, and reviewed deployment authorization.

### Safe Commands

```powershell
cd C:\Users\dahaw\OneDrive\Documents\Playground\kalshi-research-bot
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_postgres_runtime.ps1
cmd /c scripts\research_routine.cmd -Action status

# One-time read-only archive/import workflow only; never use as application runtime.
$env:PYTHONPATH = "src"
python -m kalshi_research_bot database-export-sqlite --sqlite-db <legacy-archive.sqlite> --output data\postgres_export
python -m kalshi_research_bot database-validate-export --sqlite-db <legacy-archive.sqlite> --input data\postgres_export
```

### PostgreSQL Readiness

- PostgreSQL migration files exist under `migrations\postgres\` and are applied through the configured migration role.
- Import/export validation is deterministic and archive-only.
- Authentication, session, login-audit, and operator-message tables are deliberately excluded from archive exports and never exposed in reports.
- A real import must happen against a non-production database first.
- Do not configure SQLite writers in local or hosted replicas.

### Database Safety Rules

- Do not delete the archived SQLite evidence without an independently verified backup.
- Do not commit secrets.
- Do not assume a PostgreSQL import is production-ready until counts and aggregates are validated.
- Do not change production PostgreSQL without a tested staging migration, import, and rollback path.
- Treat `docs/postgresql-parity-validation.md` as the cutover gate. Archive validation is not destination parity.

### Research ledger additions

- `raw`: immutable ingestion batches, payloads, and rejected records.
- `core`: series/event/market identity plus append-only observations, trades, books, and settlement revisions.
- `research`: immutable feature cutoffs, prediction runs, separate outcomes, simulation fills, exposure, and versioned metrics.
- `ops`: worker runs, source health, transactional checkpoints, backfills, quality, audit, migrations, and report refreshes.
- `reporting`: controlled read views that exclude rejected, blocked, stale, duplicate, and unverified rows.

See `docs/database-schema-audit.md` and `docs/sqlite-postgresql-migration-map.md` before modifying these structures.

## Data Collection

### Current Collection Loops

| Loop | Purpose | Cadence | Main command |
|---|---|---:|---|
| Kalshi market ingestion | Public market/schedule refresh | 5 min | `python -m kalshi_research_bot worker --service kalshi-market-ingestion` |
| External source ingestion | Optional public source collection | 15 min | `python -m kalshi_research_bot worker --service external-source-ingestion` |
| Crypto research | Coinbase/Kraken research cycle | 15 min | `python -m kalshi_research_bot worker --service crypto-research` |
| Sports research | Public sports source collection | 60 min | `python -m kalshi_research_bot worker --service sports-research` |
| Settlement worker | Official Kalshi settlement import | 60 min | `python -m kalshi_research_bot worker --service settlement-worker` |
| Reporting/evaluation | Reports, audits, monitoring | 6 hours | `python -m kalshi_research_bot worker --service reporting-evaluation` |

### Data Rules

- Fresh source data is required.
- Stale cache must not be treated as fresh.
- Rejected, blocked, unresolved, and duplicate rows do not count as wins.
- No live betting, order upload, or automatic trading is permitted.
- No model should be marked validated without out-of-sample evidence and a baseline comparison.

### Sports acquisition plan

`SPORTS_RETRIEVAL_PLAN=official_api,http_json,firecrawl` is the default explicit plan. It preserves the controlled preference order without invoking every method:

1. A configured Odds API key uses the existing official structured normalizer.
2. ESPN's public scoreboard/summary JSON is the free local-first source.
3. Firecrawl is an optional JSON retrieval fallback only when configured.
4. The workflow blocks if no fresh validated source produces usable rows.

Every attempt records its retrieval method, source and receipt time, content hash, parser version, freshness deadline/state, raw evidence, rejection count, and failure reason. Malformed, stale, blocked, rejected, and duplicate records remain excluded from metrics.

### Data Locations

- Kalshi reports: `data\paper_runs\`
- Crypto reports: `data\crypto_runs\`
- Sports reports: `data\sports_runs\`
- Local dashboard payload: `data\today_paper_view.json`
- Worker logs and status: `data\daemon\`
- Operator inbox: `data\operator_messages\`

### Where To Put New Instructions

Use one of these:

1. The private dashboard inbox at `http://127.0.0.1:8765/ops`
2. A UTF-8 text or Markdown file under `data\operator_messages\`
3. A GitHub issue or pull request for shared multi-model work

## Minimal Handoff Prompt

Use this prompt when you want another model to continue:

```text
Continue the hardened Kalshi research platform from its current state.

Current setup:
- PostgreSQL is the only runtime database locally and in any approved hosted service.
- SQLite is an archive/import/rollback source only and must never be enabled as a fallback.
- The platform has workerized collection loops for Kalshi, crypto, sports, external sources, settlement, and reporting.
- The local dashboard is at 127.0.0.1:8765.
- The private operator inbox is at /ops.
- Optional connectors fail closed without breaking the pipeline.

Database:
- Do not delete archived SQLite evidence.
- Keep PostgreSQL as the only runtime database.
- Use the migration and validation commands in docs/platform-handoff-database-and-collection.md.

Data collection:
- Always require fresh source data.
- Do not treat stale cache as fresh.
- Keep rejected, unresolved, and duplicate rows out of performance metrics.
- Do not place live orders or auto-upload slips.

Safe commands:
- cmd /c scripts\research_routine.cmd -Action status
- cmd /c scripts\research_routine.cmd -Action once
- cmd /c scripts\test.cmd
```

## What This Does Not Do

- It does not replace the frontend.
- It does not replace the backend.
- It does not replace the database.
- It does not make MCP the architecture.
- It does not authorize live trading.
