import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from tests.backend import _bootstrap  # noqa: F401

from app.core.db import Base
from app.domain.models import DataSource, ExternalLocation, ExternalObservation, PollenTaxon
from app.services import pollen_import_service as pis
from app.startup.seed import seed_if_empty


class PollenImportServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        seed_if_empty(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_get_or_create_source_updates_existing_row(self):
        source = pis.get_or_create_source(self.db, "custom", "Old", "api", 1, "https://old")
        updated = pis.get_or_create_source(self.db, "custom", "New", "manual", 9, "https://new")

        self.assertEqual(source.id, updated.id)
        self.assertEqual(updated.name, "New")
        self.assertEqual(updated.source_type, "manual")
        self.assertEqual(updated.priority, 9)
        self.assertEqual(updated.url, "https://new")

    def test_get_or_create_external_location_reuses_native_key_and_name(self):
        source = pis.get_or_create_source(self.db, "custom", "Custom", "api", 1)

        first = pis.get_or_create_external_location(
            self.db,
            source=source,
            native_key="one",
            name="Place",
            lat=1.0,
            lon=2.0,
            kind="station",
        )
        second = pis.get_or_create_external_location(
            self.db,
            source=source,
            native_key="one",
            name="Place Updated",
            lat=3.0,
            lon=4.0,
            kind="station",
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.name, "Place Updated")

        renamed = pis.get_or_create_external_location(
            self.db,
            source=source,
            native_key="two",
            name="Place Updated",
            lat=5.0,
            lon=6.0,
            kind="station",
        )
        self.assertEqual(first.id, renamed.id)
        self.assertEqual(renamed.native_key, "two")

    def test_upsert_external_records_skips_unknown_taxa_and_updates_rows(self):
        source = pis.get_or_create_source(self.db, "custom", "Custom", "api", 1)
        records = [
            {
                "native_key": "station:1",
                "location_name": "Alpha",
                "lat": 58.0,
                "lon": 56.0,
                "kind": "station",
                "day": date(2026, 3, 20),
                "taxon_key": "alder",
                "value": 1.0,
                "unit": "index_0_3",
            },
            {
                "native_key": "station:1",
                "location_name": "Alpha",
                "lat": 58.0,
                "lon": 56.0,
                "kind": "station",
                "day": date(2026, 3, 20),
                "taxon_key": "unknown",
                "value": 1.0,
                "unit": "index_0_3",
            },
        ]

        with patch("app.services.pollen_import_service.insert", side_effect=sqlite_insert):
            saved = pis.upsert_external_records(self.db, source=source, records=records)
        self.assertEqual(saved, 1)

        updated_record = [records[0] | {"value": 3.0}]
        with patch("app.services.pollen_import_service.insert", side_effect=sqlite_insert):
            saved = pis.upsert_external_records(self.db, source=source, records=updated_record)
        self.assertEqual(saved, 1)

        stored = self.db.scalar(select(ExternalObservation))
        self.assertEqual(stored.value, 3.0)

    def test_ensure_open_meteo_grid_locations_rebuilds_set(self):
        source = pis.get_or_create_source(self.db, "open_meteo", "Open", "api", 1)
        stale = ExternalLocation(
            source_id=source.id,
            native_key="stale",
            name="Stale",
            lat=0,
            lon=0,
            kind=pis.OPEN_METEO_GRID_KIND,
        )
        keep = ExternalLocation(
            source_id=source.id,
            native_key="grid-1",
            name="Old One",
            lat=2,
            lon=2,
            kind=pis.OPEN_METEO_GRID_KIND,
        )
        self.db.add_all([stale, keep])
        self.db.commit()
        for loc in [stale, keep]:
            self.db.refresh(loc)

        alder = self.db.scalar(select(PollenTaxon).where(PollenTaxon.key == "alder"))
        self.db.add(
            ExternalObservation(
                external_location_id=stale.id,
                taxon_id=alder.id,
                ts=datetime(2026, 3, 20, tzinfo=timezone.utc),
                value=1.0,
                unit="index_0_3",
            )
        )
        self.db.commit()

        specs = [
            {"native_key": "grid-1", "name": "Grid 1", "lat": 10.0, "lon": 20.0},
            {"native_key": "grid-2", "name": "Grid 2", "lat": 11.0, "lon": 21.0},
        ]
        with patch("app.services.pollen_import_service.generate_open_meteo_grid_points", return_value=specs), patch(
            "app.services.pollen_import_service.OPEN_METEO_GRID_TARGET", 2
        ):
            ordered = pis.ensure_open_meteo_grid_locations(self.db, source)

        self.assertEqual([loc.native_key for loc in ordered], ["grid-1", "grid-2"])
        self.assertEqual(self.db.scalars(select(ExternalLocation).where(ExternalLocation.source_id == source.id)).all().__len__(), 2)

    async def test_import_open_meteo_snapshot_handles_full_day_and_partial_failure(self):
        source = pis.get_or_create_source(self.db, "open_meteo", "Open", "api", 1)
        loc1 = ExternalLocation(source_id=source.id, native_key="grid-1", name="Grid 1", lat=50.0, lon=30.0, kind=pis.OPEN_METEO_GRID_KIND)
        loc2 = ExternalLocation(source_id=source.id, native_key="grid-2", name="Grid 2", lat=10.0, lon=10.0, kind=pis.OPEN_METEO_GRID_KIND)
        self.db.add_all([loc1, loc2])
        self.db.commit()
        self.db.refresh(loc1)
        self.db.refresh(loc2)

        day = date(2026, 3, 20)

        with patch("app.services.pollen_import_service.ensure_open_meteo_grid_locations", return_value=[loc1, loc2]), patch(
            "app.services.pollen_import_service.OPEN_METEO_SUPPORTED_TAXA",
            ("alder", "birch"),
        ), patch("app.services.pollen_import_service.is_cams_europe_point", side_effect=lambda lat, lon: lat > 20), patch(
            "app.services.pollen_import_service.fetch_current_pollen_multi",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ), patch("app.services.pollen_import_service.insert", side_effect=sqlite_insert):
            result = await pis.import_open_meteo_snapshot(self.db, day)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["locations_skipped"], 0)
        self.assertIn("батче", result["note"])

    async def test_import_open_meteo_snapshot_returns_ok_when_everything_loaded(self):
        source = pis.get_or_create_source(self.db, "open_meteo", "Open", "api", 1)
        alder = self.db.scalar(select(PollenTaxon).where(PollenTaxon.key == "alder"))
        birch = self.db.scalar(select(PollenTaxon).where(PollenTaxon.key == "birch"))
        loc = ExternalLocation(source_id=source.id, native_key="grid-1", name="Grid 1", lat=50.0, lon=30.0, kind=pis.OPEN_METEO_GRID_KIND)
        self.db.add(loc)
        self.db.commit()
        self.db.refresh(loc)

        day = date(2026, 3, 20)
        ts0 = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        self.db.add_all(
            [
                ExternalObservation(external_location_id=loc.id, taxon_id=alder.id, ts=ts0, value=1, unit="grains/m3"),
                ExternalObservation(external_location_id=loc.id, taxon_id=birch.id, ts=ts0, value=2, unit="grains/m3"),
            ]
        )
        self.db.commit()

        with patch("app.services.pollen_import_service.ensure_open_meteo_grid_locations", return_value=[loc]), patch(
            "app.services.pollen_import_service.OPEN_METEO_SUPPORTED_TAXA",
            ("alder", "birch"),
        ):
            result = await pis.import_open_meteo_snapshot(self.db, day)

        self.assertEqual(result["status"], "ok")
        self.assertIn("уже полностью загружен", result["note"])

    async def test_import_source_snapshots_cover_empty_and_saved_paths(self):
        with patch("app.services.pollen_import_service.fetch_norkko_records", new=AsyncMock(return_value=(date(2026, 3, 20), [], "empty"))):
            result = await pis.import_norkko_snapshot(self.db, date(2026, 3, 20))
        self.assertEqual(result["saved"], 0)

        norkko_records = [
            {
                "native_key": "n:1",
                "location_name": "Turku",
                "lat": 1.0,
                "lon": 2.0,
                "kind": "station",
                "day": date(2026, 3, 20),
                "taxon_key": "alder",
                "value": 1.0,
                "unit": "index_0_3",
            }
        ]
        with patch("app.services.pollen_import_service.fetch_norkko_records", new=AsyncMock(return_value=(date(2026, 3, 20), norkko_records, "ok"))), patch(
            "app.services.pollen_import_service.insert", side_effect=sqlite_insert
        ):
            result = await pis.import_norkko_snapshot(self.db, date(2026, 3, 20))
        self.assertEqual(result["saved"], 1)

        with patch("app.services.pollen_import_service.fetch_meteoswiss_records", new=AsyncMock(return_value=(None, [], "empty"))):
            result = await pis.import_meteoswiss_snapshot(self.db, date(2026, 3, 20))
        self.assertEqual(result["saved"], 0)

        meteo_records = [norkko_records[0] | {"native_key": "m:1", "location_name": "Zurich", "unit": "pollen/m3"}]
        with patch("app.services.pollen_import_service.fetch_meteoswiss_records", new=AsyncMock(return_value=(date(2026, 3, 20), meteo_records, "ok"))), patch(
            "app.services.pollen_import_service.insert", side_effect=sqlite_insert
        ):
            result = await pis.import_meteoswiss_snapshot(self.db, date(2026, 3, 20))
        self.assertEqual(result["locations"], 1)

        with patch("app.services.pollen_import_service.fetch_dwd_records", new=AsyncMock(return_value=(date(2026, 3, 20), [], "empty"))):
            result = await pis.import_dwd_snapshot(self.db, date(2026, 3, 20))
        self.assertEqual(result["saved"], 0)

        dwd_records = [norkko_records[0] | {"native_key": "d:1", "location_name": "Berlin", "kind": "region"}]
        with patch("app.services.pollen_import_service.fetch_dwd_records", new=AsyncMock(return_value=(date(2026, 3, 20), dwd_records, "ok"))), patch(
            "app.services.pollen_import_service.insert", side_effect=sqlite_insert
        ):
            result = await pis.import_dwd_snapshot(self.db, date(2026, 3, 20))
        self.assertEqual(result["locations"], 1)

    async def test_import_all_and_backfill(self):
        with patch("app.services.pollen_import_service.import_norkko_snapshot", new=AsyncMock(return_value={"status": "n"})), patch(
            "app.services.pollen_import_service.import_meteoswiss_snapshot",
            new=AsyncMock(return_value={"status": "m"}),
        ), patch("app.services.pollen_import_service.import_dwd_snapshot", new=AsyncMock(return_value={"status": "d"})), patch(
            "app.services.pollen_import_service.import_open_meteo_snapshot",
            new=AsyncMock(return_value={"status": "o"}),
        ):
            result = await pis.import_all_external_sources(self.db)
        self.assertEqual([item["status"] for item in result], ["n", "m", "d", "o"])

        with patch("app.services.pollen_import_service.import_meteoswiss_snapshot", new=AsyncMock(side_effect=[{"status": "m1"}, {"status": "m2"}])), patch(
            "app.services.pollen_import_service.import_norkko_snapshot",
            new=AsyncMock(return_value={"status": "n"}),
        ), patch("app.services.pollen_import_service.import_dwd_snapshot", new=AsyncMock(return_value={"status": "d"})), patch(
            "app.services.pollen_import_service.import_open_meteo_snapshot",
            new=AsyncMock(return_value={"status": "o"}),
        ), patch("app.services.pollen_import_service.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 3, 21, tzinfo=timezone.utc)
            mocked_datetime.side_effect = datetime
            result = await pis.backfill_available_history(self.db, days=2)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["meteoswiss_backfill"]), 2)
        self.assertEqual(result["current_snapshots"][0]["status"], "n")
