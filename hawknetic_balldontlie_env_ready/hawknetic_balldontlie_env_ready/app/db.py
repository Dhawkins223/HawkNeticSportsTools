"""Database facade used by app startup and modules expecting app.db.* APIs."""

from app.database import *  # noqa: F401,F403
from app.database import init_db


def initialize() -> None:
    """Initialize database schema and seed data for application startup."""
    init_db()
