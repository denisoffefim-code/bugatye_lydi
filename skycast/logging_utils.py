"""Shared structured logging helpers for SkyCast services."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


_RESERVED_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, default_fields: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._default_fields = default_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **self._default_fields,
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def configure_logging(*, service_name: str, level: str, json_logs: bool) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonLogFormatter(default_fields={"service": service_name}))
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s service=%(service)s %(message)s",
                defaults={"service": service_name},
            )
        )
    root_logger.addHandler(handler)
