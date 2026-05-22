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

The two **unique** moats are (1) the simulation-based correlation matrix surfaced per pair and (2) the binomial CI per leg / parlay — neither shipping competitor exposes these.

## Architecture
- **Backend:** FastAPI on port 8001 (`HawkneticSports API` v3.0.0). Bridge `/app/backend/server.py` → `app.main:app`. SQLite locally, Postgres-ready via `DATABASE_URL`.
- **Frontend:** Next.js 16 production build (`next start -H 0.0.0.0 -p 3000`). AuthProvider context wraps the app.
- **DB:** 51 tables. v2 additions: `player_skill`, `team_metrics`, `live_games`, `live_player_status`, `live_injuries`, `live_odds`, `live_line_movement`, `live_data_snapshots`, `predictions_outcomes`. Auth/saved slips reuse existing `users`, `parlays`, `parlay_legs`, `subscriptions`, `payments`, `plans`.

## Implemented (Wave A→D + competitive features)

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

### Multi-sport adapters
- 6 working adapters in `services/sport_adapters.py`: NBA, NFL, MLB, NHL, Soccer, Golf — sport-specific distributions (Normal/Poisson/Bernoulli) + trap rules + readiness signals.
- `GET /api/sports` exposes the public picker payload.

### SaaS platform
- Cookie-session auth (`/api/auth/signup` /login /logout /me, PBKDF2 hashing).
- `AuthProvider` + `useAuth()` hook, `/login`, `/signup`, `/pricing` pages.
- Auth header in dashboard, Save-slip button, 7 sport tabs.
- Saved slips API user-scoped (`POST/GET/DELETE /api/slips`).
- Admin tools quarantined to `/admin` with 4 tool groups.

### Competitive features (this session)
- **+EV scanner** — `GET /api/insights/top-ev` runs single-leg simulation across every active prop and ranks by EV. Mounted at the top of the dashboard as `<TopEvScanner />` widget; verified producing 8 edges from 25 props (Jimmy Butler under +55.4% EV, Giannis under +34.3%, etc.).
- **Competitor comparison block** on `/pricing` showing the capability matrix vs PrizePicks / Underdog / Action Network / OddsJam.
- Brand rename across UI, FastAPI title, footers, auth pages, admin page.

### Code quality (this session)
- `lib/auth.tsx`: AuthProvider `value` prop wrapped in `useMemo` to prevent unnecessary consumer re-renders.
- `HawkBet365DecisionDashboard.tsx`: 5 nested ternaries replaced with named helpers (`winProbabilityLabel`, `edgeLabel`, `evLabel`, `confidenceLabel`, `saveButtonLabel`).
- Magic numbers extracted: `FORM_MAX_WIDTH` in signup, `parlayMath.ts` already had `GRADE_*_THRESHOLD`, `SCORE_WEIGHT_*`, `EDGE_*` constants.

## Verified end-to-end
- Same-player correlation: ρ=0.126, parlay 31.6% vs naive 28.6% (was 0.006 / identical pre-fix).
- 6 sport adapters produce realistic per-sport scores.
- Auth: signup → /me → save slip → list slips full flow with cookie session.
- Run Algorithm: 7 games + 25 props, full verdict panel with simulation runs / Kelly / 95% CI / classification / trap flags.
- +EV scanner: 25 props scanned → 8 positive-EV edges ranked by EV per unit, surfaced on landing.
- All 6 sports + brand visible: H1 = "HawkneticSportsTools", scanner widget mounted, sport tabs (All/NBA/NFL/MLB/NHL/Soccer/Golf).

## Test credentials
See `/app/memory/test_credentials.md`.

## Next Action Items
- Provide Stripe keys + price IDs → wire `/api/billing/create-checkout-session`, billing portal, plan-activation webhook.
- Provide `BALLDONTLIE_API_KEY` → add a scheduled poller pushing into `/api/live/sync` so live data flows automatically.
- Per-plan rate limits on Run Algorithm (free=3/day, pro=50, premium=250) — hooks ready in `analyze_slip`.
- Sport-aware game lists: filter `/api/games/today` by sport so each tab shows only that sport's slate.
- Saved-slips dashboard page at `/dashboard/slips`.
- Real provider adapters for NFL/MLB/NHL/Soccer/Golf (the framework is in place).

## Smart enhancement suggestion
**Shareable algorithm runs** — generate a short URL per slip (`/r/<hash>`) so users can share verdicts socially. Gate share behind Pro tier — every prediction becomes viral marketing that brings new signups for free, AND share becomes another upgrade lever for the free → Pro conversion. Want me to add this next?
