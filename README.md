# NBA Edge Dashboard

Full-stack Next.js 14 application that surfaces NBA betting edges powered by live odds, injury reports, fatigue modeling, and correlated SGP simulations. The project couples a Bet365-style interface with a Prisma-backed domain layer so the same engine can power the UI and downstream analytics.

## Getting started

1. Copy `.env.example` to `.env.local` and populate the provider URLs/keys. For local development the defaults target SQLite:

   ```bash
   cp .env.example .env.local
   ```

2. Install dependencies and set up the database:

   ```bash
   npm install
   npx prisma migrate dev --name init
   ```

3. Launch the app:

   ```bash
   npm run dev
   ```

4. With the dev server running, call the sync endpoint (after setting `ADMIN_TOKEN`) to pull the latest NBA schedule, odds, injuries, and player baselines:

   ```bash
   curl -X POST http://localhost:3000/api/sync -H "x-admin-token: YOUR_ADMIN_TOKEN"
   ```

If provider credentials are missing or upstream APIs are unavailable, the UI will surface a clear banner and API routes return `503` responses instead of mock data.

## Architecture highlights

- **Next.js App Router (14.2)** with TypeScript, Tailwind, and TanStack Query for responsive, real-time UX.
- **Prisma ORM** with SQLite in development and PostgreSQL-ready schema for production deployments.
- **Providers** pull live games, odds, props, injuries, and baselines via `lib/providers/*`. Missing credentials throw so downstream routes can respond with `503` messages rather than stale data.
- **Modeling layer** (`lib/model`) computes 2K-style player ratings, market edges, Kelly staking, and correlated Monte Carlo simulations for SGPs.
- **API routes** under `/app/api/nba/*` expose games, team ratings, prop edges, and SGP simulations; `/api/sync` orchestrates full refreshes gated by `ADMIN_TOKEN`.
- **Bet365-inspired UI** with pages for Games, Props, Tickets (top EV markets), and a transparency report. Every view pulls from live API routes—no embedded fixtures.

## Development tips

- Update `DB_PROVIDER` and `DATABASE_URL` in `.env.local` when targeting Postgres or another supported database.
- Prisma logs warnings/errors by default; adjust the client instantiation in `lib/db.ts` if you need verbose query logging.
- The same `SgpComposer` and `BetSlip` components are reused across pages. Selections are converted into `SgpLegInput` entries before they hit the `/api/nba/sgp/simulate` route so correlation logic is always respected.
- Use `npm run lint` to ensure code style aligns with the Next.js default ESLint configuration.
