# GitHub, Railway, and Firecrawl Workflow

This is the active workflow for the research platform. Docker is not part of the operating path.

## Target Architecture

- Local platform: development, dashboard checks, live research loops, and manual review.
- GitHub: private source-of-truth repository for code, branches, pull requests, and AI model contributions.
- Railway: hosted runtime target connected to GitHub, with secrets stored in Railway Variables.
- Railway volume: current safest hosted persistence path for local-style reports, HTTP cache, and SQLite research state.
- Railway Postgres: later migration path for shared persistent state, but not the current source of truth because the app still uses SQLite directly.
- Firecrawl: optional scraper connector enabled by `FIRECRAWL_API_KEY` from local `.env` or Railway Variables.

## Current Connection Status

- Project `jubilant-liberation` has active service `HawkNeticSportsTools`.
- Public URL: `https://hawkneticsportstools-production.up.railway.app/`.
- That service is connected to repo `Dhawkins223/HawkNeticSportsTools`.
- Production is connected to branch `Master`.
- Dashboard auth variables are configured in Railway Variables; do not commit those secrets.
- Runtime connector variables are configured in Railway Variables where available.
- `RESEARCH_DATA_DIR=/data` is configured with a Railway volume mounted at `/data` for persistent hosted data.
- Local `railway.cmd` is installed, but direct CLI access still requires `railway login`.
- Firecrawl is connected only when `FIRECRAWL_API_KEY` is present in local `.env` or Railway Variables.

## GitHub Rules

- Use a private repository.
- AI models should pull from GitHub and push to feature branches.
- Merge to `main` only after review and tests.
- Do not commit `.env`, private keys, Railway local state, SQLite files, runtime reports, or scraper cache.

Suggested branch names:

```text
ai/<model-or-agent>/<short-task>
codex/<short-task>
```

## Railway Rules

- Deploy from GitHub `main`.
- Store secrets in Railway Variables, not GitHub and not Postgres.
- Use the existing Railway project only after confirming which project should own this platform.
- Add Railway Postgres only when you are ready to spend Railway credits or confirm it is covered by your plan.
- Keep real-money trading, auto-betting, and order placement disabled.

Required Railway variables:

```text
PYTHONPATH=src
RESEARCH_DATA_DIR=/data
KALSHI_HTTP_CACHE_TTL_SECONDS=900
KALSHI_HTTP_MAX_RETRIES=2
KALSHI_HTTP_BACKOFF_SECONDS=2
KALSHI_HTTP_MIN_INTERVAL_SECONDS=0.25
KALSHI_HTTP_ALLOW_STALE_ON_ERROR=true
KALSHI_HTTP_MAX_STALE_SECONDS=7200
KALSHI_ORDER_UPLOAD_ENABLED=false
SPORTS_SOURCE_MODE=scraper
SPORTS_SCRAPER_ENABLED=true
FIRECRAWL_API_KEY=<set in Railway, not GitHub>
```

Mount a Railway volume at `/data` before setting `RESEARCH_DATA_DIR=/data`. This keeps
`today_paper_view.json`, `evaluation.sqlite`, refresh audits, source cache, and bot reports
alive across redeploys/restarts. Without the volume, Railway starts cold and can lose the
last known-good dashboard payload after each deployment.

Railway refreshes the hosted dashboard every 15 minutes instead of the local 5-minute loop.
The hosted runtime uses a shared public IP and can receive `HTTP 429` from public source APIs
if it refreshes too aggressively. The HTTP cache may reuse an older cached public API response
only after a fresh request fails; when that happens, `source_cache_status.stale_fallback_count`
is set and the quality gate reports `stale_cache_fallback_used` so stale cache is never treated
as clean fresh data.

Optional Railway variables:

```text
KALSHI_ENV=demo
GOOGLE_DRIVE_ENABLED=false
AIRTABLE_ENABLED=false
SLACK_ALERTS_ENABLED=false
VERCEL_ENABLED=false
POSTHOG_ENABLED=false
STRIPE_ENABLED=false
```

## Firecrawl Rules

- Store `FIRECRAWL_API_KEY` only in local `.env` or Railway Variables.
- Do not commit Firecrawl keys.
- Use Firecrawl only for public pages that do not require login, CAPTCHA bypass, or paywall bypass.
- If Firecrawl blocks or fails, report the exact source status and do not fake live data.

## Local Commands

```powershell
$env:PYTHONPATH='src'; python -m kalshi_research_bot connectors-status
cmd /c scripts\live.cmd --port 8765
cmd /c scripts\test.cmd
```

## GitHub Setup Commands

After GitHub CLI is installed and authenticated:

```powershell
gh auth login
gh repo create kalshi-research-bot --private --source . --remote origin --push
```

If the private repo already exists:

```powershell
git remote add origin https://github.com/<owner>/kalshi-research-bot.git
git push -u origin main
```

## Railway Setup Commands

After the GitHub repo exists and is connected in Railway:

```powershell
railway login
railway link
railway variables set PYTHONPATH=src KALSHI_ORDER_UPLOAD_ENABLED=false SPORTS_SOURCE_MODE=scraper SPORTS_SCRAPER_ENABLED=true
railway up
```

Use the Railway dashboard or Railway MCP to add `FIRECRAWL_API_KEY`, `RESEARCH_DATA_DIR=/data`,
and the other runtime variables. Do not store secrets in GitHub.

## Database Boundary

The current code uses SQLite through `data\evaluation.sqlite` plus JSON/JSONL report files under
`data\`. On Railway, set `RESEARCH_DATA_DIR=/data` and mount a volume at `/data` to preserve the
same file-backed workflow the local app uses.

Moving the full source-of-truth database to Postgres is a real migration, not just an environment
variable change. It requires a compatibility layer for `storage.py`, `crypto_research.py`,
`sports_research.py`, and `source_quality.py`, plus schema tests. Keep `DATABASE_URL` as a placeholder
until that migration is intentionally built.
