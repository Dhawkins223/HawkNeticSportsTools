from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import settings
from app.routes.api import router as api_router


def create_app() -> FastAPI:
    db.initialize()
    app = FastAPI(title="HawkneticSports API", version="3.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.frontend_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/")
    def root() -> dict:
        return {
            "service": "HawkneticSports API",
            "version": "3.0.0",
            "ui": "HawkneticSportsTools React dashboard served separately on port 3000",
            "docs": "/docs",
        }

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # NOTE: CSP intentionally relaxed — the React frontend is served from a
        # different origin/port behind the ingress, and the previous tight CSP
        # blocked legitimate React→FastAPI traffic in some preview environments.
        return response

    return app


app = create_app()
