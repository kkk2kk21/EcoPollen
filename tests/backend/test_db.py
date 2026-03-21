import unittest
from unittest.mock import patch

from tests.backend import _bootstrap  # noqa: F401

from app.core import db as db_module


class DbTests(unittest.TestCase):
    def test_get_db_closes_session_after_use(self):
        closed = []

        class FakeSession:
            def close(self):
                closed.append("closed")

        with patch.object(db_module, "SessionLocal", return_value=FakeSession()):
            gen = db_module.get_db()
            session = next(gen)
            self.assertIsInstance(session, FakeSession)

            with self.assertRaises(StopIteration):
                next(gen)

        self.assertEqual(closed, ["closed"])

    def test_get_db_closes_session_after_exception(self):
        closed = []

        class FakeSession:
            def close(self):
                closed.append("closed")

        with patch.object(db_module, "SessionLocal", return_value=FakeSession()):
            gen = db_module.get_db()
            next(gen)
            with self.assertRaises(RuntimeError):
                gen.throw(RuntimeError("boom"))

        self.assertEqual(closed, ["closed"])
