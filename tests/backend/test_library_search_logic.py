import asyncio
import unittest
from tests.backend import _bootstrap  # noqa: F401

from app.api.routes.library import (
    _filter_results,
    _prepare_source_terms,
    _score_relevance,
    _sort_results,
)
from app.search.semantic import expand_query


class LibrarySearchLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.query = "аллергия на березу"
        cls.semantic = asyncio.run(expand_query(cls.query))

    def test_pubmed_uses_only_english_variant(self):
        terms = _prepare_source_terms(
            source_key="pubmed",
            query=self.query,
            search_terms=self.semantic["search_terms"],
            expanded_terms=self.semantic["expanded_terms"],
        )

        self.assertEqual(len(terms), 1)
        self.assertNotIn("аллергия", terms[0].lower())
        self.assertIn("birch", terms[0].lower())

    def test_crossref_uses_cyrillic_and_english_variants(self):
        terms = _prepare_source_terms(
            source_key="crossref",
            query=self.query,
            search_terms=self.semantic["search_terms"],
            expanded_terms=self.semantic["expanded_terms"],
        )

        self.assertGreaterEqual(len(terms), 2)
        self.assertEqual(terms[0], self.query)
        self.assertIn("birch", terms[1].lower())

    def test_relevance_prefers_specific_article_over_generic_match(self):
        specific_item = {
            "title": "Birch pollen allergy and allergic rhinitis",
            "snippet": "Betula sensitization and spring symptoms in adults",
            "authors": "Ivanov",
            "year": 2025,
            "published_at": "2025-03-01",
            "source": "crossref",
            "language": "en",
        }
        generic_item = {
            "title": "Pollen allergy in adults",
            "snippet": "General allergic disease and seasonal symptoms overview",
            "authors": "Petrov",
            "year": 2025,
            "published_at": "2025-03-01",
            "source": "crossref",
            "language": "en",
        }

        specific_score = _score_relevance(
            specific_item,
            self.query,
            self.semantic["expanded_terms"],
            self.semantic["expanded_term_meta"],
        )
        generic_score = _score_relevance(
            generic_item,
            self.query,
            self.semantic["expanded_terms"],
            self.semantic["expanded_term_meta"],
        )

        self.assertGreater(specific_score, generic_score)

        sorted_titles = [
            item["title"]
            for item in _sort_results(
                [generic_item, specific_item],
                "relevance",
                base_query=self.query,
                expanded_terms=self.semantic["expanded_terms"],
                expanded_term_meta=self.semantic["expanded_term_meta"],
            )
        ]
        self.assertEqual(
            sorted_titles,
            [
                "Birch pollen allergy and allergic rhinitis",
                "Pollen allergy in adults",
            ],
        )

    def test_filter_results_applies_source_author_language_and_date(self):
        results = [
            {
                "source": "crossref",
                "title": "Birch pollen allergy and allergic rhinitis",
                "snippet": "Betula sensitization and spring symptoms",
                "authors": "Ivanov",
                "year": 2025,
                "published_at": "2025-03-01",
                "language": "en",
            },
            {
                "source": "pubmed",
                "title": "Mugwort asthma study",
                "snippet": None,
                "authors": "Petrov",
                "year": 2024,
                "published_at": "2024-05-11",
                "language": "en",
            },
            {
                "source": "cyberleninka",
                "title": "Обзор по аллергии",
                "snippet": "русскоязычная статья",
                "authors": "Иванов",
                "year": 2025,
                "published_at": "2025-02-10",
                "language": "ru",
            },
        ]

        filtered = _filter_results(
            results,
            selected_sources=["crossref", "cyberleninka"],
            year_from=2025,
            year_to=2025,
            date_from="2025-02-20",
            date_to="2025-12-31",
            author="Ivan",
            language="en",
            only_with_year=True,
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["source"], "crossref")
