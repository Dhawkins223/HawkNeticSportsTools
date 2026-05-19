from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import EXPECTED_TABLES, database_readiness, init_db


def main() -> int:
    if settings.environment == "production" and not settings.database_url:
        raise RuntimeError("DATABASE_URL is required when HAWKNETIC_ENV=production.")

    print("[hawknetic] initializing database schema/bootstrap...")
    init_db()
    readiness = database_readiness()

    print(f"[hawknetic] engine={readiness['engine']} database_url_present={readiness['database_url_present']}")
    print(f"[hawknetic] tables_found={readiness['table_count']} expected={len(EXPECTED_TABLES)}")
    if readiness["missing_expected_tables"]:
        print("[hawknetic] missing_tables=" + ",".join(readiness["missing_expected_tables"]))
    else:
        print("[hawknetic] missing_tables=none")
    print("[hawknetic] init complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
