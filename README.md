# HawkNeticSportsTools

Private, research-only decision support for Kalshi, crypto, and sports workflows. It never places orders, uploads slips, enables automatic trading, or promotes models.

## Local workflow

The canonical local checkout is the native WSL repository at:

```text
/home/dahaw/projects/HawkNeticSportsTools
```

Do not edit a parallel Windows or OneDrive checkout at the same time. GitHub is the version-control source of truth.

### Prerequisites

- Docker Desktop with WSL integration
- Docker Compose
- Python 3.12 or newer
- A local `.env` copied from `.env.example`

PostgreSQL is the only supported database engine. Docker Compose starts exactly one local service; credentials remain in the untracked `.env` file.

```bash
cd /home/dahaw/projects/HawkNeticSportsTools
cp .env.example .env
./scripts/local.sh setup
./scripts/local.sh migrate
./scripts/local.sh dev
```

Useful commands:

```bash
./scripts/local.sh db-start
./scripts/local.sh db-status
./scripts/local.sh migration-status
./scripts/local.sh test
./scripts/local.sh test-integration
./scripts/local.sh smoke
./scripts/local.sh verify
./scripts/local.sh stop
```

`db-reset` destroys only the local Docker volume and requires the explicit `RESET` confirmation. It never contacts Railway.

## Database contract

All application state uses PostgreSQL and versioned migrations in `migrations/postgres/`.

- `app`: active research, prediction, simulation, and dashboard writes.
- `raw`: immutable collection batches, payload evidence, and rejection records.
- `core`: source market identity and observations.
- `research`: model and feature lineage.
- `ops`: worker state, source health, quality results, and private operator messages.
- `reporting`: read-only reporting views.
- `auth`: users, sessions, and login audits.

`raw.source_payloads` grows by one response body per collection cycle and needs a retention window. `raw-retention` ages out payload bodies past that window while preserving the row, its batch lineage, its timestamps, and its `content_hash`; it defaults to a dry run and never touches a source's newest payload. See `docs/raw-payload-retention.md`.

Runtime connections use the deterministic search path `app, pg_catalog`; cross-domain statements use explicitly qualified schema names. Exact financial and probability values remain `NUMERIC` until an API or UI serialization boundary, where fixed-point decimal strings preserve their scale without binary-float loss.

`DATABASE_STATEMENT_TIMEOUT` limits ordinary runtime queries. Migrations use the
separate `DATABASE_MIGRATION_STATEMENT_TIMEOUT` setting (300000 ms by default)
so a production-sized reviewed migration is not constrained by the shorter
request-path timeout.

## Safety controls

The application starts in research-only mode. Keep these values in `.env` and hosted variables:

```text
RESEARCH_ONLY=true
LIVE_EXECUTION_ENABLED=false
AUTO_TRADE_ENABLED=false
AUTO_UPLOAD_ENABLED=false
KALSHI_ORDER_UPLOAD_ENABLED=false
MODEL_PROMOTION_ENABLED=false
STALE_CACHE_AS_FRESH=false
DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED=true
```

Freshness, source evidence, rejection, unresolved-state, and duplicate-exposure gates remain enforced. A blocked sports source does not fabricate rows or affect Kalshi or crypto metrics.

Probability evaluation and the research-only `BET_CANDIDATE` / `NO_BET` / `WAIT_FOR_DATA` contract are documented in `docs/probability-and-decision-policy.md`. Market-implied probability alone is always a baseline and cannot create a research candidate.

Bookmaker margin removal (`math/devig.py`) supports multiplicative, additive, power, Shin, and odds-ratio methods; the sports board defaults to Shin and publishes both the method used and the disagreement between methods, because on skewed markets that disagreement can exceed the minimum edge the decision gate requires. Probability calibration (`evaluation/calibration.py`) selects among Platt, beta, and isotonic calibrators by out-of-fold log loss and leaves an already-calibrated model alone. Research hypotheses and their results — including rejections — are recorded in the hash-chained registry in `research_registry.py`. Statistical power (`evaluation/power.py`) states how many resolved predictions a claim needs and the smallest effect a given sample could detect, and `research_registry.significance_review()` applies Benjamini-Hochberg across every recorded experiment so a finding selected from a large backlog is demoted rather than cited.

Three commands make this reachable from the terminal:

```bash
python -m kalshi_research_bot devig-compare --american -900 600
python -m kalshi_research_bot research-power --edge 0.01 --sample-size 300
python -m kalshi_research_bot research-registry --negative-results
python -m kalshi_research_bot sports-ratings --league nba
python -m kalshi_research_bot sports-ratings --historical --record
```

`devig-compare` shows what every margin-removal method makes of one market and how far apart they are. `research-power` answers how many resolved predictions a claim needs, and the smallest edge a given sample could have detected. `research-registry` summarizes recorded experiments, verifies the hash chain, and lists accepted findings demoted by family-wise correction.

`sports-ratings` (`sports_ratings.py`) is the first model in the platform rather than another reading of the market. It reconstructs finished games from the settled rows the collector already wrote, walks Elo forward in start-time order so no game can inform its own forecast, and grades the result by paired Brier difference against two baselines: the home base rate and the de-vigged closing consensus across books. It states a verdict — including `inconclusive` and `rejected` — with a confidence interval and how many games the observed effect would need, and `--record` appends that verdict to the research registry. The report stays `track_only`: nothing here promotes a model, and an interval containing zero is not a result.

`--historical` grades the same rating against `nflverse/nfldata`, a public archive of every NFL game since 1999 with closing moneylines from 2006. Live collection produces a few hundred graded games a year and the paired tests this program specifies need thousands, so the archive is what makes the question answerable now. Those rows are a third party's record, not collected evidence: they never enter the collection tables, and the report carries the file's content hash so a verdict stays attached to the data that produced it.

Run against 7,159 NFL games it returns two answers. Elo beats the home base rate by 0.0171 paired Brier, CI [0.0137, 0.0206] — real signal. Elo *loses* to the de-vigged closing line by 0.0183 paired Brier, CI [-0.0219, -0.0148], on 5,266 games — the market is the better forecast, by a margin no sample size will overturn. Section O of `docs/sports-prediction-research-program.md` records both.

The findings, evidence grading, red-team review, and open experiments behind these choices are in `docs/sports-prediction-research-program.md` and `docs/research-backlog.md`.

Password-only hosted deployments retain the emergency single-owner Basic-auth
path when `DASHBOARD_BASIC_FALLBACK_ENABLED=true`; its compatibility role is
`admin`. Disable that fallback only after PostgreSQL user accounts and session
authentication have been staged and verified.

## Hosted workflow

Hosted staging and production are separate from local development and must use distinct PostgreSQL services, credentials, and data. A production cutover requires successful migration, parity, backup, restore, readiness, and research-only safety checks. See:

- The web service runs with `HAWKNETIC_SERVICE=web` and reads the latest completed Kalshi snapshot from PostgreSQL.
- The Kalshi collector runs independently with `HAWKNETIC_SERVICE=kalshi-market-ingestion` and writes immutable raw evidence plus the normalized market state.
- The web service never treats its generated JSON file as the hosted source of truth and never displays a stale PostgreSQL snapshot as fresh.
- Authenticated clients can inspect bounded current detail through `/api/v1`, `/api/v1/games`, and `/api/v1/markets`. Collection routes accept `limit` and `offset`, cap pages at 200 rows, and withhold all rows when the public freshness gate is blocked. `/games.json` and `/markets.json` remain compatibility aliases.
- The sports board (`/sports.json` and the dashboard's sports panel) reads the rows the `sports-research` worker uploads. It reports `fresh`, `stale`, `blocked`, `empty`, or `unavailable` explicitly and withholds rows in every state except `fresh`. Each market publishes both the shopper's de-vig of the best available prices and the books' own consensus — each book de-vigged on its own, then the median — plus the signed gap between them. See `docs/sports-data-upload.md`.
- Closing line value (`/sports-clv.json`, `sports-clv`) grades each recorded price against the last pre-start quote posted by the same bookmaker for the same market. It is a price comparison in probability points, not profit and not a settled result.
- Other worker roles use the names documented by `python -m kalshi_research_bot worker --help`; they remain isolated from the web process.

- `docs/sports-data-upload.md`
- `docs/staging-sports-worker-verification.md`
- `docs/raw-payload-retention.md`
- `docs/operator-runbook.md`
- `docs/database-schema-audit.md`
- `docs/data-cutover-validation.md`
- `docs/postgresql-parity-validation.md`
- `docs/railway-postgresql-deployment-and-rollback.md`
- `docs/deployment-readiness-checklist.md`

Do not use the deployment environment as proof of model validity, edge, or profitability.
