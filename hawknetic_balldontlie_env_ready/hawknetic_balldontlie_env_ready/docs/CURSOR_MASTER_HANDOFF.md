# HawkNetic Master Cursor Handoff

## What this project is

HawkNetic is not just a landing page or just a betting model.

It is the combination of:

1. a customer-facing SaaS website
2. a FastAPI backend
3. a persistent database layer
4. a sports analytics and betting engine
5. a recommendation and parlay-selection system
6. an AI explanation layer so users can understand model outputs

This handoff folds the major architectural decisions from the full project work into one document so Cursor can see the whole shape of the system without forcing you to reconstruct the conversation.

---

## Current bundle status

This bundle contains:

- website frontend rendered through FastAPI templates
- auth, leads, subscriptions, cancellation, AI chat, and history
- local SQLite database for immediate startup
- clean module split for routes, services, repositories, DB bootstrap, and tests

This handoff also defines the **full HawkNetic direction** that should continue inside Cursor:

- the sports analytics engine
- the betting recommendation stack
- the production database evolution path
- the event and live-state model
- the AI explanation model
- the market, parlay, and format-selection logic

---

## Core product surfaces

### 1. Customer website
Purpose:
- explain what HawkNetic is
- capture leads
- convert users into paid accounts
- allow easy login and account management
- allow clear cancellation

### 2. User platform
Purpose:
- show games, markets, recommendations, AI explanations, and account state
- eventually expose live simulations, props, and parlay suggestions

### 3. HawkNetic engine
Purpose:
- ingest sports data
- compute features
- compute probabilities, uncertainty, EV, and ranking
- choose the best bet format:
  - straight
  - 2-leg parlay
  - 3-leg parlay
  - round robin
  - squad-style grouped bet only when structurally justified

### 4. AI explainer
Purpose:
- translate model outputs into plain language
- explain why a recommendation exists
- show uncertainty, edge, and fragility
- answer user questions about findings through backend-only OpenAI integration

---

## Architecture summary

### Application architecture
- **FastAPI** is the backend application layer.
- **Jinja2 templates** drive the current website surface.
- **SQLite** is used for immediate local operation.
- **Production path** remains **PostgreSQL**.
- **OpenAI integration** stays on the backend only.
- **Tests** cover the local runnable product.

### Production direction
For the real system, the strongest shape is:

- **PostgreSQL** as the system of record
- **Redis** for hot cache / latest-state reads
- append-only live tables for:
  - play-by-play
  - market history
  - game-state snapshots
  - timeout / ATO windows
- materialized or derived read surfaces for user-facing recommendations
- async workers for data ingest, feature generation, and simulation refresh

---

## Database direction from the full project work

### Canonical production DB strategy
Use **PostgreSQL** as the main database.

Why:
- relational integrity
- good support for live operational writes
- strong indexing and partitioning
- good fit for FastAPI async access
- easy migration path from current SQLite local mode

### Main schema domains
Recommended schema grouping:

- `ref` — leagues, seasons, teams, venues, sportsbooks
- `core` — games, players, player-team history, injuries, lineups
- `live` — play-by-play, game-state snapshots, timeout events, ATO windows
- `feature` — player and team feature snapshots
- `market` — market offers, market history, scores
- `model` — model runs, simulation runs, covariance, parlay candidates, recommendation outputs
- `ops` — scrape runs, snapshots, audit logs, parse errors

### Local DB in this bundle
The local bundle still uses SQLite for immediate startup, but the data model is intentionally shaped so Cursor can move it to PostgreSQL cleanly.

---

## HawkNetic betting and recommendation logic

### Main modeling philosophy
- no permanent fake god-tier ratings
- context matters more than static team identity
- uncertainty must stay explicit
- live betting must be modeled from **remaining game state**, not lazy full-game priors
- the system should optimize for **probability of profitable decision-making**, not just raw payout fantasy

### Core analytical chain
Raw data -> cleaned features -> stable ratings -> live adjustments -> market scoring -> recommendation

### Live-state concepts already established
- BSO = stable base player value
- GDO = game-day contextual value
- live GDO = state-adjusted game-day value
- team strength from weighted live rotation state
- after-timeout offense effect
- regime switching:
  - competitive
  - soft blowout
  - garbage time
- joint event pricing for same-game structures
- leg compatibility
- path stress
- conservative EV / lower-confidence-bound EV
- no-bet gates

### Parlay logic already established
If the goal is highest hit rate:
1. straight
2. 2-leg parlay
3. 3-leg parlay only if all legs survive strict filters
4. round robin when several good independent legs exist
5. novelty grouped structures only when structurally supported

### Leg-selection principles
Prefer legs with:
- positive or neutral compatibility
- low fragility
- low uncertainty
- positive conservative EV
- clean role stability
- low dependence on a broken path script

Avoid legs with:
- dead-weight payout
- high path stress
- conflict with other legs
- thin minutes assumptions
- high late-game chaos exposure without price edge

---

## ATO integration

ATO = After Timeout Offense

It was added as:
- a state-triggered, decaying offensive edge
- strongest on the first one to two possessions after timeout
- heavily shrunken to avoid fake coaching-magic noise

It affects:
- live player value
- live team PPP
- certain short-window player props
- timeout-state interpretation

---

## Website and funnel decisions

### Conversion logic
The customer-facing website should do four things clearly:
- explain what HawkNetic is
- show why it is different
- reduce friction to account creation
- make account control and cancellation obvious

### Good customer flow
Landing -> value proof -> pricing -> account creation -> dashboard -> recommendations -> AI explanation -> subscription management

### Cancellation principle
Cancellation should be as easy to find and perform as signup.

That is both good product design and the legally safer direction.

---

## AI integration principles

### Backend-only
Do not expose the OpenAI API key in frontend code.

### Use cases
- explain findings
- summarize model outputs
- answer user questions about a recommendation
- translate technical metrics into understandable language

### Current bundle behavior
- real OpenAI responses when `OPENAI_API_KEY` is present
- local fallback explanation path so the app still works immediately

### Conversation storage
Store:
- user prompt
- assistant response
- timestamps
- conversation linkage to account and finding where relevant

---

## Clean-code rules for Cursor

Cursor should preserve these rules:

- no spaghetti files
- no giant God routes
- no hidden DB writes inside template handlers
- keep service logic separated from routes
- keep repositories/data access separated from business logic
- test routes and services
- comment why, not just what
- do not hardcode secrets
- use environment variables
- keep future Postgres migration easy

---

## Recommended module boundaries

### `app/routes`
Owns:
- HTML pages
- JSON API endpoints
- request/response handling only

### `app/services`
Owns:
- auth logic
- billing logic
- AI orchestration
- recommendation orchestration
- future simulation orchestration

### `app/repositories`
Owns:
- SQL access
- persistence helpers
- object retrieval and storage

### `app/db`
Owns:
- connection setup
- bootstrap
- schema initialization
- seed/reference initialization

### `app/templates` and `app/static`
Own:
- frontend rendering assets

### `tests`
Own:
- regression safety

---

## What is in scope for Cursor next

Cursor should see this bundle as the base and then continue with:

1. expand the sports domain tables from local SQLite shape toward the production Postgres schema
2. add real market and recommendation pages
3. add game detail pages
4. add player detail pages
5. add recommendation explanation surfaces
6. add real billing provider integration
7. add historical and live ingest workers
8. add simulation and scoring workers
9. add admin screens for source health and model run visibility

---

## Major implementation truths

### Truth 1
The current bundle is **runnable immediately**.

### Truth 2
The current bundle is **not the same thing as a fully licensed, fully populated real-world sportsbook data product**.

### Truth 3
The structure is intended to be a **clean, production-oriented base**, not a toy.

### Truth 4
The conversation established a much bigger HawkNetic system than a simple marketing page. This handoff is here so Cursor can build with the full vision in mind.

---

## What was missing before this handoff
The prior zip was focused mainly on the website/application bundle.

This handoff corrects that by explicitly reconnecting:
- the HawkNetic engine vision
- the DB architecture direction
- the live betting and parlay logic
- the AI explanation path
- the customer website and account flows

So yes: **this document is the conversation-to-project bridge**.

---

## Immediate Cursor brief

When opening this repo in Cursor, treat HawkNetic as:

- a sports analytics SaaS
- with a customer acquisition website
- with account/subscription management
- with a clean FastAPI backend
- with a database that must evolve toward production Postgres
- with a recommendation engine that values uncertainty, compatibility, and conservative edge
- with AI explanations served only through backend integrations

Do not simplify it into a generic betting blog or generic dashboard app.

Build forward from the architecture already decided.
