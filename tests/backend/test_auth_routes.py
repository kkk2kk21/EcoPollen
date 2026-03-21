import unittest
from tests.backend import _bootstrap  # noqa: F401

from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.auth import (
    change_password,
    get_current_user,
    login,
    me,
    register,
    require_roles,
)
from app.core.db import Base
from app.core.security import create_access_token, hash_password
from app.domain.models import User


class AuthRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _create_user(self, *, email="user@example.com", password="secret123", role="student"):
        user = User(email=email, password_hash=hash_password(password), role=role)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def test_register_creates_student_with_normalized_email(self):
        payload = register({"email": "  User@Example.com ", "password": "secret123"}, db=self.db)

        self.assertEqual(payload["email"], "user@example.com")
        self.assertEqual(payload["role"], "student")
        self.assertEqual(self.db.query(User).count(), 1)

    def test_register_rejects_invalid_payload(self):
        with self.assertRaises(HTTPException) as error:
            register({"email": "bad", "password": "123"}, db=self.db)

        self.assertEqual(error.exception.status_code, 400)

    def test_register_rejects_duplicate_email(self):
        self._create_user()

        with self.assertRaises(HTTPException) as error:
            register({"email": "user@example.com", "password": "secret123"}, db=self.db)

        self.assertEqual(error.exception.status_code, 409)

    def test_login_returns_bearer_token(self):
        self._create_user(password="secret123")
        form = OAuth2PasswordRequestForm(username="USER@example.com", password="secret123", scope="")

        payload = login(form, db=self.db)

        self.assertEqual(payload["token_type"], "bearer")
        self.assertIn("access_token", payload)

    def test_login_rejects_invalid_credentials(self):
        self._create_user(password="secret123")
        form = OAuth2PasswordRequestForm(username="user@example.com", password="wrong", scope="")

        with self.assertRaises(HTTPException) as error:
            login(form, db=self.db)

        self.assertEqual(error.exception.status_code, 401)

    def test_get_current_user_rejects_invalid_token(self):
        with self.assertRaises(HTTPException) as error:
            get_current_user(db=self.db, token="bad-token")

        self.assertEqual(error.exception.status_code, 401)

    def test_get_current_user_rejects_missing_user(self):
        token = create_access_token({"uid": 999, "sub": "ghost@example.com", "role": "student"})

        with self.assertRaises(HTTPException) as error:
            get_current_user(db=self.db, token=token)

        self.assertEqual(error.exception.status_code, 401)

    def test_get_current_user_returns_user_for_valid_token(self):
        user = self._create_user()
        token = create_access_token({"uid": user.id, "sub": user.email, "role": user.role})

        current = get_current_user(db=self.db, token=token)

        self.assertEqual(current.id, user.id)

    def test_require_roles_accepts_allowed_role(self):
        admin = self._create_user(role="admin")

        resolved = require_roles("admin")(user=admin)

        self.assertEqual(resolved.id, admin.id)

    def test_require_roles_rejects_forbidden_role(self):
        student = self._create_user(role="student")

        with self.assertRaises(HTTPException) as error:
            require_roles("admin")(user=student)

        self.assertEqual(error.exception.status_code, 403)

    def test_change_password_validates_payload_and_current_password(self):
        user = self._create_user(password="secret123")

        with self.assertRaises(HTTPException):
            change_password({}, db=self.db, user=user)

        with self.assertRaises(HTTPException):
            change_password(
                {"current_password": "wrong", "new_password": "new-secret"},
                db=self.db,
                user=user,
            )

        with self.assertRaises(HTTPException):
            change_password(
                {"current_password": "secret123", "new_password": "123"},
                db=self.db,
                user=user,
            )

        with self.assertRaises(HTTPException):
            change_password(
                {"current_password": "secret123", "new_password": "secret123"},
                db=self.db,
                user=user,
            )

    def test_change_password_updates_hash(self):
        user = self._create_user(password="secret123")

        payload = change_password(
            {"current_password": "secret123", "new_password": "new-secret"},
            db=self.db,
            user=user,
        )

        self.db.refresh(user)
        self.assertEqual(payload["status"], "ok")
        self.assertNotEqual(user.password_hash, hash_password("secret123"))

    def test_me_returns_public_user_payload(self):
        user = self._create_user(role="scientist")

        payload = me(user=user)

        self.assertEqual(payload, {"id": user.id, "email": user.email, "role": "scientist"})
