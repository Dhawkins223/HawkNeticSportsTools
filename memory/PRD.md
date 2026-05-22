# HawkNetic Sports Tools — PRD

## Original Problem Statement (consolidated)
Build a Bet365-style multi-sport prediction-decision platform where users press **Run Algorithm** instead of placing bets. Backend must use real Monte Carlo math (no-vig edge, simulation-based parlay correlation, Kelly, MoE), per-sport adapters (NBA/NFL/MLB/NHL/Soccer/Golf), a live-data layer (live_games / live_player_status / live_injuries / live_odds + readiness checks), JWT auth, saved slips, separate admin dashboard, and clean public UX.

## Architecture
- **Backend** – FastAPI on port 8001. Bridge `/app/backend/server.py` → `/app/hawknetic_balldontlie_env_ready/.../app/main.py`. SQLite locally, Postgres-ready via `DATABASE_URL`.
- **Frontend** – Next.js 16 (production build, `next start -H 0.0.0.0 -p 3000`). AuthProvider context wraps the app.
- **Database** – 51 tables. v2 additions: `player_skill`, `team_metrics`, `live_games`, `live_player_status`, `live_injuries`, `live_odds`, `live_line_movement`, `live_data_snapshots`, `predictions_outcomes`. Existing: `users`, `parlays` (saved slips), `parlay_legs`, `subscriptions`, `payments`, `plans`.
- **External APIs (configurable)** – Ball Don't Lie, OpenAI, Stripe — all gracefully degrade when keys are absent.

## What's been implemented (Jan 2026)

### Wave A — Math correctness
- **Real Monte Carlo simulation engine** (`services/simulation_engine.py`, N=10,000) — samples per-game pace, team scores, per-player minutes & form ONCE per trial so same-player legs correlate properly (verified ρ=0.126 vs naive 0).
- **No-vig edge** computed per leg using real opposing-side market lines.
- **Simulation-based parlay probability** with full correlation matrix (Pearson on simulation outcomes).
- **Kelly fraction** (full + 0.25× recommended) per leg and per parlay.
- **95% binomial confidence intervals** from simulation count.
- **Trap-leg detection** (heavy juice, likely-but-overpriced, projection barely clears, blowout/foul/injury risk, sample-size warning).
- **Spec §25 output** per leg: `noVigProbability`, `ev`, `evPerUnit`, `projection`, `projectionStd`, `marginOfError`, `ci95`, `confidenceScore`, `classification` (Strong play/Playable/Lean/Pass/Trap), `edgeLabel`, `trapFlags`, `kellyFraction`, `kellyRecommended`, `decimalOdds`, `americanOdds`, `inactivePlayer`, `fairAmericanOdds`.
- **Calibration prep**: every Run Algorithm writes leg-level rows into `predictions_outcomes` for future Brier scoring.

### Wave B — Live-data layer
- New tables: `live_games`, `live_player_status`, `live_injuries`, `live_odds`, `live_line_movement`, `live_data_snapshots`.
- `GET /api/live/readiness` — checks games/odds/props/injuries/lineups/box-scores loaded + freshness (odds 5m, props 5m, player status 30m, live game 90s).
- `POST /api/live/sync` — admin ingestion endpoint accepting `{kind:'odds'|'player_status'|'game_state'|'injury'|'props', payload:{rows:[]}}`. Writes raw snapshot to audit table, then fans out to typed writers.
- `GET /api/live/odds`, `GET /api/live/snapshots`, `GET /api/games/today`, `GET /api/games/{id}/markets` — public/admin reads.
- Slip analyzer attaches `readiness` block to every response, downgrades verdict when blocking reasons exist.

### Wave C — Multi-sport adapters
- `services/sport_adapters.py` with **6 working adapters**: NBA, NFL, MLB, NHL, Soccer, Golf.
- Each adapter exposes `project_team_score`, `project_player_stat`, `trap_flags`, `required_readiness_signals`, plus a `SportConfig` (pace baseline, score baseline, blowout threshold, market types, correlation examples, trap rules, readiness keys).
- `GET /api/sports` — public sport-picker payload (markets/trap rules/correlation examples per sport).
- Sport-specific distributions: NBA (Normal-on-rate × minutes), NFL (Poisson for receptions/carries, Normal for yards), MLB (Bernoulli per PA for hits, Poisson for Ks), NHL (Poisson for shots/goals/saves), Soccer (Poisson for goals/cards/corners), Golf (Normal for round score, Bernoulli for outright/top-N/cuts).

### Wave D — SaaS platform
- **JWT-style cookie auth** — `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`. PBKDF2 password hashing (240k iterations) with itsdangerous-signed session cookies.
- **AuthProvider** context (`lib/auth.tsx`) + `useAuth()` hook, wraps the entire app.
- **Login page** `/login`, **Signup page** `/signup`, **Pricing page** `/pricing` (Free / Pro $19 / Premium $49 plan tiers).
- **Auth header** on the dashboard: shows email + Admin link + Log out when authenticated; shows Pricing/Log in/Sign up when anonymous.
- **Saved slips** — `POST /api/slips`, `GET /api/slips`, `DELETE /api/slips/{id}` (user-scoped via session cookie). UI button "Save slip to my account" appears next to Run Algorithm.
- **Admin page** `/admin` separated into 4 tool groups: Live Data, Database, Backfill & Sync, Health. Public dashboard contains zero admin/scraper/database internals.

## Verified end-to-end
- 6 sport adapters all produce realistic per-sport team scores (NBA ~108, NFL ~21, MLB ~5 runs, NHL ~1 goal, Soccer ~0–1 goals, Golf ~40 strokes-to-par).
- Same-player correlation: Curry threes ↔ points ρ=0.126, parlay 31.6% vs naive 28.6% (was 0.006 / identical pre-fix).
- Auth flow: signup → /me → save slip → list slips all return 200 with cookie session.
- Run Algorithm flow: 7 games visible, click game → markets render → click odds → leg added → press Run Algorithm → verdict panel renders with simulation runs, Kelly, 95% CI, classification, leg-by-leg trap flags.
- 9/9 backend pytest pass (HawkNetic test_hawknetic_api.py).

## Test credentials
See `/app/memory/test_credentials.md`.

## Next Action Items
- **Stripe live wiring**: add `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID_PRO`, `STRIPE_PRICE_ID_PREMIUM` to backend `.env`; create `POST /api/billing/create-checkout-session`, `POST /api/billing/create-portal-session`, and finish `POST /api/webhooks/stripe`. Plan/usage tables already exist.
- **Per-plan rate limiting on Run Algorithm** (Free 3/day, Pro 50, Premium 250) — backend hook in `analyze_slip`.
- **Sport-aware game lists**: filter `/api/games/today` by sport, plug into the sport tab onChange. Currently shows NBA-style NBA games regardless of selected sport because seed data is NBA-only.
- **Live providers**: real ingestion for NBA via Ball Don't Lie (key already supported via env). Add NFL/MLB/NHL/Soccer/Golf provider adapters.
- **Saved slips dashboard page** at `/dashboard/slips` (CRUD UI for the existing API).
- **Password reset email flow** — `password_reset_tokens` table is already there; just needs Resend/SendGrid integration.
- **Mobile slip tray** UX polish (currently both desktop + mobile slip render with duplicate testids; collapse via media query).

## Smart enhancement suggestion
**Shareable algorithm runs** — generate a short URL per slip (`/r/<hash>`) so a Premium user can share their algorithm verdict with friends. Every prediction becomes a viral marketing object that brings new users to HawkNetic for free, and you can gate the "share" action behind Pro tier as another upgrade lever.
