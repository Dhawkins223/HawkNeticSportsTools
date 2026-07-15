# Platform Handoff: Database And Data Collection

Status: research operational. This platform is private, research-only, and manual-review only. It does not place, stage, upload, or submit orders.

## What Is Already In Place

- Local dashboard on `127.0.0.1:8765`.
- Private operator inbox at `/ops`.
- Workerized collection loops for Kalshi, crypto, sports, external sources, settlement, and reporting.
- SQLite remains the local source of truth.
- PostgreSQL migration `0004` and the legacy compatibility import are validated in isolated Railway staging, but PostgreSQL is not the active business runtime.
- Optional connectors degrade gracefully instead of breaking the pipeline.
- Core quality, per-workflow source quality, optional capability status, and deployment readiness are reported independently.

## Database

### Current State

- Local development uses SQLite in `data\evaluation.sqlite`.
- SQLite remains the active local source of truth.
- PostgreSQL schema creation, legacy import parity, and duplicate-import safety pass in Railway staging.
- Runtime query conversion is not complete; workers and reporting still use SQLite `ResearchStore`.
- Existing SQLite data is preserved.

### What To Use

- Local development and research: SQLite.
- Hosted deployment target: PostgreSQL only after business query conversion, normalized report parity, worker smoke tests, backup/restoration evidence, and reviewed deployment authorization.

### Safe Commands

```powershell
cd C:\Users\dahaw\OneDrive\Documents\Playground\kalshi-research-bot
$env:PYTHONPATH = "src"
python -m kalshi_research_bot database-status
python -m kalshi_research_bot database-migrate --backend sqlite
python -m kalshi_research_bot database-export-sqlite --db data\evaluation.sqlite --output data\postgres_export
python -m kalshi_research_bot database-validate-export --db data\evaluation.sqlite --input data\postgres_export
```

### PostgreSQL Readiness

- PostgreSQL migration files exist under `migrations\postgres\`.
- Import/export validation is deterministic.
- Sensitive auth and operator tables are excluded from research-history exports.
- A real import should only happen against a non-production database first.
- Do not run multiple SQLite writers in separate hosted replicas.

### Database Safety Rules

- Do not delete the SQLite database.
- Do not commit secrets.
- Do not assume a PostgreSQL import is production-ready until counts and aggregates are validated.
- Do not switch the hosted runtime to PostgreSQL without a tested migration path.
- Treat `docs/postgresql-parity-validation.md` as the cutover gate. Export validation is not destination parity.

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
- SQLite is the local source of truth.
- PostgreSQL is schema/import ready but not active runtime.
- The platform has workerized collection loops for Kalshi, crypto, sports, external sources, settlement, and reporting.
- The local dashboard is at 127.0.0.1:8765.
- The private operator inbox is at /ops.
- Optional connectors fail closed without breaking the pipeline.

Database:
- Do not delete SQLite.
- Do not switch to PostgreSQL until export/import validation is complete.
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
