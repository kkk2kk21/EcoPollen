import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from tests.backend import _bootstrap  # noqa: F401

from app.api.routes.science import (
    _day_start_utc,
    _ensure_trap_name_available,
    _get_or_create_location,
    _get_or_create_source,
    _get_source_by_key,
    _get_trap_or_404,
    _serialize_location,
    create_measurements,
    delete_measurement,
    list_measurements,
    update_map_circle_styles,
    update_timeseries_distance_settings,
)
from app.api.schemas import (
    ExternalTimeseriesDistanceSettingUpdateItem,
    ExternalTimeseriesDistanceSettingsUpdate,
    LocationRef,
    MapCircleStyleUpdateItem,
    MapCircleStylesUpdate,
    MeasurementValue,
    MeasurementsCreate,
)
from app.core.db import Base
from app.domain.models import (
    DataSource,
    ExternalTimeseriesDistanceSetting,
    Location,
    MapCircleStyle,
    Observation,
    PollenTaxon,
)
from app.startup.seed import seed_if_empty


class ScienceRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        seed_if_empty(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_day_start_utc_handles_date_and_datetime(self):
        self.assertEqual(
            _day_start_utc(date(2026, 3, 20)),
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(
            _day_start_utc(datetime(2026, 3, 20, 15, 30, tzinfo=timezone.utc)),
            datetime(2026, 3, 20, tzinfo=timezone.utc),
        )

    def test_source_helper_creates_and_reuses_source(self):
        created = _get_or_create_source(self.db, "custom-source", "Custom", "manual", 5)
        reused = _get_or_create_source(self.db, "custom-source", "Ignored", "api", 1)

        self.assertEqual(created.id, reused.id)
        self.assertEqual(created.name, "Custom")

    def test_location_helper_covers_error_and_reuse_paths(self):
        trap = Location(name="Первая ловушка", lat=58.0, lon=56.0, kind="trap")
        self.db.add(trap)
        self.db.commit()
        self.db.refresh(trap)

        by_id = _get_or_create_location(self.db, LocationRef(id=trap.id))
        self.assertEqual(by_id.id, trap.id)

        with self.assertRaises(HTTPException) as missing_id:
            _get_or_create_location(self.db, LocationRef(id=999))
        self.assertEqual(missing_id.exception.status_code, 404)

        with self.assertRaises(HTTPException) as missing_coords:
            _get_or_create_location(self.db, LocationRef(name="Без координат"))
        self.assertEqual(missing_coords.exception.status_code, 400)

        with self.assertRaises(HTTPException) as bad_kind:
            _get_or_create_location(self.db, LocationRef(name="Плохая", lat=1, lon=2, kind="station"))
        self.assertEqual(bad_kind.exception.status_code, 400)

        existing_by_name = _get_or_create_location(self.db, LocationRef(name="Первая ловушка", lat=1, lon=2))
        self.assertEqual(existing_by_name.id, trap.id)

        created = _get_or_create_location(self.db, LocationRef(name="Новая ловушка", lat=59.1, lon=57.2))
        self.assertEqual(created.kind, "trap")
        self.assertEqual(created.name, "Новая ловушка")

    def test_lookup_and_validation_helpers_cover_missing_paths(self):
        source = self.db.scalar(select(DataSource).where(DataSource.key == "pgniu_manual"))
        trap = Location(name="Ловушка", lat=58.1, lon=56.1, kind="trap")
        self.db.add(trap)
        self.db.commit()
        self.db.refresh(trap)

        self.assertEqual(_get_source_by_key(self.db, "pgniu_manual").id, source.id)
        self.assertEqual(_get_trap_or_404(self.db, trap.id).id, trap.id)
        self.assertEqual(_serialize_location(trap)["name"], "Ловушка")

        with self.assertRaises(HTTPException) as missing_source:
            _get_source_by_key(self.db, "missing")
        self.assertEqual(missing_source.exception.status_code, 404)

        with self.assertRaises(HTTPException) as missing_trap:
            _get_trap_or_404(self.db, 999)
        self.assertEqual(missing_trap.exception.status_code, 404)

        with self.assertRaises(HTTPException) as duplicate_name:
            _ensure_trap_name_available(self.db, "Ловушка")
        self.assertEqual(duplicate_name.exception.status_code, 409)

        self.assertIsNone(_ensure_trap_name_available(self.db, "Ловушка", exclude_id=trap.id))

    def test_create_measurements_skips_empty_values_and_validates_taxon(self):
        payload = MeasurementsCreate(
            ts=date(2026, 3, 20),
            location=LocationRef(name="Ловушка Пермь", lat=58.0, lon=56.0),
            values={
                "alder": MeasurementValue(value=12, unit="POLLEN/M3"),
                "birch": MeasurementValue(value=None),
            },
        )

        with patch("app.api.routes.science.insert", side_effect=sqlite_insert):
            result = create_measurements(payload, db=self.db, _=None)
        self.assertEqual(result["source"], "pgniu_manual")
        self.assertEqual(len(result["saved"]), 1)
        self.assertEqual(result["saved"][0]["unit"], "pollen/m3")

        stored = self.db.scalars(select(Observation)).all()
        self.assertEqual(len(stored), 1)

        bad_payload = MeasurementsCreate(
            ts=date(2026, 3, 20),
            location=LocationRef(name="Ловушка 2", lat=58.2, lon=56.2),
            values={"unknown": MeasurementValue(value=1)},
        )
        with self.assertRaises(HTTPException) as bad_taxon:
            with patch("app.api.routes.science.insert", side_effect=sqlite_insert):
                create_measurements(bad_payload, db=self.db, _=None)
        self.assertEqual(bad_taxon.exception.status_code, 400)

    def test_list_measurements_filters_by_location_and_day(self):
        source = self.db.scalar(select(DataSource).where(DataSource.key == "pgniu_manual"))
        taxon = self.db.scalar(select(PollenTaxon).where(PollenTaxon.key == "alder"))
        trap = Location(name="Фильтр ловушка", lat=58.4, lon=56.4, kind="trap")
        self.db.add(trap)
        self.db.commit()
        self.db.refresh(trap)

        self.db.add_all(
            [
                Observation(
                    source_id=source.id,
                    location_id=trap.id,
                    taxon_id=taxon.id,
                    ts=datetime(2026, 3, 20, tzinfo=timezone.utc),
                    value=10,
                    unit="grains/m3",
                ),
                Observation(
                    source_id=source.id,
                    location_id=trap.id,
                    taxon_id=taxon.id,
                    ts=datetime(2026, 3, 21, tzinfo=timezone.utc),
                    value=20,
                    unit="grains/m3",
                ),
            ]
        )
        self.db.commit()

        filtered = list_measurements(location_id=trap.id, day=date(2026, 3, 20), limit=200, db=self.db, _=None)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["value"], 10)
        self.assertEqual(filtered[0]["location"]["id"], trap.id)

    def test_settings_updates_create_rows_when_missing(self):
        source = self.db.scalar(select(DataSource).where(DataSource.key == "pgniu_manual"))
        self.db.execute(delete(MapCircleStyle).where(MapCircleStyle.source_id == source.id))
        self.db.execute(
            delete(ExternalTimeseriesDistanceSetting).where(
                ExternalTimeseriesDistanceSetting.location_kind == "trap"
            )
        )
        self.db.commit()

        style_result = update_map_circle_styles(
            MapCircleStylesUpdate(
                items=[
                    MapCircleStyleUpdateItem(source_key="pgniu_manual", base_radius_m=7000, step_radius_m=1234),
                    MapCircleStyleUpdateItem(source_key="missing", base_radius_m=1, step_radius_m=1),
                ]
            ),
            db=self.db,
            _=None,
        )
        self.assertEqual(style_result["updated"], ["pgniu_manual"])
        created_style = self.db.scalar(select(MapCircleStyle).where(MapCircleStyle.source_id == source.id))
        self.assertEqual(created_style.base_radius_m, 7000)

        distance_result = update_timeseries_distance_settings(
            ExternalTimeseriesDistanceSettingsUpdate(
                items=[
                    ExternalTimeseriesDistanceSettingUpdateItem(location_kind="trap", max_distance_m=4321),
                    ExternalTimeseriesDistanceSettingUpdateItem(location_kind="missing", max_distance_m=1),
                ]
            ),
            db=self.db,
            _=None,
        )
        self.assertEqual(distance_result["updated"], ["trap"])
        created_setting = self.db.scalar(
            select(ExternalTimeseriesDistanceSetting).where(
                ExternalTimeseriesDistanceSetting.location_kind == "trap"
            )
        )
        self.assertEqual(created_setting.max_distance_m, 4321)

    def test_delete_measurement_covers_missing_and_success_paths(self):
        with self.assertRaises(HTTPException) as missing:
            delete_measurement(999, db=self.db, _=None)
        self.assertEqual(missing.exception.status_code, 404)

        source = self.db.scalar(select(DataSource).where(DataSource.key == "pgniu_manual"))
        taxon = self.db.scalar(select(PollenTaxon).where(PollenTaxon.key == "alder"))
        trap = Location(name="Удаляемая ловушка", lat=58.5, lon=56.5, kind="trap")
        self.db.add(trap)
        self.db.commit()
        self.db.refresh(trap)

        obs = Observation(
            source_id=source.id,
            location_id=trap.id,
            taxon_id=taxon.id,
            ts=datetime(2026, 3, 20, tzinfo=timezone.utc),
            value=11,
            unit="grains/m3",
        )
        self.db.add(obs)
        self.db.commit()
        self.db.refresh(obs)

        payload = delete_measurement(obs.id, db=self.db, _=None)
        self.assertEqual(payload, {"status": "deleted", "id": obs.id})
        self.assertIsNone(self.db.get(Observation, obs.id))
