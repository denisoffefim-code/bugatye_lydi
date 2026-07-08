import unittest

from fastapi import HTTPException

from skycast.main import _determine_forecast_run_status, list_stations


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

