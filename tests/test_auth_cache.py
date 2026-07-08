from datetime import UTC, datetime, timedelta
import unittest
from unittest.mock import AsyncMock, patch

from skycast.auth_cache import (
    cache_auth_session,
    get_cached_auth_session,
    invalidate_user_sessions,
    should_touch_auth_session,
)
from skycast.config import Settings


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def sadd(self, key: str, member: str):
        self.sets.setdefault(key, set()).add(member)
        return 1

    async def srem(self, key: str, member: str):
        self.sets.setdefault(key, set()).discard(member)
        return 1

    async def expire(self, key: str, ttl: int):
        return True

    async def smembers(self, key: str):
        return set(self.sets.get(key, set()))

    async def delete(self, *keys: str):
        deleted = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                deleted += 1
            if key in self.sets:
                del self.sets[key]
                deleted += 1
        return deleted


class AuthCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_roundtrip_and_invalidate_user_sessions(self) -> None:
        fake_redis = _FakeRedis()
        test_settings = Settings(
            database_url="postgresql://test",
            auth_cache_enabled=True,
            auth_cache_ttl_seconds=300,
            auth_last_used_throttle_seconds=60,
        )

        with patch("skycast.auth_cache.get_redis_client", AsyncMock(return_value=fake_redis)), patch(
            "skycast.auth_cache.settings",
            test_settings,
        ):
            await cache_auth_session(
                "token-hash",
                session_id=12,
                user_id=7,
                user_payload={
                    "id": 7,
                    "email": "user@example.com",
                    "full_name": "Test User",
                    "role": "viewer",
                    "is_active": True,
                    "created_at": datetime(2026, 7, 8, tzinfo=UTC).isoformat(),
                    "last_login_at": None,
                },
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

            cached = await get_cached_auth_session("token-hash")

            self.assertIsNotNone(cached)
            self.assertEqual(cached["user"]["email"], "user@example.com")

            await invalidate_user_sessions(7)

            self.assertIsNone(await get_cached_auth_session("token-hash"))

    async def test_should_touch_auth_session_is_throttled(self) -> None:
        fake_redis = _FakeRedis()
        test_settings = Settings(
            database_url="postgresql://test",
            auth_cache_enabled=True,
            auth_cache_ttl_seconds=300,
            auth_last_used_throttle_seconds=60,
        )

        with patch("skycast.auth_cache.get_redis_client", AsyncMock(return_value=fake_redis)), patch(
            "skycast.auth_cache.settings",
            test_settings,
        ):
            self.assertTrue(await should_touch_auth_session(99))
            self.assertFalse(await should_touch_auth_session(99))
