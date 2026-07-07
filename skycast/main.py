"""FastAPI application for SkyCast."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any, Literal

import aiohttp
import asyncpg
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from skycast.clients import (
    AsyncRateLimiter,
    fetch_noaa_station_metadata,
    fetch_open_meteo_forecast,
    with_retries,
)
from skycast.config import settings
from skycast.db import close_pool, get_pool, init_pool
from skycast.migrations import run_migrations


class TelemetryRecordIn(BaseModel):
    wmo_index: str = Field(min_length=5, max_length=5)
    observation_date: date
    quality_flag: str | None = Field(default=None, max_length=1)
    avg_temp: float | None = None
    min_temp: float | None = None
    max_temp: float | None = None
    precipitation: float | None = None


class ForecastFetchRequest(BaseModel):
    start_date: date
    end_date: date
    model: str = settings.open_meteo_model
    station_ids: list[int] | None = None
    wmo_indices: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=200)


class CoordinateBackfillRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=500)
    dry_run: bool = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()
    pool = await init_pool(settings)
    if settings.startup_migrate:
        await run_migrations(pool)
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


async def _fetch_stations_for_forecast(
    conn: asyncpg.Connection,
    request: ForecastFetchRequest,
) -> list[asyncpg.Record]:
    clauses = ["latitude IS NOT NULL", "longitude IS NOT NULL"]
    args: list[Any] = []
    arg_index = 1

    if request.station_ids:
        clauses.append(f"id = ANY(${arg_index}::int[])")
        args.append(request.station_ids)
        arg_index += 1
    if request.wmo_indices:
        clauses.append(f"wmo_index = ANY(${arg_index}::varchar[])")
        args.append(request.wmo_indices)
        arg_index += 1

    limit_sql = ""
    if request.limit is not None:
        limit_sql = f" LIMIT ${arg_index}"
        args.append(request.limit)

    query = f"""
        SELECT id, wmo_index, name, country, latitude, longitude
        FROM stations
        WHERE {' AND '.join(clauses)}
        ORDER BY wmo_index
        {limit_sql}
    """
    return await conn.fetch(query, *args)


async def _create_forecast_run(
    conn: asyncpg.Connection,
    request: ForecastFetchRequest,
    station_count: int,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO forecast_runs (
            provider,
            model,
            run_at,
            requested_start_date,
            requested_end_date,
            requested_station_count,
            status,
            request_payload
        )
        VALUES (
            'open-meteo',
            $1,
            NOW(),
            $2,
            $3,
            $4,
            'pending',
            $5::jsonb
        )
        RETURNING id
        """,
        request.model,
        request.start_date,
        request.end_date,
        station_count,
        request.model_dump_json(),
    )


async def _save_forecast_values(
    conn: asyncpg.Connection,
    run_id: int,
    station: asyncpg.Record,
    values: list[dict[str, Any]],
) -> None:
    if not values:
        return
    await conn.executemany(
        """
        INSERT INTO forecast_values (
            run_id,
            station_id,
            forecast_date,
            horizon_days,
            latitude,
            longitude,
            avg_temp,
            min_temp,
            max_temp,
            precipitation,
            max_wind_speed,
            raw_payload
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
        ON CONFLICT (run_id, station_id, forecast_date) DO UPDATE
        SET
            horizon_days = EXCLUDED.horizon_days,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            avg_temp = EXCLUDED.avg_temp,
            min_temp = EXCLUDED.min_temp,
            max_temp = EXCLUDED.max_temp,
            precipitation = EXCLUDED.precipitation,
            max_wind_speed = EXCLUDED.max_wind_speed,
            raw_payload = EXCLUDED.raw_payload
        """,
        [
            (
                run_id,
                station["id"],
                value["forecast_date"],
                value["horizon_days"],
                station["latitude"],
                station["longitude"],
                value["avg_temp"],
                value["min_temp"],
                value["max_temp"],
                value["precipitation"],
                value["max_wind_speed"],
                value["raw_payload"],
            )
            for value in values
        ],
    )


async def _finish_forecast_run(
    conn: asyncpg.Connection,
    run_id: int,
    *,
    status: str,
    error_message: str | None,
) -> None:
    await conn.execute(
        """
        UPDATE forecast_runs
        SET status = $2,
            error_message = $3,
            completed_at = NOW()
        WHERE id = $1
        """,
        run_id,
        status,
        error_message,
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        version = await conn.fetchval("SELECT version()")
    return {"status": "ok", "service": settings.app_name, "database": version}


@app.get("/api/stations")
async def list_stations(
    with_coordinates_only: bool = False,
    missing_coordinates_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    clauses: list[str] = []
    if with_coordinates_only:
        clauses.append("latitude IS NOT NULL AND longitude IS NOT NULL")
    if missing_coordinates_only:
        clauses.append("(latitude IS NULL OR longitude IS NULL)")

    where_sql = ""
    if clauses:
        where_sql = f"WHERE {' AND '.join(clauses)}"

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, wmo_index, name, country, latitude, longitude, elevation_m, noaa_station_id
            FROM stations
            {where_sql}
            ORDER BY wmo_index
            LIMIT $1
            """,
            limit,
        )

        total = await conn.fetchval(
            f"""
            SELECT COUNT(*)
            FROM stations
            {where_sql}
            """
        )

    stations = [dict(row) for row in rows]
    return {"total": total, "returned": len(stations), "stations": stations}


@app.post("/api/stations/backfill-coordinates")
async def backfill_station_coordinates(request: CoordinateBackfillRequest) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
    pool = get_pool()

    async with pool.acquire() as conn:
        stations = await conn.fetch(
            """
            SELECT id, wmo_index, name, country, latitude, longitude
            FROM stations
            ORDER BY wmo_index
            LIMIT COALESCE($1, 1000000)
            """,
            request.limit,
        )

    async with aiohttp.ClientSession(timeout=timeout) as session:
        metadata = await with_retries(
            lambda: fetch_noaa_station_metadata(session, settings.noaa_igra_station_list_url)
        )

    matched = []
    missing = []
    for station in stations:
        noaa_station = metadata.get(station["wmo_index"])
        if not noaa_station:
            missing.append(station["wmo_index"])
            continue
        matched.append((station, noaa_station))

    if not request.dry_run:
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                UPDATE stations
                SET latitude = $2,
                    longitude = $3,
                    elevation_m = $4,
                    noaa_station_id = $5,
                    coordinates_updated_at = NOW()
                WHERE id = $1
                """,
                [
                    (
                        station["id"],
                        noaa_station.latitude,
                        noaa_station.longitude,
                        noaa_station.elevation_m,
                        noaa_station.noaa_station_id,
                    )
                    for station, noaa_station in matched
                ],
            )

    return {
        "dry_run": request.dry_run,
        "checked": len(stations),
        "matched": len(matched),
        "missing": len(missing),
        "updated_wmo_indices": [station["wmo_index"] for station, _ in matched[:20]],
        "missing_wmo_indices": missing[:20],
    }


@app.post("/api/telemetry")
async def ingest_telemetry(records: list[TelemetryRecordIn]) -> dict[str, Any]:
    if not records:
        raise HTTPException(status_code=400, detail="At least one telemetry record is required")

    pool = get_pool()
    inserted = 0
    updated = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            for record in records:
                station = await conn.fetchrow(
                    "SELECT id FROM stations WHERE wmo_index = $1",
                    record.wmo_index,
                )
                if station is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Station with wmo_index={record.wmo_index} was not found",
                    )

                existing = await conn.fetchrow(
                    """
                    SELECT id
                    FROM weather_data
                    WHERE station_id = $1 AND observation_date = $2
                    ORDER BY id
                    LIMIT 1
                    """,
                    station["id"],
                    record.observation_date,
                )

                if existing:
                    await conn.execute(
                        """
                        UPDATE weather_data
                        SET quality_flag = $2,
                            avg_temp = $3,
                            min_temp = $4,
                            max_temp = $5,
                            precipitation = $6
                        WHERE id = $1
                        """,
                        existing["id"],
                        record.quality_flag,
                        record.avg_temp,
                        record.min_temp,
                        record.max_temp,
                        record.precipitation,
                    )
                    updated += 1
                else:
                    await conn.execute(
                        """
                        INSERT INTO weather_data (
                            station_id,
                            observation_date,
                            quality_flag,
                            avg_temp,
                            min_temp,
                            max_temp,
                            precipitation
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        station["id"],
                        record.observation_date,
                        record.quality_flag,
                        record.avg_temp,
                        record.min_temp,
                        record.max_temp,
                        record.precipitation,
                    )
                    inserted += 1

    return {"inserted": inserted, "updated": updated, "processed": len(records)}


@app.post("/api/forecasts/fetch")
async def fetch_forecasts(request: ForecastFetchRequest) -> dict[str, Any]:
    if request.end_date < request.start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
    rate_limiter = AsyncRateLimiter(settings.rate_limit_per_second)
    pool = get_pool()

    async with pool.acquire() as conn:
        stations = await _fetch_stations_for_forecast(conn, request)
        if not stations:
            raise HTTPException(status_code=400, detail="No stations with coordinates matched the request")
        run_id = await _create_forecast_run(conn, request, len(stations))

    station_queue: asyncio.Queue[asyncpg.Record] = asyncio.Queue()
    for station in stations:
        station_queue.put_nowait(station)

    saved_rows = 0
    errors: list[str] = []
    saved_lock = asyncio.Lock()
    error_lock = asyncio.Lock()

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def worker() -> None:
            nonlocal saved_rows
            while True:
                try:
                    station = station_queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                try:
                    await rate_limiter.wait()
                    records, payload = await with_retries(
                        lambda: fetch_open_meteo_forecast(
                            session,
                            base_url=settings.open_meteo_base_url,
                            latitude=station["latitude"],
                            longitude=station["longitude"],
                            start_date=request.start_date,
                            end_date=request.end_date,
                            model=request.model,
                        )
                    )
                    prepared = [
                        {
                            "forecast_date": record.forecast_date,
                            "horizon_days": record.horizon_days,
                            "avg_temp": record.avg_temp,
                            "min_temp": record.min_temp,
                            "max_temp": record.max_temp,
                            "precipitation": record.precipitation,
                            "max_wind_speed": record.max_wind_speed,
                            "raw_payload": None,
                        }
                        for record in records
                    ]
                    async with pool.acquire() as conn:
                        await _save_forecast_values(conn, run_id, station, prepared)
                    async with saved_lock:
                        saved_rows += len(prepared)
                except Exception as exc:  # pragma: no cover - defensive endpoint path
                    async with error_lock:
                        errors.append(f"{station['wmo_index']}: {exc}")
                finally:
                    station_queue.task_done()

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(settings.max_parallel_requests, len(stations)))
        ]
        await station_queue.join()
        for worker_task in workers:
            await worker_task

    async with pool.acquire() as conn:
        await _finish_forecast_run(
            conn,
            run_id,
            status="partial_failed" if errors else "success",
            error_message="\n".join(errors[:20]) if errors else None,
        )

    return {
        "run_id": run_id,
        "stations_requested": len(stations),
        "forecast_rows_saved": saved_rows,
        "failed_stations": len(errors),
        "errors": errors[:20],
    }


@app.get("/api/analytics/top-errors")
async def top_errors(
    start_date: date,
    end_date: date,
    metric: Literal["avg_temp", "min_temp", "max_temp", "precipitation"] = "avg_temp",
    limit: int = Query(default=20, ge=1, le=200),
    only_with_coordinates: bool = True,
) -> dict[str, Any]:
    metric_map = {
        "avg_temp": ("fv.avg_temp", "wd.avg_temp"),
        "min_temp": ("fv.min_temp", "wd.min_temp"),
        "max_temp": ("fv.max_temp", "wd.max_temp"),
        "precipitation": ("fv.precipitation", "wd.precipitation"),
    }
    forecast_expr, actual_expr = metric_map[metric]
    coordinates_filter = ""
    if only_with_coordinates:
        coordinates_filter = "AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL"

    query = f"""
        WITH latest_forecast AS (
            SELECT DISTINCT ON (fv.station_id, fv.forecast_date)
                fv.station_id,
                fv.forecast_date,
                fv.horizon_days,
                fv.latitude,
                fv.longitude,
                fr.provider,
                fr.model,
                fr.run_at,
                {forecast_expr} AS forecast_value
            FROM forecast_values fv
            JOIN forecast_runs fr ON fr.id = fv.run_id
            WHERE fv.forecast_date BETWEEN $1 AND $2
            ORDER BY fv.station_id, fv.forecast_date, fr.run_at DESC
        )
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
            lf.forecast_value,
            {actual_expr} AS actual_value,
            ROUND((lf.forecast_value - {actual_expr})::numeric, 2) AS signed_error,
            ROUND(ABS((lf.forecast_value - {actual_expr})::numeric), 2) AS absolute_error
        FROM latest_forecast lf
        JOIN weather_data wd
            ON wd.station_id = lf.station_id
           AND wd.observation_date = lf.forecast_date
        JOIN stations s
            ON s.id = lf.station_id
        WHERE lf.forecast_value IS NOT NULL
          AND {actual_expr} IS NOT NULL
          {coordinates_filter}
        ORDER BY absolute_error DESC, lf.forecast_date DESC
        LIMIT $3
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, start_date, end_date, limit)

    return {
        "metric": metric,
        "start_date": start_date,
        "end_date": end_date,
        "returned": len(rows),
        "items": [dict(row) for row in rows],
    }


@app.get("/api/analytics/coverage")
async def analytics_coverage() -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM stations) AS stations_total,
                (SELECT COUNT(*) FROM stations WHERE latitude IS NOT NULL AND longitude IS NOT NULL)
                    AS stations_with_coordinates,
                (SELECT COUNT(*) FROM forecast_runs) AS forecast_runs_total,
                (SELECT COUNT(*) FROM forecast_values) AS forecast_values_total
            """
        )
    return dict(row)
