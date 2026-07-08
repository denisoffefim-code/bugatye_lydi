"""Authentication helpers for password hashing and bearer token parsing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or len(normalized) > 320 or not _EMAIL_RE.match(normalized):
        raise ValueError("email must be a valid email address")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters long")
    if len(password) > 128:
        raise ValueError("password must be at most 128 characters long")


def hash_password(password: str, *, iterations: int) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{_urlsafe_b64encode(salt)}$"
        f"{_urlsafe_b64encode(derived_key)}"
    )


def verify_password(password: str, encoded_password: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, expected_hash_text = encoded_password.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iterations_text)
    except ValueError:
        return False

    salt = _urlsafe_b64decode(salt_text)
    expected_hash = _urlsafe_b64decode(expected_hash_text)
    actual_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_hash, expected_hash)


def generate_session_token(*, nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def extract_bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None

    scheme, _, token_value = authorization_header.partition(" ")
    if scheme.lower() != "bearer":
        return None

    token = token_value.strip()
    if not token:
        return None
    return token


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
