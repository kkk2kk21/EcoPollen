import unittest
from unittest.mock import patch
from tests.backend import _bootstrap  # noqa: F401

from app.geo import open_meteo_region as region


class OpenMeteoRegionTests(unittest.TestCase):
    def test_normalize_geo_longitude_wraps_negative_values(self):
        self.assertEqual(region.normalize_geo_longitude(-10.0), 350.0)
        self.assertEqual(region.normalize_geo_longitude(25.0), 25.0)

    def test_point_in_ring_and_polygon_handle_simple_shapes(self):
        ring = [[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]
        polygon = [ring]

        self.assertTrue(region.point_in_ring(1.0, 1.0, ring))
        self.assertFalse(region.point_in_ring(3.0, 3.0, ring))
        self.assertTrue(region.point_in_polygon(1.0, 1.0, polygon))
        self.assertFalse(region.point_in_polygon(3.0, 3.0, polygon))
        self.assertFalse(region.point_in_polygon(1.0, 1.0, []))

    def test_point_in_polygon_respects_holes(self):
        outer = [[0, 0], [0, 4], [4, 4], [4, 0], [0, 0]]
        hole = [[1, 1], [1, 2], [2, 2], [2, 1], [1, 1]]

        self.assertFalse(region.point_in_polygon(1.5, 1.5, [outer, hole]))

    def test_point_in_open_meteo_region_mask_supports_polygon_and_multipolygon(self):
        polygon = {"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]}
        multi = {
            "type": "MultiPolygon",
            "coordinates": [
                [[[10, 10], [10, 12], [12, 12], [12, 10], [10, 10]]],
            ],
        }

        with patch.object(region, "load_open_meteo_region_geometry", return_value=polygon):
            self.assertTrue(region.point_in_open_meteo_region_mask(1.0, 1.0))
            self.assertFalse(region.point_in_open_meteo_region_mask(5.0, 5.0))

        with patch.object(region, "load_open_meteo_region_geometry", return_value=multi):
            self.assertTrue(region.point_in_open_meteo_region_mask(11.0, 11.0))
            self.assertFalse(region.point_in_open_meteo_region_mask(1.0, 1.0))

        with patch.object(region, "load_open_meteo_region_geometry", return_value={"type": "LineString", "coordinates": []}):
            self.assertFalse(region.point_in_open_meteo_region_mask(1.0, 1.0))

    def test_is_open_meteo_region_point_checks_bbox_and_mask(self):
        with patch.object(region, "point_in_open_meteo_region_mask", return_value=True):
            self.assertTrue(region.is_open_meteo_region_point(50.0, 30.0))
            self.assertFalse(region.is_open_meteo_region_point(10.0, 30.0))

    def test_build_grid_points_applies_optional_filter(self):
        points = region.build_grid_points(
            min_lat=0.0,
            max_lat=2.0,
            min_lon=0.0,
            max_lon=2.0,
            rows=3,
            cols=3,
            filter_fn=lambda lat, lon: lat == lon,
        )

        self.assertEqual(points, [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])

    def test_generate_open_meteo_grid_points_builds_expected_payload(self):
        points = [(float(index), float(index + 1)) for index in range(region.OPEN_METEO_GRID_TARGET)]

        with patch.object(region, "build_grid_points", return_value=points):
            payload = region.generate_open_meteo_grid_points()

        self.assertEqual(len(payload), region.OPEN_METEO_GRID_TARGET)
        self.assertEqual(payload[0]["native_key"], "open-meteo-grid-0001")
        self.assertEqual(payload[-1]["kind"], region.OPEN_METEO_GRID_KIND)

    def test_generate_open_meteo_grid_points_rejects_unexpected_size(self):
        with patch.object(region, "build_grid_points", return_value=[(1.0, 2.0)]):
            with self.assertRaises(RuntimeError):
                region.generate_open_meteo_grid_points()
