from __future__ import annotations

from urllib.parse import urlencode

from .http import HttpClient


class KalshiPublicClient:
    def __init__(self, base_url: str = "https://external-api.demo.kalshi.co/trade-api/v2") -> None:
        self.base_url = base_url.rstrip("/")
        self.http = HttpClient()

    def markets(self, limit: int = 20, status: str = "open", query: str | None = None) -> dict:
        params: dict[str, str | int] = {"limit": limit, "status": status}
        if query:
            params["query"] = query
        url = f"{self.base_url}/markets?{urlencode(params)}"
        return self.http.get_text(url).json()
