"""Background scheduler that periodically syncs live data from providers.

Runs in-process via an asyncio task started in `app.main` startup hook.
Polls BALLDONTLIE games-by-date every `HAWKNETIC_LIVE_SYNC_INTERVAL_SECONDS`
(default 60s) and writes into `live_games` via `live_sync.ingest_snapshot`,
which keeps `/api/live/readiness` fresh and unblocks algorithm runs.

Disable by setting `HAWKNETIC_LIVE_SYNC_INTERVAL_SECONDS=0`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger("hawknetic.live_poller")

_poller_task: Optional[asyncio.Task[None]] = None


def _interval_seconds() -> int:
    raw = os.environ.get("HAWKNETIC_LIVE_SYNC_INTERVAL_SECONDS", "60")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 60


async def _one_tick() -> None:
    """Single sync attempt — never raises (errors are logged + swallowed)."""
    from app.services.balldontlie import BallDontLieService, BallDontLieProviderError
    try:
        result = await BallDontLieService.sync_live(user_id=None)
        logger.info(
            "live_poller tick: source_count=%s live_games_written=%s",
            result.source_count, result.canonical_records_written,
        )
    except BallDontLieProviderError as exc:
        logger.warning("live_poller skipped: %s", exc)
    except Exception:
        logger.exception("live_poller tick failed")


async def _poller_loop(interval: int) -> None:
    logger.info("live_poller starting (interval=%ss)", interval)
    # Initial delay so app startup completes cleanly before the first network call.
    await asyncio.sleep(min(interval, 5))
    while True:
        await _one_tick()
        await asyncio.sleep(interval)


def start_live_poller() -> None:
    """Idempotent: start the background poller if interval > 0 and not already running."""
    global _poller_task
    interval = _interval_seconds()
    if interval == 0:
        logger.info("live_poller disabled (HAWKNETIC_LIVE_SYNC_INTERVAL_SECONDS=0)")
        return
    if _poller_task and not _poller_task.done():
        return
    if not os.environ.get("BALLDONTLIE_API_KEY"):
        logger.info("live_poller skipped — BALLDONTLIE_API_KEY not set")
        return
    _poller_task = asyncio.create_task(_poller_loop(interval), name="hawknetic-live-poller")


def stop_live_poller() -> None:
    global _poller_task
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
    _poller_task = None
