# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

HawkNetic is an NBA sports analytics / betting intelligence platform with two services:
- **Backend** (FastAPI/Python): `hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/`
- **Frontend** (Next.js/React): `frontend/`

### Starting services

**Backend (port 8000):**
```bash
cd hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready
export HAWKNETIC_ALLOW_SQLITE=1
python3 run_local.py
```

**Frontend (port 3000):**
```bash
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

### Running tests

```bash
cd hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready
HAWKNETIC_ALLOW_SQLITE=1 python3 -m pytest -q
```
Tests use SQLite (auto-created at `data/test_hawknetic.sqlite`). No external services needed.

### Linting / type checking

- **Frontend typecheck:** `cd frontend && npx tsc --noEmit`
- **Frontend ESLint:** Not configured yet (no `eslint.config.js` exists; `next lint` was removed in Next.js 16).
- **Backend:** No linter configured in the repository.

### Key gotchas

- Use `python3` not `python` (the latter is not available on this VM).
- pip installs to `~/.local/bin` — ensure `PATH` includes it (`export PATH="$HOME/.local/bin:$PATH"`).
- The backend requires `HAWKNETIC_ALLOW_SQLITE=1` for local dev (otherwise it expects `DATABASE_URL` for PostgreSQL).
- Seeded test account: `free@hawknetic.local` / `free-access` (created automatically on first DB init).
- External APIs (OpenAI, BallDontLie, Stripe) all have local fallbacks; the app runs fully without API keys.
- The `testuser@hawknetic.local` email may already be registered in the SQLite DB from previous runs.
