import unittest
from tests.backend import _bootstrap  # noqa: F401

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.domain.models import DataSource
from app.services.map_circle_styles import (
    ensure_map_circle_styles,
    list_map_circle_styles,
)


class MapCircleStyleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all(
            [
                DataSource(key="pgniu_manual", name="Замеры ПГНИУ", source_type="manual", priority=100),
                DataSource(key="open_meteo", name="Open-Meteo", source_type="api", priority=90),
                DataSource(key="norkko", name="Norkko", source_type="api", priority=80),
                DataSource(key="meteoswiss", name="MeteoSwiss", source_type="api", priority=70),
                DataSource(key="dwd", name="DWD", source_type="api", priority=60),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_ensure_creates_styles_for_supported_sources(self):
        ensure_map_circle_styles(self.db)

        items = list_map_circle_styles(self.db)
        keys = [item["source_key"] for item in items]

        self.assertIn("pgniu_manual", keys)
        self.assertIn("norkko", keys)
        self.assertIn("meteoswiss", keys)
        self.assertIn("dwd", keys)
        self.assertIn("default", keys)

    def test_list_includes_fallback_row(self):
        ensure_map_circle_styles(self.db)

        fallback = [item for item in list_map_circle_styles(self.db) if item["source_key"] == "default"][0]

        self.assertTrue(fallback["is_fallback"])
        self.assertEqual(fallback["source_name"], "Другие источники")
