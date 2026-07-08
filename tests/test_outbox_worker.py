from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from skycast.config import Settings
from skycast.outbox_worker import (
    LocalOutboxSpool,
    OutboxMessage,
    build_kafka_producer_kwargs,
    build_kafka_payload,
    build_stream_fields,
    compute_retry_delay_seconds,
    deserialize_outbox_message,
    kafka_topic_name,
    normalize_outbox_payload,
    redis_stream_name,
    serialize_outbox_message,
)


class OutboxWorkerHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.message = OutboxMessage(
            id=10,
            topic="forecast.accepted",
            message_key="forecast.accepted:forecast:7:42:2026-07-10",
            aggregate_key="7",
            payload={"forecast_date": "2026-07-10", "avg_temp": 17.4},
            attempts=2,
            created_at=datetime(2026, 7, 8, 12, 30, tzinfo=UTC),
        )

    def test_redis_stream_name_is_stable(self) -> None:
        self.assertEqual(
            redis_stream_name("skycast", "forecast.accepted"),
            "skycast.forecast.accepted",
        )

    def test_kafka_topic_name_is_stable(self) -> None:
        self.assertEqual(
            kafka_topic_name("skycast", "telemetry.accepted"),
            "skycast.telemetry.accepted",
        )

    def test_retry_delay_grows_exponentially_with_cap(self) -> None:
        self.assertEqual(
            compute_retry_delay_seconds(1, base_seconds=5, max_delay_seconds=300),
            5,
        )
        self.assertEqual(
            compute_retry_delay_seconds(4, base_seconds=5, max_delay_seconds=300),
            40,
        )
        self.assertEqual(
            compute_retry_delay_seconds(12, base_seconds=5, max_delay_seconds=300),
            300,
        )

    def test_stream_fields_are_stringified(self) -> None:
        fields = build_stream_fields(self.message)

        self.assertEqual(fields["message_id"], "10")
        self.assertEqual(fields["attempts"], "2")
        self.assertEqual(fields["topic"], "forecast.accepted")
        self.assertEqual(
            json.loads(fields["payload_json"]),
            {"forecast_date": "2026-07-10", "avg_temp": 17.4},
        )

    def test_kafka_payload_contains_envelope(self) -> None:
        payload = json.loads(build_kafka_payload(self.message).decode("utf-8"))

        self.assertEqual(payload["message_id"], 10)
        self.assertEqual(payload["message_key"], self.message.message_key)
        self.assertEqual(payload["aggregate_key"], "7")
        self.assertEqual(payload["payload"]["avg_temp"], 17.4)

    def test_message_serialization_roundtrip_is_stable(self) -> None:
        restored = deserialize_outbox_message(serialize_outbox_message(self.message))

        self.assertEqual(restored, self.message)

    def test_normalize_outbox_payload_accepts_json_string(self) -> None:
        payload = normalize_outbox_payload('{\"forecast_date\":\"2026-07-10\",\"avg_temp\":17.4}')

        self.assertEqual(
            payload,
            {"forecast_date": "2026-07-10", "avg_temp": 17.4},
        )

    def test_deserialize_outbox_message_accepts_json_string_payload(self) -> None:
        restored = deserialize_outbox_message(
            {
                "id": 10,
                "topic": "forecast.accepted",
                "message_key": "forecast.accepted:forecast:7:42:2026-07-10",
                "aggregate_key": "7",
                "payload": '{\"forecast_date\":\"2026-07-10\",\"avg_temp\":17.4}',
                "attempts": 2,
                "created_at": "2026-07-08T12:30:00+00:00",
            }
        )

        self.assertEqual(restored, self.message)

    def test_kafka_producer_kwargs_support_plaintext_defaults(self) -> None:
        settings = Settings(database_url="postgresql://test", kafka_bootstrap_servers="kafka:9092")

        kwargs = build_kafka_producer_kwargs(settings)

        self.assertEqual(kwargs["bootstrap_servers"], "kafka:9092")
        self.assertEqual(kwargs["security_protocol"], "PLAINTEXT")
        self.assertNotIn("ssl_context", kwargs)
        self.assertNotIn("sasl_mechanism", kwargs)

    def test_kafka_producer_kwargs_support_sasl_ssl(self) -> None:
        settings = Settings(
            database_url="postgresql://test",
            kafka_bootstrap_servers="kafka:9092",
            kafka_security_protocol="SASL_SSL",
            kafka_ssl_cafile="C:/certs/yandex-ca.pem",
            kafka_sasl_mechanism="SCRAM-SHA-512",
            kafka_sasl_username="user",
            kafka_sasl_password="password",
        )

        ssl_context = Mock()
        with patch("skycast.outbox_worker.ssl.create_default_context", return_value=ssl_context):
            kwargs = build_kafka_producer_kwargs(settings)

        self.assertEqual(kwargs["security_protocol"], "SASL_SSL")
        self.assertEqual(kwargs["sasl_mechanism"], "SCRAM-SHA-512")
        self.assertEqual(kwargs["sasl_plain_username"], "user")
        self.assertEqual(kwargs["sasl_plain_password"], "password")
        self.assertIs(kwargs["ssl_context"], ssl_context)

    def test_local_spool_writes_reads_and_deletes_message(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            spool = LocalOutboxSpool(tmp_dir, enabled=True)

            spool_path = spool.write_message(self.message, error_text="broker offline")

            self.assertIsNotNone(spool_path)
            self.assertTrue(Path(spool_path).exists())

            records = spool.read_messages()

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0][1], self.message)

            spool.delete_message(self.message.id)
            self.assertEqual(spool.read_messages(), [])
