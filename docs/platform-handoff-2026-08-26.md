# HawkNetic Platform — State of Play and Work Queue

Handoff briefing. Repo: `Dhawkins223/HawkNeticSportsTools` @ `Master` = `dbcea9e`.
Assessed 2026-08-26. Self-contained: assume no prior conversation.

## How to read the evidence tags

Every claim below carries how it was established. Do not treat them as equivalent.

- `[RAN]` — verified by executing it in a sandbox this session
- `[READ]` — from source or committed docs; not executed
- `[UNVERIFIED]` — about hosted infrastructure that could NOT be reached; treat as a
  hypothesis to re-check, not a fact

**Scope limit that matters:** Railway is blocked at the assessing environment's egress
proxy (`connect_rejected` for `railway.app`, `api.railway.app`, `backboard.railway.app`),
and there was no Railway CLI, API token, or production/staging `DATABASE_URL`. **No hosted
database, service, volume, or worker was inspected.** All database figures below come from
a local PostgreSQL created in the sandbox. If you have Railway access, you can settle in
minutes what this assessment could not settle at all.

---

## 1. URGENT — do this before anything else

### Production applies no migrations, and `0014` has been pending since 2026-08-22

`[READ from docs/schema-migration-application.md]` The production web service has **no
`source` block** in Railway — it is not connected to the repository. Two consequences
follow from that single gap:

1. **Merges do not deploy it.** Its last deployment carrying commit metadata was
   **2026-07-18**. Later deployments record `reason: deploy` with no commit or branch —
   uploads of a local directory, not builds of a merge.
2. **The pre-deploy `database-migrate` never runs.** The live start command
   (`paper --refresh-seconds 300`) is not the one root `railway.json` declares
   (`service-start`), which is direct evidence config-as-code is not being applied.

Workers run `DATABASE_MIGRATION_MODE=check` — they verify, deliberately never apply. So
**nothing in production applies schema changes.**

This already caused an outage once: migration `0013` sat in `Master` for days while every
worker crash-looped on `postgres_database_not_ready:['0013']`, and was eventually applied
by hand.

**Migration `0014` (`app.sports_current_quotes`) was merged 2026-08-22 and is very likely
in that same state now.** Code on `Master` reads that table; if the migration is unapplied,
the table does not exist in production.

#### Check (read-only, safe)

```sql
SELECT version, applied_at FROM ops.migration_executions ORDER BY version;
-- expect 0001 .. 0014. Stopping at 0013 confirms the problem.

SELECT to_regclass('app.sports_current_quotes') AS projection_table;
-- NULL means migration 0014 is not applied.
```

Or via the CLI:

```bash
DATABASE_URL=<production> PYTHONPATH=src python -m kalshi_research_bot database-status
```

#### Fix (forward-only, idempotent, safe to re-run)

```bash
DATABASE_URL=<production> PYTHONPATH=src python -m kalshi_research_bot database-migrate
```

#### Then fix the cause, not just the symptom

Reconnect the web service to `Dhawkins223/HawkNeticSportsTools` on `Master` with config
path `railway.json`. The repo already landed the start-command equivalence
(`DASHBOARD_REFRESH_SECONDS`, default 300) that makes this a non-behavioural change.
Confirm afterwards that the pre-deploy `database-migrate` ran, `/readyz` still reports
`data_gate: fresh_data_ready`, and `database.pending_versions` is empty.

Until that is done, **every merged migration must be applied by hand.**

### The docs contradict each other on what is deployed

`[UNVERIFIED]` Cannot be settled without Railway access.

- `docs/railway-worker-services.md`: "Production currently runs only the web service and
  `kalshi-market-ingestion`. The sports, crypto, settlement, external-source, and reporting
  workers are not deployed."
- `docs/sports-data-upload.md`: `SportsResearchProduction`, `RawRetentionProduction` and
  `SettlementWorkerProduction` are running, "sports rows are arriving hourly", with five
  hourly cycles tabulated as evidence.

Both cannot be true. Settle it, then correct the losing doc.

### Staleness of every hosted claim

| Record | Last observed | Age at 2026-08-26 |
| --- | --- | --- |
| Production collection cycles | 2026-08-16 | 10 days |
| Staging worker verification | 2026-08-16 | 10 days |
| Deployment & rollback notes | 2026-08-03 | 23 days |
| Volume storage audit | 2026-07-25 | 32 days |

Two known-bad items from those records, neither confirmed fixed: **staging PostgreSQL was
full and refusing connections**, and production logs `data_fresh_at` / `source_fresh_at`
as null for sports.

Useful triage queries once connected:

```sql
SELECT worker_name, status, consecutive_failures, last_error_code, heartbeat_at
FROM ops.worker_status ORDER BY worker_name;

SELECT source, freshness_state, last_successful_at, last_error
FROM ops.source_health ORDER BY source;

SELECT COUNT(*) AS valid_rows, MAX(api_fetched_at) AS newest
FROM app.sports_prediction_logs WHERE validation_status = 'valid';
```

---

## 2. What the system is

`[RAN]` unless noted.

| Dimension | Value |
| --- | --- |
| Source | 32,665 LOC, 87 modules |
| Tests | 12,119 LOC, 53 files, 680 tests — green on Python 3.11 and 3.12 |
| Runtime dependencies | 2 (`psycopg[binary]`, `psycopg_pool`) |
| Web tier | Python stdlib `ThreadingHTTPServer`; HTML built by f-string concatenation |
| HTTP routes | 27 |
| CLI commands | 60+ |
| Service roles | 8 (`web` + 7 workers) |
| Migrations | 14, forward-only |
| Schemas / tables | 8 / 37 |

There is **no framework, no bundler, no static assets, no build step**. That is deliberate
and defensible: no supply chain, strict CSP, page readable with JS off. Do not "modernize"
it without a specific reason — the front-end audit in
`docs/frontend-improvement-research.md` explicitly stays inside this architecture.

### Verified end-to-end path `[RAN]`

Against a freshly created local database:

| Step | Result |
| --- | --- |
| Apply migrations to empty DB | 14 applied, `ready: true`, no pending |
| Repeat migrations | no-op |
| `auth-create-user` | user_id 1, scrypt hash, role `admin` |
| Unauthenticated `GET /` | `401` — auth enforced |
| `POST /auth/login` | `200`, session + CSRF issued |
| `GET /auth/me` | `200`, role and expiry |
| `GET /` authenticated | `200`, 68,562 bytes |
| `GET /sports.json` | `board_state: unavailable`, `state_reason: no_sports_rows_uploaded` |

That last row is correct behaviour: with no data, the board withheld everything and said
precisely why rather than rendering an empty shell.

---

## 3. Layer assessment

### Database — strongest layer `[RAN]`

PostgreSQL only. Forward-only versioned migrations across 8 schemas. Exact `NUMERIC` /
`Decimal` discipline end to end — binary floats never touch money or probability. Applies
clean from empty, repeats as no-op, passes the Railway migration-only command.

Recent work (merged): `app.sports_current_quotes`, a trigger-maintained projection so the
board reads the current slate instead of the whole collection history. Board load went
**1.6 s → 9 ms warm** at 400,000 collected rows. `sports_board.verify_current_quotes()`
re-derives the answer with the `DISTINCT ON` query it replaced and reports drift by kind.

Note for anyone touching that trigger: it must **promote the surviving snapshot** when the
newest one is deleted, invalidated, or settled. Two non-obvious constraints, both
regression-tested:
- The delete path cannot test its own `DELETE` — the FK is `ON DELETE CASCADE`, so the
  projection row is usually already gone and `FOUND` is false. It promotes on the key's
  absence instead.
- Promotion must be guarded to the row that owned the projection. Settlement updates every
  snapshot of an event; promoting on all of them measured 3x the cost for an identical
  result (42 ms → 140–190 ms per 1,000-row event).

### Back end — solid, not production-grade `[RAN]`

`ThreadingHTTPServer` / `BaseHTTPRequestHandler`. Python's own docs say it implements only
basic security checks and is not recommended for production. No request size limits, no
meaningful timeout policy, thread per connection. Works; whether it should carry paying
traffic is a deliberate decision, not an inherited default.

### Front end — works, unoptimized `[RAN]`

Single server-rendered page. Measured composition of one dashboard load:

| Part | Bytes | Share |
| --- | ---: | ---: |
| Inline CSS | 42,229 | 62% |
| Inline JS | 9,645 | 14% |
| Actual markup | 16,326 | 24% |
| **Total** | **68,562** | |

Also: 68 `!important` declarations, 10 `@media` blocks. CSS and JS are re-sent uncached on
every response.

`docs/frontend-improvement-research.md` is a real audit with a prioritized plan. Its P0/P1
and half of P2 are implemented and verified `[RAN]`; **P3–P5 remain**. The favicon (A6) is
implemented as an inline `data:image/svg+xml` on all three pages — searching for the string
"favicon" misses it, because the markup is `rel="icon"`.

### Research — rigorous, and conclusive in a way that constrains the product `[RAN]`

Five verdicts in a hash-chained registry (`data/research/experiment_registry.jsonl`, chain
verifies). The registry refuses an `accepted` verdict whose confidence interval contains
zero.

| Verdict | Hypothesis |
| --- | --- |
| ACCEPTED | Elo beats the home base rate (+0.0171 paired Brier, CI [0.0137, 0.0206], n=7,159) |
| REJECTED | Elo beats the de-vigged closing line (−0.0183, CI [−0.0219, −0.0148], n=5,266) |
| INCONCLUSIVE | Market blend beats the close (−0.0001, CI [−0.00060, +0.00039], n=4,780) |
| ACCEPTED | Market blend beats Elo alone (+0.0192, CI [0.0157, 0.0227], n=4,780) |
| REJECTED | Required sample sizes are attainable at NFL-only volume (E-09) |

**Implication that governs marketing and product:** on NFL moneylines a team-strength
rating adds nothing detectable to the closing line. E-09 quantified why it will stay that
way — at 284.8 gradable NFL games/season, the realized 4,780-game sample (16.8 seasons)
has a minimum detectable paired Brier improvement of 0.000703; the observed effect was
−0.000104, i.e. 15% of the floor and negative. Demonstrating it would take ~774 seasons.

So **"our model beats the book" is not available** and must not be built into copy — the
project's own registry records it as rejected.

**What is defensible and sellable:** line shopping across books, a de-vigged consensus
(each book de-vigged separately then medianed, so one book's margin never lands on
another's price), closing-line value, and freshness discipline that withholds rather than
shows stale data. None requires beating the market.

**The one finding that changes prioritization:** pooling NFL + NBA + NHL + MLB raises
gradable games from 285 to ~5,257 per season, taking a 1% edge from 68.7 seasons of
evidence down to 3.7. **League coverage buys ~18x more evidence per season than any
modelling improvement can.** Prefer backlog entries that widen coverage over those that
deepen a single-league model. Run `power-audit --pooled` as coverage grows.

Also: **a quote is not an observation.** A market resolves once however many books priced
it. Five books across an NFL season = 1,424 prices, 285 independent outcomes. Never cite
stored quote counts as evidence; it inflates 5x.

---

## 4. Blockers to selling, in order

1. **No business layer at all** `[RAN]` — no billing, no subscriptions, no plans, no
   multi-tenancy. `grep` for `stripe|billing|subscription|tenant` returns 0 hits in `src/`.
   `user_id` appears in exactly **one** foreign key across all 14 migrations
   (`auth.app_sessions`). Every authenticated user sees the identical global board.
   Nothing is scoped per customer. Retrofitting tenancy touches every read path — this is
   the largest item and the easiest to underestimate.

2. **Data ceiling undercuts the only sellable feature** `[READ]` — line shopping depends
   entirely on The Odds API, the only multi-book source wired in, whose free tier is
   ~500 requests/month. Hourly collection needs ~720/month for a *single* sport. The free
   tier cannot run the core feature for one league. This is a purchasing decision.

3. **Seven deployment gates unchecked** `[READ]` — from
   `docs/deployment-readiness-checklist.md`. Most important: **no verified backup or
   restore**. Also: unfinished volume audit, unverified research-only flags in the target
   environment, unverified auth config, no secret-scan sign-off, unreviewed deploy-trigger
   policy. The checklist is itself stale — it records 281 tests against today's 669.

4. **Three of six data sources have never met a live response** `[READ]` — Polymarket,
   MLB StatsAPI, NHL API each have a connector, a refusing normalizer, and fixture tests,
   but were written against published docs in an environment blocking their hosts. Each
   needs one `source-probe <name>` run from a networked machine. Minutes of work.

5. **Web tier is stdlib** — see above.

---

## 5. Plan

**Phase 0 — Decide (no code).** Settle what is being sold and to whom. A line-shopping
tool for bettors, a data feed for builders, and a research platform for analysts are three
products sharing one backend. Nothing in Phase 2 can be scoped until this is answered. The
biggest cost driver is: shared board, or per-customer data?

**Phase 1 — Operate.** Start with `preflight`, which reports migration state, the
research-only controls, the auth posture, and whether a usable account exists, in one
read-only pass and exits non-zero if a gate blocks:

```bash
DATABASE_URL=<production> PYTHONPATH=src python -m kalshi_research_bot preflight
```

Then: migration `0014` check/apply (above). Reconnect the web service to
the repo. Settle which workers are deployed. Backup + verified restore. Volume audit.
Verify research-only flags and auth config in the live environment. Secret scan. Review
deploy-trigger policy. Refresh the stale checklist.

**Phase 2 — Productize.** Tenant/account entity, every read path scoped to it. Per-customer
state (watchlists, filters, alerts, history). Entitlements enforced server-side at the
query boundary. Billing + subscription lifecycle. Self-service signup (`auth-create-user`
is an operator command needing `AUTH_REGISTRATION_ENABLED` and `AUTH_NEW_USER_PASSWORD`).
Per-account rate limiting, which does not exist.

**Phase 3 — Widen.** Paid Odds API tier sized to real cadence. Probe Polymarket/MLB/NHL and
promote to verified. Turn on the leagues those unlock. Deploy the worker roles that exist
but have never run hosted.

**Phase 4 — Harden.** Extract CSS/JS to cached static routes (76% of every page load; also
drops `unsafe-inline` from the CSP). Real WSGI/ASGI server. Browser smoke gate the
front-end audit already specified. P4/P5 items. Add the missing favicon.

---

## 6. Standing constraints — do not violate

From `AGENTS.md`. These are not preferences.

- Require fresh, timestamped sources. Never label cached, blocked, failed, historical,
  rejected, unresolved, or duplicate rows as current, or include them in performance
  metrics.
- Preserve research-only controls: no live orders, automatic trading, slip uploads, model
  promotion, or unsupported profitability claims.
- Never expose or commit credentials, private keys, database URLs, tokens, or local env
  files.
- Use feature branches and pull requests. Do not push directly to `Master`, deploy, or
  alter hosted services without a documented readiness gate.

Historical archive rows (nflverse) must never enter `app.sports_prediction_logs` or reach
the board, freshness gates, or any live metric. This is enforced structurally, not by
label — `test_archive_grading_never_writes_to_the_collection_tables` fails if it changes.

## 7. Open questions for the owner

1. Shared board or per-customer data? Drives most of Phase 2's cost.
2. Budget for odds data? The free tier cannot run the core feature.
3. Who is the customer — bettors, analysts, or builders? The backend serves all three; the
   front end can only be built for one at a time.
4. Does the research-only posture hold commercially? Selling a *tool* fits inside it;
   selling *picks* does not, and would mean revisiting controls that exist for good reasons.
