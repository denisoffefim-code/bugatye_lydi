import unittest

from skycast.forecast_contract import (
    FORECAST_SOURCE_SQL,
    LATEST_FORECAST_CONTRACT,
    latest_forecast_identity_sql,
    latest_forecast_order_by_sql,
)
from skycast.migrations import _create_or_replace_dm_forecast_errors_view


class _MigrationRecordingConnection:
    def __init__(self) -> None:
        self.execute_calls: list[str] = []

    async def execute(self, query: str) -> None:
        self.execute_calls.append(query)


class LatestForecastContractTests(unittest.TestCase):
    def test_identity_sql_tracks_station_date_horizon_provider_and_model(self) -> None:
        identity_sql = latest_forecast_identity_sql()

        self.assertIn("fv.station_id", identity_sql)
        self.assertIn("fv.forecast_date", identity_sql)
        self.assertIn("fv.horizon_days", identity_sql)
        self.assertIn("fr.provider", identity_sql)
        self.assertIn("fr.model", identity_sql)
        self.assertNotIn(FORECAST_SOURCE_SQL, identity_sql)

    def test_public_source_sql_is_unified_forecast(self) -> None:
        self.assertEqual(FORECAST_SOURCE_SQL, "'forecast'")

    def test_order_by_sql_uses_deterministic_tie_breakers(self) -> None:
        order_by_sql = latest_forecast_order_by_sql()

        self.assertIn("fr.run_at DESC", order_by_sql)
        self.assertIn("fr.id DESC", order_by_sql)
        self.assertIn("fv.id DESC", order_by_sql)
        self.assertIn("ties are broken", LATEST_FORECAST_CONTRACT)


class ForecastErrorsViewContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_dm_forecast_errors_uses_shared_latest_forecast_contract(self) -> None:
        conn = _MigrationRecordingConnection()

        await _create_or_replace_dm_forecast_errors_view(conn)

        self.assertEqual(conn.execute_calls[0], "DROP VIEW IF EXISTS dm_forecast_errors")
        create_view_sql = conn.execute_calls[1]
        self.assertIn(f"SELECT DISTINCT ON ({latest_forecast_identity_sql()})", create_view_sql)
        self.assertIn(f"ORDER BY {latest_forecast_order_by_sql()}", create_view_sql)
        self.assertIn(f"{FORECAST_SOURCE_SQL} AS source", create_view_sql)
