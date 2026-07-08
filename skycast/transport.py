"""Shared Redis and Kafka transport helpers."""

from __future__ import annotations

import ssl
from typing import Any

from skycast.config import Settings

DEFAULT_TRANSPORT_TOPICS: tuple[str, ...] = ("forecast.accepted", "telemetry.accepted")


def redis_stream_name(prefix: str, topic: str) -> str:
    return f"{prefix}.{topic}"


def kafka_topic_name(prefix: str, topic: str) -> str:
    return f"{prefix}.{topic}"


def configured_transport_topics(app_settings: Settings) -> tuple[str, ...]:
    if app_settings.transport_topics:
        return app_settings.transport_topics
    return DEFAULT_TRANSPORT_TOPICS


def load_redis_module():
    try:
        import redis.asyncio
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("redis package is required to run SkyCast transport workers") from exc

    return redis.asyncio


def load_aiokafka_producer():
    try:
        from aiokafka import AIOKafkaProducer
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("aiokafka package is required to run SkyCast transport workers") from exc

    return AIOKafkaProducer


def load_aiokafka_consumer():
    try:
        from aiokafka import AIOKafkaConsumer
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("aiokafka package is required to run SkyCast transport workers") from exc

    return AIOKafkaConsumer


def build_kafka_security_kwargs(app_settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "security_protocol": app_settings.kafka_security_protocol,
    }
    if app_settings.kafka_security_protocol in {"SSL", "SASL_SSL"}:
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


def build_kafka_producer_kwargs(app_settings: Settings) -> dict[str, Any]:
    return {
        "bootstrap_servers": app_settings.kafka_bootstrap_servers,
        "client_id": app_settings.kafka_client_id,
        "acks": "all",
        "enable_idempotence": True,
        **build_kafka_security_kwargs(app_settings),
    }


def build_kafka_consumer_kwargs(
    app_settings: Settings,
    *,
    client_id: str,
    group_id: str | None,
) -> dict[str, Any]:
    return {
        "bootstrap_servers": app_settings.kafka_bootstrap_servers,
        "client_id": client_id,
        "group_id": group_id,
        "enable_auto_commit": False,
        "auto_offset_reset": "earliest",
        **build_kafka_security_kwargs(app_settings),
    }
