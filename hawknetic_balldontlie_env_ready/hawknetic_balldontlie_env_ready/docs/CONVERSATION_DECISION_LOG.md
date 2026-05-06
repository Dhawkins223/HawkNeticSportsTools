# HawkNetic Conversation Decision Log

This file compresses the important decisions that were made across the project work so Cursor can use them as durable rules.

## Product decisions
- HawkNetic is both a **customer SaaS website** and a **sports analytics engine**.
- The website must support:
  - landing page
  - pricing
  - register/login
  - dashboard
  - account management
  - easy cancellation
  - AI explanation/chat

## Backend decisions
- FastAPI is the backend framework.
- AI calls stay backend-only.
- SQLite is acceptable for immediate local run.
- PostgreSQL remains the target production database.

## Database decisions
- use normalized writes, denormalized read surfaces
- keep append-only history for live facts and market history
- separate reference, core, live, feature, market, model, ops concerns
- preserve room for source mappings and replay-safe ingest

## Betting-engine decisions
- optimize for hit quality and conservative edge
- do not use naive independent-leg multiplication for correlated same-game bets
- use leg compatibility and path stress
- default order of bet format for hit rate:
  1. straight
  2. 2-leg parlay
  3. 3-leg parlay only if justified
  4. round robin when independent edges exist
  5. grouped novelty formats only when structurally supported

## Modeling decisions
- BSO stable, GDO contextual
- live model should work from remaining state, not lazy full-game priors
- ATO matters as a small decaying timeout edge
- uncertainty must always be stored and shown

## UX decisions
- cancellation should be easy and visible
- the website should reduce friction and explain value fast
- AI should make findings understandable, not just technical

## Code decisions
- no spaghetti code
- services separate from routes
- repositories separate from services
- tests required
- comments should explain reasoning
