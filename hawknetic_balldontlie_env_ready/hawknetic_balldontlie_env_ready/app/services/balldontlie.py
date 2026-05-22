from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.repositories import AuditRepository, BdlRepository, MappingRepository


@dataclass(frozen=True)
class BallDontLieSyncResult:
    resource: str
    raw_records_written: int
    canonical_records_written: int
    source_count: int


class BallDontLieProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        return {"Authorization": self.api_key, "Accept": "application/json"}

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict:
        if not self.configured:
            raise BallDontLieProviderError("BALLDONTLIE_API_KEY is not configured.", status_code=503)

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise BallDontLieProviderError("BALLDONTLIE request timed out.", status_code=504) from exc
        except httpx.HTTPStatusError as exc:
            detail = BallDontLieClient._provider_error_detail(exc.response)
            raise BallDontLieProviderError(
                f"BALLDONTLIE returned HTTP {exc.response.status_code}: {detail}",
                status_code=502,
            ) from exc
        except httpx.RequestError as exc:
            raise BallDontLieProviderError(f"BALLDONTLIE request failed: {exc}", status_code=502) from exc
        except ValueError as exc:
            raise BallDontLieProviderError("BALLDONTLIE returned a non-JSON response.", status_code=502) from exc

        if not isinstance(payload, dict):
            raise BallDontLieProviderError("BALLDONTLIE returned an unexpected response shape.", status_code=502)
        return payload

    @staticmethod
    def _provider_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:300] or response.reason_phrase
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                value = payload.get(key)
                if value:
                    return str(value)
        return str(payload)[:300]

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
            raise BallDontLieProviderError("BALLDONTLIE_API_KEY is not configured.", status_code=503)

    @staticmethod
    async def sync_teams(user_id: int | None = None) -> BallDontLieSyncResult:
        BallDontLieService.ensure_configured()
        sync_id = BdlRepository.start_log(resource="teams")
        try:
            payload = await BallDontLieService.client().get_teams()
            items = payload.get("data", [])
            raw_written = BdlRepository.upsert_teams(items)
            canonical_written = MappingRepository.auto_map_teams()
            BdlRepository.finish_log(sync_id, status="succeeded", records_read=len(items), records_written=raw_written)
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
            BdlRepository.finish_log(sync_id, status="failed", error_text=str(exc))
            raise

    @staticmethod
    async def sync_players(search: str, user_id: int | None = None) -> BallDontLieSyncResult:
        BallDontLieService.ensure_configured()
        sync_id = BdlRepository.start_log(resource=f"players:{search}", request={"search": search})
        try:
            payload = await BallDontLieService.client().search_players(search=search)
            items = payload.get("data", [])
            raw_written = BdlRepository.upsert_players(items)
            canonical_written = MappingRepository.auto_map_players()
            BdlRepository.finish_log(sync_id, status="succeeded", records_read=len(items), records_written=raw_written)
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
            BdlRepository.finish_log(sync_id, status="failed", error_text=str(exc))
            raise

    @staticmethod
    async def sync_games(date_str: str, user_id: int | None = None) -> BallDontLieSyncResult:
        BallDontLieService.ensure_configured()
        sync_id = BdlRepository.start_log(resource=f"games:{date_str}", request={"date": date_str})
        try:
            payload = await BallDontLieService.client().get_games_by_date(date_str=date_str)
            items = payload.get("data", [])
            raw_written = BdlRepository.upsert_games(items)
            canonical_written = MappingRepository.auto_map_games()
            BdlRepository.finish_log(sync_id, status="succeeded", records_read=len(items), records_written=raw_written)
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
            BdlRepository.finish_log(sync_id, status="failed", error_text=str(exc))
            raise

    @staticmethod
    async def sync_stats(user_id: int | None = None) -> BallDontLieSyncResult:
        sync_id = BdlRepository.start_log(resource="stats")
        message = "Ball Don't Lie stats ingestion endpoint is not configured in this build."
        BdlRepository.finish_log(sync_id, status="failed", error_text=message)
        raise BallDontLieProviderError(message, status_code=501)

    @staticmethod
    async def sync_live(user_id: int | None = None) -> BallDontLieSyncResult:
        """Pull today's NBA games from BALLDONTLIE → write into live_games for readiness."""
        from datetime import datetime, timezone
        from app.services.live_sync import ingest_snapshot

        BallDontLieService.ensure_configured()
        today = datetime.now(timezone.utc).date().isoformat()
        sync_id = BdlRepository.start_log(resource=f"live:{today}", request={"date": today})
        try:
            payload = await BallDontLieService.client().get_games_by_date(date_str=today)
            items = payload.get("data", [])
            raw_written = BdlRepository.upsert_games(items)
            MappingRepository.auto_map_games()

            game_rows_written = 0
            for game in items:
                row = {
                    "game_id": int(game.get("id")),
                    "status": (game.get("status") or "scheduled").lower(),
                    "period": game.get("period"),
                    "clock": game.get("time"),
                    "home_score": game.get("home_team_score"),
                    "away_score": game.get("visitor_team_score"),
                    "home_team_id": (game.get("home_team") or {}).get("id"),
                    "away_team_id": (game.get("visitor_team") or {}).get("id"),
                    "tipoff_at": game.get("datetime") or game.get("date"),
                    "source": "balldontlie",
                }
                result = ingest_snapshot({
                    "kind": "game_state",
                    "payload": {"rows": [row]},
                })
                game_rows_written += int(result.get("rows_written") or 0)

            BdlRepository.finish_log(sync_id, status="succeeded", records_read=len(items), records_written=game_rows_written)
            AuditRepository.log(
                user_id,
                "balldontlie_sync_live",
                "provider_sync_runs",
                str(sync_id),
                f"date={today};live_games={game_rows_written};raw={raw_written}",
            )
            return BallDontLieSyncResult(
                resource="live",
                raw_records_written=raw_written,
                canonical_records_written=game_rows_written,
                source_count=len(items),
            )
        except Exception as exc:
            BdlRepository.finish_log(sync_id, status="failed", error_text=str(exc))
            raise
