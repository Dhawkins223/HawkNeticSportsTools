# Odds Provider Evaluation

Status: Phase 0 evaluation. No paid provider has been activated or purchased.

## Technical summary

The platform should not choose an odds provider from advertised sportsbook count alone. The current integration supports The Odds API when a key exists, then ESPN public structured data, then optional Firecrawl retrieval. During the 2026-07-13 audit, sports collection was blocked because the public source produced no scheduled events or usable odds rows. That is correct fail-closed behavior, but it is not sufficient for a competitive product.

The recommended next step is a controlled bakeoff in isolated staging. Use the same sport, event window, markets, and polling schedule for every candidate. Activate no paid plan without explicit approval and a rights review.

## Evaluation criteria

Every candidate must be scored on:

- contractual rights for research, commercial display, storage, history, and redistribution;
- sportsbook, sport, league, player-prop, alternate-line, futures, and live coverage;
- source observation timestamps and update cadence;
- event/player/market identifiers and mapping stability;
- opening, current, closing, and historical depth;
- corrections and settlement coverage;
- latency, freshness, missing rate, duplicate rate, and mapping accuracy;
- rate limits, payload size, monthly request volume, and total cost;
- reliability, support, auditability, and termination terms.

## Candidate registry

| Candidate | Proposed registry status | Strengths | Gaps and blockers | Current action |
|---|---|---|---|---|
| ESPN public structured endpoints | `permitted_public_endpoint` only after terms review | No key; useful schedules, statuses, scores, and occasional odds metadata | Odds coverage is incomplete and can be empty; commercial display/redistribution rights are not established | Keep as research schedule/result fallback; never promise odds coverage |
| Firecrawl | `optional` retrieval connector | Controlled snapshot retrieval, hashes, blocked-page detection, timeout/backoff | It is not an odds license or source of truth; source rights still control use | Keep optional and fail closed |
| [The Odds API](https://the-odds-api.com/) | `licensed_aggregator` when configured under an approved plan | Existing adapter; broad sports/books; standard markets; paid historical snapshots and additional markets | Credit costs scale by markets/regions; player-prop and history access vary by plan; display rights need terms review | Best low-friction bakeoff candidate; no purchase authorized |
| [SportsGameOdds](https://sportsgameodds.com/docs/basics) | `licensed_aggregator` candidate | Publicly describes event-based billing, props, alternates, scores, results, history, and WebSocket options | Coverage and accuracy claims need independent measurement; commercial rights and exact history vary by plan | Compare in free trial only after key authorization |
| [SportsDataIO](https://sportsdata.io/live-odds-api) | `licensed_aggregator` candidate | Aggregated odds, props, futures, live/closing lines, official-data mapping, injuries/lineups/stats products | Sales-led access; historical data and rights can require separate products/keys; likely higher cost | Enterprise comparison, not initial activation |
| [Sportradar Odds APIs](https://developer.sportradar.com/odds/reference/intro) | `official_api` / enterprise candidate | Prematch, live, player props, futures, probability and mapping APIs; extensive bookmaker coverage described publicly | Contract, licensing, jurisdiction, and cost require sales review; integration scope is large | Long-term enterprise candidate only |

The registry status describes the intended legal/operational category, not an approval. A provider is not activated until credentials, contract rights, supported use, and retention rules are recorded.

## Controlled bakeoff design

### Scope

- Start with one in-season league.
- Use moneyline, spread, and total first.
- Add player props only after event/team/player mapping passes.
- Collect pregame snapshots at a fixed cadence; do not claim live latency until measured.
- Use the same event window and bookmaker subset for each provider.

### Measurements

For each provider and collection run, record:

- request start and completion time;
- provider source time and local receipt time;
- response latency and source age;
- events expected, received, mapped, rejected, and duplicated;
- books and markets expected/received;
- prop and alternate-line coverage;
- corrections and final settlement availability;
- response bytes and request/credit cost;
- rate-limit and error responses;
- estimated monthly cost at 1-, 5-, 15-, and 60-minute cadences.

### Acceptance gate

A candidate can become the primary source only when:

1. usage and display rights are approved;
2. source timestamps are available or a conservative receipt-time policy is documented;
3. at least 95% of the controlled event slate maps automatically with no forced joins;
4. missing/duplicate/correction behavior is measured;
5. settlement coverage is sufficient for evaluation;
6. operating cost fits an explicitly approved budget;
7. stale, blocked, and quota-exhausted responses fail closed.

These thresholds are initial engineering gates, not provider quality guarantees.

## Current measured result

- Activated paid providers: none.
- Current sports source mode: scraper/public structured fallback.
- Latest controlled sports collection: blocked with `blocked_no_scheduled_events`, `empty_content`, and `no_source_records` evidence.
- Valid current source records in that payload: 0.
- No latency, bookmaker coverage, prop coverage, or projected cost comparison is yet decision-ready.
- Rejected and blocked rows remain excluded from metrics.

## Decision

Keep ESPN and Firecrawl as research fallbacks. Evaluate The Odds API first because an adapter already exists, then one event-priced candidate such as SportsGameOdds. Keep SportsDataIO and Sportradar as enterprise comparisons. Do not pay for or activate a provider until the bakeoff, rights review, and budget approval are complete.

