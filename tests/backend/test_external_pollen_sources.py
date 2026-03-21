import unittest
from datetime import date
from unittest.mock import patch

from tests.backend import _bootstrap  # noqa: F401

from app.services import external_pollen_sources as eps


class _FakeResponse:
    def __init__(self, *, text=None, json_data=None):
        self.text = text
        self._json_data = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, _url):
        if not self._responses:
            raise AssertionError("Нет подготовленного ответа")
        return self._responses.pop(0)


class ExternalPollenSourceTests(unittest.IsolatedAsyncioTestCase):
    def test_small_helpers_cover_edge_cases(self):
        self.assertEqual(eps._clean_text("\ufeff test\r "), "test")
        self.assertEqual(eps._parse_fi_date("21.03.2026"), date(2026, 3, 21))
        self.assertEqual(eps._parse_dwd_last_update("Last update: 2026-03-21 11:00"), date(2026, 3, 21))
        self.assertEqual(eps._index_0_3_from_range(None), None)
        self.assertEqual(eps._index_0_3_from_range(""), None)
        self.assertEqual(eps._index_0_3_from_range("1-3"), 2.0)
        self.assertEqual(eps._index_0_3_from_range(2), 2.0)

        with self.assertRaises(ValueError):
            eps._parse_dwd_last_update("bad")

    async def test_fetch_norkko_records_handles_current_forecast_and_out_of_range(self):
        bulletin = "\n".join(
            [
                "TILANNE",
                "21.03.2026",
                "Turku LL K",
                "ENNUSTE",
                "22.03.2026 - 24.03.2026",
                "Turku HHH",
                "Tunnukset:",
            ]
        )
        with patch("app.services.external_pollen_sources.httpx.AsyncClient", return_value=_FakeAsyncClient([_FakeResponse(text=bulletin)])):
            current_day, current_records, current_note = await eps.fetch_norkko_records()
        self.assertEqual(current_day, date(2026, 3, 21))
        self.assertEqual(current_note, "Norkko mode=current")
        self.assertTrue(any(item["taxon_key"] == "alder" for item in current_records))
        self.assertTrue(any(item["taxon_key"] == "birch" for item in current_records))

        with patch("app.services.external_pollen_sources.httpx.AsyncClient", return_value=_FakeAsyncClient([_FakeResponse(text=bulletin)])):
            _, forecast_records, forecast_note = await eps.fetch_norkko_records(date(2026, 3, 22))
        self.assertEqual(forecast_note, "Norkko mode=forecast")
        self.assertEqual(len(forecast_records), 1)
        self.assertEqual(forecast_records[0]["taxon_key"], "grass")

        with patch("app.services.external_pollen_sources.httpx.AsyncClient", return_value=_FakeAsyncClient([_FakeResponse(text=bulletin)])):
            _, no_records, no_note = await eps.fetch_norkko_records(date(2026, 3, 30))
        self.assertEqual(no_records, [])
        self.assertIn("нет бюллетеня", no_note)

    async def test_fetch_norkko_records_rejects_unexpected_structure(self):
        with patch("app.services.external_pollen_sources.httpx.AsyncClient", return_value=_FakeAsyncClient([_FakeResponse(text="bad")])):
            with self.assertRaises(ValueError):
                await eps.fetch_norkko_records()

    async def test_fetch_meteoswiss_records_reads_selected_day_and_empty_cases(self):
        stations_csv = (
            "station_abbr;station_name;station_coordinates_wgs84_lat;station_coordinates_wgs84_lon\n"
            "AAA;Alpha;46.1;7.2\n"
            "BBB;Beta;47.2;8.3\n"
        )
        alpha_csv = (
            "reference_timestamp;kaalnud1;kabetud1\n"
            "20.03.2026 00:00;1;2\n"
            "21.03.2026 00:00;3;4\n"
        )
        beta_csv = (
            "reference_timestamp;kaalnud1;kabetud1\n"
            "21.03.2026 00:00;5;6\n"
        )

        with patch(
            "app.services.external_pollen_sources.httpx.AsyncClient",
            return_value=_FakeAsyncClient(
                [
                    _FakeResponse(text=stations_csv),
                    _FakeResponse(text=alpha_csv),
                    _FakeResponse(text=beta_csv),
                ]
            ),
        ):
            imported_day, records, note = await eps.fetch_meteoswiss_records(date(2026, 3, 21))

        self.assertEqual(imported_day, date(2026, 3, 21))
        self.assertEqual(note, "MeteoSwiss daily station import")
        self.assertTrue(any(item["location_name"] == "Alpha, Switzerland" for item in records))
        self.assertTrue(any(item["value"] == 6.0 for item in records))

        with patch(
            "app.services.external_pollen_sources.httpx.AsyncClient",
            return_value=_FakeAsyncClient([_FakeResponse(text=stations_csv), _FakeResponse(text=""), _FakeResponse(text="")]),
        ):
            imported_day, records, _ = await eps.fetch_meteoswiss_records()
        self.assertEqual(imported_day, None)
        self.assertEqual(records, [])

    async def test_fetch_dwd_records_covers_day_selection_and_empty_case(self):
        payload = {
            "last_update": "2026-03-21T11:00",
            "content": [
                {
                    "region_id": 10,
                    "partregion_id": 11,
                    "region_name": "Nord",
                    "partregion_name": "Kuste",
                    "Pollen": {
                        "Erle": {"today": "1-2", "tomorrow": "2", "dayafter_to": "3"},
                        "Birke": {"today": "", "tomorrow": None, "dayafter_to": "0-1"},
                    },
                },
                {
                    "region_id": 999,
                    "partregion_id": 999,
                    "region_name": "Unknown",
                    "partregion_name": "",
                    "Pollen": {},
                },
            ],
        }

        with patch("app.services.external_pollen_sources.httpx.AsyncClient", return_value=_FakeAsyncClient([_FakeResponse(json_data=payload)])):
            base_day, records, note = await eps.fetch_dwd_records(date(2026, 3, 22))
        self.assertEqual(base_day, date(2026, 3, 21))
        self.assertEqual(note, "DWD tomorrow")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["taxon_key"], "alder")

        with patch("app.services.external_pollen_sources.httpx.AsyncClient", return_value=_FakeAsyncClient([_FakeResponse(json_data=payload)])):
            _, no_records, no_note = await eps.fetch_dwd_records(date(2026, 3, 30))
        self.assertEqual(no_records, [])
        self.assertIn("today/tomorrow/dayafter_to", no_note)
