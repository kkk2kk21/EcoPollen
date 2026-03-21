import unittest
from tests.backend import _bootstrap  # noqa: F401

from app.domain.danger_levels import (
    clamp_0_3,
    concentration_thresholds_for_taxon,
    describe_index_0_3,
    describe_concentration_level,
    describe_measurement,
    grains_m3_to_danger_level,
    measurement_label_rank,
    overall_label,
    recommendations,
    to_danger_level,
)


class DangerLevelTests(unittest.TestCase):
    def test_index_labels_cover_all_intervals(self):
        self.assertEqual(describe_index_0_3(0), "Опасности нет")
        self.assertEqual(describe_index_0_3(0.5), "Очень низкий")
        self.assertEqual(describe_index_0_3(1), "Низкий")
        self.assertEqual(describe_index_0_3(1.5), "Ощутимый")
        self.assertEqual(describe_index_0_3(2), "Умеренный")
        self.assertEqual(describe_index_0_3(2.5), "Значительный")
        self.assertEqual(describe_index_0_3(3), "Высокий")

    def test_grains_to_danger_level_uses_taxon_thresholds(self):
        self.assertEqual(grains_m3_to_danger_level(0, taxon_key="mugwort"), 0)
        self.assertEqual(grains_m3_to_danger_level(5, taxon_key="mugwort"), 1)
        self.assertEqual(grains_m3_to_danger_level(10, taxon_key="mugwort"), 2)
        self.assertEqual(grains_m3_to_danger_level(30, taxon_key="mugwort"), 3)

    def test_measurement_helpers_stay_consistent(self):
        label = describe_measurement(2, "index_0_3")
        self.assertEqual(label, "Умеренный")
        self.assertLess(measurement_label_rank("Низкий"), measurement_label_rank("Высокий"))

    def test_threshold_and_clamp_helpers_cover_fallbacks(self):
        self.assertEqual(concentration_thresholds_for_taxon(None), concentration_thresholds_for_taxon("missing"))
        self.assertEqual(clamp_0_3(None), 0)
        self.assertEqual(clamp_0_3(-1), 0)
        self.assertEqual(clamp_0_3(1.6), 2)
        self.assertEqual(clamp_0_3(10), 3)

    def test_to_danger_level_and_descriptions_cover_all_units(self):
        self.assertEqual(to_danger_level(None, "index_0_3"), 0)
        self.assertEqual(to_danger_level(2.2, "danger_0_3"), 2)
        self.assertEqual(to_danger_level(15, "grains/m3", taxon_key="alder"), grains_m3_to_danger_level(15, "alder"))
        self.assertEqual(to_danger_level(10, "unknown"), 0)

        self.assertIsNone(describe_measurement(10, "unknown"))
        self.assertEqual(describe_measurement(15, "grains/m3", taxon_key="alder"), describe_concentration_level(15, "alder"))
        self.assertIsNone(describe_concentration_level(None))
        self.assertEqual(describe_concentration_level(0), "Опасности нет")
        self.assertEqual(describe_concentration_level(1, taxon_key="alder"), "Низкий")
        self.assertEqual(describe_concentration_level(1000, taxon_key="alder"), "Высокий")

    def test_label_and_recommendation_helpers_cover_all_branches(self):
        self.assertEqual(measurement_label_rank(None), -1)
        self.assertEqual(measurement_label_rank("missing"), -1)
        self.assertEqual(overall_label(0)["label"], "Минимальный")
        self.assertEqual(overall_label(99)["label"], "Минимальный")

        self.assertEqual(len(recommendations(0)), 2)
        self.assertEqual(len(recommendations(1)), 2)
        self.assertEqual(len(recommendations(2)), 3)
        self.assertEqual(len(recommendations(3)), 3)
