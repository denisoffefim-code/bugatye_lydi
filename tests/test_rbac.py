from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from skycast.main import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_VIEWER,
    UserOut,
    analytics_coverage,
    get_current_admin_auth_context,
    get_current_analyst_auth_context,
    get_current_viewer_auth_context,
    ingest_telemetry,
    list_stations,
    logout_user_sessions,
    transport_overview,
)


class _FakeAcquire:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakePool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


class _RBACConnection:
    def __init__(self, *, fetch_results=None, fetchrow_results=None, fetchval_results=None) -> None:
        self.fetch_results = list(fetch_results or [])
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetchval_results = list(fetchval_results or [])
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args):
        self.fetch_calls.append((query, args))
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return []

    async def fetchrow(self, query: str, *args):
        self.fetchrow_calls.append((query, args))
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def fetchval(self, query: str, *args):
        self.fetchval_calls.append((query, args))
        if self.fetchval_results:
            return self.fetchval_results.pop(0)
        return None

    async def execute(self, query: str, *args):
        self.execute_calls.append((query, args))
        return "OK"


def _auth_context(role: str) -> dict[str, object]:
    return {
        "session_id": 55,
        "client_ip": "127.0.0.1",
        "user": UserOut(
            id=7,
            email="user@example.com",
            full_name="Test User",
            role=role,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            last_login_at=None,
        ),
    }


class RBACDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_viewer_dependency_accepts_viewer_and_legacy_user_role(self) -> None:
        viewer = await get_current_viewer_auth_context(current_auth=_auth_context(ROLE_VIEWER))
        legacy_user = await get_current_viewer_auth_context(current_auth=_auth_context("user"))

        self.assertEqual(viewer["user"].role, ROLE_VIEWER)
        self.assertEqual(legacy_user["user"].role, "user")

    async def test_analyst_dependency_rejects_viewer(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await get_current_analyst_auth_context(current_auth=_auth_context(ROLE_VIEWER))

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("required one of: analyst, admin", ctx.exception.detail)

    async def test_admin_dependency_rejects_analyst(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await get_current_admin_auth_context(current_auth=_auth_context(ROLE_ANALYST))

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("required one of: admin", ctx.exception.detail)


class RBACEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_viewer_can_access_station_list(self) -> None:
        conn = _RBACConnection(fetch_results=[[]], fetchval_results=[0])

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await list_stations(limit=5, _=_auth_context(ROLE_VIEWER))

        self.assertEqual(response["returned"], 0)
        self.assertEqual(len(conn.fetch_calls), 1)

    async def test_analyst_can_reach_telemetry_endpoint_logic(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await ingest_telemetry(records=[], current_auth=_auth_context(ROLE_ANALYST))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "At least one telemetry record is required")

    async def test_admin_can_view_service_coverage(self) -> None:
        conn = _RBACConnection(fetchrow_results=[{"stations_total": 1, "forecast_runs_total": 2}])

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await analytics_coverage(_=_auth_context(ROLE_ADMIN))

        self.assertEqual(response["stations_total"], 1)
        self.assertEqual(len(conn.fetchrow_calls), 1)

    async def test_admin_can_revoke_user_sessions(self) -> None:
        conn = _RBACConnection(fetchval_results=[1], fetch_results=[[]])

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)), patch(
            "skycast.main.invalidate_user_sessions",
            new_callable=AsyncMock,
        ), patch(
            "skycast.main.invalidate_auth_session",
            new_callable=AsyncMock,
        ):
            await logout_user_sessions(user_id=42, current_auth=_auth_context(ROLE_ADMIN))

        self.assertEqual(len(conn.execute_calls), 1)
        self.assertIn("UPDATE auth_sessions", conn.execute_calls[0][0])

    async def test_admin_can_view_transport_overview(self) -> None:
        conn = _RBACConnection()
        fake_redis = AsyncMock()
        fake_redis.ping = AsyncMock()

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)), patch(
            "skycast.main.collect_db_metrics",
            new=AsyncMock(return_value={"outbox_pending_total": 3}),
        ), patch(
            "skycast.main.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ), patch(
            "skycast.main.load_transport_runtime_snapshot",
            new=AsyncMock(return_value={"publisher": {"counters": {"published_total": 5}}}),
        ), patch(
            "skycast.main._probe_kafka_topics",
            new=AsyncMock(return_value={"available": True}),
        ):
            response = await transport_overview(_=_auth_context(ROLE_ADMIN))

        self.assertEqual(response["database_metrics"]["outbox_pending_total"], 3)
        self.assertTrue(response["kafka"]["available"])
        self.assertEqual(response["redis"]["snapshot"]["publisher"]["counters"]["published_total"], 5)
