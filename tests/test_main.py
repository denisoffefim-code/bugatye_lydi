from datetime import date
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from skycast.forecast_contract import latest_forecast_identity_sql, latest_forecast_order_by_sql
from skycast.main import (
    _determine_forecast_run_status,
    analytics_summary,
    forecast_coverage,
    list_forecast_runs,
    list_stations,
    station_series,
    top_errors,
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


class _RecordingConnection:
    def __init__(self, *, fetch_results=None, fetchrow_results=None) -> None:
        self.fetch_results = list(fetch_results or [])
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []

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


class ForecastRunStatusTests(unittest.TestCase):
    def test_success_when_no_errors(self) -> None:
        self.assertEqual(
            _determine_forecast_run_status(saved_rows=10, error_count=0),
            "success",
        )

    def test_partial_failed_when_rows_saved_and_errors_present(self) -> None:
        self.assertEqual(
            _determine_forecast_run_status(saved_rows=3, error_count=1),
            "partial_failed",
        )

    def test_failed_when_every_station_failed(self) -> None:
        self.assertEqual(
            _determine_forecast_run_status(saved_rows=0, error_count=2),
            "failed",
        )


class StationFilterValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_conflicting_station_filters_raise_400(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await list_stations(
                with_coordinates_only=True,
                missing_coordinates_only=True,
                limit=10,
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("cannot both be true", ctx.exception.detail)

    async def test_end_date_before_start_date_validation_message_is_stable(self) -> None:
        from skycast.main import top_errors

        with self.assertRaises(HTTPException) as ctx:
            await top_errors(
                start_date=date(2026, 7, 10),
                end_date=date(2026, 7, 9),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("end_date must be greater than or equal to start_date", ctx.exception.detail)


class ForecastAnalyticsQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_forecast_runs_applies_source_model_and_horizon_filters(self) -> None:
        conn = _RecordingConnection(fetch_results=[[{"id": 9, "source": "forecast"}]])

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await list_forecast_runs(
                limit=5,
                status="success",
                model="best_match",
                source="previous_runs",
                horizon_days=3,
            )

        self.assertEqual(response["returned"], 1)
        query, args = conn.fetch_calls[0]
        self.assertNotIn(" AS source = ", query)
        self.assertNotIn("COALESCE(fr.request_payload->>'source', 'forecast') =", query)
        self.assertIn("fv_filter.horizon_days = $3", query)
        self.assertEqual(args, ("success", "best_match", 3, 5))

    async def test_top_errors_applies_source_model_and_horizon_filters(self) -> None:
        conn = _RecordingConnection(fetch_results=[[]])

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await top_errors(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
                metric="avg_temp",
                limit=20,
                model="best_match",
                source="previous_runs",
                horizon_days=2,
            )

        self.assertEqual(response["returned"], 0)
        query, args = conn.fetch_calls[0]
        self.assertNotIn("source =", query)
        self.assertIn("fv.horizon_days = $4", query)
        self.assertEqual(response["source"], "forecast")
        self.assertEqual(
            args,
            (date(2026, 7, 1), date(2026, 7, 10), "best_match", 2, 20),
        )

    async def test_top_errors_defaults_blank_source_to_forecast(self) -> None:
        conn = _RecordingConnection(fetch_results=[[]])

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await top_errors(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
                metric="avg_temp",
                limit=20,
                source="  ",
                horizon_days=None,
            )

        self.assertEqual(response["source"], "forecast")
        query, args = conn.fetch_calls[0]
        self.assertNotIn("source =", query)
        self.assertEqual(args, (date(2026, 7, 1), date(2026, 7, 10), 20))

    async def test_top_errors_returns_unique_stations(self) -> None:
        conn = _RecordingConnection(
            fetch_results=[
                [
                    {
                        "station_id": 1,
                        "wmo_index": "24944",
                        "name": "Vitim",
                        "country": "RU",
                        "latitude": 59.45,
                        "longitude": 112.57,
                        "forecast_date": date(2026, 7, 10),
                        "horizon_days": 5,
                        "provider": "open-meteo",
                        "model": "best_match",
                        "source": "forecast",
                        "run_at": None,
                        "forecast_value": -16.4,
                        "actual_value": -41.8,
                        "signed_error": 25.4,
                        "absolute_error": 25.4,
                        "error_rank": 1,
                    }
                ]
            ]
        )

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await top_errors(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
                metric="avg_temp",
                limit=20,
                horizon_days=None,
            )

        self.assertEqual(response["returned"], 1)
        self.assertEqual(response["items"][0]["station_id"], 1)
        query, args = conn.fetch_calls[0]
        self.assertIn("WITH latest_forecast AS", query)
        self.assertIn(", station_top_errors AS", query)
        self.assertIn("SELECT DISTINCT ON (lf.station_id)", query)
        self.assertIn("ORDER BY absolute_error DESC, forecast_date DESC, horizon_days ASC", query)
        self.assertEqual(args, (date(2026, 7, 1), date(2026, 7, 10), 20))

    async def test_analytics_summary_ignores_blank_model_filter(self) -> None:
        conn = _RecordingConnection(
            fetch_results=[[]],
            fetchrow_results=[
                {"stations_total": 0, "actual_rows": 0, "forecast_rows": 0, "atm8c_rows": 0, "srok8c_rows": 0},
            ]
        )

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await analytics_summary(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
                model="",
                source="",
                horizon_days=None,
        )

        self.assertIsNone(response["model"])
        self.assertEqual(response["source"], "forecast")
        metric_query, metric_args = conn.fetch_calls[0]
        totals_query, totals_args = conn.fetchrow_calls[0]
        self.assertNotIn("model = ", metric_query)
        self.assertNotIn("fr.model = ", totals_query)
        self.assertNotIn("source =", metric_query)
        self.assertNotIn("COALESCE(fr.request_payload->>'source', 'forecast') =", totals_query)
        self.assertEqual(metric_args, (date(2026, 7, 1), date(2026, 7, 10)))
        self.assertEqual(totals_args, (date(2026, 7, 1), date(2026, 7, 10)))

    async def test_station_series_keeps_horizon_model_and_source_dimensions(self) -> None:
        conn = _RecordingConnection(
            fetchrow_results=[{"id": 1, "wmo_index": "12345", "name": "Test", "country": "RU", "latitude": 1, "longitude": 2}],
            fetch_results=[[{"observation_date": date(2026, 7, 1), "horizon_days": 2, "source": "previous_runs"}]],
        )

        with (
            patch("skycast.main.get_pool", return_value=_FakePool(conn)),
            patch("skycast.main._resolve_station_id", return_value=1),
        ):
            response = await station_series(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
                station_id=1,
                model="best_match",
                source="previous_runs",
                horizon_days=2,
            )

        self.assertEqual(response["returned"], 1)
        query, args = conn.fetch_calls[0]
        self.assertIn(f"DISTINCT ON ({latest_forecast_identity_sql()})", query)
        self.assertIn("'forecast' AS source", query)
        self.assertIn("fv.horizon_days = $5", query)
        self.assertIn(f"ORDER BY {latest_forecast_order_by_sql()}", query)
        self.assertIn("fr.id DESC", query)
        self.assertIn("fv.id DESC", query)
        self.assertEqual(
            args,
            (1, date(2026, 7, 1), date(2026, 7, 2), "best_match", 2),
        )
        self.assertEqual(response["source"], "forecast")

    async def test_station_series_can_skip_forecast_join_for_observations(self) -> None:
        conn = _RecordingConnection(
            fetchrow_results=[{"id": 1, "wmo_index": "12345", "name": "Test", "country": "RU", "latitude": 1, "longitude": 2}],
            fetch_results=[[{"observation_date": date(2026, 7, 1), "actual_avg_temp": 12.3}]],
        )

        with (
            patch("skycast.main.get_pool", return_value=_FakePool(conn)),
            patch("skycast.main._resolve_station_id", return_value=1),
        ):
            response = await station_series(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
                station_id=1,
                include_forecast=False,
            )

        self.assertEqual(response["returned"], 1)
        query, args = conn.fetch_calls[0]
        self.assertNotIn("forecast_values", query)
        self.assertIn("FROM weather_data wd", query)
        self.assertEqual(args, (1, date(2026, 7, 1), date(2026, 7, 2)))

    async def test_forecast_coverage_applies_date_source_model_and_horizon_filters(self) -> None:
        conn = _RecordingConnection(
            fetch_results=[[{"model": "best_match", "source": "previous_runs", "horizon_days": 3, "forecast_rows": 42}]]
        )

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await forecast_coverage(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
                model="best_match",
                source="previous_runs",
                horizon_days=3,
            )

        self.assertEqual(response["returned"], 1)
        query, args = conn.fetch_calls[0]
        self.assertIn("fv.forecast_date >= $1", query)
        self.assertIn("fv.forecast_date <= $2", query)
        self.assertIn("fr.model = $3", query)
        self.assertNotIn("COALESCE(fr.request_payload->>'source', 'forecast') =", query)
        self.assertIn("fv.horizon_days = $4", query)
        self.assertEqual(
            args,
            (date(2026, 7, 1), date(2026, 7, 31), "best_match", 3),
        )
        self.assertEqual(response["source"], "forecast")

    async def test_forecast_runs_ignores_blank_source_filter(self) -> None:
        conn = _RecordingConnection(fetch_results=[[{"id": 9}]])

        with patch("skycast.main.get_pool", return_value=_FakePool(conn)):
            response = await list_forecast_runs(
                limit=5,
                status="",
                model=" ",
                source="",
                horizon_days=None,
            )

        self.assertEqual(response["returned"], 1)
        query, args = conn.fetch_calls[0]
        self.assertNotIn("fr.status =", query)
        self.assertNotIn("fr.model =", query)
        self.assertNotIn("COALESCE(fr.request_payload->>'source', 'forecast') =", query)
        self.assertEqual(args, (5,))

    async def test_forecast_coverage_rejects_reversed_date_range(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await forecast_coverage(
                start_date=date(2026, 7, 10),
                end_date=date(2026, 7, 1),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("end_date must be greater than or equal to start_date", ctx.exception.detail)
