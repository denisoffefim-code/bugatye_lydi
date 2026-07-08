from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from skycast.outbox_worker import (
    LocalOutboxSpool,
    OutboxMessage,
    build_kafka_payload,
    build_stream_fields,
    compute_retry_delay_seconds,
    deserialize_outbox_message,
    kafka_topic_name,
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
