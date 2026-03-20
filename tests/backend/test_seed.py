import unittest

from app.startup.seed import _taxon_model_payload


class SeedTests(unittest.TestCase):
    def test_taxon_payload_ignores_catalog_only_fields(self):
        payload = _taxon_model_payload(
            {
                "key": "alder",
                "name_ru": "Ольха",
                "emoji": "🌳",
                "group": "tree",
                "concentration_thresholds": (1, 11, 40, 70, 250),
            }
        )

        self.assertEqual(
            payload,
            {
                "key": "alder",
                "name_ru": "Ольха",
                "emoji": "🌳",
                "group": "tree",
            },
        )

