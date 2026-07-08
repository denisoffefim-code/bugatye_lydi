"""Helpers for raw ingest, deduplication, and outbox messages."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from skycast.clients import ForecastRecord


def build_telemetry_dedupe_key(wmo_index: str, observation_date: date) -> str:
    return f"telemetry:{wmo_index}:{observation_date.isoformat()}"


def build_forecast_dedupe_key(run_id: int, station_id: int, forecast_date: date) -> str:
    return f"forecast:{run_id}:{station_id}:{forecast_date.isoformat()}"


def build_outbox_message_key(topic: str, dedupe_key: str) -> str:
    return f"{topic}:{dedupe_key}"


def build_forecast_raw_payload(record: ForecastRecord) -> dict[str, Any]:
    return {
        "forecast_date": record.forecast_date.isoformat(),
        "horizon_days": record.horizon_days,
        "avg_temp": _json_number(record.avg_temp),
        "min_temp": _json_number(record.min_temp),
        "max_temp": _json_number(record.max_temp),
        "precipitation": _json_number(record.precipitation),
        "max_wind_speed": _json_number(record.max_wind_speed),
    }


def json_dumps_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
