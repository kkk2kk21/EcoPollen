import unittest

from app.domain.danger_levels import (
    describe_index_0_3,
    describe_measurement,
    grains_m3_to_danger_level,
    measurement_label_rank,
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
