"""Schema migrations for SkyCast."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import asyncpg


MigrationFn = Callable[[asyncpg.Connection], Awaitable[None]]


async def _ensure_migrations_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            applied_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )


async def _apply_migration(conn: asyncpg.Connection, name: str, fn: MigrationFn) -> None:
    async with conn.transaction():
        row = await conn.fetchrow("SELECT 1 FROM schema_migrations WHERE name = $1", name)
        if row:
            return

        await fn(conn)
        await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", name)


async def _migration_add_station_coordinates(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        ALTER TABLE stations
        ADD COLUMN IF NOT EXISTS latitude NUMERIC(8, 4),
        ADD COLUMN IF NOT EXISTS longitude NUMERIC(9, 4),
        ADD COLUMN IF NOT EXISTS elevation_m NUMERIC(7, 1),
        ADD COLUMN IF NOT EXISTS noaa_station_id VARCHAR(16),
        ADD COLUMN IF NOT EXISTS coordinates_updated_at TIMESTAMP
        """
    )


async def _migration_create_forecast_runs(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_runs (
            id BIGSERIAL PRIMARY KEY,
            provider VARCHAR(64) NOT NULL,
            model VARCHAR(128) NOT NULL,
            run_at TIMESTAMPTZ NOT NULL,
            requested_start_date DATE NOT NULL,
            requested_end_date DATE NOT NULL,
            requested_station_count INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            request_payload JSONB,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )


async def _migration_create_forecast_values(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS forecast_values (
            id BIGSERIAL PRIMARY KEY,
            run_id BIGINT NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
            station_id INTEGER NOT NULL REFERENCES stations(id),
            forecast_date DATE NOT NULL,
            horizon_days INTEGER NOT NULL,
            latitude NUMERIC(8, 4),
            longitude NUMERIC(9, 4),
            avg_temp NUMERIC(5, 1),
            min_temp NUMERIC(5, 1),
            max_temp NUMERIC(5, 1),
            precipitation NUMERIC(6, 1),
            max_wind_speed NUMERIC(6, 1),
            raw_payload JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (run_id, station_id, forecast_date)
        )
        """
    )


async def _migration_add_forecast_indexes(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stations_coordinates ON stations(latitude, longitude)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_forecast_values_station_date ON forecast_values(station_id, forecast_date)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_forecast_runs_run_at ON forecast_runs(run_at DESC)"
    )


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply all pending migrations."""
    async with pool.acquire() as conn:
        await _ensure_migrations_table(conn)

        migrations: list[tuple[str, MigrationFn]] = [
            ("skycast_add_station_coordinates", _migration_add_station_coordinates),
            ("skycast_create_forecast_runs", _migration_create_forecast_runs),
            ("skycast_create_forecast_values", _migration_create_forecast_values),
            ("skycast_add_forecast_indexes", _migration_add_forecast_indexes),
        ]

        for name, fn in migrations:
            await _apply_migration(conn, name, fn)
