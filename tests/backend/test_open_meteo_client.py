import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from tests.backend import _bootstrap  # noqa: F401

import httpx

from app.services import open_meteo_client as client_module


class FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = headers or {}
        self.request = httpx.Request("GET", client_module.BASE_URL)

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=self.request, response=self)


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        self.calls.append({"url": url, "params": params})
        return self.responses.pop(0)


class OpenMeteoClientTests(unittest.TestCase):
    def test_as_csv_and_bounds_helpers(self):
        self.assertEqual(client_module._as_csv([1.0, 2.5]), "1.0,2.5")
        self.assertTrue(client_module.is_cams_europe_point(50.0, 10.0))
        self.assertFalse(client_module.is_cams_europe_point(80.0, 10.0))

    def test_retry_delay_prefers_retry_after_header(self):
        response = FakeResponse(headers={"Retry-After": "5"})
        self.assertEqual(client_module._retry_delay_seconds(response, 2), 5.0)

        invalid = FakeResponse(headers={"Retry-After": "bad"})
        self.assertEqual(
            client_module._retry_delay_seconds(invalid, 2),
            float(client_module.DEFAULT_RETRY_DELAY_SECONDS * 2),
        )

    def test_fetch_current_pollen_returns_json(self):
        fake_client = FakeAsyncClient([FakeResponse(json_data={"current": {"grass_pollen": 10}})])

        with patch.object(client_module.httpx, "AsyncClient", return_value=fake_client):
            payload = asyncio.run(client_module.fetch_current_pollen(58.0, 56.2, ["grass", "invalid"]))

        self.assertEqual(payload["current"]["grass_pollen"], 10)
        self.assertEqual(fake_client.calls[0]["params"]["current"], "grass_pollen")

    def test_fetch_current_pollen_raises_unavailable_for_400(self):
        fake_client = FakeAsyncClient([FakeResponse(status_code=400, text="out of season")])

        with patch.object(client_module.httpx, "AsyncClient", return_value=fake_client):
            with self.assertRaises(client_module.PollenUnavailableError):
                asyncio.run(client_module.fetch_current_pollen(58.0, 56.2, ["grass"]))

    def test_fetch_current_pollen_retries_after_429(self):
        fake_client = FakeAsyncClient(
            [
                FakeResponse(status_code=429, headers={"Retry-After": "1"}),
                FakeResponse(json_data={"current": {"grass_pollen": 10}}),
            ]
        )

        with patch.object(client_module.httpx, "AsyncClient", return_value=fake_client), \
             patch.object(client_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            payload = asyncio.run(client_module.fetch_current_pollen(58.0, 56.2, ["grass"]))

        self.assertEqual(payload["current"]["grass_pollen"], 10)
        self.assertEqual(sleep_mock.await_count, 1)

    def test_fetch_current_pollen_multi_validates_lengths_and_supported_taxa(self):
        with self.assertRaises(ValueError):
            asyncio.run(client_module.fetch_current_pollen_multi([1.0], [1.0, 2.0], ["grass"]))

        payload = asyncio.run(client_module.fetch_current_pollen_multi([1.0], [2.0], ["invalid"]))
        self.assertEqual(payload, [])

    def test_fetch_current_pollen_multi_handles_dict_and_list_responses(self):
        fake_client = FakeAsyncClient(
            [
                FakeResponse(json_data={"current": {"grass_pollen": 1}}),
                FakeResponse(json_data=[{"current": {"grass_pollen": 2}}]),
            ]
        )

        with patch.object(client_module.httpx, "AsyncClient", return_value=fake_client), \
             patch.object(client_module, "MAX_POINTS_PER_REQUEST", 1), \
             patch.object(client_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            payload = asyncio.run(
                client_module.fetch_current_pollen_multi(
                    [1.0, 2.0],
                    [3.0, 4.0],
                    ["grass"],
                    chunk_delay_seconds=1.5,
                )
            )

        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["current"]["grass_pollen"], 1)
        self.assertEqual(payload[1]["current"]["grass_pollen"], 2)
        self.assertEqual(sleep_mock.await_count, 1)

    def test_fetch_current_pollen_multi_retries_and_raises_for_400(self):
        retry_client = FakeAsyncClient(
            [
                FakeResponse(status_code=429, headers={"Retry-After": "1"}),
                FakeResponse(json_data={"current": {"grass_pollen": 3}}),
            ]
        )
        with patch.object(client_module.httpx, "AsyncClient", return_value=retry_client), \
             patch.object(client_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            payload = asyncio.run(client_module.fetch_current_pollen_multi([1.0], [2.0], ["grass"]))

        self.assertEqual(payload[0]["current"]["grass_pollen"], 3)
        self.assertEqual(sleep_mock.await_count, 1)

        bad_client = FakeAsyncClient([FakeResponse(status_code=400, text="bad request")])
        with patch.object(client_module.httpx, "AsyncClient", return_value=bad_client):
            with self.assertRaises(client_module.PollenUnavailableError):
                asyncio.run(client_module.fetch_current_pollen_multi([1.0], [2.0], ["grass"]))
