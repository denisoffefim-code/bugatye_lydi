"""Minimal metrics helpers shared by all SkyCast services."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, DefaultDict

try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - helper tests may run without runtime deps
    asyncpg = Any  # type: ignore[assignment]


LabelKey = tuple[str, str, str]


@dataclass
class RequestMetrics:
    totals: DefaultDict[LabelKey, int] = field(default_factory=lambda: defaultdict(int))
    duration_sums: DefaultDict[LabelKey, float] = field(default_factory=lambda: defaultdict(float))

    def record(self, method: str, path: str, status_code: int, duration_seconds: float) -> None:
        key = (method, path, str(status_code))
        self.totals[key] += 1
        self.duration_sums[key] += duration_seconds


def request_started_at() -> float:
    return perf_counter()


def format_prometheus_metrics(
    service_name: str,
    request_metrics: RequestMetrics,
    db_metrics: dict[str, float],
) -> str:
    lines = [
        "# HELP skycast_http_requests_total Total HTTP requests handled by the service.",
        "# TYPE skycast_http_requests_total counter",
    ]
    for (method, path, status), total in sorted(request_metrics.totals.items()):
        lines.append(
            f'skycast_http_requests_total{{service="{service_name}",method="{method}",path="{path}",status="{status}"}} {total}'
        )

    lines.extend(
        [
            "# HELP skycast_http_request_duration_seconds_sum Total request duration in seconds.",
            "# TYPE skycast_http_request_duration_seconds_sum counter",
        ]
    )
    for labels, duration_sum in sorted(request_metrics.duration_sums.items()):
        method, path, status = labels
        lines.append(
            f'skycast_http_request_duration_seconds_sum{{service="{service_name}",method="{method}",path="{path}",status="{status}"}} {duration_sum:.6f}'
        )

    lines.extend(
        [
            "# HELP skycast_http_request_duration_seconds_count Number of requests contributing to duration sums.",
            "# TYPE skycast_http_request_duration_seconds_count counter",
        ]
    )
    for labels, total in sorted(request_metrics.totals.items()):
        method, path, status = labels
        lines.append(
            f'skycast_http_request_duration_seconds_count{{service="{service_name}",method="{method}",path="{path}",status="{status}"}} {total}'
        )

    lines.extend(
        [
            "# HELP skycast_runtime_gauge Operational gauges collected from PostgreSQL.",
            "# TYPE skycast_runtime_gauge gauge",
        ]
    )
    for name, value in sorted(db_metrics.items()):
        lines.append(f'skycast_runtime_gauge{{service="{service_name}",metric="{name}"}} {value}')

    return "\n".join(lines) + "\n"


async def collect_db_metrics(conn: asyncpg.Connection) -> dict[str, float]:
    row = await conn.fetchrow(
        """
        SELECT
            1::DOUBLE PRECISION AS database_up,
            (SELECT COUNT(*)::DOUBLE PRECISION FROM service_outbox WHERE status = 'pending') AS outbox_pending_total,
            (SELECT COUNT(*)::DOUBLE PRECISION FROM service_outbox WHERE status = 'processing') AS outbox_processing_total,
            (SELECT COUNT(*)::DOUBLE PRECISION FROM service_outbox WHERE status = 'published') AS outbox_published_total,
            (SELECT COUNT(*)::DOUBLE PRECISION FROM service_outbox WHERE status = 'failed') AS outbox_failed_total,
            (
                SELECT COALESCE(EXTRACT(EPOCH FROM NOW() - MIN(available_at)), 0)::DOUBLE PRECISION
                FROM service_outbox
                WHERE status = 'pending'
                  AND available_at <= NOW()
            ) AS outbox_oldest_pending_age_seconds,
            (SELECT COUNT(*)::DOUBLE PRECISION FROM raw_telemetry_events WHERE processed_at IS NULL) AS raw_telemetry_backlog_total,
            (
                SELECT COALESCE(EXTRACT(EPOCH FROM NOW() - MIN(ingested_at)), 0)::DOUBLE PRECISION
                FROM raw_telemetry_events
                WHERE processed_at IS NULL
            ) AS raw_telemetry_oldest_unprocessed_age_seconds,
            (SELECT COUNT(*)::DOUBLE PRECISION FROM raw_forecast_events WHERE processed_at IS NULL) AS raw_forecast_backlog_total,
            (
                SELECT COALESCE(EXTRACT(EPOCH FROM NOW() - MIN(ingested_at)), 0)::DOUBLE PRECISION
                FROM raw_forecast_events
                WHERE processed_at IS NULL
            ) AS raw_forecast_oldest_unprocessed_age_seconds
        """
    )
    return {
        "database_up": row["database_up"],
        "outbox_pending_total": row["outbox_pending_total"],
        "outbox_processing_total": row["outbox_processing_total"],
        "outbox_published_total": row["outbox_published_total"],
        "outbox_failed_total": row["outbox_failed_total"],
        "outbox_oldest_pending_age_seconds": row["outbox_oldest_pending_age_seconds"],
        "raw_telemetry_backlog_total": row["raw_telemetry_backlog_total"],
        "raw_telemetry_oldest_unprocessed_age_seconds": row["raw_telemetry_oldest_unprocessed_age_seconds"],
        "raw_forecast_backlog_total": row["raw_forecast_backlog_total"],
        "raw_forecast_oldest_unprocessed_age_seconds": row["raw_forecast_oldest_unprocessed_age_seconds"],
    }
