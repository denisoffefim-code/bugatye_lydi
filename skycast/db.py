"""Database helpers for SkyCast."""

from __future__ import annotations

from typing import Optional

import asyncpg

from skycast.config import Settings


_pool: Optional[asyncpg.Pool] = None


async def init_pool(settings: Settings) -> asyncpg.Pool:
    """Create a shared asyncpg pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=60,
        )
    return _pool


def get_pool() -> asyncpg.Pool:
    """Return the initialized pool."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool


async def close_pool() -> None:
    """Close the shared asyncpg pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
