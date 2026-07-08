"""Redis-backed transport runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from typing import Any

from skycast.config import settings
from skycast.transport import configured_transport_topics, redis_stream_name

logger = logging.getLogger(__name__)

TRANSPORT_PUBLISHER_HEARTBEAT_KEY = "skycast:transport:publisher:heartbeat"
TRANSPORT_PUBLISHER_COUNTERS_KEY = "skycast:transport:publisher:counters"
TRANSPORT_PUBLISHER_RECENT_SUCCESS_KEY = "skycast:transport:publisher:recent-success"
TRANSPORT_PUBLISHER_RECENT_FAILURE_KEY = "skycast:transport:publisher:recent-failure"
TRANSPORT_AUDIT_HEARTBEAT_KEY = "skycast:transport:audit:heartbeat"
TRANSPORT_AUDIT_STATS_KEY = "skycast:transport:audit:stats"
TRANSPORT_AUDIT_RECENT_KEY = "skycast:transport:audit:recent"
TRANSPORT_AUDIT_STREAM_OFFSETS_KEY = "skycast:transport:audit:stream-offsets"
TRANSPORT_AUDIT_KAFKA_OFFSETS_KEY = "skycast:transport:audit:kafka-offsets"
TRANSPORT_AUDIT_EVENT_KEY_PREFIX = "skycast:transport:audit:event"


@dataclass(frozen=True)
class TransportObservation:
    source: str
    topic: str
    message_key: str
    message_id: int | None
    aggregate_key: str | None
    payload: dict[str, Any] | None
    attempts: int | None
    created_at: str | None
    observed_at: str
    redis_stream: str | None = None
    redis_entry_id: str | None = None
    kafka_topic: str | None = None
    kafka_partition: int | None = None
    kafka_offset: int | None = None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _event_key(message_key: str) -> str:
    return f"{TRANSPORT_AUDIT_EVENT_KEY_PREFIX}:{message_key}"


def _parse_scalar(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _parse_hash_values(raw: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in raw.items():
        parsed[key] = _parse_scalar(value)
    return parsed


def _heartbeat_age_seconds(raw_timestamp: str | None) -> float | None:
    if not raw_timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(raw_timestamp)
    except ValueError:
        return None
    return max((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds(), 0.0)


async def record_publisher_heartbeat(
    client,
    *,
    status: str,
    worker_name: str,
    spool_backlog_total: int,
    last_error: str | None = None,
) -> None:
    mapping = {
        "status": status,
        "worker_name": worker_name,
        "updated_at": _utc_now_iso(),
        "spool_backlog_total": str(spool_backlog_total),
    }
    if last_error:
        mapping["last_error"] = last_error
    try:
        await client.hset(TRANSPORT_PUBLISHER_HEARTBEAT_KEY, mapping=mapping)
    except Exception:
        logger.exception("transport_publisher_heartbeat_failed")


async def record_published_event(
    client,
    *,
    topic: str,
    message_id: int,
    message_key: str,
    aggregate_key: str | None,
    attempts: int,
    redis_stream: str,
    redis_entry_id: str,
    kafka_topic: str,
    kafka_partition: int,
    kafka_offset: int,
) -> None:
    observed_at = _utc_now_iso()
    payload = {
        "topic": topic,
        "message_id": message_id,
        "message_key": message_key,
        "aggregate_key": aggregate_key,
        "attempts": attempts,
        "redis_stream": redis_stream,
        "redis_entry_id": redis_entry_id,
        "kafka_topic": kafka_topic,
        "kafka_partition": kafka_partition,
        "kafka_offset": kafka_offset,
        "published_at": observed_at,
    }
    try:
        await client.hincrby(TRANSPORT_PUBLISHER_COUNTERS_KEY, "published_total", 1)
        await client.hincrby(TRANSPORT_PUBLISHER_COUNTERS_KEY, "redis_stream_published_total", 1)
        await client.hincrby(TRANSPORT_PUBLISHER_COUNTERS_KEY, "kafka_published_total", 1)
        await client.hincrby(TRANSPORT_PUBLISHER_COUNTERS_KEY, f"topic:{topic}:published_total", 1)
        await client.hset(
            TRANSPORT_PUBLISHER_HEARTBEAT_KEY,
            mapping={
                "status": "running",
                "last_published_at": observed_at,
                "last_topic": topic,
                "last_message_id": str(message_id),
            },
        )
        await client.lpush(TRANSPORT_PUBLISHER_RECENT_SUCCESS_KEY, _compact_json(payload))
        await client.ltrim(TRANSPORT_PUBLISHER_RECENT_SUCCESS_KEY, 0, settings.transport_recent_events_limit - 1)
    except Exception:
        logger.exception("transport_publish_event_record_failed", extra={"topic": topic, "message_id": message_id})


async def record_publish_failure(
    client,
    *,
    topic: str,
    message_id: int,
    message_key: str,
    attempts: int,
    error_text: str,
) -> None:
    failed_at = _utc_now_iso()
    payload = {
        "topic": topic,
        "message_id": message_id,
        "message_key": message_key,
        "attempts": attempts,
        "error": error_text,
        "failed_at": failed_at,
    }
    try:
        await client.hincrby(TRANSPORT_PUBLISHER_COUNTERS_KEY, "failed_total", 1)
        await client.hincrby(TRANSPORT_PUBLISHER_COUNTERS_KEY, f"topic:{topic}:failed_total", 1)
        await client.hset(
            TRANSPORT_PUBLISHER_HEARTBEAT_KEY,
            mapping={
                "status": "degraded",
                "last_error": error_text,
                "last_error_at": failed_at,
                "last_failed_topic": topic,
                "last_failed_message_id": str(message_id),
            },
        )
        await client.lpush(TRANSPORT_PUBLISHER_RECENT_FAILURE_KEY, _compact_json(payload))
        await client.ltrim(TRANSPORT_PUBLISHER_RECENT_FAILURE_KEY, 0, settings.transport_recent_events_limit - 1)
    except Exception:
        logger.exception("transport_publish_failure_record_failed", extra={"topic": topic, "message_id": message_id})


async def record_observer_heartbeat(
    client,
    *,
    status: str,
    worker_name: str,
    kafka_messages_total: int,
    redis_stream_messages_total: int,
    last_error: str | None = None,
) -> None:
    mapping = {
        "status": status,
        "worker_name": worker_name,
        "updated_at": _utc_now_iso(),
        "kafka_messages_total": str(kafka_messages_total),
        "redis_stream_messages_total": str(redis_stream_messages_total),
    }
    if last_error:
        mapping["last_error"] = last_error
    try:
        await client.hset(TRANSPORT_AUDIT_HEARTBEAT_KEY, mapping=mapping)
    except Exception:
        logger.exception("transport_observer_heartbeat_failed")


async def record_transport_observation(client, observation: TransportObservation) -> None:
    event_mapping = {
        "topic": observation.topic,
        "message_key": observation.message_key,
        "last_source": observation.source,
    }
    if observation.message_id is not None:
        event_mapping["message_id"] = str(observation.message_id)
    if observation.aggregate_key is not None:
        event_mapping["aggregate_key"] = observation.aggregate_key
    if observation.payload is not None:
        event_mapping["payload_json"] = _compact_json(observation.payload)
    if observation.attempts is not None:
        event_mapping["attempts"] = str(observation.attempts)
    if observation.created_at is not None:
        event_mapping["created_at"] = observation.created_at
    if observation.source == "redis_stream":
        event_mapping["redis_stream_observed_at"] = observation.observed_at
    if observation.redis_stream is not None:
        event_mapping["redis_stream"] = observation.redis_stream
    if observation.redis_entry_id is not None:
        event_mapping["redis_entry_id"] = observation.redis_entry_id
    if observation.source == "kafka":
        event_mapping["kafka_observed_at"] = observation.observed_at
    if observation.kafka_topic is not None:
        event_mapping["kafka_topic"] = observation.kafka_topic
    if observation.kafka_partition is not None:
        event_mapping["kafka_partition"] = str(observation.kafka_partition)
    if observation.kafka_offset is not None:
        event_mapping["kafka_offset"] = str(observation.kafka_offset)

    recent_payload = {
        "source": observation.source,
        "topic": observation.topic,
        "message_key": observation.message_key,
        "message_id": observation.message_id,
        "observed_at": observation.observed_at,
        "redis_stream": observation.redis_stream,
        "redis_entry_id": observation.redis_entry_id,
        "kafka_topic": observation.kafka_topic,
        "kafka_partition": observation.kafka_partition,
        "kafka_offset": observation.kafka_offset,
    }
    try:
        await client.hset(_event_key(observation.message_key), mapping=event_mapping)
        await client.expire(_event_key(observation.message_key), settings.transport_event_ttl_seconds)
        await client.hincrby(TRANSPORT_AUDIT_STATS_KEY, "observed_total", 1)
        await client.hincrby(TRANSPORT_AUDIT_STATS_KEY, f"source:{observation.source}:observed_total", 1)
        await client.hincrby(TRANSPORT_AUDIT_STATS_KEY, f"topic:{observation.topic}:observed_total", 1)
        await client.hincrby(
            TRANSPORT_AUDIT_STATS_KEY,
            f"source_topic:{observation.source}:{observation.topic}:observed_total",
            1,
        )
        await client.lpush(TRANSPORT_AUDIT_RECENT_KEY, _compact_json(recent_payload))
        await client.ltrim(TRANSPORT_AUDIT_RECENT_KEY, 0, settings.transport_recent_events_limit - 1)
    except Exception:
        logger.exception(
            "transport_observation_record_failed",
            extra={"source": observation.source, "topic": observation.topic, "message_key": observation.message_key},
        )


async def load_stream_offsets(client) -> dict[str, str]:
    try:
        return await client.hgetall(TRANSPORT_AUDIT_STREAM_OFFSETS_KEY)
    except Exception:
        logger.exception("transport_stream_offsets_read_failed")
        return {}


async def store_stream_offset(client, *, stream_name: str, entry_id: str) -> None:
    try:
        await client.hset(TRANSPORT_AUDIT_STREAM_OFFSETS_KEY, mapping={stream_name: entry_id})
    except Exception:
        logger.exception("transport_stream_offset_write_failed", extra={"stream_name": stream_name, "entry_id": entry_id})


async def store_kafka_offset(client, *, topic: str, partition: int, offset: int) -> None:
    try:
        await client.hset(TRANSPORT_AUDIT_KAFKA_OFFSETS_KEY, mapping={f"{topic}:{partition}": str(offset)})
    except Exception:
        logger.exception("transport_kafka_offset_write_failed", extra={"topic": topic, "partition": partition})


async def load_transport_runtime_snapshot(client) -> dict[str, Any]:
    publisher_heartbeat_raw = await client.hgetall(TRANSPORT_PUBLISHER_HEARTBEAT_KEY)
    publisher_counters_raw = await client.hgetall(TRANSPORT_PUBLISHER_COUNTERS_KEY)
    audit_heartbeat_raw = await client.hgetall(TRANSPORT_AUDIT_HEARTBEAT_KEY)
    audit_stats_raw = await client.hgetall(TRANSPORT_AUDIT_STATS_KEY)
    stream_offsets = await client.hgetall(TRANSPORT_AUDIT_STREAM_OFFSETS_KEY)
    kafka_offsets = await client.hgetall(TRANSPORT_AUDIT_KAFKA_OFFSETS_KEY)
    publisher_recent_success = [
        json.loads(item)
        for item in await client.lrange(TRANSPORT_PUBLISHER_RECENT_SUCCESS_KEY, 0, settings.transport_recent_events_limit - 1)
    ]
    publisher_recent_failure = [
        json.loads(item)
        for item in await client.lrange(TRANSPORT_PUBLISHER_RECENT_FAILURE_KEY, 0, settings.transport_recent_events_limit - 1)
    ]
    audit_recent = [
        json.loads(item)
        for item in await client.lrange(TRANSPORT_AUDIT_RECENT_KEY, 0, settings.transport_recent_events_limit - 1)
    ]

    stream_lengths: dict[str, int] = {}
    for topic in configured_transport_topics(settings):
        stream_name = redis_stream_name(settings.redis_stream_prefix, topic)
        try:
            stream_lengths[stream_name] = int(await client.xlen(stream_name))
        except Exception:
            stream_lengths[stream_name] = -1

    publisher_heartbeat = _parse_hash_values(publisher_heartbeat_raw)
    audit_heartbeat = _parse_hash_values(audit_heartbeat_raw)
    publisher_heartbeat["age_seconds"] = _heartbeat_age_seconds(publisher_heartbeat_raw.get("updated_at"))
    audit_heartbeat["age_seconds"] = _heartbeat_age_seconds(audit_heartbeat_raw.get("updated_at"))

    return {
        "publisher": {
            "heartbeat": publisher_heartbeat,
            "counters": _parse_hash_values(publisher_counters_raw),
            "recent_success": publisher_recent_success,
            "recent_failure": publisher_recent_failure,
        },
        "audit": {
            "heartbeat": audit_heartbeat,
            "stats": _parse_hash_values(audit_stats_raw),
            "recent_events": audit_recent,
            "stream_offsets": stream_offsets,
            "kafka_offsets": _parse_hash_values(kafka_offsets),
        },
        "redis_stream_lengths": stream_lengths,
    }
