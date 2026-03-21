import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.backend import _bootstrap  # noqa: F401

import app.main as app_main
from app.core.db import Base, get_db
from app.core.security import create_access_token, hash_password
from app.domain.models import (
    DataSource,
    ExternalLocation,
    ExternalObservation,
    Location,
    Observation,
    PollenTaxon,
    User,
)
from app.main import app
from app.startup.seed import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD


class PublicApiRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

        self._old_engine = app_main.engine
        self._old_session_local = app_main.SessionLocal
        app_main.engine = self.engine
        app_main.SessionLocal = self.SessionLocal

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        self.start_scheduler_patch = patch("app.main.start_pollen_scheduler", new=AsyncMock(return_value=None))
        self.stop_scheduler_patch = patch("app.main.stop_pollen_scheduler", new=AsyncMock(return_value=None))
        self.start_scheduler_patch.start()
        self.stop_scheduler_patch.start()

        self.client_manager = TestClient(app)
        self.client = self.client_manager.__enter__()

    def tearDown(self):
        self.client_manager.__exit__(None, None, None)
        self.start_scheduler_patch.stop()
        self.stop_scheduler_patch.stop()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()
        app_main.engine = self._old_engine
        app_main.SessionLocal = self._old_session_local

    def _db(self):
        return self.SessionLocal()

    def _create_user(self, *, email: str, role: str, password: str = "secret123") -> User:
        with self._db() as db:
            user = User(email=email, password_hash=hash_password(password), role=role)
            db.add(user)
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user

    def _auth_headers(self, user: User) -> dict[str, str]:
        token = create_access_token({"uid": user.id, "sub": user.email, "role": user.role})
        return {"Authorization": f"Bearer {token}"}

    def test_public_map_endpoints_include_internal_catalog_and_external_places(self):
        with self._db() as db:
            trap = Location(name="Ловушка Пермь", lat=58.0105, lon=56.2502, kind="trap")
            source = db.scalar(select(DataSource).where(DataSource.key == "norkko"))
            station = ExternalLocation(
                source_id=source.id,
                native_key="norkko:turku",
                name="Turku, Finland",
                lat=60.4518,
                lon=22.2666,
                kind="station",
            )
            db.add_all([trap, station])
            db.commit()

        locations = self.client.get("/api/v1/locations")
        self.assertEqual(locations.status_code, 200)
        self.assertEqual(locations.json()[0]["name"], "Ловушка Пермь")

        styles = self.client.get("/api/v1/map-circle-styles")
        self.assertEqual(styles.status_code, 200)
        self.assertTrue(any(item["source_key"] == "default" for item in styles.json()))

        city_catalog = [
            {
                "id": "catalog:perm",
                "name": "Пермь",
                "lat": 58.0105,
                "lon": 56.2502,
                "search_text": "Пермь",
                "population": 1000,
                "country_name": "Россия",
            },
            {
                "id": "catalog:izhevsk",
                "name": "Ижевск",
                "lat": 56.8526,
                "lon": 53.2114,
                "search_text": "Ижевск",
                "population": 2000,
                "country_name": "Россия",
            },
        ]
        with patch("app.api.routes.pollen.load_open_meteo_region_city_catalog", return_value=city_catalog):
            map_locations = self.client.get("/api/v1/map-locations")

        self.assertEqual(map_locations.status_code, 200)
        items = map_locations.json()
        self.assertEqual(len([item for item in items if item["name"] == "Пермь" and item["kind"] == "city"]), 1)
        self.assertTrue(any(item["name"] == "Ижевск" and item["scope"] == "catalog" for item in items))
        self.assertTrue(any(item["source_key"] == "norkko" and item["scope"] == "external" for item in items))

    def test_summary_covers_validation_and_open_meteo_fallback(self):
        missing = self.client.get("/api/v1/summary")
        self.assertEqual(missing.status_code, 400)

        bad_location = self.client.get("/api/v1/summary", params={"location_id": 999})
        self.assertEqual(bad_location.status_code, 404)

        bad_external = self.client.get("/api/v1/summary", params={"external_location_id": 999})
        self.assertEqual(bad_external.status_code, 404)

        with patch("app.api.routes.pollen.is_open_meteo_region_point", return_value=True), patch(
            "app.api.routes.pollen.fetch_current_pollen",
            new=AsyncMock(
                return_value={
                    "current": {"alder_pollen": 5.0},
                    "current_units": {"alder_pollen": "grains/m3"},
                }
            ),
        ):
            response = self.client.get("/api/v1/summary", params={"lat": 60.0, "lon": 30.0})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        alder = next(item for item in payload["taxa"] if item["key"] == "alder")
        self.assertEqual(alder["source"], "open_meteo")
        self.assertIn("open_meteo", payload["used_sources"])
        self.assertIn("Open-Meteo", payload["note"])

    def test_timeseries_and_heatmap_cover_public_paths(self):
        with self._db() as db:
            source = db.scalar(select(DataSource).where(DataSource.key == "norkko"))
            taxon = db.scalar(select(PollenTaxon).where(PollenTaxon.key == "alder"))
            ext = ExternalLocation(
                source_id=source.id,
                native_key="norkko:turku",
                name="Turku, Finland",
                lat=60.4518,
                lon=22.2666,
                kind="station",
            )
            db.add(ext)
            db.commit()
            db.refresh(ext)

            db.add(
                ExternalObservation(
                    external_location_id=ext.id,
                    taxon_id=taxon.id,
                    ts=datetime.now(timezone.utc) - timedelta(days=1),
                    value=2.0,
                    unit="index_0_3",
                )
            )
            db.commit()
            ext_id = ext.id

        missing = self.client.get("/api/v1/timeseries", params={"taxon_key": "alder"})
        self.assertEqual(missing.status_code, 400)

        bad_external = self.client.get(
            "/api/v1/timeseries",
            params={"external_location_id": 999, "taxon_key": "alder"},
        )
        self.assertEqual(bad_external.status_code, 404)

        unknown_taxon = self.client.get(
            "/api/v1/timeseries",
            params={"external_location_id": ext_id, "taxon_key": "unknown"},
        )
        self.assertEqual(unknown_taxon.status_code, 400)

        ok = self.client.get(
            "/api/v1/timeseries",
            params={"external_location_id": ext_id, "taxon_key": "alder", "days": 3},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(any(series["source"] == "norkko" for series in ok.json()["series"]))
        self.assertIn("внешней точке", ok.json()["note"])

        bad_source = self.client.get(
            "/api/v1/heatmap/db",
            params={"source_key": "missing", "taxon_key": "alder"},
        )
        self.assertEqual(bad_source.status_code, 404)

        bad_taxon = self.client.get(
            "/api/v1/heatmap/db",
            params={"source_key": "norkko", "taxon_key": "unknown"},
        )
        self.assertEqual(bad_taxon.status_code, 400)

        heatmap = self.client.get(
            "/api/v1/heatmap/db",
            params={"source_key": "norkko", "taxon_key": "alder"},
        )
        self.assertEqual(heatmap.status_code, 200)
        self.assertEqual(len(heatmap.json()["points"]), 1)

    def test_library_search_validation_and_cache_paths(self):
        bad_years = self.client.get(
            "/api/v1/library/search",
            params={"q": "birch", "year_from": 2026, "year_to": 2025},
            headers=self._auth_headers(self._create_user(email="reader1@example.com", role="student")),
        )
        self.assertEqual(bad_years.status_code, 400)

        bad_dates = self.client.get(
            "/api/v1/library/search",
            params={"q": "birch", "date_from": "2026-03-22", "date_to": "2026-03-01"},
            headers=self._auth_headers(self._create_user(email="reader2@example.com", role="student")),
        )
        self.assertEqual(bad_dates.status_code, 400)

        bad_sort = self.client.get(
            "/api/v1/library/search",
            params={"q": "birch", "sort": "weird"},
            headers=self._auth_headers(self._create_user(email="reader3@example.com", role="student")),
        )
        self.assertEqual(bad_sort.status_code, 400)

        bad_language = self.client.get(
            "/api/v1/library/search",
            params={"q": "birch", "language": "de"},
            headers=self._auth_headers(self._create_user(email="reader4@example.com", role="student")),
        )
        self.assertEqual(bad_language.status_code, 400)

        user = self._create_user(email="reader5@example.com", role="student")
        headers = self._auth_headers(user)
        cached_payload = {
            "expanded_terms": ["birch", "pollen"],
            "expanded_term_meta": {
                "birch": {"type": "allergen", "is_generic": False},
                "pollen": {"type": "generic", "is_generic": True},
            },
            "source_statuses": [{"source": "crossref", "status": "ok", "success_terms": 1, "failed_terms": 0, "warning": None}],
            "warnings": [{"source": "crossref", "message": "warn"}],
            "results": [
                {
                    "source": "crossref",
                    "title": "Birch pollen allergy",
                    "snippet": "Study",
                    "authors": "Ivanov",
                    "year": 2025,
                    "published_at": "2025-03-01",
                    "language": "en",
                    "url": "https://example.com/1",
                }
            ],
        }

        with patch("app.api.routes.library._get_cached_search", new=AsyncMock(return_value=(cached_payload, True))):
            cached = self.client.get(
                "/api/v1/library/search",
                params={"q": "birch", "sources": "crossref"},
                headers=headers,
            )
        self.assertEqual(cached.status_code, 200)
        self.assertTrue(cached.json()["cache"]["hit"])
        self.assertEqual(cached.json()["results"][0]["title"], "Birch pollen allergy")

        miss_payload = {
            **cached_payload,
            "warnings": [],
        }
        with patch("app.api.routes.library._get_cached_search", new=AsyncMock(return_value=(None, False))), patch(
            "app.api.routes.library._get_or_execute_inflight_search",
            new=AsyncMock(return_value=miss_payload),
        ) as inflight, patch("app.api.routes.library._store_cached_search", new=AsyncMock()) as store:
            missed = self.client.get(
                "/api/v1/library/search",
                params={"q": "birch", "sources": "crossref"},
                headers=headers,
            )
        self.assertEqual(missed.status_code, 200)
        self.assertFalse(missed.json()["cache"]["hit"])
        inflight.assert_awaited()
        store.assert_awaited()

    def test_library_search_rejects_unknown_source(self):
        user = self._create_user(email="reader6@example.com", role="student")
        response = self.client.get(
            "/api/v1/library/search",
            params={"q": "birch", "sources": "unknown"},
            headers=self._auth_headers(user),
        )
        self.assertEqual(response.status_code, 400)
