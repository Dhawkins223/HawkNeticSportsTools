# Backend API Contract

Status: current-route inventory plus additive target contract. No new public API is implemented by this document.

## Technical summary

The existing dashboard and operator endpoints remain the compatibility surface. New customer features will use versioned JSON endpoints only after PostgreSQL business-runtime parity. All responses must distinguish current, stale, blocked, unavailable, empty, and error states. Research outputs must never be presented as orders, guaranteed outcomes, or verified profitability.

## Current routes

| Method | Path | Audience | Purpose |
|---|---|---|---|
| `GET` | `/` | authenticated when hosted | Current research dashboard |
| `GET` | `/login` | public | Login page when user auth is enabled |
| `POST` | `/auth/login` | public with controls | Create authenticated session |
| `POST` | `/auth/logout` | authenticated | Revoke session |
| `GET` | `/auth/me` | authenticated | Current principal summary |
| `GET` | `/healthz` | infrastructure | Process liveness only |
| `GET` | `/readyz` | infrastructure/operator | Database migration and research-safety readiness |
| `GET` | `/data.json` | dashboard | Current safe dashboard payload |
| `GET` | `/refresh-status` | dashboard/operator | Refresh state |
| `GET` | `/quality.json` | dashboard/operator | Data-quality summary |
| `GET` | `/research-record.json` | dashboard/operator | De-duplicated settled research record |
| `GET` | `/review-packets.json` | manual review | Available review packets |
| `GET` | `/review-packet.json` | manual review | One structured review packet |
| `GET` | `/review-packet.txt` | manual review | One copyable text packet |
| `POST` | `/refresh` | admin/manual control | Request a bounded refresh |
| `GET` | `/ops` | admin | Private operator inbox |
| `GET` | `/internal/status.json` | admin | Internal worker/database/model status |
| `GET` | `/internal/operator-messages.json` | admin | Operator queue read |
| `POST` | `/internal/operator-messages` | admin + CSRF | Add a non-executing operator message |

The current route behavior is defined by tests and remains supported during Phase 1.

## Common response envelope for new versioned routes

Future `/api/v1/*` JSON responses use:

```json
{
  "request_id": "opaque-id",
  "generated_at": "2026-07-13T16:45:53Z",
  "source_cutoff": "2026-07-13T16:45:00Z",
  "state": "current",
  "data": {},
  "warnings": [],
  "error": null
}
```

Allowed top-level states:

```text
current
stale
blocked
unavailable
empty
error
```

`stale` data is never labeled live. When a hard freshness deadline passes, live opportunity and review endpoints return no actionable data.

## Error shape

```json
{
  "code": "low_confidence_event_match",
  "message": "The source event could not be matched safely.",
  "retryable": false,
  "details": {},
  "request_id": "opaque-id"
}
```

`details` is allow-listed and contains no secrets, raw SQL, stack trace, database URL, cookies, auth headers, private service addresses, or raw private payloads.

## Planned additive route groups

These are contract targets, not implemented endpoints:

| Group | Purpose | Minimum gate before implementation |
|---|---|---|
| `/api/v1/sports` | Supported sports/leagues and source coverage | Provider registry |
| `/api/v1/events` | Canonical events, participants, status, start time | Canonical identity/mapping |
| `/api/v1/odds` | Comparable current quotes and source age | Licensed provider + odds history |
| `/api/v1/markets/{id}/history` | Line/price history | Append-only quote history |
| `/api/v1/opportunities` | EV, arbitrage, low-hold, movement, combo candidates | Phase 4 calculation lineage |
| `/api/v1/predictions` | Approved research predictions and validation context | Phase 5 model gate |
| `/api/v1/combos` | Source-available compatible combinations | Phase 6 correlation/availability gate |
| `/api/v1/alerts` | User alert rules and current notifications | Hosted auth + entitlements |
| `/api/v1/tracker` | Manual research decisions and outcomes | Hosted auth + PostgreSQL |
| `/api/v1/stream` | SSE updates | Measured need, auth, backpressure, resume IDs |

## Odds resource requirements

Every quote returned to a customer includes:

- canonical event, market, selection, and sportsbook IDs;
- sport, league, teams/players, and event start time;
- line, price, and odds format using exact serialized decimals;
- pregame/live/closed status;
- provider observation time, local receipt time, generated time, source age, and hard expiry;
- source and calculation version;
- mapping confidence/status;
- freshness state and invalidation reason.

Low-confidence mappings, blocked sources, stale quotes, and incompatible market definitions are excluded from opportunity calculations.

## Opportunity resource requirements

Every opportunity includes:

- stable ID and type;
- created, updated, source-cutoff, and expiration times;
- source quotes and comparable market definition;
- method and calculation version;
- fair/no-vig/model probability fields only when supported;
- estimated edge/EV with uncertainty and cost assumptions;
- evidence, warnings, and invalidation reason;
- entitlement and research-only state.

Arbitrage requires a complete outcome set, comparable settlement rules, fresh active quotes, rounding, and fees. It is never labeled risk-free.

## Combo resource requirements

A combo response includes source/book availability, complete legs, source quote/payout, estimated joint probability when supported, dependency evidence, correlation status, expiry, and rejected-alternative reasons. When evidence is insufficient:

```text
correlation_status = insufficient_evidence
```

The response is blocked or downgraded. It never implies that unrelated individually visible legs can be combined.

## Authentication and authorization

- Hosted customer and operator routes require server-side authentication.
- Roles are checked server-side.
- State-changing routes require CSRF protection for cookie sessions.
- Entitlements are checked server-side when introduced.
- Disabled, expired, locked, or revoked accounts are denied.
- Operator routes never share customer response payloads by accident.

## Pagination, filtering, and caching

List endpoints use bounded cursor pagination. Filters are allow-listed and deterministic. Responses may expose an `ETag`; unchanged requests can return `304`. Cache metadata never extends a source hard-expiry deadline.

## Health and readiness

`/healthz` remains process liveness only.

`/readyz` reports whether the selected database is connected and migrated, required schemas exist, hosted auth is configured, research-only controls pass, cache state is known, and critical internal dependencies are ready. Optional provider outages do not fail global readiness; affected resources become blocked or unavailable.

## Compatibility policy

- Current dashboard/operator endpoints remain stable during Phase 1.
- New customer endpoints are additive and versioned.
- Breaking response changes require a new version or a documented compatibility period.
- No route silently changes metric denominators, freshness rules, or research-only semantics.

