from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import repo_path


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status: int
    text: str
    fetched_at: str
    from_cache: bool = False

    def json(self) -> dict[str, Any]:
        return json.loads(self.text)


class HttpClient:
    def __init__(
        self,
        user_agent: str = "kalshi-research-bot/0.1",
        cache_dir: str | Path | None = None,
        cache_ttl_seconds: int = 120,
    ) -> None:
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir) if cache_dir else repo_path("data", "http_cache")
        self.cache_ttl_seconds = max(0, int(cache_ttl_seconds))

    def get_text(self, url: str, timeout: int = 20) -> HttpResponse:
        cache_path = self._cache_path(url)
        if self.cache_ttl_seconds and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                saved_at = float(cached.get("saved_at", 0))
                if time.time() - saved_at <= self.cache_ttl_seconds:
                    return HttpResponse(
                        url=url,
                        status=int(cached.get("status", 200)),
                        text=str(cached.get("text", "")),
                        fetched_at=_iso_from_epoch(saved_at),
                        from_cache=True,
                    )
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            result = HttpResponse(url=url, status=response.status, text=body, fetched_at=_iso_from_epoch(time.time()))
            self._write_cache(cache_path, result)
            return result

    def _cache_path(self, url: str) -> Path:
        import hashlib

        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _write_cache(self, cache_path: Path, response: HttpResponse) -> None:
        if not self.cache_ttl_seconds:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "url": response.url,
                        "status": response.status,
                        "saved_at": time.time(),
                        "fetched_at": response.fetched_at,
                        "text": response.text,
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            return


def _iso_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
