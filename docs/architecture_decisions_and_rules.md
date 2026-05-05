# HawkNetic architecture decisions and rules

Product rules:
- HawkNetic is both a customer SaaS website and a sports analytics engine.
- The website must support landing page, pricing, register and login, dashboard, account management, cancellation, and AI explanation chat.

Backend rules:
- FastAPI is the backend framework.
- AI calls stay backend-only.
- SQLite is acceptable for immediate local run.
- PostgreSQL remains the target production database.

Database rules:
- Use normalized writes and denormalized read surfaces.
- Keep append-only history for live facts and market history.
- Separate reference, core, live, feature, market, model, and ops concerns.
- Preserve room for source mappings and replay-safe ingest.

Betting engine rules:
- Optimize for hit quality and conservative edge.
- Do not use naive independent-leg multiplication for correlated same-game bets.
- Use leg compatibility and path stress.
- Default order of bet format for hit rate: straight, then 2-leg parlay, then 3-leg parlay only if justified, then round robin when independent edges exist.

Modeling rules:
- BSO stable, GDO contextual.
- Live model should work from remaining state, not lazy full-game priors.
- ATO matters as a small decaying timeout edge.
- Uncertainty must always be stored and shown.

Provider integration rules:
- Do not let BALLDONTLIE define HawkNetic core schema.
- Store raw provider data in provider-specific tables.
- Normalize provider data into HawkNetic canonical tables.
- The HawkNetic algorithm must read canonical tables, not provider payloads.

Code rules:
- No spaghetti code.
- Services separate from routes.
- Repositories separate from services.
- Tests required.
- Comments should explain reasoning.
