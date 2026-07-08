import unittest

from skycast.auth import (
    extract_bearer_token,
    hash_password,
    hash_token,
    normalize_email,
    verify_password,
)


class EmailNormalizationTests(unittest.TestCase):
    def test_normalize_email_lowercases_and_trims(self) -> None:
        self.assertEqual(normalize_email("  User@Example.COM "), "user@example.com")

    def test_normalize_email_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValueError):
            normalize_email("not-an-email")


class PasswordHashingTests(unittest.TestCase):
    def test_password_hash_roundtrip(self) -> None:
        encoded = hash_password("very-secret-123", iterations=120000)

        self.assertTrue(verify_password("very-secret-123", encoded))

    def test_password_hash_rejects_wrong_password(self) -> None:
        encoded = hash_password("very-secret-123", iterations=120000)

        self.assertFalse(verify_password("wrong-password", encoded))


class TokenHelpersTests(unittest.TestCase):
    def test_extract_bearer_token(self) -> None:
        self.assertEqual(extract_bearer_token("Bearer token-123"), "token-123")
        self.assertIsNone(extract_bearer_token("Basic abc"))
        self.assertIsNone(extract_bearer_token(None))

    def test_hash_token_is_stable(self) -> None:
        self.assertEqual(
            hash_token("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
