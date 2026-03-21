import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.backend import _bootstrap  # noqa: F401

from app.services import open_meteo_places_catalog as catalog


class OpenMeteoPlacesCatalogTests(unittest.TestCase):
    def tearDown(self):
        catalog.load_open_meteo_region_city_catalog.cache_clear()

    def test_clean_and_unique_normalize_values(self):
        self.assertEqual(catalog._clean("  Foo \u200e  , "), "Foo")
        self.assertEqual(catalog._unique([" Foo ", "foo", "", "Bar"]), ["Foo", "Bar"])

    def test_load_admin1_catalog_skips_invalid_rows(self):
        payload = "RU.01\tPerm Krai\tPerm Krai\t123\nbroken\n"

        with patch.object(catalog, "_fetch_text", return_value=payload):
            admin1_map, admin1_ids = catalog._load_admin1_catalog()

        self.assertEqual(admin1_map["RU.01"]["name"], "Perm Krai")
        self.assertIn("123", admin1_ids)

    def test_build_catalog_creates_labels_aliases_and_search_text(self):
        cities = [
            ["100", "Perm", "Perm", "Perm,Пермь", "58.0", "56.2", "P", "PPLA", "RU", "", "01", "", "", "", "1000000"],
            ["101", "Perm", "Perm", "", "59.0", "57.2", "P", "PPLA", "RU", "", "02", "", "", "", "900000"],
            ["102", "Skip", "Skip", "", "10.0", "10.0", "P", "PPL", "RU", "", "01", "", "", "", "100"],
        ]
        alternate_names = [
            ["1", "100", "ru", "Пермь", "1"],
            ["2", "101", "ru", "Пермь", "1"],
            ["3", "201", "ru", "Пермский край", "1"],
            ["4", "202", "ru", "Другой край", "1"],
        ]
        admin1_text = "\n".join(
            [
                "RU.01\tPerm Krai\tPerm Krai\t201",
                "RU.02\tOther Region\tOther Region\t202",
            ]
        )

        with patch.object(catalog, "_fetch_text", return_value=admin1_text), \
             patch.object(catalog, "_iter_cities500_rows", return_value=iter(cities)), \
             patch.object(catalog, "_iter_alternate_name_rows", return_value=iter(alternate_names)), \
             patch.object(catalog, "is_open_meteo_region_point", side_effect=lambda lat, lon: lat > 50):
            payload = catalog.build_open_meteo_region_city_catalog()

        self.assertEqual(len(payload), 2)
        first_perm = next(item for item in payload if item["admin1_name"] == "Пермский край")
        second_perm = next(item for item in payload if item["admin1_name"] == "Другой край")
        self.assertEqual(first_perm["name"], "Пермь")
        self.assertIn("Россия", first_perm["label"])
        self.assertIn("Пермский край", first_perm["search_text"])
        self.assertIn("Другой край", second_perm["label"])

    def test_save_and_load_catalog_roundtrip(self):
        rows = [{"id": "catalog:city:1", "name": "Пермь"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "catalog.json"

            with patch.object(catalog, "build_open_meteo_region_city_catalog", return_value=rows):
                saved = catalog.save_open_meteo_region_city_catalog(path)

            self.assertEqual(saved, rows)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), rows)

            with patch.object(catalog, "OPEN_METEO_REGION_CITY_CATALOG_PATH", path):
                loaded = catalog.load_open_meteo_region_city_catalog()

            self.assertEqual(loaded, rows)

    def test_load_catalog_returns_empty_for_missing_or_invalid_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.json"
            bad = Path(tmpdir) / "bad.json"
            bad.write_text(json.dumps({"not": "a-list"}), encoding="utf-8")

            with patch.object(catalog, "OPEN_METEO_REGION_CITY_CATALOG_PATH", missing):
                self.assertEqual(catalog.load_open_meteo_region_city_catalog(), [])

            catalog.load_open_meteo_region_city_catalog.cache_clear()

            with patch.object(catalog, "OPEN_METEO_REGION_CITY_CATALOG_PATH", bad):
                self.assertEqual(catalog.load_open_meteo_region_city_catalog(), [])
