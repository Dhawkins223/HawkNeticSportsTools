# HawkNetic Test Credentials

These accounts exist in the local SQLite database for testing purposes only.
The production PostgreSQL DB has no seeded users — use `POST /api/auth/signup` to create one fresh.

## App test users (created via /api/auth/signup, password ≥6 chars)
| Email | Password | Notes |
|---|---|---|
| `hawk@test.com` | `testpass123` | Original smoke-test user (may not exist on a fresh DB) |
| Any `*-<timestamp>@hawk.test` | `hawkpass123` | Created by automated E2E scripts |

To create a new user: `POST /api/auth/signup` with `{email, password, full_name}`, then `POST /api/auth/login` with the same email/password to get a session cookie (cookie name: `hwk_session`, samesite=lax, 7-day max-age).

## Admin / superuser
No seeded admin yet. To promote a user to admin (SQLite):
```sql
UPDATE users SET role = 'admin' WHERE email = '<your email>';
```
On Postgres:
```sql
UPDATE users SET role = 'admin' WHERE email = '<your email>';
```
(or wire into `/app/scripts/seed_v2.py` once you have a real admin email).

## Provider keys

The app gracefully degrades when these are absent. Add them to `/app/backend/.env` to enable the corresponding feature:

| Key | Used for | Status |
|---|---|---|
| `BALLDONTLIE_API_KEY` | Real NBA games/props/odds (replaces seed) | NOT SET |
| `OPENAI_API_KEY` | AI insights endpoint `/api/ai/chat` | NOT SET |
| `STRIPE_API_KEY` | Pro/Premium plan checkout | `sk_test_emergent` (placeholder — checkout returns 503) |
| `STRIPE_WEBHOOK_SECRET` | `/api/webhooks/stripe` signature verification | `whsec_emergent_preview` (placeholder) |
| `STRIPE_PRICE_ID_PRO` | Pro plan checkout session | `price_pro_placeholder` (placeholder — checkout returns 503) |
| `STRIPE_PRICE_ID_PREMIUM` | Premium plan checkout session | `price_premium_placeholder` (placeholder) |
| `RESEND_API_KEY` *or* `SENDGRID_API_KEY` | Password-reset email | NOT SET |

## Database engine

Local (preview) uses **SQLite** at `/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/data/hawknetic.sqlite`. Set `HAWKNETIC_ALLOW_SQLITE=1` in `/app/backend/.env`.

Production (Railway) uses **PostgreSQL** via `DATABASE_URL`. `schema_v2.py` is fully PG-compatible as of Feb 2026 (AUTOINCREMENT → SERIAL, information_schema for column checks).
