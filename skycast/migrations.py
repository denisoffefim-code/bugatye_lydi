"""Schema migrations for SkyCast."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - helper tests may run without runtime deps
    asyncpg = Any  # type: ignore[assignment]


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


async def _migration_create_raw_layers(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_telemetry_events (
            id BIGSERIAL PRIMARY KEY,
            dedupe_key VARCHAR(128) NOT NULL UNIQUE,
            station_id INTEGER NOT NULL REFERENCES stations(id),
            wmo_index VARCHAR(5) NOT NULL,
            observation_date DATE NOT NULL,
            payload JSONB NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_forecast_events (
            id BIGSERIAL PRIMARY KEY,
            dedupe_key VARCHAR(128) NOT NULL UNIQUE,
            run_id BIGINT NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
            station_id INTEGER NOT NULL REFERENCES stations(id),
            provider VARCHAR(64) NOT NULL,
            model VARCHAR(128) NOT NULL,
            forecast_date DATE NOT NULL,
            horizon_days INTEGER NOT NULL,
            payload JSONB NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS service_outbox (
            id BIGSERIAL PRIMARY KEY,
            topic VARCHAR(128) NOT NULL,
            message_key VARCHAR(255) NOT NULL UNIQUE,
            aggregate_key VARCHAR(255) NOT NULL,
            payload JSONB NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_telemetry_station_date
        ON raw_telemetry_events(station_id, observation_date)
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_forecast_station_date
        ON raw_forecast_events(station_id, forecast_date)
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_service_outbox_status_available
        ON service_outbox(status, available_at)
        """
    )


async def _migration_create_dm_forecast_errors(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE OR REPLACE VIEW dm_forecast_errors AS
        WITH latest_forecast AS (
            SELECT DISTINCT ON (fv.station_id, fv.forecast_date)
                fv.station_id,
                fv.forecast_date,
                fv.horizon_days,
                fr.provider,
                fr.model,
                fr.run_at,
                fv.avg_temp,
                fv.min_temp,
                fv.max_temp,
                fv.precipitation
            FROM forecast_values fv
            JOIN forecast_runs fr ON fr.id = fv.run_id
            WHERE fr.status IN ('success', 'partial_failed')
            ORDER BY fv.station_id, fv.forecast_date, fr.run_at DESC
        ),
        metric_rows AS (
            SELECT
                s.id AS station_id,
                s.wmo_index,
                s.name,
                s.country,
                s.latitude,
                s.longitude,
                lf.forecast_date,
                lf.horizon_days,
                lf.provider,
                lf.model,
                lf.run_at,
                'avg_temp'::VARCHAR(32) AS metric,
                lf.avg_temp::NUMERIC AS forecast_value,
                wd.avg_temp::NUMERIC AS actual_value
            FROM latest_forecast lf
            JOIN weather_data wd
                ON wd.station_id = lf.station_id
               AND wd.observation_date = lf.forecast_date
            JOIN stations s
                ON s.id = lf.station_id
            WHERE lf.avg_temp IS NOT NULL
              AND wd.avg_temp IS NOT NULL

            UNION ALL

            SELECT
                s.id AS station_id,
                s.wmo_index,
                s.name,
                s.country,
                s.latitude,
                s.longitude,
                lf.forecast_date,
                lf.horizon_days,
                lf.provider,
                lf.model,
                lf.run_at,
                'min_temp'::VARCHAR(32) AS metric,
                lf.min_temp::NUMERIC AS forecast_value,
                wd.min_temp::NUMERIC AS actual_value
            FROM latest_forecast lf
            JOIN weather_data wd
                ON wd.station_id = lf.station_id
               AND wd.observation_date = lf.forecast_date
            JOIN stations s
                ON s.id = lf.station_id
            WHERE lf.min_temp IS NOT NULL
              AND wd.min_temp IS NOT NULL

            UNION ALL

            SELECT
                s.id AS station_id,
                s.wmo_index,
                s.name,
                s.country,
                s.latitude,
                s.longitude,
                lf.forecast_date,
                lf.horizon_days,
                lf.provider,
                lf.model,
                lf.run_at,
                'max_temp'::VARCHAR(32) AS metric,
                lf.max_temp::NUMERIC AS forecast_value,
                wd.max_temp::NUMERIC AS actual_value
            FROM latest_forecast lf
            JOIN weather_data wd
                ON wd.station_id = lf.station_id
               AND wd.observation_date = lf.forecast_date
            JOIN stations s
                ON s.id = lf.station_id
            WHERE lf.max_temp IS NOT NULL
              AND wd.max_temp IS NOT NULL

            UNION ALL

            SELECT
                s.id AS station_id,
                s.wmo_index,
                s.name,
                s.country,
                s.latitude,
                s.longitude,
                lf.forecast_date,
                lf.horizon_days,
                lf.provider,
                lf.model,
                lf.run_at,
                'precipitation'::VARCHAR(32) AS metric,
                lf.precipitation::NUMERIC AS forecast_value,
                wd.precipitation::NUMERIC AS actual_value
            FROM latest_forecast lf
            JOIN weather_data wd
                ON wd.station_id = lf.station_id
               AND wd.observation_date = lf.forecast_date
            JOIN stations s
                ON s.id = lf.station_id
            WHERE lf.precipitation IS NOT NULL
              AND wd.precipitation IS NOT NULL
        )
        SELECT
            station_id,
            wmo_index,
            name,
            country,
            latitude,
            longitude,
            forecast_date,
            horizon_days,
            provider,
            model,
            run_at,
            metric,
            ROUND(forecast_value, 2) AS forecast_value,
            ROUND(actual_value, 2) AS actual_value,
            ROUND((forecast_value - actual_value), 2) AS signed_error,
            ROUND(ABS(forecast_value - actual_value), 2) AS absolute_error,
            DENSE_RANK() OVER (
                PARTITION BY metric
                ORDER BY ABS(forecast_value - actual_value) DESC, forecast_date DESC
            ) AS error_rank
        FROM metric_rows
        """
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
            ("skycast_create_raw_layers", _migration_create_raw_layers),
            ("skycast_create_dm_forecast_errors", _migration_create_dm_forecast_errors),
        ]

        for name, fn in migrations:
            await _apply_migration(conn, name, fn)
