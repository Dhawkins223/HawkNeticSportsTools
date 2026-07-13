# Competitive Capability Analysis

Status: Phase 0 research baseline. Updated 2026-07-13.

## Technical summary

HawkNetic already has a defensible research foundation: fresh-source checks, deterministic snapshot hashes, retained rejections, settlement-only labels, de-duplicated evaluation, manual-review slip integrity, and research-only controls. It does not yet have the licensed multi-book odds breadth, player-prop depth, line-history coverage, sub-minute delivery, or customer workflow needed to compete with established odds workstations.

The first competitive advantage should not be a claim of better picks. It should be trustworthy evidence: every visible opportunity must show what source was observed, when it was observed, how it was normalized, which calculation produced it, why it is still valid, and why incompatible legs were rejected.

Public competitor descriptions below are product claims, not independently verified performance evidence. Pricing and feature availability can change and must be rechecked before product decisions.

## Public competitor capabilities

| Product | Publicly described capabilities | Product lesson | What HawkNetic must not copy or claim |
|---|---|---|---|
| [ProfitDuel](https://www.profitduel.com/) | Promo conversion, arbitrage matching, positive-EV matching, low-hold matching, odds screening, education, and community access | New users value a guided workflow more than a raw odds grid | Do not promise locked profit, consistent profit, or promo conversion without licensed odds, exact settlement rules, and jurisdiction review |
| [Prop Professor](https://www.propprofessor.com/) | Positive-EV, arbitrage, smart-money, odds-screen, fantasy optimization/comparison, slip generation, and mobile alerts; its site publicly claims average updates below two seconds | Prop research and alerts are core workflows, not side panels | Do not repeat the latency claim without measuring source-to-screen latency end to end |
| [OddsJam](https://oddsjam.com/) | Odds comparison, positive-EV, arbitrage, promo tools, and parlay construction | Opportunity discovery must connect directly to supporting prices and assumptions | Do not describe an opportunity as risk-free or algorithmically profitable |
| [Unabated](https://unabated.com/articles/learn-about-the-game-odds-screen) | Best-line comparison, synthetic hold, vig-free consensus line, line history, alternate-line comparison, and market-movement cues | Fair-price context and price history make an odds screen useful | Do not label movement as sharp or smart money without a documented method and evidence |

## Capability comparison

| Capability | HawkNetic today | Competitive requirement | Current decision |
|---|---|---|---|
| Kalshi listed-combo verification | Implemented for exact active quoted KXMVE listings | Preserve and generalize the evidence model | Keep as a differentiator |
| Multi-book odds aggregation | One optional Odds API adapter plus limited ESPN/public-source research | Licensed, normalized, timestamped multi-book feed | Blocked pending provider bakeoff and rights review |
| Best-line discovery | Not implemented as a canonical sportsbook workstation | Comparable line/price identity across books | Phase 2-3 |
| Line and price history | Kalshi snapshots and research ledgers exist; sportsbook history is incomplete | Append-only quote history with opening/current/closing context | Phase 2 |
| Player props | Not a production capability | Player identity, prop taxonomy, alternate lines, settlement | Phase 2 after provider selection |
| No-vig probability | Basic implied-probability math exists | Multiple documented methods and market-specific validation | Phase 4 |
| Positive EV | Existing edge research is Kalshi-oriented and not promotable | Consensus inputs, uncertainty, expiration, lineage, cost assumptions | Phase 4, research-only |
| Arbitrage | Not implemented as a verified cross-book engine | Matching rules, settlement parity, fees, rounding, freshness | Phase 4 |
| Low hold | Not implemented | Complete outcome set and exact hold calculation | Phase 4 |
| Line movement and CLV | Partial audit concepts exist | Full quote history, closing-line capture, annotated events | Phase 5 |
| Model probabilities | Baselines and validation controls exist; no model qualifies for promotion | Approved versions, leakage controls, calibration, holdout evidence | Phase 5 only after data foundation |
| Correlation-aware combos | Kalshi compatibility and overlap guards exist | Book-specific availability, joint probability, dependency evidence | Phase 6 |
| Alerts | Optional deduplicated Slack operational alerts exist | User rules, entitlement, freshness, expiry, quiet hours | Phase 7 |
| Tracker | Research ledgers exist; no user decision tracker | Manual decisions, source snapshot, closing line, result provenance | Phase 7 |
| Authentication | Local roles, sessions, CSRF, lockout, audit, hosted auth requirement | Hosted session verification and recovery policy | Complete before customer staging |
| Entitlements | Not implemented | Server-side feature and usage gates | Phase 8; no billing yet |

## Deliberate non-goals

- No wager placement, order staging, sportsbook login, or slip upload.
- No sportsbook credentials.
- No casino or promotional conversion workflow in the current program.
- No claims of guaranteed profit, risk-free outcomes, locks, verified win rate, or competitive parity.
- No copying proprietary code, product surfaces, branding, or private data.
- No public model promotion while current model states remain baseline-only, insufficient-sample, or failed-validation.

## Credible differentiation

1. **Evidence-first opportunities.** Every recommendation can carry source timestamps, hashes, freshness, parser version, calculation version, and invalidation reason.
2. **Kalshi combination integrity.** The current platform already fails closed unless a complete active listed combo can be reproduced.
3. **Research honesty.** Rejected, unresolved, blocked, stale, duplicate, and push/no-edge rows stay out of win-rate and profitability denominators.
4. **Local and hosted parity.** SQLite remains a supported local runtime while PostgreSQL becomes the explicit hosted store through one contract.
5. **Failure visibility.** A provider outage should become stale, blocked, or unavailable data instead of silently changing the answer.

## Provider and licensing requirements

Competitive features require more than technical access. Before activating a provider, record:

- legal and commercial usage rights;
- display and redistribution rights;
- supported books, jurisdictions, sports, markets, props, alternates, and live coverage;
- source timestamps and update cadence;
- historical and closing-line depth;
- mapping identifiers and correction behavior;
- settlement coverage;
- rate limits, expected request volume, and total operating cost;
- reliability, support, and termination/retention terms.

Public pages and no-key endpoints may remain research inputs only when their terms permit the use. Firecrawl is a retrieval tool, not a license to reuse or redistribute source data.

## Decision

HawkNetic is not at competitive parity. The architecture is worth extending because its validation and slip-integrity controls are stronger than a typical prototype. The next implementation phase is PostgreSQL business-runtime completion, followed by a measured odds-provider bakeoff and canonical odds model. Product claims remain blocked.

