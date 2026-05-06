from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

DB_PATH = ROOT / "data" / "test_hawknetic.sqlite"
os.environ["HAWKNETIC_DB_PATH"] = str(DB_PATH)

from app.db import reset_db  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    reset_db()
    app = create_app()
    with TestClient(app) as client:
        yield client
