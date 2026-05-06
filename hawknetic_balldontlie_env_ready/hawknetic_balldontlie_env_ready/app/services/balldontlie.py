from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.repositories import (
    AuditRepository,
    CanonicalRepository,
    ProviderSyncRepository,
    RawBallDontLieRepository,
)


@dataclass(frozen=True)
class BallDontLieSyncResult:
    resource: str
    raw_records_written: int
    canonical_records_written: int
    source_count: int


class BallDontLieClient:
    """Thin provider client that follows BALLDONTLIE's HTTP structure exactly."""

    def __init__(self, api_key: str, base_url: str, v2_base_url: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.v2_base_url = v2_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key}

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()

    async def get_teams(self) -> dict:
        return await self._get(f"{self.base_url}/teams")

    async def search_players(self, search: str, per_page: int = 25) -> dict:
        return await self._get(
            f"{self.base_url}/players",
            params={"search": search, "per_page": min(max(per_page, 1), 100)},
        )

    async def get_games_by_date(self, date_str: str, per_page: int = 100) -> dict:
        return await self._get(
            f"{self.base_url}/games",
            params={"dates[]": date_str, "per_page": min(max(per_page, 1), 100)},
        )


class BallDontLieService:
    PROVIDER = "balldontlie"

    @staticmethod
    def client() -> BallDontLieClient:
        return BallDontLieClient(
            api_key=settings.balldontlie_api_key,
            base_url=settings.balldontlie_base_url,
            v2_base_url=settings.balldontlie_v2_base_url,
            timeout_seconds=settings.balldontlie_timeout_seconds,
        )

    @staticmethod
    def ensure_configured() -> None:
        if not settings.balldontlie_api_key:
            raise RuntimeError("BALLDONTLIE_API_KEY is not configured.")

    @staticmethod
    async def sync_teams(user_id: int | None = None) -> BallDontLieSyncResult:
        BallDontLieService.ensure_configured()
        sync_id = ProviderSyncRepository.start(provider=BallDontLieService.PROVIDER, resource="teams")
        try:
            payload = await BallDontLieService.client().get_teams()
            items = payload.get("data", [])
            raw_written = RawBallDontLieRepository.upsert_teams(items)
            canonical_written = CanonicalRepository.normalize_teams_from_raw()
            ProviderSyncRepository.finish(sync_id, status="succeeded", records_written=raw_written)
            AuditRepository.log(
                user_id,
                "balldontlie_sync_teams",
                "provider_sync_runs",
                str(sync_id),
                f"raw={raw_written};canonical={canonical_written}",
            )
            return BallDontLieSyncResult(
                resource="teams",
                raw_records_written=raw_written,
                canonical_records_written=canonical_written,
                source_count=len(items),
            )
        except Exception as exc:
            ProviderSyncRepository.finish(sync_id, status="failed", error_text=str(exc))
            raise

    @staticmethod
    async def sync_players(search: str, user_id: int | None = None) -> BallDontLieSyncResult:
        BallDontLieService.ensure_configured()
        sync_id = ProviderSyncRepository.start(provider=BallDontLieService.PROVIDER, resource=f"players:{search}")
        try:
            payload = await BallDontLieService.client().search_players(search=search)
            items = payload.get("data", [])
            raw_written = RawBallDontLieRepository.upsert_players(items)
            canonical_written = CanonicalRepository.normalize_players_from_raw()
            ProviderSyncRepository.finish(sync_id, status="succeeded", records_written=raw_written)
            AuditRepository.log(
                user_id,
                "balldontlie_sync_players",
                "provider_sync_runs",
                str(sync_id),
                f"search={search};raw={raw_written};canonical={canonical_written}",
            )
            return BallDontLieSyncResult(
                resource="players",
                raw_records_written=raw_written,
                canonical_records_written=canonical_written,
                source_count=len(items),
            )
        except Exception as exc:
            ProviderSyncRepository.finish(sync_id, status="failed", error_text=str(exc))
            raise

    @staticmethod
    async def sync_games(date_str: str, user_id: int | None = None) -> BallDontLieSyncResult:
        BallDontLieService.ensure_configured()
        sync_id = ProviderSyncRepository.start(provider=BallDontLieService.PROVIDER, resource=f"games:{date_str}")
        try:
            payload = await BallDontLieService.client().get_games_by_date(date_str=date_str)
            items = payload.get("data", [])
            raw_written = RawBallDontLieRepository.upsert_games(items)
            canonical_written = CanonicalRepository.normalize_games_from_raw()
            ProviderSyncRepository.finish(sync_id, status="succeeded", records_written=raw_written)
            AuditRepository.log(
                user_id,
                "balldontlie_sync_games",
                "provider_sync_runs",
                str(sync_id),
                f"date={date_str};raw={raw_written};canonical={canonical_written}",
            )
            return BallDontLieSyncResult(
                resource="games",
                raw_records_written=raw_written,
                canonical_records_written=canonical_written,
                source_count=len(items),
            )
        except Exception as exc:
            ProviderSyncRepository.finish(sync_id, status="failed", error_text=str(exc))
            raise
