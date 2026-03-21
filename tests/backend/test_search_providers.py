import asyncio
import unittest
from unittest.mock import patch
from tests.backend import _bootstrap  # noqa: F401

import httpx

from app.search.providers import crossref, cyberleninka, openalex, pubmed


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.request = httpx.Request("GET", "https://example.test")

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        self.calls.append(("GET", url, params))
        return self.responses.pop(0)

    async def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        return self.responses.pop(0)


class SearchProviderTests(unittest.TestCase):
    def test_openalex_year_filter_and_author_join(self):
        fake_client = FakeAsyncClient(
            [
                FakeResponse(
                    {
                        "results": [
                            {
                                "title": "Birch pollen paper",
                                "publication_year": 2024,
                                "publication_date": "2024-05-01",
                                "language": "en",
                                "id": "https://openalex.org/W1",
                                "primary_location": {"landing_page_url": "https://paper.example"},
                                "authorships": [
                                    {"author": {"display_name": "Alice"}},
                                    {"author": {"display_name": "Bob"}},
                                ],
                            },
                            {
                                "title": "Old paper",
                                "publication_year": 2020,
                                "id": "https://openalex.org/W2",
                                "authorships": [],
                            },
                        ]
                    }
                )
            ]
        )

        with patch.object(openalex.httpx, "AsyncClient", return_value=fake_client), \
             patch.object(openalex.os, "getenv", return_value="token"):
            payload = asyncio.run(openalex.search_openalex("birch", year_from=2023))

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["authors"], "Alice, Bob")
        self.assertEqual(fake_client.calls[0][2]["api_key"], "token")
        self.assertTrue(openalex._within_year_range(2024, 2023, 2025))
        self.assertFalse(openalex._within_year_range(2022, 2023, 2025))

    def test_crossref_helpers_and_search(self):
        item = {
            "title": ["<b>Birch</b> pollen"],
            "resource": {"primary": {"URL": "https://paper.example/1"}},
            "author": [{"given": "Ivan", "family": "Petrov"}],
            "abstract": "<jats:p>Useful abstract</jats:p>",
            "language": "ru",
            "published-online": {"date-parts": [[2024, 6, 5]]},
        }
        duplicate = {
            "title": ["Duplicate"],
            "URL": "https://paper.example/1",
            "issued": {"date-parts": [[2024]]},
        }
        fake_client = FakeAsyncClient([FakeResponse({"message": {"items": [item, duplicate]}})])

        with patch.object(crossref.httpx, "AsyncClient", return_value=fake_client):
            payload = asyncio.run(crossref.search_crossref("birch", year_from=2024, year_to=2024))

        self.assertEqual(crossref._clean_text("<i>Hello</i>"), "Hello")
        self.assertEqual(crossref._format_date_parts((2024, 6, 5)), "2024-06-05")
        self.assertEqual(crossref._format_date_parts((2024, 6, None)), "2024-06")
        self.assertEqual(crossref._format_date_parts((2024, None, None)), "2024")
        self.assertEqual(crossref._extract_date_parts(item), (2024, 6, 5))
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["title"], "Birch pollen")
        self.assertEqual(payload[0]["authors"], "Ivan Petrov")
        self.assertEqual(payload[0]["published_at"], "2024-06-05")

    def test_cyberleninka_search_cleans_and_filters(self):
        fake_client = FakeAsyncClient(
            [
                FakeResponse(
                    {
                        "articles": [
                            {
                                "link": "/article/n/1",
                                "name": "<b>Береза</b>",
                                "authors": ["Иванов И.И."],
                                "year": 2024,
                                "annotation": "<p>Аннотация</p>",
                            },
                            {
                                "link": "/article/n/1",
                                "name": "duplicate",
                                "year": 2024,
                            },
                            {
                                "link": "/article/n/2",
                                "name": "old",
                                "year": 2020,
                            },
                        ]
                    }
                )
            ]
        )

        with patch.object(cyberleninka.httpx, "AsyncClient", return_value=fake_client):
            payload = asyncio.run(cyberleninka.search_cyberleninka("береза", year_from=2023))

        self.assertEqual(cyberleninka._clean_text("<p>Текст</p>"), "Текст")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["url"], "https://cyberleninka.ru/article/n/1")
        self.assertEqual(payload[0]["authors"], "Иванов И.И.")

    def test_pubmed_helpers_and_search(self):
        esearch = {"esearchresult": {"idlist": ["1", "2"]}}
        esummary = {
            "result": {
                "1": {
                    "title": "Grass allergy",
                    "sortpubdate": "2024/05/12 00:00",
                    "authors": [{"name": "Alice"}],
                },
                "2": {
                    "title": "Old study",
                    "pubdate": "2020 Sep",
                    "authors": [{"name": "Bob"}],
                },
            }
        }
        fake_client = FakeAsyncClient([FakeResponse(esearch), FakeResponse(esummary)])

        with patch.object(pubmed.httpx, "AsyncClient", return_value=fake_client):
            payload = asyncio.run(pubmed.search_pubmed("grass", year_from=2023))

        self.assertEqual(pubmed._format_date(2024, 5, 12), "2024-05-12")
        self.assertEqual(pubmed._extract_publication_date({"sortpubdate": "2024/05/12 00:00"}), (2024, "2024-05-12"))
        self.assertEqual(pubmed._extract_publication_date({"pubdate": "2020 Sep"}), (2020, "2020-09"))
        self.assertEqual(pubmed._extract_publication_date({"pubdate": "2020"}), (2020, "2020"))
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["url"], "https://pubmed.ncbi.nlm.nih.gov/1/")
        self.assertEqual(payload[0]["authors"], "Alice")
