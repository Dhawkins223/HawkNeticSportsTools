# GitHub, Railway, and Firecrawl Workflow

This is the active workflow for the research platform. Docker is not part of the operating path.

## Target Architecture

- Local platform: development, dashboard checks, live research loops, and manual review.
- GitHub: private source-of-truth repository for code, branches, pull requests, and AI model contributions.
- Railway: hosted runtime target connected to GitHub, with secrets stored in Railway Variables.
- Railway Postgres: intended hosted database path for shared persistent state, but not provisioned here because creating a database service can consume paid credits.
- Firecrawl: optional scraper connector enabled by `FIRECRAWL_API_KEY` from local `.env` or Railway Variables.

## Current Connection Status

- Railway MCP is connected to the account and can see projects.
- Project `jubilant-liberation` has service `HawkNeticSportsTools`, but its latest deployment is failed.
- Project `ravishing-elegance` exists with no services.
- Local `gh` and `railway` CLIs are not installed on PATH.
- Firecrawl is not connected locally until `FIRECRAWL_API_KEY` is present in `.env` or Railway Variables.

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
KALSHI_ORDER_UPLOAD_ENABLED=false
SPORTS_SOURCE_MODE=scraper
SPORTS_SCRAPER_ENABLED=true
FIRECRAWL_API_KEY=<set in Railway, not GitHub>
DATABASE_URL=<provided by Railway Postgres after service creation>
```

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

Use the Railway dashboard or Railway MCP to add `FIRECRAWL_API_KEY` and the Railway Postgres `DATABASE_URL`.

## Database Boundary

The current code uses SQLite through `data\evaluation.sqlite`. Moving the full source-of-truth database to Postgres is a real migration, not just an environment variable change. Do it as a controlled migration with schema tests and a compatibility layer, then switch Railway to `DATABASE_URL`.
