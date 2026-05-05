# HawkNetic customer platform

FastAPI project with:
- landing page
- lead capture
- account registration and login
- pricing and subscriptions
- self-serve cancellation
- AI explanations
- BALLDONTLIE integration for teams, players, and games

## Run locally
```bash
pip install -r requirements.txt
python run_local.py
```

Open `http://127.0.0.1:8000`

## Provider structure
BALLDONTLIE stays isolated in a provider area.
HawkNetic logic should read canonical HawkNetic tables, not raw provider payloads.
