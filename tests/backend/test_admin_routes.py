import unittest
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tests.backend import _bootstrap  # noqa: F401

from app.api.routes.admin import (
    _admin_count,
    _ensure_not_last_admin,
    _normalize_email,
    _normalize_role,
    _serialize_user,
    create_user,
    delete_user,
    list_users,
    update_user,
)
from app.core.db import Base
from app.core.security import verify_password
from app.domain.models import User


class AdminRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _create_user(self, *, email: str, role: str, password_hash: str = "hash") -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            role=role,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def test_normalizers_and_serializer(self):
        self.assertEqual(_normalize_role(None), "student")
        self.assertEqual(_normalize_role(" Admin "), "admin")
        self.assertEqual(_normalize_email(" User@Example.COM "), "user@example.com")

        user = self._create_user(email="user@example.com", role="scientist")
        payload = _serialize_user(user)
        self.assertEqual(payload["email"], "user@example.com")
        self.assertEqual(payload["role"], "scientist")
        self.assertEqual(payload["id"], user.id)

    def test_admin_count_and_last_admin_guard(self):
        student = self._create_user(email="student@example.com", role="student")
        admin = self._create_user(email="admin@example.com", role="admin")

        self.assertEqual(_admin_count(self.db), 1)
        self.assertIsNone(_ensure_not_last_admin(self.db, student))
        self.assertIsNone(_ensure_not_last_admin(self.db, admin, next_role="admin"))
        self.assertIsNone(_ensure_not_last_admin(self.db, admin, next_role=None))

        with self.assertRaises(HTTPException) as demote_error:
            _ensure_not_last_admin(self.db, admin, next_role="student")
        self.assertEqual(demote_error.exception.status_code, 400)

        with self.assertRaises(HTTPException) as delete_error:
            _ensure_not_last_admin(self.db, admin, deleting=True)
        self.assertEqual(delete_error.exception.status_code, 400)

        self._create_user(email="admin2@example.com", role="admin")
        self.assertIsNone(_ensure_not_last_admin(self.db, admin, next_role="student"))
        self.assertIsNone(_ensure_not_last_admin(self.db, admin, deleting=True))

    def test_list_users_returns_newest_first(self):
        older = self._create_user(email="older@example.com", role="student")
        newer = self._create_user(email="newer@example.com", role="admin")
        older.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer.created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.db.commit()

        payload = list_users(db=self.db, _=newer)

        self.assertEqual([item["email"] for item in payload], ["newer@example.com", "older@example.com"])

    def test_create_user_creates_hash_and_rejects_duplicates(self):
        created = create_user(
            {"email": " User@Example.com ", "password": "secret123", "role": "scientist"},
            db=self.db,
            _=None,
        )
        self.assertEqual(created["email"], "user@example.com")
        stored = self.db.get(User, created["id"])
        self.assertTrue(verify_password("secret123", stored.password_hash))

        with self.assertRaises(HTTPException) as duplicate_error:
            create_user(
                {"email": "user@example.com", "password": "secret123", "role": "student"},
                db=self.db,
                _=None,
            )
        self.assertEqual(duplicate_error.exception.status_code, 409)

    def test_update_user_covers_validation_and_success_paths(self):
        current_admin = self._create_user(email="admin@example.com", role="admin")
        target = self._create_user(email="target@example.com", role="student")
        self._create_user(email="taken@example.com", role="scientist")

        with self.assertRaises(HTTPException) as not_found:
            update_user(999, {}, db=self.db, current_user=current_admin)
        self.assertEqual(not_found.exception.status_code, 404)

        with self.assertRaises(HTTPException) as empty_payload:
            update_user(target.id, {}, db=self.db, current_user=current_admin)
        self.assertEqual(empty_payload.exception.status_code, 400)

        with self.assertRaises(HTTPException) as invalid_email:
            update_user(target.id, {"email": "bad"}, db=self.db, current_user=current_admin)
        self.assertEqual(invalid_email.exception.status_code, 400)

        with self.assertRaises(HTTPException) as invalid_role:
            update_user(target.id, {"role": "ghost"}, db=self.db, current_user=current_admin)
        self.assertEqual(invalid_role.exception.status_code, 400)

        with self.assertRaises(HTTPException) as short_password:
            update_user(target.id, {"password": "123"}, db=self.db, current_user=current_admin)
        self.assertEqual(short_password.exception.status_code, 400)

        with self.assertRaises(HTTPException) as duplicate_email:
            update_user(target.id, {"email": "taken@example.com"}, db=self.db, current_user=current_admin)
        self.assertEqual(duplicate_email.exception.status_code, 409)

        updated = update_user(
            target.id,
            {"email": "updated@example.com", "role": "scientist", "password": "new-secret"},
            db=self.db,
            current_user=current_admin,
        )
        self.assertEqual(updated["email"], "updated@example.com")
        self.assertEqual(updated["role"], "scientist")
        self.db.refresh(target)
        self.assertTrue(verify_password("new-secret", target.password_hash))

    def test_delete_user_covers_not_found_and_success(self):
        current_admin = self._create_user(email="admin@example.com", role="admin")
        self._create_user(email="admin2@example.com", role="admin")
        target = self._create_user(email="target@example.com", role="student")

        with self.assertRaises(HTTPException) as not_found:
            delete_user(999, db=self.db, current_user=current_admin, _=None)
        self.assertEqual(not_found.exception.status_code, 404)

        payload = delete_user(target.id, db=self.db, current_user=current_admin, _=None)
        self.assertEqual(payload["email"], "target@example.com")
        self.assertIsNone(self.db.get(User, target.id))
