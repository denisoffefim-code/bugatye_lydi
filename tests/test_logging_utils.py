import json
import logging
import unittest

from skycast.logging_utils import JsonLogFormatter
from skycast.monitoring import RequestMetrics, format_prometheus_metrics


class JsonLogFormatterTests(unittest.TestCase):
    def test_formatter_emits_json_with_extra_fields(self) -> None:
        formatter = JsonLogFormatter(default_fields={"service": "SkyCast Test"})
        record = logging.makeLogRecord(
            {
                "name": "skycast.test",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "msg": "request completed",
                "event": "http_request_completed",
                "request_id": "abc123",
                "status_code": 200,
            }
        )

        payload = json.loads(formatter.format(record))

        self.assertEqual(payload["service"], "SkyCast Test")
        self.assertEqual(payload["message"], "request completed")
        self.assertEqual(payload["event"], "http_request_completed")
        self.assertEqual(payload["request_id"], "abc123")
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["logger"], "skycast.test")


class PrometheusMetricsFormattingTests(unittest.TestCase):
    def test_metrics_include_runtime_gauges_for_ingest_lag(self) -> None:
        request_metrics = RequestMetrics()
        request_metrics.record("GET", "/health", 200, 0.012)

        body = format_prometheus_metrics(
            "SkyCast Test",
            request_metrics,
            {
                "database_up": 1.0,
                "raw_telemetry_oldest_unprocessed_age_seconds": 15.0,
                "raw_forecast_oldest_unprocessed_age_seconds": 25.0,
            },
        )

        self.assertIn('skycast_runtime_gauge{service="SkyCast Test",metric="database_up"} 1.0', body)
        self.assertIn(
            'skycast_runtime_gauge{service="SkyCast Test",metric="raw_telemetry_oldest_unprocessed_age_seconds"} 15.0',
            body,
        )
        self.assertIn(
            'skycast_runtime_gauge{service="SkyCast Test",metric="raw_forecast_oldest_unprocessed_age_seconds"} 25.0',
            body,
        )
