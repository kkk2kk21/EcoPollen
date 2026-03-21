import unittest
from datetime import date
from unittest.mock import AsyncMock, sentinel, patch

from fastapi import HTTPException
from tests.backend import _bootstrap  # noqa: F401

from app.api.routes.jobs import (
    backfill_week,
    import_dwd,
    import_meteoswiss,
    import_norkko,
    import_open_meteo,
)


class JobsRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_routes_pass_day_to_services(self):
        day = date(2026, 3, 20)

        with patch("app.api.routes.jobs.import_open_meteo_snapshot", new=AsyncMock(return_value={"status": "ok"})) as mocked:
            payload = await import_open_meteo(day=day, db=sentinel.db, _=None)
        self.assertEqual(payload["status"], "ok")
        mocked.assert_awaited_once_with(sentinel.db, day)

        with patch("app.api.routes.jobs.import_norkko_snapshot", new=AsyncMock(return_value={"status": "ok"})) as mocked:
            await import_norkko(day=day, db=sentinel.db, _=None)
        mocked.assert_awaited_once_with(sentinel.db, day)

        with patch("app.api.routes.jobs.import_meteoswiss_snapshot", new=AsyncMock(return_value={"status": "ok"})) as mocked:
            await import_meteoswiss(day=day, db=sentinel.db, _=None)
        mocked.assert_awaited_once_with(sentinel.db, day)

        with patch("app.api.routes.jobs.import_dwd_snapshot", new=AsyncMock(return_value={"status": "ok"})) as mocked:
            await import_dwd(day=day, db=sentinel.db, _=None)
        mocked.assert_awaited_once_with(sentinel.db, day)

        with patch("app.api.routes.jobs.backfill_available_history", new=AsyncMock(return_value={"status": "ok"})) as mocked:
            await backfill_week(days=5, db=sentinel.db, _=None)
        mocked.assert_awaited_once_with(sentinel.db, days=5)

    async def test_import_routes_wrap_service_errors(self):
        cases = [
            (import_norkko, "app.api.routes.jobs.import_norkko_snapshot", "Norkko ошибка"),
            (import_meteoswiss, "app.api.routes.jobs.import_meteoswiss_snapshot", "MeteoSwiss ошибка"),
            (import_dwd, "app.api.routes.jobs.import_dwd_snapshot", "DWD ошибка"),
            (backfill_week, "app.api.routes.jobs.backfill_available_history", "Backfill ошибка"),
        ]

        for fn, target, message in cases:
            with self.subTest(target=target):
                with patch(target, new=AsyncMock(side_effect=RuntimeError("boom"))):
                    with self.assertRaises(HTTPException) as error:
                        if fn is backfill_week:
                            await fn(days=7, db=sentinel.db, _=None)
                        else:
                            await fn(day=None, db=sentinel.db, _=None)
                self.assertEqual(error.exception.status_code, 502)
                self.assertIn(message, error.exception.detail)
