from __future__ import annotations

import json

from app.database import database_readiness


def main() -> int:
    report = database_readiness()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
