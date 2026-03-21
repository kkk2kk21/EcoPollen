import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.backend import _bootstrap  # noqa: F401

from app.services import pollen_scheduler as scheduler


class _FakeDateTime:
    @classmethod
    def now(cls, _tz):
        import datetime as _dt

        return _dt.datetime(2026, 3, 21, 7, 30, tzinfo=_tz)


class _AwaitableTask:
    def __init__(self):
        self.cancel = MagicMock()

    def __await__(self):
        async def _done():
            raise asyncio.CancelledError

        return _done().__await__()


class PollenSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def test_env_flag_and_schedule_helpers(self):
        with patch("app.services.pollen_scheduler.os.getenv", side_effect=lambda name, default=None: {"FLAG": "false"}.get(name, default)):
            self.assertFalse(scheduler._env_flag("FLAG", True))
            self.assertTrue(scheduler._env_flag("MISSING", True))

        with patch("app.services.pollen_scheduler.os.getenv", side_effect=lambda name, default=None: {"POLLEN_IMPORTS_ENABLED": "0", "POLLEN_IMPORT_ON_STARTUP": "yes"}.get(name, default)):
            self.assertFalse(scheduler.pollen_imports_enabled())
            self.assertTrue(scheduler.pollen_import_on_startup())

        with patch("app.services.pollen_scheduler.os.getenv", side_effect=lambda name, default=None: {"POLLEN_IMPORT_HOUR_UTC": "99", "POLLEN_IMPORT_MINUTE_UTC": "-5"}.get(name, default)):
            self.assertEqual(scheduler.scheduled_time_utc(), (23, 0))

    def test_seconds_until_next_run(self):
        with patch("app.services.pollen_scheduler.datetime", _FakeDateTime):
            self.assertEqual(scheduler._seconds_until_next_run(8, 0), 1800.0)
            self.assertGreater(scheduler._seconds_until_next_run(7, 0), 23 * 3600)

    async def test_run_import_cycle_and_safe_wrapper(self):
        fake_db = MagicMock()
        fake_context = MagicMock()
        fake_context.__enter__.return_value = fake_db
        fake_context.__exit__.return_value = None

        with patch("app.services.pollen_scheduler.SessionLocal", return_value=fake_context), patch(
            "app.services.pollen_scheduler.import_all_external_sources",
            new=AsyncMock(return_value=[{"status": "ok"}]),
        ) as mocked_import, patch("app.services.pollen_scheduler.logger.warning") as warning:
            result = await scheduler.run_import_cycle("manual")

        self.assertEqual(result, [{"status": "ok"}])
        mocked_import.assert_awaited_once_with(fake_db)
        warning.assert_called_once()

        with patch("app.services.pollen_scheduler.run_import_cycle", new=AsyncMock(side_effect=RuntimeError("boom"))), patch(
            "app.services.pollen_scheduler.logger.exception"
        ) as exception_logger:
            await scheduler._run_import_cycle_safe("startup", "failed")
        exception_logger.assert_called_once_with("failed")

    async def test_start_scheduler_and_stop_scheduler(self):
        fake_task = MagicMock(spec=asyncio.Task)
        fake_task.cancel = MagicMock()

        with patch("app.services.pollen_scheduler.pollen_imports_enabled", return_value=False):
            self.assertEqual(await scheduler.start_pollen_scheduler(), [])

        def fake_create_task(coro, name=None):
            coro.close()
            return fake_task

        with patch("app.services.pollen_scheduler.pollen_imports_enabled", return_value=True), patch(
            "app.services.pollen_scheduler.pollen_import_on_startup",
            return_value=False,
        ), patch("app.services.pollen_scheduler.asyncio.create_task", side_effect=fake_create_task) as create_task:
            tasks = await scheduler.start_pollen_scheduler()
        self.assertEqual(tasks, [fake_task])
        self.assertEqual(create_task.call_count, 1)

        cancelled_task = _AwaitableTask()

        await scheduler.stop_pollen_scheduler([cancelled_task])
        cancelled_task.cancel.assert_called_once()
