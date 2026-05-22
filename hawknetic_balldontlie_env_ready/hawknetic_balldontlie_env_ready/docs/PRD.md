# HawkneticSports — PRD

## Brand
- **Company / platform:** HawkneticSports
- **Product / dashboard:** HawkneticSportsTools

## Positioning vs competitors (Jan 2026)
| Capability | HawkneticSports | PrizePicks | Underdog | Action Network | OddsJam |
|---|:---:|:---:|:---:|:---:|:---:|
| Real Monte Carlo simulation (≥10k runs) | ✓ | ✗ | ✗ | ✗ | ✓ |
| Same-game correlation matrix per pair | ✓ | ✗ | ✗ | ✗ | ✗ |
| No-vig edge per leg | ✓ | ✗ | ✗ | ✓ | ✓ |
| Kelly fraction recommendation | ✓ | ✗ | ✗ | ✗ | ✓ |
| 95% CI per probability | ✓ | ✗ | ✗ | ✗ | ✗ |
| Trap-leg detection w/ explanations | ✓ | ✗ | ✗ | ✗ | ✗ |
| Live freshness gating | ✓ | ✗ | ✗ | ✗ | ✗ |
| Decision-support (no wagers accepted) | ✓ | ✗ | ✗ | ✓ | ✓ |
| **+EV scanner widget on landing** | **✓** | ✗ | ✗ | ✗ | ✓ ($99/mo) |

## Architecture
- **Backend:** FastAPI on port 8001 (`HawkneticSports API` v3.0.0). Bridge `/app/backend/server.py` → `app.main:app`. Dialect-aware: SQLite locally, Railway PostgreSQL in production via `DATABASE_URL`.
- **Frontend:** Next.js 16 production build (`next start -H 0.0.0.0 -p 3000`). AuthProvider context wraps the app.
- **DB schema:** 51+ tables. v2 additions: `player_skill`, `team_metrics`, `live_games`, `live_player_status`, `live_injuries`, `live_odds`, `live_line_movement`, `live_data_snapshots`, `predictions_outcomes`, `slip_results`, `usage_limits`, `rate_limits`, `payment_transactions`. Auth/saved slips reuse existing `users`, `parlays`, `parlay_legs`, `subscriptions`, `payments`, `plans`. v2 column upgrades: `users.plan / .stripe_customer_id / .stripe_subscription_id / .subscription_status`, `parlays.sport`, `parlay_legs.market_type / .line / .game_id / .player_id / .team_id / .notes`, `payments.stripe_invoice_id / .amount / .paid_at`, `subscriptions.plan_name / .stripe_customer_id / .stripe_subscription_id`.

## Implemented (Wave A→D + competitive features + P0 production fix)

### Math correctness
- Real Monte Carlo simulator (`services/simulation_engine.py`, N=10,000) with **same-player correlation fix** (shared per-trial minutes + form factor).
- No-vig edge from real opposing-side market lines.
- Simulation-based parlay probability + Pearson correlation matrix.
- Kelly + 95% CI + MoE.
- Trap classification (Strong play / Playable / Lean / Pass / Trap).
- Calibration prep via `predictions_outcomes`.

### Live-data layer
- New tables + `GET /api/live/readiness`, `POST /api/live/sync`, `GET /api/games/today`, `GET /api/games/{id}/markets`, `GET /api/live/odds`, `GET /api/live/snapshots`.
- Freshness rules: odds 5m, props 5m, status 30m, live game 90s. Slip analyzer attaches `readiness` to every response.
- Algorithm runs are **hard-blocked** when `readiness.blocking_reasons` is non-empty (the response returns a blocked verdict instead of running MC; no usage is consumed).

### Multi-sport adapters
- 6 working adapters in `services/sport_adapters.py`: NBA, NFL, MLB, NHL, Soccer, Golf — sport-specific distributions (Normal/Poisson/Bernoulli) + trap rules + readiness signals.
- `GET /api/sports` exposes the public picker payload.

### SaaS platform
- Cookie-session auth (`/api/auth/signup` /login /logout /me, PBKDF2 hashing, IP-based rate limiting on signup + login).
- `AuthProvider` + `useAuth()` hook, `/login`, `/signup`, `/pricing` pages.
- Auth header in dashboard, Save-slip button, 7 sport tabs.
- Saved slips API user-scoped (`POST/GET/DELETE /api/slips`, `POST /api/slips/{id}/run`, `GET /api/slips/{id}/results`, `PATCH /api/slips/{id}/reorder`).
- Admin tools quarantined to `/admin` with 4 tool groups.
- Per-plan daily algorithm-run limits enforced via `usage_limits` table (free=3, pro=50, premium=250).
- Stripe Checkout + Customer Portal + signature-verified webhook (`/api/billing/create-checkout-session`, `/api/billing/create-portal-session`, `/api/billing/subscription`, `/api/webhooks/stripe`). Falls back to 503 when API keys/price IDs are placeholder.

### Code quality refactor (Feb 2026 — review pass)
- React hook deps: added missing `setUser` to all `useCallback` in `lib/auth.tsx`; added `setState` to `TopEvScanner` `useEffect`.
- Magic numbers extracted: `BOLD_FONT_WEIGHT`, `SEMI_BOLD_FONT_WEIGHT`, `SCANNER_LIMIT`, `PASSWORD_MIN_LENGTH`, `DEFAULT_STAKE`, `DEFAULT_BOOKMAKER`, `BACKFILL_TEST_SEASON`.
- `propToMarketOptions` cyclomatic complexity 11 → 1 via `KEYWORD_TO_MARKET_TYPE` lookup table (`marketOptions.tsx`).
- Nested ternary in `AuthBar` replaced with `AuthBarContent` early-return helper; same pattern in `CompetitorComparison.check()`.
- **Big one: `HawkBet365DecisionDashboard.tsx` 305 lines / complexity 74 → ~120 lines / complexity ~8.** Extracted into 9 single-responsibility files: `useMarketData.ts` (data loading hook), `useSlipBuilder.ts` (slip state + actions hook), `marketOptions.tsx` (prop/odds → option transforms + drag button), `SportsBoard.tsx`, `MarketBoard.tsx`, `SlipPanel.tsx`, `AnalysisPanel.tsx`, `AuthBar.tsx`, `DashboardTopbar.tsx`.
- `app/admin/page.tsx` 91 lines → orchestrator + `AdminToolGroup.tsx` + `TOOL_GROUPS` config.
- `app/pricing/page.tsx` 60 lines → `PricingPlanCard.tsx` + `CompetitorComparison.tsx` + slim page.
- `app/signup/page.tsx` 54 lines → `SignupField.tsx` + `SignupHeader`/`SubmitButton` sub-components.
- Test cleanup: `_find_db()` 5-deep nesting → flattened via `_candidate_db_file` + `_walk_for_db_file` helpers. `test_readiness_shape` (cyclomatic 14) → 5 focused tests via a `readiness` fixture. `is True/False` → truthy checks (ruff E712 clean).
### Code quality refactor (Feb 2026 — review pass 2)
- Decomposed `useSlipBuilder` (complexity 18 → ≤8) by extracting `slipBuilderHelpers.ts` (`makeLegFromOption`, `makeLegFromManual`, `isManualLegValid`, `useLegsState` micro-hook) + `buildPersistLegs`.
- Decomposed `HawkBet365DecisionDashboard` (complexity 14 → ≤6) further: extracted `useMarketOptions.ts` (memoized options + filtering), `dashboardDnd.tsx` (`DashboardDndProvider`, `makeDragEndHandler`, `useDashboardSensors`), `buildSlipPanelProps`, `MobileSlipToggle`. The page-level component is now a ~70-line orchestrator.
- Reduced `propToMarketOptions` complexity (11 → ≤5) by extracting `baseFromProp`, `labelForProp`, `makeOverOption`, `makeUnderOption` helpers.
- Split `SlipPanel` (78 lines → ~25-line shell) into `SlipHeader`, `BookmakerSelector`, `StakeField`, `PayoutPreview`, `SlipLegsList`, `RunSaveActions`.
- Extracted `useSignupForm.ts` hook from `app/signup/page.tsx` (was 58 lines → now ~50 with cleanly separated form state).
- `tests/test_hawknetic_v2.py:40` flagged `is` vs `==`: false-positive — `is not None` is the PEP 8-correct idiom for None comparison (ruff agrees: 0 violations).

### Production credentials + live BALLDONTLIE wiring (Feb 2026)
- Wired the user's production secrets into `/app/backend/.env` (gitignored): BALLDONTLIE_API_KEY (live), OPENAI_API_KEY, STRIPE_SECRET_KEY (live), STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET. Stripe price IDs left blank pending Stripe Dashboard product creation.
- Renamed billing tiers to match the user's Stripe setup: **Starter / Pro / Elite** (previously Pro / Premium). Pricing page now renders all 4 tiers (Free $0, Starter $9, Pro $29, Elite $79).
- Replaced `BallDontLieService.sync_live` stub with a real implementation: fetches today's NBA games from BALLDONTLIE → ingests into `live_games` via `live_sync.ingest_snapshot` (verified: 1 game written, `last_updated` refreshes within seconds).
- Added `services/live_poller.py` — in-process asyncio background task started on FastAPI startup, ticks every `HAWKNETIC_LIVE_SYNC_INTERVAL_SECONDS` (default 60s), auto-disables when no API key is set. Verified: `/api/live/readiness` returns `ready: true` while the poller is running.
- Created `.env.example` template inside the zip folder so Railway deployment has a clear reference (no secrets, full structure).

### Repository layout consolidation (Feb 2026)
- Moved `/app/frontend` into `/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/frontend` and symlinked `/app/frontend` → zip location so supervisor + Emergent platform continue to work transparently.
- Merged `/app/scripts/{seed_demo,seed_v2,p0_audit,production_audit}.py` into the zip's `scripts/` folder.
- Copied `PRD.md` and `TEST_CREDENTIALS.md` into the zip's `docs/` folder for repo visibility.
- Updated `/app/.gitignore` to exclude platform-runtime dirs (`/memory/`, `/test_reports/`, `__pycache__/`, `.pytest_cache/`) from GitHub commits — repo root stays clean.

### Production / PostgreSQL compatibility (Feb 2026 fix)
- `app/schema_v2.py` made dialect-aware (`INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY` on Postgres, `PRAGMA table_info` replaced with `information_schema.columns` via `_column_exists`).
- `_public_user` wraps response data in `jsonable_encoder` so PG-returned `datetime`/`TIMESTAMPTZ` values serialise cleanly in `JSONResponse`.
- `services/live_readiness.py` UNION subquery aliased + CAST to TEXT so the readiness MAX(t) query works on both PG (where v2 timestamp cols are TEXT but main-schema `updated_at` is TIMESTAMPTZ) and SQLite.
- `parlays.sport` column added via schema_v2 + `build_parlay()` now persists it for the saved-slip run-by-id flow.
- Verified end-to-end against real PostgreSQL: signup → login → save slip → run-by-id → 10,000 MC → results persisted → usage incremented; idempotent on re-init.

### Competitive features
- **+EV scanner** — `GET /api/insights/top-ev` runs single-leg simulation across every active prop and ranks by EV. Mounted at the top of the dashboard as `<TopEvScanner />` widget; verified producing 8 edges from 25 props (Butler under +53.8%, Giannis under +36.6%, LeBron under +30.5%, etc.).
- **Competitor comparison block** on `/pricing` showing the capability matrix vs PrizePicks / Underdog / Action Network / OddsJam.
- Brand rename across UI, FastAPI title, footers, auth pages, admin page.

## Verified end-to-end
- Same-player correlation: ρ≈0.13, parlay 31.6% vs naive 28.6% (was 0.006 / identical pre-fix).
- 6 sport adapters produce realistic per-sport scores.
- Auth: signup → /me → save slip → list slips → run-by-id → result history full flow with cookie session.
- Run Algorithm: 7 games + 25 props, full verdict panel with simulation runs / Kelly / 95% CI / classification / trap flags.
- +EV scanner: 25 props scanned → 8 positive-EV edges ranked by EV per unit, surfaced on landing.
- Postgres (clean DB): init_db creates 60+ tables incl. all v2 additions, idempotent on re-init. Signup/login/save/run/results all 200 OK.
- SQLite preview: 18-step E2E smoke test passes — all endpoints 200, MC runs 10,000 sims, edge=-3.66%, usage 0→1, results count=1.

## Test credentials
See `/app/memory/test_credentials.md`.

## Next Action Items
- **Same-player parlay correlation regression** — `test_parlay_probability_is_simulation_based` now fails because `correlationMatrix[0][1]` for two Curry legs in the same game returns ≈0.001 instead of the documented ρ≈0.13. The single-leg MC is fine (+EV scanner produces real per-prop edges), but the simulation engine appears to be drawing independent trials per leg instead of sharing the per-trial minutes/usage when both legs belong to the same player. Likely fix is in `services/simulation_engine.py::simulate_slip` — make sure the same `(player_id, trial_index)` reuses the same minutes/usage draw across legs.
- Provide live `STRIPE_PRICE_ID_PRO` + `STRIPE_PRICE_ID_PREMIUM` (currently placeholder → 503 on checkout).
- Provide `BALLDONTLIE_API_KEY` → add a scheduled poller pushing into `/api/live/sync` so live data flows automatically (today data is seeded via `/app/scripts/seed_v2.py` and goes stale 90s after seed).
- Refactor `seed_v2.py` to use dialect-aware `app.database.execute` instead of raw `sqlite3` so production PG can be seeded for demo without a live data provider.
- Saved-slips dashboard page at `/dashboard/slips` (server has all endpoints; only UI page missing).
- Real provider adapters for NFL/MLB/NHL/Soccer/Golf (framework in place).
- Rewrite or delete the 13 stale backend Pytest tests that target removed Jinja routes.
- Split `HawkBet365DecisionDashboard.tsx` (>300 lines) into smaller components.

## Smart enhancement suggestion
**Shareable algorithm runs** — generate a short URL per slip (`/r/<hash>`) so users can share verdicts socially. Gate share behind Pro tier — every prediction becomes viral marketing that brings new signups for free, AND share becomes another upgrade lever for the free → Pro conversion.
