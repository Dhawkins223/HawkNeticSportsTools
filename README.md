# Kalshi Research Bot

Local decision-support pipeline for researching Kalshi sports markets.

This project is built as a set of small "bots" that pass structured data forward:

1. `ResearchBot` chooses sport-specific model families and assumptions.
2. `SourceBot` validates allowed data sources and fetch policies.
3. `ScrapeBot` collects public API, RSS, CSV, and robots-allowed web data.
4. `ModelBot` turns game data and signals into probabilities.
5. `EdgeBot` compares model probability with Kalshi prices.
6. `ReportBot` produces ranked research cards for each game.

The first version is read-only and paper-only. It does not place real-money orders.

## Quick Start

```powershell
cd C:\Users\dahaw\OneDrive\Documents\Playground\kalshi-research-bot
.\scripts\demo.cmd
```

Run the smoke tests:

```powershell
.\scripts\test.cmd
```

If you prefer direct Python commands:

```powershell
$env:PYTHONPATH = "src"
python -m kalshi_research_bot demo
python -m kalshi_research_bot combo --target 0.80
python -m kalshi_research_bot demo --save-db data\research.sqlite
python -m unittest discover -s tests
```

## Combo Builder

For totals combos like the example screenshot, use:

```powershell
$env:PYTHONPATH = "src"
python -m kalshi_research_bot combo --target 0.80 --min-legs 2 --max-legs 4
```

Or use the Windows helper:

```powershell
cmd /c scripts\combo.cmd --target 0.80 --min-legs 2 --max-legs 4
```

## Paper View

Generate public schedule data, public Kalshi combo markets, and live underlying Kalshi leg quotes:

```powershell
cmd /c scripts\today.cmd --date 20260702
```

Start the local dashboard:

```powershell
cmd /c scripts\paper.cmd --port 8765
```

Then open `http://127.0.0.1:8765`.

Start the live dashboard from the latest local JSON while refreshing live data in the background:

```powershell
cmd /c scripts\live.cmd --port 8765
```

`scripts\live.cmd` binds immediately, then runs a safe 5-minute live refresh cadence. The browser also checks freshness once per minute and reloads when the underlying `generated_at` changes. The installed watchdog still checks freshness and requests refreshes when data is stale, which keeps the local platform available even if a public source is slow or blocked.

The live dashboard now shows two manual-only slips:

- Primary 80% slip: each leg must clear the standard 80% individual-leg filter.
- 75% leverage slip: each leg must clear a lower 75% individual-leg filter for more payout leverage and more risk.

It also includes a Deep Research Bot panel that updates every refresh with model-improvement priorities, liquidity/correlation notes, and accuracy rules. Real-money order placement is intentionally not automated.

## Always-On Local Mode

Codex heartbeats are useful for supervision, but Windows Task Scheduler should keep the private research loops alive.

Install the local tasks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_tasks.ps1
```

Check status:

```powershell
cmd /c scripts\daemon_status.cmd
cmd /c scripts\company_status.cmd
```

Remove the local tasks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall_tasks.ps1
```

Installed tasks are local/private only:

- `DashboardWatchdog`: checks port `8765` every 5 minutes, starts the dashboard if it stopped, and refreshes stale data.
- `SourceHealthSentinel`: records dashboard/source health and the full data-quality audit every 15 minutes.
- `CryptoStage3A`: runs `crypto-cycle` every 15 minutes.
- `SportsScraperStage3A`: runs `sports-cycle` every 60 minutes.
- `StatusSyncHourly`: syncs optional Airtable status every hour when enabled.
- `KalshiPassiveCheck`: imports official Kalshi settlements and refreshes research reports every 12 hours.
- `CompanyBriefDaily`: writes a daily local company brief.
- `CryptoDiagnosticsDaily`: regenerates crypto Stage 4 diagnostics without changing live logic.
- `FeatureExportsDaily`: exports leakage-guarded feature/label files without training.
- `QualityAuditDaily`: runs the test suite daily.
- `ReportArchiveDaily`: archives reports to optional Google Drive when enabled.

Sports cycles also append a validation ledger at `data\sports_runs\sports_private_20260704_validation_ledger.jsonl`. The ledger records valid rows, rejected rows, settlement counts, de-duped settled exposures, and win-rate status. If there are no settled sports rows, it records `unavailable / no settled rows` rather than `0%`. When ESPN/public payloads include official final scores, `sports-cycle` settles eligible rows automatically from those finals; it never fabricates scores.

Logs are written under `data\daemon`. These tasks do not place trades, bets, or account orders.

Run a full private data-quality audit any time:

```powershell
cmd /c scripts\data_quality.cmd
```

The audit writes `data\data_quality_report.txt` and `data\data_quality_report.json`. It checks dashboard freshness, source timestamps, source snapshot hashes, crypto zero-heartbeat causes, sports scraper status, prediction-table quality, and metric-contamination guardrails. The local dashboard also includes a `Data Quality Gate` panel. This does not change prediction logic or metrics.

## Private Bot Company

The platform now has a local "bot company" roster. Each bot has a narrow job, cadence, and safety boundary:

- Operations: dashboard watchdog, source health sentinel, status sync, report archive.
- Crypto Research: market scout and diagnostics analyst.
- Sports Research: scraper-first public source scout.
- Kalshi Research: settlement clerk.
- Research Data: feature export librarian.
- Quality: test-suite auditor.
- Executive: daily local briefing chief.

Inspect the full roster:

```powershell
cmd /c scripts\company_status.cmd
```

The bot company is not an execution desk. It does not auto-trade, auto-bet, upload Kalshi orders, bypass access controls, train ML, or make public profitability claims.

## Kalshi Account Handoff Policy

Do not upload or stage orders inside a real Kalshi account from this research system. The safe handoff is manual review only:

- Allowed: local dashboard cards, copyable slip text, JSON/CSV review exports, and read-only reports.
- Not allowed: authenticated order creation, draft-order upload, cart injection, auto-clicking order tickets, or any workflow that can submit or pre-stage real-money trades.
- Future account integration, if ever added, should be read-only until a separate compliance/safety review approves a narrower workflow.

The dashboard includes a 3D/4D slip map:

- Chance, payout, and leg count are shown as a 3D risk/reward position.
- Refresh time is the 4th dimension, so you can see when the current recommendation was rebuilt.
- The combo builder blocks overlapping same-matchup legs, so a slip does not stack total/spread/half-game variants from the same game.

Fast manual review packets reduce copy friction without crossing into account automation:

- Each slip card has `Copy Fast Packet`, `Copy Tickers + Sides`, `Text Packet`, and `JSON` controls.
- Direct local endpoints are available at `http://127.0.0.1:8765/review-packet.txt?slip=all_day` and `http://127.0.0.1:8765/review-packet.json?slip=all_day`.
- Valid slip keys are `primary`, `leverage`, `all_day`, and `research_edge`.
- Packets include ticker, side, selection, price hint, source generation time, packet hash, and a manual checklist.
- Packets explicitly do not create, stage, upload, or submit orders; live prices and market status still need human review.

## Public Intel Strategy

The bot now has a Public Intel Strategy panel. It is designed to copy the useful part of connector-heavy research systems without crossing into private or insider data.

Signals can come from public bettors/traders, public social posts, public market data, news, weather, stocks, crypto, and on-chain data. Each signal must have a public URL and timestampable source. Private, leaked, hacked, or untraceable signals are blocked.

Create a local signal file from the template:

```powershell
copy config\public_intel.example.json config\public_intel.local.json
```

Then run live mode with those public signals:

```powershell
cmd /c scripts\live.cmd --date 20260702 --port 8765 --public-intel config\public_intel.local.json
```

Public intel can boost a leg's exact-bet score, but it does not bypass the no-overlap guard, liquidity/spread filters, or manual-only trading rule.

## Failure Guardrails

Missed slips are converted into hard filters. The first guardrail blocks the Miami vs Colorado failure pattern:

- Exclude MLB `NO` legs on `Over 14.5+` total-runs markets.
- Exclude Colorado/Coors-style MLB `NO` legs on `Over 12.5+` total-runs markets.
- Never take MLB total-runs unders in high-scoring environments.
- Require `85%+` for high-scoring MLB over legs.
- Require `90%+` for Colorado/Coors-style over legs or MLB over lines at `12.5+`.
- Keep one normalized matchup per combo slip.

The paper view is strict real-data mode. It does not invent probabilities. Combo probabilities are market-implied from the underlying Kalshi leg bid/ask data; if a leg cannot be priced, the market is marked incomplete.

Generate a strict bot decision:

```powershell
cmd /c scripts\pick.cmd --date 20260702
```

The pick command returns `BET_CANDIDATE` only when a tradable combo has real underlying leg quotes, adjusted probability of at least 80%, and positive edge versus the combo YES ask. Otherwise it returns `NO_BET`.

The combo bot multiplies leg probabilities and applies a penalty when legs share the same sport/event context. A target like 80% combined is much stricter than 80% per leg: two independent legs need about 89.4% each, three need about 92.8% each, and five need about 95.6% each before correlation penalties.

Generate a large mixed-sport slip where every individual leg clears about 80%:

```powershell
cmd /c scripts\slip.cmd --date 20260702 --target 0.80 --min-legs 8 --max-legs 20 --stake 5
```

The slip command maximizes the number of real priced legs that pass the individual-leg filter. The full combo probability will be much lower because the legs multiply together; that is what creates the larger payout.

## What It Can Do Now

- Load sample game projections and Kalshi-style quotes.
- Calculate fair prices from model probabilities.
- Rank YES/NO contract edges by expected value.
- Fetch RSS feeds and public web pages from configured sources.
- Check `robots.txt` before generic page scraping.
- Fetch public Kalshi market data without credentials when network access is available.

## What Comes Next

- Add sport-specific feature builders for MLB, NFL, NBA, WNBA, soccer, golf, and tennis.
- Add paid or official data provider connectors when you provide keys.
- Add authenticated Kalshi account/position read access.
- Add paper trading, then guarded production order support with manual confirmation.

## Safety Rules

- Do not bypass logins, paywalls, CAPTCHAs, or technical access controls.
- Prefer official APIs, public RSS feeds, downloadable CSVs, and licensed data.
- Treat results as research, not guaranteed betting advice.
- Require explicit confirmation before any production trade.
