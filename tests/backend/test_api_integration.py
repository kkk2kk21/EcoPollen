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
from app.domain.models import DataSource, Location, Observation, PollenTaxon, User
from app.main import app
from app.startup.seed import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD


class ApiIntegrationTests(unittest.TestCase):
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

        self.start_scheduler_patch = patch(
            "app.main.start_pollen_scheduler",
            new=AsyncMock(return_value=None),
        )
        self.stop_scheduler_patch = patch(
            "app.main.stop_pollen_scheduler",
            new=AsyncMock(return_value=None),
        )
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

    def test_health_and_public_reference_endpoints(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

        taxa = self.client.get("/api/v1/taxa")
        self.assertEqual(taxa.status_code, 200)
        self.assertTrue(any(item["key"] == "alder" for item in taxa.json()))

        sources = self.client.get("/api/v1/sources")
        self.assertEqual(sources.status_code, 200)
        self.assertTrue(any(item["key"] == "pgniu_manual" for item in sources.json()))

        with patch("app.api.routes.pollen.load_open_meteo_region_city_catalog", return_value=[]):
            map_locations = self.client.get("/api/v1/map-locations")
        self.assertEqual(map_locations.status_code, 200)
        self.assertTrue(any(item["id"] == "manual-city:perm" for item in map_locations.json()))

    def test_auth_register_login_and_me_flow(self):
        response = self.client.post(
            "/api/v1/auth/register",
            json={"email": "User@Example.com", "password": "secret123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "user@example.com")

        login = self.client.post(
            "/api/v1/auth/login",
            data={"username": "user@example.com", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200)
        token = login.json()["access_token"]

        me = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "user@example.com")

    def test_summary_and_heatmap_fallback_endpoints(self):
        with self._db() as db:
            source = db.scalar(select(DataSource).where(DataSource.key == "pgniu_manual"))
            taxon = db.scalar(select(PollenTaxon).where(PollenTaxon.key == "alder"))
            trap = Location(name="Ловушка ПГНИУ", lat=58.0105, lon=56.2502, kind="trap")
            db.add(trap)
            db.commit()
            db.refresh(trap)

            previous_day = datetime.now(timezone.utc).date() - timedelta(days=1)
            db.add(
                Observation(
                    source_id=source.id,
                    location_id=trap.id,
                    taxon_id=taxon.id,
                    ts=datetime.combine(previous_day, datetime.min.time(), tzinfo=timezone.utc),
                    value=12.0,
                    unit="grains/m3",
                )
            )
            db.commit()
            trap_id = trap.id

        summary = self.client.get(
            "/api/v1/summary",
            params={"location_id": trap_id, "preferred_source_key": "pgniu_manual"},
        )
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["time"][:10], previous_day.isoformat())
        alder = next(item for item in summary.json()["taxa"] if item["key"] == "alder")
        self.assertEqual(alder["source"], "pgniu_manual")
        self.assertEqual(alder["raw_value"], 12.0)

        heatmap = self.client.get(
            "/api/v1/heatmap/db",
            params={"source_key": "pgniu_manual", "taxon_key": "alder"},
        )
        self.assertEqual(heatmap.status_code, 200)
        self.assertEqual(heatmap.json()["effective_day"], previous_day.isoformat())
        self.assertEqual(len(heatmap.json()["points"]), 1)

    def test_science_trap_measurement_and_delete_flow(self):
        scientist = self._create_user(email="scientist@example.com", role="scientist")
        headers = self._auth_headers(scientist)

        create_trap = self.client.post(
            "/api/v1/science/traps",
            json={"name": "Тестовая ловушка", "lat": 58.01, "lon": 56.25},
            headers=headers,
        )
        self.assertEqual(create_trap.status_code, 200)
        trap_id = create_trap.json()["location"]["id"]

        with patch("app.api.routes.science.insert") as insert_mock:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            insert_mock.side_effect = sqlite_insert
            save = self.client.post(
                "/api/v1/science/measurements",
                json={
                    "ts": (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),
                    "location": {"id": trap_id},
                    "values": {"alder": {"value": 17}},
                },
                headers=headers,
            )
        self.assertEqual(save.status_code, 200)
        self.assertEqual(save.json()["saved"][0]["taxon_key"], "alder")

        measurements = self.client.get(
            "/api/v1/science/measurements",
            params={"location_id": trap_id},
            headers=headers,
        )
        self.assertEqual(measurements.status_code, 200)
        self.assertEqual(len(measurements.json()), 1)
        obs_id = measurements.json()[0]["id"]

        delete_measurement = self.client.delete(
            f"/api/v1/science/measurements/{obs_id}",
            headers=headers,
        )
        self.assertEqual(delete_measurement.status_code, 200)

        delete_trap = self.client.delete(
            f"/api/v1/science/traps/{trap_id}",
            headers=headers,
        )
        self.assertEqual(delete_trap.status_code, 200)

    def test_admin_user_crud_and_protection(self):
        unauthorized = self.client.get("/api/v1/admin/users")
        self.assertEqual(unauthorized.status_code, 401)

        login = self.client.post(
            "/api/v1/auth/login",
            data={"username": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD},
        )
        self.assertEqual(login.status_code, 200)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        users = self.client.get("/api/v1/admin/users", headers=headers)
        self.assertEqual(users.status_code, 200)

        created = self.client.post(
            "/api/v1/admin/users",
            json={"email": "new-user@example.com", "password": "secret123", "role": "student"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 200)
        user_id = created.json()["id"]

        updated = self.client.patch(
            f"/api/v1/admin/users/{user_id}",
            json={"role": "scientist", "email": "updated-user@example.com"},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["role"], "scientist")

        deleted = self.client.delete(f"/api/v1/admin/users/{user_id}", headers=headers)
        self.assertEqual(deleted.status_code, 200)

    def test_admin_validation_and_self_protection_paths(self):
        login = self.client.post(
            "/api/v1/auth/login",
            data={"username": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        invalid = self.client.post(
            "/api/v1/admin/users",
            json={"email": "bad", "password": "123", "role": "ghost"},
            headers=headers,
        )
        self.assertEqual(invalid.status_code, 400)

        duplicate = self.client.post(
            "/api/v1/admin/users",
            json={"email": DEFAULT_ADMIN_EMAIL, "password": "secret123", "role": "admin"},
            headers=headers,
        )
        self.assertEqual(duplicate.status_code, 409)

        with self._db() as db:
            admin = db.scalar(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
            admin_id = admin.id

        self_demote = self.client.patch(
            f"/api/v1/admin/users/{admin_id}",
            json={"role": "student"},
            headers=headers,
        )
        self.assertEqual(self_demote.status_code, 400)

        self_delete = self.client.delete(f"/api/v1/admin/users/{admin_id}", headers=headers)
        self.assertEqual(self_delete.status_code, 400)

    def test_science_settings_endpoints(self):
        scientist = self._create_user(email="settings@example.com", role="scientist")
        headers = self._auth_headers(scientist)

        get_styles = self.client.get("/api/v1/science/map-circle-styles", headers=headers)
        self.assertEqual(get_styles.status_code, 200)
        self.assertTrue(any(item["source_key"] == "pgniu_manual" for item in get_styles.json()))

        put_styles = self.client.put(
            "/api/v1/science/map-circle-styles",
            json={
                "items": [
                    {"source_key": "pgniu_manual", "base_radius_m": 5000, "step_radius_m": 1500},
                    {"source_key": "missing", "base_radius_m": 1, "step_radius_m": 1},
                ]
            },
            headers=headers,
        )
        self.assertEqual(put_styles.status_code, 200)
        self.assertEqual(put_styles.json()["updated"], ["pgniu_manual"])

        get_distance = self.client.get("/api/v1/science/timeseries-distance-settings", headers=headers)
        self.assertEqual(get_distance.status_code, 200)
        self.assertTrue(any(item["location_kind"] == "trap" for item in get_distance.json()))

        put_distance = self.client.put(
            "/api/v1/science/timeseries-distance-settings",
            json={
                "items": [
                    {"location_kind": "trap", "max_distance_m": 12345},
                    {"location_kind": "missing", "max_distance_m": 1},
                ]
            },
            headers=headers,
        )
        self.assertEqual(put_distance.status_code, 200)
        self.assertEqual(put_distance.json()["updated"], ["trap"])

    def test_jobs_endpoint_handles_success_and_failure(self):
        scientist = self._create_user(email="jobs@example.com", role="scientist")
        headers = self._auth_headers(scientist)

        with patch(
            "app.api.routes.jobs.import_open_meteo_snapshot",
            new=AsyncMock(return_value={"status": "ok"}),
        ):
            ok = self.client.post("/api/v1/jobs/import-open-meteo", headers=headers)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["status"], "ok")

        with patch(
            "app.api.routes.jobs.import_open_meteo_snapshot",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            failed = self.client.post("/api/v1/jobs/import-open-meteo", headers=headers)
        self.assertEqual(failed.status_code, 502)
        self.assertIn("Open-Meteo ошибка", failed.json()["detail"])

    def test_other_jobs_endpoints(self):
        scientist = self._create_user(email="jobs2@example.com", role="scientist")
        headers = self._auth_headers(scientist)

        cases = [
            ("/api/v1/jobs/import-norkko", "app.api.routes.jobs.import_norkko_snapshot", {"status": "norkko"}),
            ("/api/v1/jobs/import-meteoswiss", "app.api.routes.jobs.import_meteoswiss_snapshot", {"status": "meteoswiss"}),
            ("/api/v1/jobs/import-dwd", "app.api.routes.jobs.import_dwd_snapshot", {"status": "dwd"}),
            ("/api/v1/jobs/backfill-week", "app.api.routes.jobs.backfill_available_history", {"status": "backfill"}),
        ]

        for url, target, payload in cases:
            with patch(target, new=AsyncMock(return_value=payload)):
                response = self.client.post(url, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], payload["status"])
