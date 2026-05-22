# HawkNetic Test Credentials

These accounts exist in the local SQLite database for testing purposes only.

## App test users (created via /api/auth/signup)
| Email | Password | Notes |
|---|---|---|
| `hawk@test.com` | `testpass123` | Created by initial smoke test |
| `e2e-1779425539@hawk.test` | `hawkpass123` | Created by Playwright signup E2E |
| `final-1779425613@hawk.test` | `hawkpass123` | Created by API save-slip verification |

To create more, hit `POST /api/auth/signup` with `{email, password (≥6), full_name}`, then `POST /api/auth/login` with the same email/password to get a session cookie.

## Admin / superuser
No seeded admin yet. To promote a user to admin:
```sql
UPDATE users SET role = 'admin' WHERE email = '<your email>';
```
or wire into `/app/scripts/seed_v2.py` once you have a real admin email.

## Provider keys (NOT yet configured)
The app gracefully degrades when these are absent. Add them to `/app/backend/.env` to enable live data:

| Key | Used for |
|---|---|
| `BALLDONTLIE_API_KEY` | Real NBA games/props/odds (replaces seed) |
| `OPENAI_API_KEY` | AI insights endpoint `/api/ai/chat` |
| `STRIPE_SECRET_KEY` | Pro/Premium plan checkout |
| `STRIPE_WEBHOOK_SECRET` | `/api/webhooks/stripe` signature verification |
| `STRIPE_PRICE_ID_PRO` | Pro plan checkout session |
| `STRIPE_PRICE_ID_PREMIUM` | Premium plan checkout session |
| `RESEND_API_KEY` *or* `SENDGRID_API_KEY` | Password-reset email |
