from datetime import UTC, datetime
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from skycast.config import Settings
from skycast.transport_observer import parse_kafka_observation, parse_redis_stream_observation
from skycast.transport_runtime import (
    TransportObservation,
    load_transport_runtime_snapshot,
    record_observer_heartbeat,
    record_published_event,
    record_transport_observation,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.stream_lengths: dict[str, int] = {}

    async def hset(self, key: str, mapping: dict[str, str]):
        self.hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def hincrby(self, key: str, field: str, amount: int):
        current = int(self.hashes.setdefault(key, {}).get(field, "0"))
        self.hashes[key][field] = str(current + amount)
        return current + amount

    async def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    async def lpush(self, key: str, value: str):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def ltrim(self, key: str, start: int, end: int):
        items = self.lists.get(key, [])
        if end < 0:
            self.lists[key] = items[start:]
        else:
            self.lists[key] = items[start : end + 1]
        return True

    async def lrange(self, key: str, start: int, end: int):
        items = self.lists.get(key, [])
        if end < 0:
            return items[start:]
        return items[start : end + 1]

    async def expire(self, key: str, ttl: int):
        return True

    async def xlen(self, key: str):
        return self.stream_lengths.get(key, 0)


class TransportRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_snapshot_contains_publish_and_audit_data(self) -> None:
        fake_redis = _FakeRedis()
        fake_redis.stream_lengths["skycast.forecast.accepted"] = 3
        test_settings = Settings(
            database_url="postgresql://test",
            transport_topics=("forecast.accepted",),
            transport_recent_events_limit=10,
            transport_event_ttl_seconds=3600,
        )

        with patch("skycast.transport_runtime.settings", test_settings), patch(
            "skycast.transport_observer.settings",
            test_settings,
        ):
            await record_published_event(
                fake_redis,
                topic="forecast.accepted",
                message_id=15,
                message_key="forecast.accepted:15",
                aggregate_key="7",
                attempts=1,
                redis_stream="skycast.forecast.accepted",
                redis_entry_id="1710000000000-0",
                kafka_topic="skycast.forecast.accepted",
                kafka_partition=0,
                kafka_offset=21,
            )
            await record_transport_observation(
                fake_redis,
                TransportObservation(
                    source="kafka",
                    topic="forecast.accepted",
                    message_key="forecast.accepted:15",
                    message_id=15,
                    aggregate_key="7",
                    payload={"forecast_date": "2026-07-10"},
                    attempts=1,
                    created_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC).isoformat(),
                    observed_at=datetime(2026, 7, 8, 12, 1, tzinfo=UTC).isoformat(),
                    kafka_topic="skycast.forecast.accepted",
                    kafka_partition=0,
                    kafka_offset=21,
                ),
            )
            await record_observer_heartbeat(
                fake_redis,
                status="running",
                worker_name="transport-observer",
                kafka_messages_total=1,
                redis_stream_messages_total=0,
            )

            snapshot = await load_transport_runtime_snapshot(fake_redis)

        self.assertEqual(snapshot["publisher"]["counters"]["published_total"], 1)
        self.assertEqual(snapshot["audit"]["stats"]["observed_total"], 1)
        self.assertEqual(snapshot["redis_stream_lengths"]["skycast.forecast.accepted"], 3)
        self.assertEqual(snapshot["publisher"]["recent_success"][0]["message_id"], 15)
        self.assertEqual(snapshot["audit"]["recent_events"][0]["source"], "kafka")


class TransportObserverParsingTests(unittest.TestCase):
    def test_parse_redis_stream_observation_reads_outbox_fields(self) -> None:
        observation = parse_redis_stream_observation(
            "skycast.forecast.accepted",
            "1710000000000-0",
            {
                "message_id": "10",
                "topic": "forecast.accepted",
                "message_key": "forecast.accepted:10",
                "aggregate_key": "7",
                "attempts": "2",
                "created_at": "2026-07-08T12:30:00+00:00",
                "payload_json": json.dumps({"forecast_date": "2026-07-10"}),
            },
        )

        self.assertEqual(observation.source, "redis_stream")
        self.assertEqual(observation.message_id, 10)
        self.assertEqual(observation.payload, {"forecast_date": "2026-07-10"})

    def test_parse_kafka_observation_reads_headers_and_payload(self) -> None:
        record = SimpleNamespace(
            topic="skycast.telemetry.accepted",
            partition=2,
            offset=9,
            headers=[
                ("topic", b"telemetry.accepted"),
                ("message_key", b"telemetry.accepted:9"),
                ("aggregate_key", b"24944"),
            ],
            value=json.dumps(
                {
                    "message_id": 9,
                    "topic": "telemetry.accepted",
                    "message_key": "telemetry.accepted:9",
                    "aggregate_key": "24944",
                    "attempts": 1,
                    "created_at": "2026-07-08T12:30:00+00:00",
                    "payload": {"wmo_index": "24944"},
                }
            ).encode("utf-8"),
        )

        observation = parse_kafka_observation(record)

        self.assertEqual(observation.source, "kafka")
        self.assertEqual(observation.topic, "telemetry.accepted")
        self.assertEqual(observation.kafka_partition, 2)
        self.assertEqual(observation.payload, {"wmo_index": "24944"})
