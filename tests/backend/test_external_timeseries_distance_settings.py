import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.services.external_timeseries_distance_settings import (
    ensure_external_timeseries_distance_settings,
    get_external_timeseries_distance_map,
    list_external_timeseries_distance_settings,
)


class ExternalTimeseriesDistanceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_ensure_creates_all_default_rows(self):
        ensure_external_timeseries_distance_settings(self.db)

        items = list_external_timeseries_distance_settings(self.db)

        self.assertEqual(
            [item["location_kind"] for item in items],
            ["trap", "open_meteo_grid", "station", "region"],
        )
        self.assertEqual(items[0]["label"], "Ловушки ПГНИУ")
        self.assertEqual(items[2]["label"], "Станции Norkko и MeteoSwiss")

    def test_distance_map_returns_expected_metric_defaults(self):
        ensure_external_timeseries_distance_settings(self.db)

        distance_map = get_external_timeseries_distance_map(self.db)

        self.assertEqual(distance_map["trap"], 44400.0)
        self.assertEqual(distance_map["open_meteo_grid"], 133200.0)
        self.assertEqual(distance_map["station"], 166500.0)
        self.assertEqual(distance_map["region"], 388500.0)
