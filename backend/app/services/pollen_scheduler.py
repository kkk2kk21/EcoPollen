from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from ..core.db import SessionLocal
from .pollen_import_service import import_all_external_sources

logger = logging.getLogger(__name__)

_IMPORT_LOCK = asyncio.Lock()


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def pollen_imports_enabled() -> bool:
    return _env_flag("POLLEN_IMPORTS_ENABLED", True)


def pollen_import_on_startup() -> bool:
    return _env_flag("POLLEN_IMPORT_ON_STARTUP", True)


def scheduled_time_utc() -> tuple[int, int]:
    hour = int(os.getenv("POLLEN_IMPORT_HOUR_UTC", "8"))
    minute = int(os.getenv("POLLEN_IMPORT_MINUTE_UTC", "0"))
    return max(0, min(hour, 23)), max(0, min(minute, 59))


async def run_import_cycle(reason: str) -> list[dict]:
    async with _IMPORT_LOCK:
        with SessionLocal() as db:
            results = await import_all_external_sources(db)
        logger.warning(
            "Pollen import cycle finished",
            extra={"reason": reason, "results": results},
        )
        return results


async def _run_import_cycle_safe(reason: str, error_message: str) -> None:
    try:
        await run_import_cycle(reason)
    except Exception:
        logger.exception(error_message)


def _seconds_until_next_run(hour: int, minute: int) -> float:
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return max((next_run - now).total_seconds(), 1.0)


async def pollen_scheduler_loop() -> None:
    hour, minute = scheduled_time_utc()
    while True:
        await asyncio.sleep(_seconds_until_next_run(hour, minute))
        try:
            await run_import_cycle("scheduled")
        except Exception:
            logger.exception("Scheduled pollen import failed")


async def start_pollen_scheduler() -> list[asyncio.Task]:
    if not pollen_imports_enabled():
        return []

    tasks = []
    if pollen_import_on_startup():
        tasks.append(
            asyncio.create_task(
                _run_import_cycle_safe("startup", "Startup pollen import failed"),
                name="pollen-startup-import",
            )
        )

    tasks.append(asyncio.create_task(pollen_scheduler_loop(), name="pollen-daily-import"))
    return tasks


async def stop_pollen_scheduler(tasks: list[asyncio.Task] | None) -> None:
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
