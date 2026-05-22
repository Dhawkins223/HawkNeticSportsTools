"""Bridge module so Emergent supervisor can import the HawkNetic FastAPI app.

The Emergent supervisor runs `uvicorn server:app` from /app/backend on port 8001.
The real application lives in /app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/
under the `app` package, so we add that path to sys.path and re-export `app`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Default to SQLite for local/preview environment unless explicit DATABASE_URL is set.
os.environ.setdefault("HAWKNETIC_ALLOW_SQLITE", "1")
os.environ.setdefault("HAWKNETIC_FRONTEND_ORIGINS", "*")
os.environ.setdefault("HAWKNETIC_ENV", "preview")

HAWKNETIC_ROOT = Path("/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready")
if str(HAWKNETIC_ROOT) not in sys.path:
    sys.path.insert(0, str(HAWKNETIC_ROOT))

from app.main import app  # noqa: E402

# Re-configure CORS to use a regex wildcard so `allow_credentials=True` works
# with arbitrary preview/cloud subdomains. The default CORS middleware was
# initialized with `allow_origins=["*"]` + `allow_credentials=True`, which the
# CORS spec rejects (browsers ignore the response). Patch the middleware here.
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

for mw in app.user_middleware:
    if mw.cls is CORSMiddleware:
        mw.kwargs["allow_origins"] = []
        mw.kwargs["allow_origin_regex"] = ".*"
        mw.kwargs["allow_credentials"] = True
        mw.kwargs["allow_methods"] = ["*"]
        mw.kwargs["allow_headers"] = ["*"]
# Force middleware stack to rebuild on next request
app.middleware_stack = None
