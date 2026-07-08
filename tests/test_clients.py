from decimal import Decimal
import unittest

from skycast.clients import _aggregate_previous_runs_daily


class PreviousRunsAggregationTests(unittest.TestCase):
    def test_aggregate_previous_runs_daily_rolls_hourly_values_up(self) -> None:
        payload = {
            "hourly": {
                "time": [
                    "2026-07-06T00:00",
                    "2026-07-06T12:00",
                    "2026-07-07T00:00",
                    "2026-07-07T12:00",
                ],
                "temperature_2m_previous_day1": [10.0, 14.0, 9.0, 15.0],
                "precipitation_previous_day1": [1.0, 2.5, 0.0, 3.0],
                "wind_speed_10m_previous_day1": [12.0, 18.0, 7.0, 11.0],
            }
        }

        records = _aggregate_previous_runs_daily(payload, horizon_days=1)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].forecast_date.isoformat(), "2026-07-06")
        self.assertEqual(records[0].horizon_days, 1)
        self.assertEqual(records[0].avg_temp, Decimal("12.0"))
        self.assertEqual(records[0].min_temp, Decimal("10.0"))
        self.assertEqual(records[0].max_temp, Decimal("14.0"))
        self.assertEqual(records[0].precipitation, Decimal("3.5"))
        self.assertEqual(records[0].max_wind_speed, Decimal("18.0"))

        self.assertEqual(records[1].forecast_date.isoformat(), "2026-07-07")
        self.assertEqual(records[1].avg_temp, Decimal("12.0"))
        self.assertEqual(records[1].min_temp, Decimal("9.0"))
        self.assertEqual(records[1].max_temp, Decimal("15.0"))
        self.assertEqual(records[1].precipitation, Decimal("3.0"))
        self.assertEqual(records[1].max_wind_speed, Decimal("11.0"))

    def test_aggregate_previous_runs_daily_keeps_missing_metric_as_none(self) -> None:
        payload = {
            "hourly": {
                "time": ["2026-07-06T00:00", "2026-07-06T12:00"],
                "temperature_2m_previous_day3": [None, None],
                "precipitation_previous_day3": [0.2, None],
                "wind_speed_10m_previous_day3": [None, None],
            }
        }

        records = _aggregate_previous_runs_daily(payload, horizon_days=3)

        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].avg_temp)
        self.assertIsNone(records[0].min_temp)
        self.assertIsNone(records[0].max_temp)
        self.assertEqual(records[0].precipitation, Decimal("0.2"))
        self.assertIsNone(records[0].max_wind_speed)

    def test_aggregate_previous_runs_daily_skips_fully_empty_days(self) -> None:
        payload = {
            "hourly": {
                "time": ["2026-07-06T00:00", "2026-07-06T12:00"],
                "temperature_2m_previous_day2": [None, None],
                "precipitation_previous_day2": [None, None],
                "wind_speed_10m_previous_day2": [None, None],
            }
        }

        records = _aggregate_previous_runs_daily(payload, horizon_days=2)

        self.assertEqual(records, [])
