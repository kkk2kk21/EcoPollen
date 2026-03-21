import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from tests.backend import _bootstrap  # noqa: F401

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.pollen import summary
from app.core.db import Base
from app.domain.models import DataSource, Location, Observation, PollenTaxon


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_internal_summary_falls_back_to_latest_available_day(self):
        source = DataSource(
            key="pgniu_manual",
            name="Замеры ПГНИУ",
            source_type="manual",
            priority=100,
        )
        trap = Location(name="Ловушка ПГНИУ", lat=80.0, lon=80.0, kind="trap")
        taxon = PollenTaxon(key="alder", name_ru="Ольха", emoji="🌳", group="tree")
        self.db.add_all([source, trap, taxon])
        self.db.commit()

        previous_day = datetime.now(timezone.utc).date() - timedelta(days=1)
        self.db.add(
            Observation(
                source_id=source.id,
                location_id=trap.id,
                taxon_id=taxon.id,
                ts=datetime.combine(previous_day, datetime.min.time(), tzinfo=timezone.utc),
                value=11.0,
                unit="grains/m3",
            )
        )
        self.db.commit()

        payload = asyncio.run(
            summary(
                location_id=trap.id,
                external_location_id=None,
                preferred_source_key="pgniu_manual",
                lat=None,
                lon=None,
                db=self.db,
            )
        )

        self.assertEqual(payload["time"][:10], previous_day.isoformat())
        self.assertEqual(payload["taxa"][0]["source"], "pgniu_manual")
        self.assertEqual(payload["taxa"][0]["raw_value"], 11.0)
