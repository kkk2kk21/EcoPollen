import asyncio
import unittest

from app.search.semantic import expand_query


class SemanticExpansionTests(unittest.TestCase):
    def test_specific_allergen_query_expands_expected_terms(self):
        result = asyncio.run(expand_query("аллергия на березу"))

        self.assertIn("Birch", result["expanded_terms"])
        self.assertIn("Betula", result["expanded_terms"])
        self.assertIn("birch pollen", result["expanded_terms"])
        self.assertIn("birch pollen allergy", result["search_terms"])
        self.assertEqual(
            result["expanded_term_meta"]["birch"],
            {"type": "allergen", "is_generic": False},
        )

    def test_generic_population_query_does_not_expand(self):
        result = asyncio.run(expand_query("дети"))

        self.assertEqual(result["search_terms"], ["дети"])
        self.assertEqual(result["expanded_terms"], [])
        self.assertEqual(result["expanded_term_meta"], {})

    def test_allergen_and_condition_query_combines_both_domains(self):
        result = asyncio.run(expand_query("полынь астма"))

        self.assertIn("Mugwort", result["expanded_terms"])
        self.assertIn("asthma", result["expanded_terms"])
        self.assertIn("mugwort pollen asthma", result["search_terms"])
