import unittest

from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


class SecurityTests(unittest.TestCase):
    def test_password_hash_roundtrip(self):
        password_hash = hash_password("secret123")

        self.assertNotEqual(password_hash, "secret123")
        self.assertTrue(verify_password("secret123", password_hash))
        self.assertFalse(verify_password("wrong", password_hash))

    def test_access_token_roundtrip(self):
        token = create_access_token({"sub": "admin@admin", "role": "admin"}, expires_hours=1)
        payload = decode_token(token)

        self.assertEqual(payload["sub"], "admin@admin")
        self.assertEqual(payload["role"], "admin")
        self.assertIn("exp", payload)
