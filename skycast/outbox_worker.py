"""Outbox dispatcher that publishes DB-backed events to Redis Streams."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - helper tests may run without runtime deps
    asyncpg = Any  # type: ignore[assignment]

from skycast.config import settings
from skycast.config import Settings
from skycast.logging_utils import configure_logging

if TYPE_CHECKING:
    from aiokafka import AIOKafkaProducer
    import redis.asyncio as redis_async


logger = logging.getLogger("skycast.outbox")


@dataclass(frozen=True)
class OutboxMessage:
    id: int
    topic: str
    message_key: str
    aggregate_key: str
    payload: dict[str, Any]
    attempts: int
    created_at: datetime


def redis_stream_name(prefix: str, topic: str) -> str:
    return f"{prefix}.{topic}"


def kafka_topic_name(prefix: str, topic: str) -> str:
    return f"{prefix}.{topic}"


def compute_retry_delay_seconds(
    attempts: int,
    *,
    base_seconds: float,
    max_delay_seconds: float,
) -> float:
    multiplier = max(attempts - 1, 0)
    return min(base_seconds * (2**multiplier), max_delay_seconds)


def build_stream_fields(message: OutboxMessage) -> dict[str, str]:
    return {
        "message_id": str(message.id),
        "topic": message.topic,
        "message_key": message.message_key,
        "aggregate_key": message.aggregate_key,
        "attempts": str(message.attempts),
        "created_at": message.created_at.astimezone(UTC).isoformat(),
        "payload_json": json.dumps(message.payload, ensure_ascii=True, sort_keys=True),
    }


def build_kafka_payload(message: OutboxMessage) -> bytes:
    return json.dumps(
        {
            "message_id": message.id,
            "topic": message.topic,
            "message_key": message.message_key,
            "aggregate_key": message.aggregate_key,
            "attempts": message.attempts,
            "created_at": message.created_at.astimezone(UTC).isoformat(),
            "payload": message.payload,
        },
        ensure_ascii=True,
        sort_keys=True,
    ).encode("utf-8")


def serialize_outbox_message(message: OutboxMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "topic": message.topic,
        "message_key": message.message_key,
        "aggregate_key": message.aggregate_key,
        "payload": message.payload,
        "attempts": message.attempts,
        "created_at": message.created_at.astimezone(UTC).isoformat(),
    }


def normalize_outbox_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ValueError("Outbox payload JSON must decode to an object")
        return decoded
    raise TypeError(f"Unsupported outbox payload type: {type(payload).__name__}")


def deserialize_outbox_message(payload: dict[str, Any]) -> OutboxMessage:
    return OutboxMessage(
        id=int(payload["id"]),
        topic=str(payload["topic"]),
        message_key=str(payload["message_key"]),
        aggregate_key=str(payload["aggregate_key"]),
        payload=normalize_outbox_payload(payload["payload"]),
        attempts=int(payload["attempts"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
    )


def load_redis_module():
    try:
        import redis.asyncio as redis_async
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("redis package is required to run the outbox worker") from exc
    return redis_async


def load_aiokafka_producer():
    try:
        from aiokafka import AIOKafkaProducer as producer_cls
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("aiokafka package is required to run the outbox worker") from exc
    return producer_cls


def build_kafka_producer_kwargs(app_settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "bootstrap_servers": app_settings.kafka_bootstrap_servers,
        "client_id": app_settings.kafka_client_id,
        "enable_idempotence": True,
        "security_protocol": app_settings.kafka_security_protocol,
    }
    if (
        app_settings.kafka_ssl_cafile
        or app_settings.kafka_ssl_certfile
        or app_settings.kafka_ssl_keyfile
    ):
        ssl_context = ssl.create_default_context(cafile=app_settings.kafka_ssl_cafile)
        if app_settings.kafka_ssl_certfile and app_settings.kafka_ssl_keyfile:
            ssl_context.load_cert_chain(
                certfile=app_settings.kafka_ssl_certfile,
                keyfile=app_settings.kafka_ssl_keyfile,
            )
        kwargs["ssl_context"] = ssl_context
    if app_settings.kafka_security_protocol.startswith("SASL"):
        kwargs["sasl_mechanism"] = app_settings.kafka_sasl_mechanism
        kwargs["sasl_plain_username"] = app_settings.kafka_sasl_username
        kwargs["sasl_plain_password"] = app_settings.kafka_sasl_password
    return kwargs


class LocalOutboxSpool:
    def __init__(self, directory: str | Path, *, enabled: bool) -> None:
        self.enabled = enabled
        self.directory = Path(directory)

    def start(self) -> None:
        if not self.enabled:
            return
        self.directory.mkdir(parents=True, exist_ok=True)

    def file_path(self, message_id: int) -> Path:
        return self.directory / f"{message_id}.json"

    def write_message(self, message: OutboxMessage, *, error_text: str) -> Path | None:
        if not self.enabled:
            return None
        self.start()
        payload = {
            "message": serialize_outbox_message(message),
            "error_text": error_text[:4000],
            "spooled_at": datetime.now(UTC).isoformat(),
        }
        target_path = self.file_path(message.id)
        temp_path = target_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(target_path)
        return target_path

    def read_messages(self, *, limit: int | None = None) -> list[tuple[Path, OutboxMessage]]:
        if not self.enabled or not self.directory.exists():
            return []
        records: list[tuple[Path, OutboxMessage]] = []
        for path in sorted(self.directory.glob("*.json"), key=lambda item: item.name):
            document = json.loads(path.read_text(encoding="utf-8"))
            records.append((path, deserialize_outbox_message(document["message"])))
            if limit is not None and len(records) >= limit:
                break
        return records

    def delete_message(self, message_id: int) -> None:
        if not self.enabled:
            return
        path = self.file_path(message_id)
        if path.exists():
            path.unlink()


async def claim_outbox_batch(conn: asyncpg.Connection, batch_size: int) -> list[OutboxMessage]:
    rows = await conn.fetch(
        """
        WITH candidates AS (
            SELECT id
            FROM service_outbox
            WHERE status = 'pending'
              AND available_at <= NOW()
            ORDER BY available_at ASC, id ASC
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        )
        UPDATE service_outbox AS outbox
        SET status = 'processing',
            attempts = outbox.attempts + 1
        FROM candidates
        WHERE outbox.id = candidates.id
        RETURNING
            outbox.id,
            outbox.topic,
            outbox.message_key,
            outbox.aggregate_key,
            outbox.payload,
            outbox.attempts,
            outbox.created_at
        """,
        batch_size,
    )
    return [
        OutboxMessage(
            id=row["id"],
            topic=row["topic"],
            message_key=row["message_key"],
            aggregate_key=row["aggregate_key"],
            payload=normalize_outbox_payload(row["payload"]),
            attempts=row["attempts"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


async def mark_message_published(conn: asyncpg.Connection, message_id: int) -> None:
    await conn.execute(
        """
        UPDATE service_outbox
        SET status = 'published',
            published_at = NOW(),
            last_error = NULL
        WHERE id = $1
        """,
        message_id,
    )


async def reschedule_message(
    conn: asyncpg.Connection,
    message_id: int,
    *,
    attempts: int,
    error_text: str,
    max_attempts: int,
    retry_base_seconds: float,
    max_retry_delay_seconds: float,
) -> None:
    if attempts >= max_attempts:
        await conn.execute(
            """
            UPDATE service_outbox
            SET status = 'failed',
                last_error = $2
            WHERE id = $1
            """,
            message_id,
            error_text[:4000],
        )
        return

    retry_delay_seconds = compute_retry_delay_seconds(
        attempts,
        base_seconds=retry_base_seconds,
        max_delay_seconds=max_retry_delay_seconds,
    )
    await conn.execute(
        """
        UPDATE service_outbox
        SET status = 'pending',
            available_at = NOW() + ($2::double precision * interval '1 second'),
            last_error = $3
        WHERE id = $1
        """,
        message_id,
        retry_delay_seconds,
        error_text[:4000],
    )


async def publish_to_redis_stream(
    client: Any,
    *,
    stream_prefix: str,
    message: OutboxMessage,
) -> str:
    return await client.xadd(
        redis_stream_name(stream_prefix, message.topic),
        build_stream_fields(message),
    )


async def publish_to_kafka(
    producer: Any,
    *,
    topic_prefix: str,
    message: OutboxMessage,
) -> Any:
    return await producer.send_and_wait(
        kafka_topic_name(topic_prefix, message.topic),
        build_kafka_payload(message),
        key=message.message_key.encode("utf-8"),
        headers=[
            ("topic", message.topic.encode("utf-8")),
            ("message_key", message.message_key.encode("utf-8")),
            ("aggregate_key", message.aggregate_key.encode("utf-8")),
        ],
    )


class OutboxPublisher:
    def __init__(self) -> None:
        self._redis_client: Any | None = None
        self._kafka_producer: Any | None = None

    async def start(self) -> None:
        redis_async = load_redis_module()
        producer_cls = load_aiokafka_producer()
        redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        kafka_producer = producer_cls(**build_kafka_producer_kwargs(settings))
        try:
            await kafka_producer.start()
        except Exception:
            await redis_client.aclose()
            raise
        self._redis_client = redis_client
        self._kafka_producer = kafka_producer

    async def ensure_started(self) -> None:
        if self._redis_client is not None and self._kafka_producer is not None:
            return
        await self.start()

    async def stop(self) -> None:
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()
            self._kafka_producer = None
        if self._redis_client is not None:
            await self._redis_client.aclose()
            self._redis_client = None

    async def publish(self, message: OutboxMessage) -> tuple[str, Any]:
        await self.ensure_started()
        try:
            stream_entry_id = await publish_to_redis_stream(
                self._redis_client,
                stream_prefix=settings.redis_stream_prefix,
                message=message,
            )
            kafka_metadata = await publish_to_kafka(
                self._kafka_producer,
                topic_prefix=settings.kafka_topic_prefix,
                message=message,
            )
            return stream_entry_id, kafka_metadata
        except Exception:
            await self.stop()
            raise


async def replay_spool_once(
    pool: asyncpg.Pool,
    publisher: OutboxPublisher,
    spool: LocalOutboxSpool,
) -> int:
    replayed = 0
    for path, message in spool.read_messages(limit=settings.outbox_batch_size):
        try:
            stream_entry_id, kafka_metadata = await publisher.publish(message)
            async with pool.acquire() as conn:
                await mark_message_published(conn, message.id)
            spool.delete_message(message.id)
            replayed += 1
            logger.info(
                "outbox_spool_replayed id=%s spool_file=%s redis_entry_id=%s kafka_topic=%s kafka_partition=%s kafka_offset=%s",
                message.id,
                path.name,
                stream_entry_id,
                kafka_metadata.topic,
                kafka_metadata.partition,
                kafka_metadata.offset,
            )
        except Exception:
            logger.exception("outbox_spool_replay_failed id=%s spool_file=%s", message.id, path.name)
            break
    return replayed


async def dispatch_outbox_once(
    pool: asyncpg.Pool,
    publisher: OutboxPublisher,
    spool: LocalOutboxSpool,
) -> int:
    async with pool.acquire() as conn:
        messages = await claim_outbox_batch(conn, settings.outbox_batch_size)

    if not messages:
        return 0

    published = 0
    for message in messages:
        try:
            stream_entry_id, kafka_metadata = await publisher.publish(message)
            async with pool.acquire() as conn:
                await mark_message_published(conn, message.id)
            spool.delete_message(message.id)
            published += 1
            logger.info(
                "outbox_published id=%s topic=%s redis_stream=%s redis_entry_id=%s kafka_topic=%s kafka_partition=%s kafka_offset=%s attempts=%s",
                message.id,
                message.topic,
                redis_stream_name(settings.redis_stream_prefix, message.topic),
                stream_entry_id,
                kafka_metadata.topic,
                kafka_metadata.partition,
                kafka_metadata.offset,
                message.attempts,
            )
        except Exception as exc:  # pragma: no cover - exercised through DB integration
            spool_path = spool.write_message(message, error_text=str(exc))
            logger.exception("outbox_publish_failed id=%s topic=%s", message.id, message.topic)
            if spool_path is not None:
                logger.warning(
                    "outbox_spooled id=%s topic=%s spool_file=%s",
                    message.id,
                    message.topic,
                    spool_path.name,
                )
            async with pool.acquire() as conn:
                await reschedule_message(
                    conn,
                    message.id,
                    attempts=message.attempts,
                    error_text=str(exc),
                    max_attempts=settings.outbox_max_attempts,
                    retry_base_seconds=settings.outbox_retry_base_seconds,
                    max_retry_delay_seconds=settings.outbox_max_retry_delay_seconds,
                )
    return published


async def run_dispatch_loop() -> None:
    from skycast.db import close_pool, init_pool

    configure_logging(
        service_name="SkyCast Outbox Worker",
        level=settings.log_level,
        json_logs=settings.log_json,
    )
    settings.validate()
    pool = await init_pool(settings)
    publisher = OutboxPublisher()
    spool = LocalOutboxSpool(
        settings.outbox_spool_dir,
        enabled=settings.outbox_spool_enabled,
    )
    spool.start()
    try:
        await publisher.start()
    except Exception:
        logger.exception("outbox_publisher_initial_connect_failed")
    logger.info(
        "outbox_worker_started batch_size=%s poll_seconds=%s redis_url=%s redis_stream_prefix=%s kafka_bootstrap_servers=%s kafka_topic_prefix=%s spool_enabled=%s spool_dir=%s",
        settings.outbox_batch_size,
        settings.outbox_poll_seconds,
        settings.redis_url,
        settings.redis_stream_prefix,
        settings.kafka_bootstrap_servers,
        settings.kafka_topic_prefix,
        settings.outbox_spool_enabled,
        settings.outbox_spool_dir,
    )
    try:
        while True:
            replayed = await replay_spool_once(pool, publisher, spool)
            published = await dispatch_outbox_once(pool, publisher, spool)
            if replayed == 0 and published == 0:
                await asyncio.sleep(settings.outbox_poll_seconds)
    finally:
        await publisher.stop()
        await close_pool()


def main() -> None:
    asyncio.run(run_dispatch_loop())


if __name__ == "__main__":
    main()
