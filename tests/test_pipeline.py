from datetime import date
from decimal import Decimal
import unittest

from skycast.clients import ForecastRecord
from skycast.pipeline import (
    build_forecast_dedupe_key,
    build_forecast_raw_payload,
    build_outbox_message_key,
    build_telemetry_dedupe_key,
    json_dumps_payload,
)


class PipelineHelpersTests(unittest.TestCase):
    def test_telemetry_dedupe_key_is_stable(self) -> None:
        self.assertEqual(
            build_telemetry_dedupe_key("12345", date(2026, 7, 8)),
            "telemetry:12345:2026-07-08",
        )

    def test_forecast_dedupe_key_is_stable(self) -> None:
        self.assertEqual(
            build_forecast_dedupe_key(7, 42, date(2026, 7, 10)),
            "forecast:7:42:2026-07-10",
        )

    def test_outbox_message_key_prefixes_topic(self) -> None:
        self.assertEqual(
            build_outbox_message_key("forecast.accepted", "forecast:7:42:2026-07-10"),
            "forecast.accepted:forecast:7:42:2026-07-10",
        )

    def test_forecast_payload_is_json_ready(self) -> None:
        payload = build_forecast_raw_payload(
            ForecastRecord(
                forecast_date=date(2026, 7, 11),
                horizon_days=3,
                avg_temp=Decimal("18.5"),
                min_temp=Decimal("12.1"),
                max_temp=Decimal("22.9"),
                precipitation=Decimal("4.0"),
                max_wind_speed=Decimal("10.3"),
            )
        )

        self.assertEqual(payload["forecast_date"], "2026-07-11")
        self.assertEqual(payload["avg_temp"], 18.5)
        self.assertEqual(payload["precipitation"], 4.0)

    def test_json_payload_dump_is_compact_and_ascii(self) -> None:
        self.assertEqual(
            json_dumps_payload({"station": "Moscow", "value": 1}),
            '{"station":"Moscow","value":1}',
        )
