from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.services import historical_raw


class _Resp:
    def __init__(self, status_code: int, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            req = httpx.Request("GET", "https://example.com")
            resp = httpx.Response(self.status_code, request=req, text=self.text, headers=self.headers)
            raise httpx.HTTPStatusError("boom", request=req, response=resp)


def test_append_error_includes_retry_fields() -> None:
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(429, request=req, text="rate limited", headers={"Retry-After": "60"})
    exc = httpx.HTTPStatusError("429", request=req, response=resp)
    row = historical_raw.append_error(2024, "https://example.com", "schedule.csv", exc, attempt=4, retry_after="60", final_failure=True, elapsed_seconds=12.2)
    assert row["status_code"] == "429"
    assert row["retry_after"] == "60"
    assert row["attempt"] == 4
    assert row["final_failure"] == "true"


def test_scrape_cooldown_blocks_retry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(historical_raw, "raw_root", lambda: tmp_path)
    season_dir = tmp_path / "2024"
    season_dir.mkdir(parents=True, exist_ok=True)
    (season_dir / "cooldown_429.json").write_text(json.dumps({"retry_after_epoch": 9999999999}), encoding="utf-8")
    result = historical_raw.BasketballReferenceScraper().scrape_season(2024)
    assert result.coverage["status"] == "failed"
    assert "rate-limited" in result.coverage.get("failure_reason", "")
