"""Database migrations for weather data service."""

from typing import Callable, Coroutine, Any

import asyncpg

# Type alias for a migration body - receives a connection, returns a coroutine.
MigrationFn = Callable[[asyncpg.Connection], Coroutine[Any, Any, None]]


async def _ensure_migrations_table(conn: asyncpg.Connection) -> None:
    """Idempotently create the schema_migrations tracking table."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR(255) NOT NULL UNIQUE,
            applied_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)


async def _apply_migration(
    conn: asyncpg.Connection,
    name: str,
    fn: MigrationFn,
) -> None:
    """
    Check whether migration *name* has already been applied and, if not,
    run *fn* — all inside a single transaction.
    """
    async with conn.transaction():
        row = await conn.fetchrow(
            "SELECT 1 FROM schema_migrations WHERE name = $1", name
        )
        if row:
            return

        await fn(conn)

        await conn.execute(
            "INSERT INTO schema_migrations (name) VALUES ($1)", name
        )
        print(f"[MIGRATION] Applied: {name}", flush=True)


# Existing migrations (unchanged)

async def _migration_initial_schema(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            id        SERIAL PRIMARY KEY,
            wmo_index VARCHAR(5)   NOT NULL UNIQUE,
            name      VARCHAR(255) NOT NULL,
            country   VARCHAR(255)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS weather_data (
            id               SERIAL PRIMARY KEY,
            station_id       INTEGER      NOT NULL REFERENCES stations(id),
            observation_date DATE         NOT NULL,
            quality_flag     VARCHAR(1),
            avg_temp         DECIMAL(5,1)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS load_progress (
            id          SERIAL PRIMARY KEY,
            source_name VARCHAR(255) NOT NULL UNIQUE,
            byte_offset BIGINT       NOT NULL DEFAULT 0,
            updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
        )
    """)


async def _migration_add_loaded_column(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        ALTER TABLE load_progress
        ADD COLUMN IF NOT EXISTS loaded BOOLEAN NOT NULL DEFAULT FALSE
    """)


async def _migration_add_country_column(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        ALTER TABLE stations
        ADD COLUMN IF NOT EXISTS country VARCHAR(255)
    """)


async def _migration_add_weather_fields(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        ALTER TABLE weather_data
        ADD COLUMN IF NOT EXISTS min_temp DECIMAL(5,1),
        ADD COLUMN IF NOT EXISTS max_temp DECIMAL(5,1),
        ADD COLUMN IF NOT EXISTS precipitation DECIMAL(5,1)
    """)


async def _migration_add_indexes(conn: asyncpg.Connection) -> None:
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_weather_date ON weather_data(observation_date)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_weather_station_date ON weather_data(station_id, observation_date)")


# ----- NEW migrations for atm8c and srok8c data -----

async def _migration_create_atm8c_table(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS atm8c_data (
            id                  SERIAL PRIMARY KEY,
            station_id          INTEGER NOT NULL REFERENCES stations(id),
            -- Гринвичское время
            year_gmt            INTEGER NOT NULL,
            month_gmt           INTEGER NOT NULL,
            day_gmt             INTEGER NOT NULL,
            hour_gmt            INTEGER NOT NULL,
            -- Местное время источника
            year_src            INTEGER NOT NULL,
            month_src           INTEGER NOT NULL,
            day_src             INTEGER NOT NULL,
            hour_src            INTEGER NOT NULL,
            -- Дополнительные поля
            period_number       INTEGER,
            local_time          INTEGER,
            timezone            INTEGER,
            day_start           INTEGER,
            phenomenon_code     INTEGER,
            phenomenon_type     INTEGER,
            intensity           INTEGER,
            start_time          TIME,
            end_time            TIME
        )
    """)


async def _migration_create_srok8c_table(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS srok8c_data (
            id                  SERIAL PRIMARY KEY,
            station_id          INTEGER NOT NULL REFERENCES stations(id),
            -- Гринвичское время
            year_gmt            INTEGER NOT NULL,
            month_gmt           INTEGER NOT NULL,
            day_gmt             INTEGER NOT NULL,
            hour_gmt            INTEGER NOT NULL,
            -- Местное время источника
            year_src            INTEGER NOT NULL,
            month_src           INTEGER NOT NULL,
            day_src             INTEGER NOT NULL,
            hour_src            INTEGER NOT NULL,
            -- Срочные данные (поля из fld)
            period_number       INTEGER,
            local_time          INTEGER,
            timezone            INTEGER,
            day_start           INTEGER,
            visibility          INTEGER,
            total_cloud         INTEGER,
            low_cloud           INTEGER,
            cloud_form_high     INTEGER,
            cloud_form_mid      INTEGER,
            cloud_form_vert     INTEGER,
            cloud_st_str        INTEGER,
            cloud_ns            INTEGER,
            cloud_base_height   INTEGER,
            cloud_below_station INTEGER,
            weather_past        INTEGER,
            weather_now         INTEGER,
            wind_dir            INTEGER,
            wind_speed_avg      INTEGER,
            wind_speed_max      INTEGER,
            precip_sum          DECIMAL(6,1),
            soil_temp           DECIMAL(5,1),
            soil_temp_min       DECIMAL(5,1),
            soil_temp_min_period DECIMAL(5,1),
            soil_temp_max_period DECIMAL(5,1),
            soil_temp_max_after  DECIMAL(5,1),
            air_temp_dry        DECIMAL(5,1),
            air_temp_wet        DECIMAL(5,1),
            air_temp_min        DECIMAL(5,1),
            air_temp_min_period DECIMAL(5,1),
            air_temp_max_period DECIMAL(5,1),
            air_temp_max_after  DECIMAL(5,1),
            vapor_pressure      DECIMAL(5,2),
            humidity            INTEGER,
            saturation_deficit  DECIMAL(7,2),
            dew_point           DECIMAL(5,1),
            station_pressure    DECIMAL(6,1),
            sea_level_pressure  DECIMAL(6,1),
            pressure_trend_code INTEGER,
            pressure_trend_value DECIMAL(4,1)
        )
    """)


async def run_migration(pool: asyncpg.Pool) -> None:
    """
    Apply all pending migrations.
    """
    async with pool.acquire() as conn:
        await _ensure_migrations_table(conn)

        await _apply_migration(conn, "initial_schema", _migration_initial_schema)
        await _apply_migration(conn, "add_loaded_column", _migration_add_loaded_column)
        await _apply_migration(conn, "add_country_column", _migration_add_country_column)
        await _apply_migration(conn, "add_weather_fields", _migration_add_weather_fields)
        await _apply_migration(conn, "add_indexes", _migration_add_indexes)

        # Новые миграции
        await _apply_migration(conn, "create_atm8c_table", _migration_create_atm8c_table)
        await _apply_migration(conn, "create_srok8c_table", _migration_create_srok8c_table)