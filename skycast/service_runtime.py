"""Shared runtime helpers for split SkyCast services."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from skycast.cache import close_redis_client
from skycast.config import settings
from skycast.db import close_pool, get_pool, init_pool
from skycast.logging_utils import configure_logging
from skycast.migrations import run_migrations
from skycast.monitoring import RequestMetrics, collect_db_metrics, format_prometheus_metrics


def create_service_lifespan(title: str, *, migrate_on_startup: bool | None = None):
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger = logging.getLogger("skycast.runtime")
        configure_logging(
            service_name=title,
            level=settings.log_level,
            json_logs=settings.log_json,
        )
        settings.validate()
        logger.info(
            "service_starting",
            extra={
                "event": "service_starting",
                "migrate_on_startup": settings.startup_migrate if migrate_on_startup is None else migrate_on_startup,
            },
        )
        pool = await init_pool(settings)
        should_migrate = settings.startup_migrate if migrate_on_startup is None else migrate_on_startup
        if should_migrate:
            await run_migrations(pool)
        logger.info(
            "service_started",
            extra={
                "event": "service_started",
                "migrate_on_startup": should_migrate,
            },
        )
        try:
            yield
        finally:
            logger.info("service_stopping", extra={"event": "service_stopping"})
            await close_redis_client()
            await close_pool()
            logger.info("service_stopped", extra={"event": "service_stopped"})

    return lifespan


def create_service_app(
    *,
    title: str,
    version: str = "0.1.0",
    migrate_on_startup: bool | None = None,
) -> FastAPI:
    app = FastAPI(
        title=title,
        version=version,
        lifespan=create_service_lifespan(title, migrate_on_startup=migrate_on_startup),
    )
    app.state.request_metrics = RequestMetrics()

    @app.middleware("http")
    async def request_metrics_middleware(request: Request, call_next):
        started_at = perf_counter()
        request_id = request.headers.get("x-request-id") or uuid4().hex
        logger = logging.getLogger("skycast.http")
        try:
            response = await call_next(request)
        except Exception:
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            duration_seconds = perf_counter() - started_at
            app.state.request_metrics.record(request.method, path, 500, duration_seconds)
            logger.exception(
                "http_request_failed",
                extra={
                    "event": "http_request_failed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "status_code": 500,
                    "duration_ms": round(duration_seconds * 1000, 2),
                    "client_ip": request.client.host if request.client else None,
                    "query_string": request.url.query,
                },
            )
            raise

        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        duration_seconds = perf_counter() - started_at
        app.state.request_metrics.record(
            request.method,
            path,
            response.status_code,
            duration_seconds,
        )
        response.headers["x-request-id"] = request_id
        logger.info(
            "http_request_completed",
            extra={
                "event": "http_request_completed",
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": round(duration_seconds * 1000, 2),
                "client_ip": request.client.host if request.client else None,
                "query_string": request.url.query,
            },
        )
        return response

    @app.get("/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": title}

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        pool = get_pool()
        async with pool.acquire() as conn:
            version_text = await conn.fetchval("SELECT version()")
        return {"status": "ok", "service": title, "database": version_text}

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return await ready()

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        pool = get_pool()
        async with pool.acquire() as conn:
            db_metrics = await collect_db_metrics(conn)
        body = format_prometheus_metrics(title, app.state.request_metrics, db_metrics)
        return PlainTextResponse(body, media_type="text/plain; version=0.0.4")

    return app
