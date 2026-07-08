"""Shared runtime helpers for split SkyCast services."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from skycast.config import settings
from skycast.db import close_pool, get_pool, init_pool
from skycast.migrations import run_migrations


def create_service_lifespan(*, migrate_on_startup: bool | None = None):
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.validate()
        pool = await init_pool(settings)
        should_migrate = settings.startup_migrate if migrate_on_startup is None else migrate_on_startup
        if should_migrate:
            await run_migrations(pool)
        try:
            yield
        finally:
            await close_pool()

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
        lifespan=create_service_lifespan(migrate_on_startup=migrate_on_startup),
    )

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

    return app
