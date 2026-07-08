"""Consume Kafka and Redis Streams into a Redis-backed transport audit feed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import logging
from typing import Any

from skycast.config import settings
from skycast.logging_utils import configure_logging
from skycast.transport import (
    build_kafka_consumer_kwargs,
    configured_transport_topics,
    kafka_topic_name,
    load_aiokafka_consumer,
    load_redis_module,
    redis_stream_name,
)
from skycast.transport_runtime import (
    TransportObservation,
    load_stream_offsets,
    record_observer_heartbeat,
    record_transport_observation,
    store_kafka_offset,
    store_stream_offset,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_payload_json(raw_value: str | bytes | dict[str, Any] | None) -> dict[str, Any] | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8")
    parsed = json.loads(raw_value)
    if not isinstance(parsed, dict):
        raise ValueError("transport payload must be a JSON object")
    return parsed


def _coerce_int(raw_value: str | bytes | int | None) -> int | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8")
    return int(raw_value)


def _topic_from_prefixed_name(prefixed_topic: str) -> str:
    prefix = f"{settings.kafka_topic_prefix}."
    if prefixed_topic.startswith(prefix):
        return prefixed_topic[len(prefix) :]
    return prefixed_topic


def parse_redis_stream_observation(stream_name: str, entry_id: str, fields: dict[str, Any]) -> TransportObservation:
    payload = _normalize_payload_json(fields.get("payload_json"))
    return TransportObservation(
        source="redis_stream",
        topic=str(fields["topic"]),
        message_key=str(fields["message_key"]),
        message_id=_coerce_int(fields.get("message_id")),
        aggregate_key=str(fields["aggregate_key"]) if fields.get("aggregate_key") is not None else None,
        payload=payload,
        attempts=_coerce_int(fields.get("attempts")),
        created_at=str(fields["created_at"]) if fields.get("created_at") is not None else None,
        observed_at=_utc_now_iso(),
        redis_stream=stream_name,
        redis_entry_id=entry_id,
    )


def parse_kafka_observation(record: Any) -> TransportObservation:
    payload = _normalize_payload_json(record.value)
    headers = {
        key.decode("utf-8") if isinstance(key, bytes) else key: value.decode("utf-8") if isinstance(value, bytes) else value
        for key, value in (record.headers or [])
    }
    return TransportObservation(
        source="kafka",
        topic=str(headers.get("topic") or payload.get("topic") or _topic_from_prefixed_name(record.topic)),
        message_key=str(headers.get("message_key") or payload.get("message_key")),
        message_id=_coerce_int(payload.get("message_id")),
        aggregate_key=str(headers["aggregate_key"]) if headers.get("aggregate_key") is not None else payload.get("aggregate_key"),
        payload=payload.get("payload"),
        attempts=_coerce_int(payload.get("attempts")),
        created_at=payload.get("created_at"),
        observed_at=_utc_now_iso(),
        kafka_topic=record.topic,
        kafka_partition=record.partition,
        kafka_offset=record.offset,
    )


async def _consume_redis_streams_once(client, cursors: dict[str, str]) -> int:
    stream_names = {
        redis_stream_name(settings.redis_stream_prefix, topic): cursors.get(
            redis_stream_name(settings.redis_stream_prefix, topic),
            "0-0",
        )
        for topic in configured_transport_topics(settings)
    }
    results = await client.xread(
        streams=stream_names,
        count=settings.transport_observer_batch_size,
        block=int(settings.transport_observer_poll_seconds * 1000),
    )
    processed = 0
    if not results:
        return processed
    for stream_name, entries in results:
        for entry_id, fields in entries:
            observation = parse_redis_stream_observation(stream_name, entry_id, fields)
            await record_transport_observation(client, observation)
            await store_stream_offset(client, stream_name=stream_name, entry_id=entry_id)
            cursors[stream_name] = entry_id
            processed += 1
    return processed


async def _consume_kafka_once(client, consumer) -> int:
    batches = await consumer.getmany(
        timeout_ms=int(settings.transport_observer_poll_seconds * 1000),
        max_records=settings.transport_observer_batch_size,
    )
    processed = 0
    if not batches:
        return processed
    for _, records in batches.items():
        for record in records:
            observation = parse_kafka_observation(record)
            await record_transport_observation(client, observation)
            await store_kafka_offset(client, topic=record.topic, partition=record.partition, offset=record.offset)
            processed += 1
    if processed:
        await consumer.commit()
    return processed


async def run_transport_observer() -> None:
    settings.validate()
    redis_module = load_redis_module()
    consumer_cls = load_aiokafka_consumer()
    redis_client = redis_module.from_url(settings.redis_url, decode_responses=True)
    kafka_topics = tuple(
        kafka_topic_name(settings.kafka_topic_prefix, topic)
        for topic in configured_transport_topics(settings)
    )
    consumer = consumer_cls(
        *kafka_topics,
        **build_kafka_consumer_kwargs(
            settings,
            client_id=settings.transport_observer_client_id,
            group_id=settings.transport_observer_consumer_group,
        ),
    )
    await redis_client.ping()
    await consumer.start()
    cursors = await load_stream_offsets(redis_client)
    kafka_messages_total = 0
    redis_messages_total = 0
    await record_observer_heartbeat(
        redis_client,
        status="running",
        worker_name=settings.transport_observer_client_id,
        kafka_messages_total=0,
        redis_stream_messages_total=0,
    )
    try:
        while True:
            try:
                consumed_kafka, consumed_redis = await asyncio.gather(
                    _consume_kafka_once(redis_client, consumer),
                    _consume_redis_streams_once(redis_client, cursors),
                )
                kafka_messages_total += consumed_kafka
                redis_messages_total += consumed_redis
                await record_observer_heartbeat(
                    redis_client,
                    status="running",
                    worker_name=settings.transport_observer_client_id,
                    kafka_messages_total=kafka_messages_total,
                    redis_stream_messages_total=redis_messages_total,
                )
            except Exception as exc:
                logger.exception("transport_observer_iteration_failed")
                await record_observer_heartbeat(
                    redis_client,
                    status="degraded",
                    worker_name=settings.transport_observer_client_id,
                    kafka_messages_total=kafka_messages_total,
                    redis_stream_messages_total=redis_messages_total,
                    last_error=str(exc),
                )
                await asyncio.sleep(settings.transport_observer_poll_seconds)
    finally:
        await consumer.stop()
        await redis_client.aclose()


def main() -> None:
    configure_logging(service_name=settings.app_name, json_logs=settings.log_json, level=settings.log_level)
    asyncio.run(run_transport_observer())


if __name__ == "__main__":
    main()
