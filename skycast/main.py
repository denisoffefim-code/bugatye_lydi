"""FastAPI application for SkyCast."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

import aiohttp
try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - helper tests may run without runtime deps
    asyncpg = Any  # type: ignore[assignment]
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from skycast.auth import (
    extract_bearer_token,
    generate_session_token,
    hash_password,
    hash_token,
    normalize_email,
    validate_password,
    verify_password,
)
from skycast.cache import close_redis_client, invalidate_analytics_cache, maybe_cached_json_response
from skycast.clients import (
    AsyncRateLimiter,
    fetch_noaa_station_metadata,
    fetch_open_meteo_forecast,
    fetch_open_meteo_previous_runs_forecast,
    with_retries,
)
from skycast.config import settings
from skycast.db import close_pool, get_pool, init_pool
from skycast.forecast_contract import (
    FORECAST_SOURCE_SQL,
    latest_forecast_identity_sql,
    latest_forecast_order_by_sql,
)
from skycast.logging_utils import configure_logging
from skycast.migrations import run_migrations
from skycast.pipeline import (
    build_forecast_dedupe_key,
    build_forecast_raw_payload,
    build_outbox_message_key,
    build_telemetry_dedupe_key,
    json_dumps_payload,
)

configure_logging(
    service_name=settings.app_name,
    level=settings.log_level,
    json_logs=settings.log_json,
)
logger = logging.getLogger("skycast.api")


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
    source: Literal["forecast", "previous_runs"] = "forecast"
    archive_horizon_days: int = Field(default=1, ge=1, le=7)
    publish_outbox_events: bool = True
    station_ids: list[int] | None = None
    wmo_indices: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=200)


class CoordinateBackfillRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=500)
    dry_run: bool = False


class UserRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()
    pool = await init_pool(settings)
    if settings.startup_migrate:
        await run_migrations(pool)
    try:
        yield
    finally:
        await close_redis_client()
        await close_pool()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

METRIC_SQL_MAP = {
    "avg_temp": ("fv.avg_temp", "wd.avg_temp"),
    "min_temp": ("fv.min_temp", "wd.min_temp"),
    "max_temp": ("fv.max_temp", "wd.max_temp"),
    "precipitation": ("fv.precipitation", "wd.precipitation"),
}
ROLE_VIEWER = "viewer"
ROLE_ANALYST = "analyst"
ROLE_ADMIN = "admin"
LEGACY_ROLE_ALIASES = {"user": ROLE_VIEWER}
PUBLIC_FORECAST_SOURCE = "forecast"
FORECAST_SOURCE_ALIASES = {
    PUBLIC_FORECAST_SOURCE: PUBLIC_FORECAST_SOURCE,
    "previous_runs": PUBLIC_FORECAST_SOURCE,
}


def _auth_required_exception() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _invalid_credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden_role_exception(allowed_roles: tuple[str, ...], actual_role: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail=f"Role '{actual_role}' is not allowed; required one of: {', '.join(allowed_roles)}",
    )


def _normalize_user_role(role: str | None) -> str:
    normalized = (role or ROLE_VIEWER).strip().lower()
    return LEGACY_ROLE_ALIASES.get(normalized, normalized)


def _require_roles(current_auth: dict[str, Any], *allowed_roles: str) -> dict[str, Any]:
    actual_role = _normalize_user_role(current_auth["user"].role)
    if actual_role not in allowed_roles:
        raise _forbidden_role_exception(tuple(allowed_roles), actual_role)
    return current_auth


def _append_sql_filter(clauses: list[str], args: list[Any], expression: str, value: Any) -> None:
    if value is None:
        return
    clauses.append(f"{expression} = ${len(args) + 1}")
    args.append(value)


def _normalize_optional_query_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_optional_forecast_source(
    value: str | None,
    *,
    blank_default: Literal["forecast"] | None = None,
) -> Literal["forecast"] | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return blank_default
    aliased = FORECAST_SOURCE_ALIASES.get(normalized)
    if aliased is None:
        raise HTTPException(status_code=422, detail="source must be 'forecast'")
    return aliased


def _append_forecast_run_filters(
    clauses: list[str],
    args: list[Any],
    *,
    status: str | None,
    model: str | None,
    source: Literal["forecast"] | None,
    horizon_days: int | None,
) -> None:
    _append_sql_filter(clauses, args, "fr.status", status)
    _append_sql_filter(clauses, args, "fr.model", model)
    if horizon_days is not None:
        clauses.append(
            f"""
            EXISTS (
                SELECT 1
                FROM forecast_values fv_filter
                WHERE fv_filter.run_id = fr.id
                  AND fv_filter.horizon_days = ${len(args) + 1}
            )
            """.strip()
        )
        args.append(horizon_days)


def _append_dm_forecast_filters(
    clauses: list[str],
    args: list[Any],
    *,
    model: str | None,
    source: Literal["forecast"] | None,
    horizon_days: int | None,
) -> None:
    _append_sql_filter(clauses, args, "model", model)
    _append_sql_filter(clauses, args, "horizon_days", horizon_days)


def _append_station_series_filters(
    clauses: list[str],
    args: list[Any],
    *,
    model: str | None,
    source: Literal["forecast"] | None,
    horizon_days: int | None,
) -> None:
    _append_sql_filter(clauses, args, "fr.model", model)
    _append_sql_filter(clauses, args, "fv.horizon_days", horizon_days)


def _append_latest_forecast_window_filters(
    clauses: list[str],
    args: list[Any],
    *,
    start_date: date,
    end_date: date,
    model: str | None,
    horizon_days: int | None,
) -> None:
    clauses.append(f"fv.forecast_date BETWEEN ${len(args) + 1} AND ${len(args) + 2}")
    args.extend([start_date, end_date])
    _append_sql_filter(clauses, args, "fr.model", model)
    _append_sql_filter(clauses, args, "fv.horizon_days", horizon_days)


def _metric_forecast_column_sql(metric: str) -> str:
    return METRIC_SQL_MAP[metric][0]


def _metric_actual_column_sql(metric: str) -> str:
    return METRIC_SQL_MAP[metric][1]


def _latest_forecast_cte_sql(
    *,
    select_fields: list[str],
    where_clauses: list[str],
) -> str:
    return f"""
        WITH latest_forecast AS (
            SELECT DISTINCT ON ({latest_forecast_identity_sql()})
                fv.station_id,
                fv.forecast_date,
                fv.horizon_days,
                fr.provider,
                fr.model,
                {FORECAST_SOURCE_SQL} AS source,
                fr.run_at,
                {', '.join(select_fields)}
            FROM forecast_values fv
            JOIN forecast_runs fr ON fr.id = fv.run_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY {latest_forecast_order_by_sql()}
        )
    """


def _user_out_from_row(row: Any) -> UserOut:
    return UserOut(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=_normalize_user_role(row["role"]),
        is_active=row["is_active"],
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


async def _resolve_auth_context(request: Request, authorization: str | None) -> dict[str, Any]:
    token = extract_bearer_token(authorization)
    if token is None:
        raise _auth_required_exception()

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                u.id,
                u.email,
                u.full_name,
                u.role,
                u.is_active,
                u.created_at,
                u.last_login_at,
                s.id AS session_id
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = $1
              AND s.revoked_at IS NULL
              AND s.expires_at > NOW()
            """,
            hash_token(token),
        )
        if row is None or not row["is_active"]:
            raise _auth_required_exception()

        await conn.execute(
            """
            UPDATE auth_sessions
            SET last_used_at = NOW()
            WHERE id = $1
            """,
            row["session_id"],
        )

    return {
        "session_id": row["session_id"],
        "user": _user_out_from_row(row),
        "client_ip": request.client.host if request.client else None,
    }


async def get_current_auth_context(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    return await _resolve_auth_context(request, authorization)


async def get_current_viewer_auth_context(
    current_auth: dict[str, Any] = Depends(get_current_auth_context),
) -> dict[str, Any]:
    return _require_roles(current_auth, ROLE_VIEWER, ROLE_ANALYST, ROLE_ADMIN)


async def get_current_analyst_auth_context(
    current_auth: dict[str, Any] = Depends(get_current_auth_context),
) -> dict[str, Any]:
    return _require_roles(current_auth, ROLE_ANALYST, ROLE_ADMIN)


async def get_current_admin_auth_context(
    current_auth: dict[str, Any] = Depends(get_current_auth_context),
) -> dict[str, Any]:
    return _require_roles(current_auth, ROLE_ADMIN)


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
                json_dumps_payload(value["raw_payload"]),
            )
            for value in values
        ],
    )


async def _save_raw_forecast_events(
    conn: asyncpg.Connection,
    run_id: int,
    station: asyncpg.Record,
    model: str,
    values: list[dict[str, Any]],
) -> None:
    if not values:
        return
    await conn.executemany(
        """
        INSERT INTO raw_forecast_events (
            dedupe_key,
            run_id,
            station_id,
            provider,
            model,
            forecast_date,
            horizon_days,
            payload,
            processed_at
        )
        VALUES ($1, $2, $3, 'open-meteo', $4, $5, $6, $7::jsonb, NOW())
        ON CONFLICT (dedupe_key) DO UPDATE
        SET payload = EXCLUDED.payload,
            processed_at = NOW()
        """,
        [
            (
                build_forecast_dedupe_key(run_id, station["id"], value["forecast_date"]),
                run_id,
                station["id"],
                model,
                value["forecast_date"],
                value["horizon_days"],
                json_dumps_payload(value["raw_payload"]),
            )
            for value in values
        ],
    )


async def _save_raw_telemetry_event(
    conn: asyncpg.Connection,
    station_id: int,
    record: TelemetryRecordIn,
) -> None:
    dedupe_key = build_telemetry_dedupe_key(record.wmo_index, record.observation_date)
    await conn.execute(
        """
        INSERT INTO raw_telemetry_events (
            dedupe_key,
            station_id,
            wmo_index,
            observation_date,
            payload,
            processed_at
        )
        VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
        ON CONFLICT (dedupe_key) DO UPDATE
        SET payload = EXCLUDED.payload,
            processed_at = NOW()
        """,
        dedupe_key,
        station_id,
        record.wmo_index,
        record.observation_date,
        json_dumps_payload(record.model_dump(mode="json")),
    )


async def _enqueue_outbox_message(
    conn: asyncpg.Connection,
    *,
    topic: str,
    aggregate_key: str,
    dedupe_key: str,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO service_outbox (
            topic,
            message_key,
            aggregate_key,
            payload
        )
        VALUES ($1, $2, $3, $4::jsonb)
        ON CONFLICT (message_key) DO NOTHING
        """,
        topic,
        build_outbox_message_key(topic, dedupe_key),
        aggregate_key,
        json_dumps_payload(payload),
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


def _determine_forecast_run_status(*, saved_rows: int, error_count: int) -> str:
    if error_count == 0:
        return "success"
    if saved_rows > 0:
        return "partial_failed"
    return "failed"


@app.post("/api/auth/register", response_model=UserOut, status_code=201)
async def register_user(payload: UserRegisterRequest) -> UserOut:
    try:
        email = normalize_email(payload.email)
        validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    full_name = payload.full_name.strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, full_name, password_hash, role)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (email) DO NOTHING
            RETURNING id, email, full_name, role, is_active, created_at, last_login_at
            """,
            email,
            full_name,
            hash_password(payload.password, iterations=settings.auth_password_hash_iterations),
            ROLE_VIEWER,
        )
        if row is None:
            raise HTTPException(status_code=409, detail="User with this email already exists")

    logger.info(
        "user_registered",
        extra={
            "event": "user_registered",
            "email": email,
            "user_id": row["id"],
        },
    )
    return _user_out_from_row(row)


@app.post("/api/auth/login", response_model=AuthTokenResponse)
async def login_user(payload: UserLoginRequest, request: Request) -> AuthTokenResponse:
    try:
        email = normalize_email(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pool = get_pool()
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            """
            SELECT id, email, full_name, role, is_active, created_at, last_login_at, password_hash
            FROM users
            WHERE email = $1
            """,
            email,
        )
        if user_row is None or not verify_password(payload.password, user_row["password_hash"]):
            raise _invalid_credentials_exception()
        if not user_row["is_active"]:
            raise HTTPException(status_code=403, detail="User is inactive")

        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.auth_session_ttl_hours)
        token = generate_session_token()
        await conn.execute(
            """
            INSERT INTO auth_sessions (user_id, token_hash, expires_at, user_agent, ip_address)
            VALUES ($1, $2, $3, $4, $5)
            """,
            user_row["id"],
            hash_token(token),
            expires_at,
            request.headers.get("user-agent"),
            request.client.host if request.client else None,
        )
        user_row = await conn.fetchrow(
            """
            UPDATE users
            SET last_login_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
            RETURNING id, email, full_name, role, is_active, created_at, last_login_at
            """,
            user_row["id"],
        )

    logger.info(
        "user_logged_in",
        extra={
            "event": "user_logged_in",
            "email": email,
            "user_id": user_row["id"],
        },
    )
    return AuthTokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=_user_out_from_row(user_row),
    )


@app.post("/api/auth/logout", status_code=204)
async def logout_user(current_auth: dict[str, Any] = Depends(get_current_auth_context)) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = NOW()
            WHERE id = $1
            """,
            current_auth["session_id"],
        )

    logger.info(
        "user_logged_out",
        extra={
            "event": "user_logged_out",
            "user_id": current_auth["user"].id,
        },
    )


@app.post("/api/auth/users/{user_id}/logout-sessions", status_code=204)
async def logout_user_sessions(
    user_id: int,
    exclude_current_session: bool = True,
    current_auth: dict[str, Any] = Depends(get_current_admin_auth_context),
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM users WHERE id = $1", user_id)
        if not exists:
            raise HTTPException(status_code=404, detail=f"User with id={user_id} was not found")

        clauses = ["user_id = $1", "revoked_at IS NULL"]
        args: list[Any] = [user_id]
        if exclude_current_session and user_id == current_auth["user"].id:
            clauses.append(f"id <> ${len(args) + 1}")
            args.append(current_auth["session_id"])

        await conn.execute(
            f"""
            UPDATE auth_sessions
            SET revoked_at = NOW()
            WHERE {' AND '.join(clauses)}
            """,
            *args,
        )

    logger.info(
        "user_sessions_revoked",
        extra={
            "event": "user_sessions_revoked",
            "admin_user_id": current_auth["user"].id,
            "target_user_id": user_id,
            "exclude_current_session": exclude_current_session,
        },
    )


@app.get("/api/auth/me", response_model=UserOut)
async def auth_me(current_auth: dict[str, Any] = Depends(get_current_auth_context)) -> UserOut:
    return current_auth["user"]


async def _resolve_station_id(
    conn: asyncpg.Connection,
    *,
    station_id: int | None = None,
    wmo_index: str | None = None,
) -> int:
    if station_id is None and wmo_index is None:
        raise HTTPException(status_code=400, detail="station_id or wmo_index is required")

    if station_id is not None:
        exists = await conn.fetchval("SELECT 1 FROM stations WHERE id = $1", station_id)
        if not exists:
            raise HTTPException(status_code=404, detail=f"Station with id={station_id} was not found")
        return station_id

    resolved = await conn.fetchval("SELECT id FROM stations WHERE wmo_index = $1", wmo_index)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"Station with wmo_index={wmo_index} was not found",
        )
    return resolved

@app.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/ready")
async def ready() -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        version = await conn.fetchval("SELECT version()")
    return {"status": "ok", "service": settings.app_name, "database": version}


@app.get("/health")
async def health() -> dict[str, Any]:
    return await ready()


@app.get("/api/stations")
async def list_stations(
    with_coordinates_only: bool = False,
    missing_coordinates_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    _: dict[str, Any] = Depends(get_current_viewer_auth_context),
) -> dict[str, Any]:
    if with_coordinates_only and missing_coordinates_only:
        raise HTTPException(
            status_code=400,
            detail="with_coordinates_only and missing_coordinates_only cannot both be true",
        )

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


@app.get("/api/stations/{station_id}/details")
async def station_details(
    station_id: int,
    _: dict[str, Any] = Depends(get_current_viewer_auth_context),
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        station = await conn.fetchrow(
            """
            SELECT id, wmo_index, name, country, latitude, longitude,
                   elevation_m, noaa_station_id, coordinates_updated_at
            FROM stations
            WHERE id = $1
            """,
            station_id,
        )
        if station is None:
            raise HTTPException(status_code=404, detail=f"Station with id={station_id} was not found")

        stats = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM weather_data WHERE station_id = $1) AS weather_rows,
                (SELECT MIN(observation_date) FROM weather_data WHERE station_id = $1) AS weather_start_date,
                (SELECT MAX(observation_date) FROM weather_data WHERE station_id = $1) AS weather_end_date,
                (SELECT COUNT(*) FROM forecast_values WHERE station_id = $1) AS forecast_rows,
                (SELECT MIN(forecast_date) FROM forecast_values WHERE station_id = $1) AS forecast_start_date,
                (SELECT MAX(forecast_date) FROM forecast_values WHERE station_id = $1) AS forecast_end_date,
                (SELECT COUNT(*) FROM atm8c_data WHERE station_id = $1) AS atm8c_rows,
                (SELECT COUNT(*) FROM srok8c_data WHERE station_id = $1) AS srok8c_rows
            """,
            station_id,
        )

    return {"station": dict(station), "stats": dict(stats)}


@app.post("/api/stations/backfill-coordinates")
async def backfill_station_coordinates(
    request: CoordinateBackfillRequest,
    current_auth: dict[str, Any] = Depends(get_current_admin_auth_context),
) -> dict[str, Any]:
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

    logger.info(
        "station_backfill_completed",
        extra={
            "event": "station_backfill_completed",
            "user_id": current_auth["user"].id,
            "dry_run": request.dry_run,
            "checked": len(stations),
            "matched": len(matched),
            "missing": len(missing),
        },
    )
    if matched and not request.dry_run:
        await invalidate_analytics_cache()
    return {
        "dry_run": request.dry_run,
        "checked": len(stations),
        "matched": len(matched),
        "missing": len(missing),
        "updated_wmo_indices": [station["wmo_index"] for station, _ in matched[:20]],
        "missing_wmo_indices": missing[:20],
    }


@app.post("/api/telemetry")
async def ingest_telemetry(
    records: list[TelemetryRecordIn],
    current_auth: dict[str, Any] = Depends(get_current_analyst_auth_context),
) -> dict[str, Any]:
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
                await _save_raw_telemetry_event(conn, station["id"], record)

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

                dedupe_key = build_telemetry_dedupe_key(record.wmo_index, record.observation_date)
                await _enqueue_outbox_message(
                    conn,
                    topic="telemetry.accepted",
                    aggregate_key=record.wmo_index,
                    dedupe_key=dedupe_key,
                    payload=record.model_dump(mode="json"),
                )

    logger.info(
        "telemetry_ingest_completed",
        extra={
            "event": "telemetry_ingest_completed",
            "user_id": current_auth["user"].id,
            "processed": len(records),
            "inserted": inserted,
            "updated": updated,
        },
    )
    if inserted or updated:
        await invalidate_analytics_cache()
    return {"inserted": inserted, "updated": updated, "processed": len(records)}


@app.post("/api/forecasts/fetch")
async def fetch_forecasts(
    request: ForecastFetchRequest,
    current_auth: dict[str, Any] = Depends(get_current_admin_auth_context),
) -> dict[str, Any]:
    if request.end_date < request.start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
    rate_limiter = AsyncRateLimiter(settings.rate_limit_per_second)
    pool = get_pool()
    run_id: int | None = None

    try:
        async with pool.acquire() as conn:
            stations = await _fetch_stations_for_forecast(conn, request)
            if not stations:
                raise HTTPException(
                    status_code=400,
                    detail="No stations with coordinates matched the request",
                )
            run_id = await _create_forecast_run(conn, request, len(stations))
        logger.info(
            "forecast_run_started",
            extra={
                "event": "forecast_run_started",
                "user_id": current_auth["user"].id,
                "run_id": run_id,
                "stations_requested": len(stations),
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "model": request.model,
                "source": request.source,
                "archive_horizon_days": request.archive_horizon_days,
                "publish_outbox_events": request.publish_outbox_events,
            },
        )

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
                        if request.source == "previous_runs":
                            records, _payload = await with_retries(
                                lambda: fetch_open_meteo_previous_runs_forecast(
                                    session,
                                    base_url=settings.open_meteo_previous_runs_base_url,
                                    latitude=station["latitude"],
                                    longitude=station["longitude"],
                                    start_date=request.start_date,
                                    end_date=request.end_date,
                                    model=request.model,
                                    horizon_days=request.archive_horizon_days,
                                )
                            )
                        else:
                            records, _payload = await with_retries(
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
                                "raw_payload": build_forecast_raw_payload(record),
                            }
                            for record in records
                        ]
                        async with pool.acquire() as conn:
                            await _save_raw_forecast_events(conn, run_id, station, request.model, prepared)
                            await _save_forecast_values(conn, run_id, station, prepared)
                            if request.publish_outbox_events:
                                for value in prepared:
                                    dedupe_key = build_forecast_dedupe_key(
                                        run_id,
                                        station["id"],
                                        value["forecast_date"],
                                    )
                                    await _enqueue_outbox_message(
                                        conn,
                                        topic="forecast.accepted",
                                        aggregate_key=str(run_id),
                                        dedupe_key=dedupe_key,
                                        payload={
                                            "run_id": run_id,
                                            "station_id": station["id"],
                                            "wmo_index": station["wmo_index"],
                                            "model": request.model,
                                            "source": request.source,
                                            **value["raw_payload"],
                                        },
                                    )
                        async with saved_lock:
                            saved_rows += len(prepared)
                    except Exception as exc:  # pragma: no cover - defensive endpoint path
                        async with error_lock:
                            errors.append(f"{station['wmo_index']}: {exc}")
                        logger.warning(
                            "forecast_station_fetch_failed",
                            extra={
                                "event": "forecast_station_fetch_failed",
                                "user_id": current_auth["user"].id,
                                "run_id": run_id,
                                "station_id": station["id"],
                                "wmo_index": station["wmo_index"],
                                "error": str(exc),
                            },
                        )
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
            final_status = _determine_forecast_run_status(
                saved_rows=saved_rows,
                error_count=len(errors),
            )
            await _finish_forecast_run(
                conn,
                run_id,
                status=final_status,
                error_message="\n".join(errors[:20]) if errors else None,
            )

        logger.info(
            "forecast_run_completed",
            extra={
                "event": "forecast_run_completed",
                "user_id": current_auth["user"].id,
                "run_id": run_id,
                "status": final_status,
                "stations_requested": len(stations),
                "forecast_rows_saved": saved_rows,
                "failed_stations": len(errors),
                "publish_outbox_events": request.publish_outbox_events,
            },
        )
        if saved_rows:
            await invalidate_analytics_cache()
        return {
            "run_id": run_id,
            "stations_requested": len(stations),
            "forecast_rows_saved": saved_rows,
            "failed_stations": len(errors),
            "source": request.source,
            "archive_horizon_days": request.archive_horizon_days if request.source == "previous_runs" else None,
            "publish_outbox_events": request.publish_outbox_events,
            "errors": errors[:20],
        }
    except Exception as exc:
        if run_id is not None:
            async with pool.acquire() as conn:
                await _finish_forecast_run(conn, run_id, status="failed", error_message=str(exc))
        logger.exception(
            "forecast_run_failed",
            extra={
                "event": "forecast_run_failed",
                "user_id": current_auth["user"].id,
                "run_id": run_id,
                "error": str(exc),
            },
        )
        raise


@app.get("/api/forecast-runs")
async def list_forecast_runs(
    limit: int = Query(default=20, ge=1, le=200),
    status: str | None = None,
    model: str | None = None,
    source: str | None = None,
    horizon_days: int | None = Query(default=None, ge=1, le=7),
    _: dict[str, Any] = Depends(get_current_viewer_auth_context),
) -> dict[str, Any]:
    status = _normalize_optional_query_text(status)
    model = _normalize_optional_query_text(model)
    source_filter = _normalize_optional_forecast_source(source)
    clauses = []
    args: list[Any] = []
    _append_forecast_run_filters(
        clauses,
        args,
        status=status,
        model=model,
        source=source_filter,
        horizon_days=horizon_days,
    )

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                fr.id,
                fr.provider,
                fr.model,
                {FORECAST_SOURCE_SQL} AS source,
                NULLIF(fr.request_payload->>'archive_horizon_days', '')::INTEGER AS requested_archive_horizon_days,
                fr.status,
                fr.run_at,
                fr.requested_start_date,
                fr.requested_end_date,
                fr.requested_station_count,
                fr.created_at,
                fr.completed_at,
                fr.error_message,
                COUNT(fv.id) AS saved_rows,
                COUNT(DISTINCT fv.station_id) AS saved_stations,
                COALESCE(
                    ARRAY_AGG(DISTINCT fv.horizon_days) FILTER (WHERE fv.horizon_days IS NOT NULL),
                    ARRAY[]::INTEGER[]
                ) AS saved_horizon_days
            FROM forecast_runs fr
            LEFT JOIN forecast_values fv ON fv.run_id = fr.id
            {where_sql}
            GROUP BY
                fr.id,
                NULLIF(fr.request_payload->>'archive_horizon_days', '')::INTEGER
            ORDER BY fr.run_at DESC
            LIMIT ${len(args)}
            """,
            *args,
        )
    return {"returned": len(rows), "runs": [dict(row) for row in rows]}


@app.get("/api/analytics/top-errors", response_model=None)
async def top_errors(
    start_date: date,
    end_date: date,
    metric: Literal["avg_temp", "min_temp", "max_temp", "precipitation"] = "avg_temp",
    limit: int = Query(default=20, ge=1, le=200),
    only_with_coordinates: bool = True,
    model: str | None = None,
    source: str | None = None,
    horizon_days: int | None = Query(default=None, ge=1, le=7),
    request: Request = None,
    _: dict[str, Any] = Depends(get_current_viewer_auth_context),
) -> Any:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    model = _normalize_optional_query_text(model)
    source_filter = _normalize_optional_forecast_source(source, blank_default=PUBLIC_FORECAST_SOURCE)
    forecast_column = _metric_forecast_column_sql(metric)
    actual_column = _metric_actual_column_sql(metric)
    latest_forecast_clauses = ["fr.status IN ('success', 'partial_failed')"]
    args: list[Any] = []
    _append_latest_forecast_window_filters(
        latest_forecast_clauses,
        args,
        start_date=start_date,
        end_date=end_date,
        model=model,
        horizon_days=horizon_days,
    )
    latest_forecast_clauses.append(f"{forecast_column} IS NOT NULL")

    station_filters = [f"{actual_column} IS NOT NULL"]
    if only_with_coordinates:
        station_filters.append("s.latitude IS NOT NULL")
        station_filters.append("s.longitude IS NOT NULL")

    query = (
        _latest_forecast_cte_sql(
            select_fields=[f"{forecast_column} AS forecast_value"],
            where_clauses=latest_forecast_clauses,
        )
        + f"""
        , station_top_errors AS (
            SELECT DISTINCT ON (lf.station_id)
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
                lf.source,
                lf.run_at,
                ROUND(lf.forecast_value::numeric, 2) AS forecast_value,
                ROUND({actual_column}::numeric, 2) AS actual_value,
                ROUND((lf.forecast_value - {actual_column})::numeric, 2) AS signed_error,
                ROUND(ABS(lf.forecast_value - {actual_column})::numeric, 2) AS absolute_error
            FROM latest_forecast lf
            JOIN weather_data wd
              ON wd.station_id = lf.station_id
             AND wd.observation_date = lf.forecast_date
            JOIN stations s
              ON s.id = lf.station_id
            WHERE {' AND '.join(station_filters)}
            ORDER BY
                lf.station_id,
                ABS(lf.forecast_value - {actual_column}) DESC,
                lf.forecast_date DESC,
                lf.horizon_days ASC
        ),
        ranked_station_top_errors AS (
            SELECT
                *,
                DENSE_RANK() OVER (
                    ORDER BY absolute_error DESC, forecast_date DESC
                ) AS error_rank
            FROM station_top_errors
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
            source,
            run_at,
            forecast_value,
            actual_value,
            signed_error,
            absolute_error,
            error_rank
        FROM ranked_station_top_errors
        ORDER BY absolute_error DESC, forecast_date DESC, horizon_days ASC
        LIMIT ${len(args) + 1}
    """
    )

    async def _load_payload() -> dict[str, Any]:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args, limit)
        return {
            "metric": metric,
            "start_date": start_date,
            "end_date": end_date,
            "model": model,
            "source": source_filter,
            "horizon_days": horizon_days,
            "returned": len(rows),
            "items": [dict(row) for row in rows],
        }

    return await maybe_cached_json_response(
        request,
        namespace="top-errors",
        loader=_load_payload,
    )


@app.get("/api/analytics/summary", response_model=None)
async def analytics_summary(
    start_date: date,
    end_date: date,
    only_with_coordinates: bool = True,
    model: str | None = None,
    source: str | None = None,
    horizon_days: int | None = Query(default=None, ge=1, le=7),
    request: Request = None,
    _: dict[str, Any] = Depends(get_current_viewer_auth_context),
) -> Any:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    model = _normalize_optional_query_text(model)
    source_filter = _normalize_optional_forecast_source(source, blank_default=PUBLIC_FORECAST_SOURCE)
    latest_forecast_clauses = ["fr.status IN ('success', 'partial_failed')"]
    metric_args: list[Any] = []
    _append_latest_forecast_window_filters(
        latest_forecast_clauses,
        metric_args,
        start_date=start_date,
        end_date=end_date,
        model=model,
        horizon_days=horizon_days,
    )

    station_filters: list[str] = []
    if only_with_coordinates:
        station_filters.extend(["s.latitude IS NOT NULL", "s.longitude IS NOT NULL"])
    station_where_sql = f"WHERE {' AND '.join(station_filters)}" if station_filters else ""

    metrics_query = (
        _latest_forecast_cte_sql(
            select_fields=[
                "fv.avg_temp",
                "fv.min_temp",
                "fv.max_temp",
                "fv.precipitation",
            ],
            where_clauses=latest_forecast_clauses,
        )
        + f"""
        , metric_rows AS (
            SELECT
                metric_values.metric,
                metric_values.forecast_value,
                metric_values.actual_value
            FROM latest_forecast lf
            JOIN weather_data wd
              ON wd.station_id = lf.station_id
             AND wd.observation_date = lf.forecast_date
            JOIN stations s
              ON s.id = lf.station_id
            CROSS JOIN LATERAL (
                VALUES
                    ('avg_temp', lf.avg_temp::numeric, wd.avg_temp::numeric),
                    ('min_temp', lf.min_temp::numeric, wd.min_temp::numeric),
                    ('max_temp', lf.max_temp::numeric, wd.max_temp::numeric),
                    ('precipitation', lf.precipitation::numeric, wd.precipitation::numeric)
            ) AS metric_values(metric, forecast_value, actual_value)
            {station_where_sql}
        )
        SELECT
            metric,
            COUNT(*) FILTER (
                WHERE forecast_value IS NOT NULL
                  AND actual_value IS NOT NULL
            ) AS compared_points,
            ROUND(
                AVG(ABS(forecast_value - actual_value)) FILTER (
                    WHERE forecast_value IS NOT NULL
                      AND actual_value IS NOT NULL
                ),
                2
            ) AS mae,
            ROUND(
                SQRT(
                    AVG(POWER(forecast_value - actual_value, 2)) FILTER (
                        WHERE forecast_value IS NOT NULL
                          AND actual_value IS NOT NULL
                    )
                ),
                2
            ) AS rmse,
            ROUND(
                AVG(forecast_value - actual_value) FILTER (
                    WHERE forecast_value IS NOT NULL
                      AND actual_value IS NOT NULL
                ),
                2
            ) AS bias,
            ROUND(
                MAX(ABS(forecast_value - actual_value)) FILTER (
                    WHERE forecast_value IS NOT NULL
                      AND actual_value IS NOT NULL
                ),
                2
            ) AS max_absolute_error
        FROM metric_rows
        GROUP BY metric
    """
    )

    forecast_value_clauses = ["fv.forecast_date BETWEEN $1 AND $2"]
    forecast_value_args: list[Any] = [start_date, end_date]
    _append_sql_filter(forecast_value_clauses, forecast_value_args, "fr.model", model)
    _append_sql_filter(forecast_value_clauses, forecast_value_args, "fv.horizon_days", horizon_days)

    async def _load_payload() -> dict[str, Any]:
        metrics: dict[str, Any] = {
            metric_name: {
                "compared_points": 0,
                "mae": None,
                "rmse": None,
                "bias": None,
                "max_absolute_error": None,
            }
            for metric_name in METRIC_SQL_MAP
        }
        pool = get_pool()
        async with pool.acquire() as conn:
            metric_rows = await conn.fetch(metrics_query, *metric_args)
            for row in metric_rows:
                metrics[row["metric"]] = {
                    "compared_points": row["compared_points"],
                    "mae": row["mae"],
                    "rmse": row["rmse"],
                    "bias": row["bias"],
                    "max_absolute_error": row["max_absolute_error"],
                }

            totals = await conn.fetchrow(
                f"""
                SELECT
                    (SELECT COUNT(*) FROM stations) AS stations_total,
                    (SELECT COUNT(*) FROM weather_data WHERE observation_date BETWEEN $1 AND $2) AS actual_rows,
                    (
                        SELECT COUNT(*)
                        FROM forecast_values fv
                        JOIN forecast_runs fr ON fr.id = fv.run_id
                        WHERE {' AND '.join(forecast_value_clauses)}
                    ) AS forecast_rows,
                    (SELECT COUNT(*) FROM atm8c_data) AS atm8c_rows,
                    (SELECT COUNT(*) FROM srok8c_data) AS srok8c_rows
                """,
                *forecast_value_args,
            )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "model": model,
            "source": source_filter,
            "horizon_days": horizon_days,
            "metrics": metrics,
            "totals": dict(totals),
        }

    return await maybe_cached_json_response(
        request,
        namespace="summary",
        loader=_load_payload,
    )


@app.get("/api/analytics/worst-stations", response_model=None)
async def worst_stations(
    start_date: date,
    end_date: date,
    metric: Literal["avg_temp", "min_temp", "max_temp", "precipitation"] = "avg_temp",
    limit: int = Query(default=20, ge=1, le=200),
    model: str | None = None,
    source: str | None = None,
    horizon_days: int | None = Query(default=None, ge=1, le=7),
    request: Request = None,
    _: dict[str, Any] = Depends(get_current_viewer_auth_context),
) -> Any:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    model = _normalize_optional_query_text(model)
    source_filter = _normalize_optional_forecast_source(source, blank_default=PUBLIC_FORECAST_SOURCE)
    forecast_column = _metric_forecast_column_sql(metric)
    actual_column = _metric_actual_column_sql(metric)
    latest_forecast_clauses = ["fr.status IN ('success', 'partial_failed')"]
    args: list[Any] = []
    _append_latest_forecast_window_filters(
        latest_forecast_clauses,
        args,
        start_date=start_date,
        end_date=end_date,
        model=model,
        horizon_days=horizon_days,
    )
    latest_forecast_clauses.append(f"{forecast_column} IS NOT NULL")

    query = (
        _latest_forecast_cte_sql(
            select_fields=[f"{forecast_column} AS forecast_value"],
            where_clauses=latest_forecast_clauses,
        )
        + f"""
        , metric_rows AS (
            SELECT
                s.id AS station_id,
                s.wmo_index,
                s.name,
                s.country,
                s.latitude,
                s.longitude,
                ABS(lf.forecast_value - {actual_column}) AS absolute_error
            FROM latest_forecast lf
            JOIN weather_data wd
              ON wd.station_id = lf.station_id
             AND wd.observation_date = lf.forecast_date
            JOIN stations s
              ON s.id = lf.station_id
            WHERE {actual_column} IS NOT NULL
        )
        SELECT
            station_id,
            wmo_index,
            name,
            country,
            latitude,
            longitude,
            COUNT(*) AS compared_points,
            ROUND(AVG(absolute_error), 2) AS mae,
            ROUND(MAX(absolute_error), 2) AS max_absolute_error
        FROM metric_rows
        GROUP BY station_id, wmo_index, name, country, latitude, longitude
        ORDER BY mae DESC NULLS LAST, max_absolute_error DESC NULLS LAST
        LIMIT ${len(args) + 1}
    """
    )

    async def _load_payload() -> dict[str, Any]:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args, limit)
        return {
            "metric": metric,
            "start_date": start_date,
            "end_date": end_date,
            "model": model,
            "source": source_filter,
            "horizon_days": horizon_days,
            "returned": len(rows),
            "items": [dict(row) for row in rows],
        }

    return await maybe_cached_json_response(
        request,
        namespace="worst-stations",
        loader=_load_payload,
    )


@app.get("/api/analytics/station-series")
async def station_series(
    start_date: date,
    end_date: date,
    station_id: int | None = None,
    wmo_index: str | None = None,
    model: str | None = None,
    source: str | None = None,
    horizon_days: int | None = Query(default=None, ge=1, le=7),
    _: dict[str, Any] = Depends(get_current_viewer_auth_context),
) -> dict[str, Any]:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    wmo_index = _normalize_optional_query_text(wmo_index)
    model = _normalize_optional_query_text(model)
    source_filter = _normalize_optional_forecast_source(source, blank_default=PUBLIC_FORECAST_SOURCE)
    pool = get_pool()
    async with pool.acquire() as conn:
        resolved_station_id = await _resolve_station_id(
            conn,
            station_id=station_id,
            wmo_index=wmo_index,
        )
        latest_forecast_clauses = [
            "fv.station_id = $1",
            "fr.status IN ('success', 'partial_failed')",
            "fv.forecast_date BETWEEN $2 AND $3",
        ]
        latest_forecast_args: list[Any] = [resolved_station_id, start_date, end_date]
        _append_station_series_filters(
            latest_forecast_clauses,
            latest_forecast_args,
            model=model,
            source=source_filter,
            horizon_days=horizon_days,
        )

        station = await conn.fetchrow(
            """
            SELECT id, wmo_index, name, country, latitude, longitude
            FROM stations
            WHERE id = $1
            """,
            resolved_station_id,
        )

        rows = await conn.fetch(
            f"""
            WITH latest_forecast AS (
                SELECT DISTINCT ON ({latest_forecast_identity_sql()})
                    fv.forecast_date,
                    fv.horizon_days,
                    fr.provider,
                    fr.model,
                    {FORECAST_SOURCE_SQL} AS source,
                    fr.run_at,
                    fv.avg_temp AS forecast_avg_temp,
                    fv.min_temp AS forecast_min_temp,
                    fv.max_temp AS forecast_max_temp,
                    fv.precipitation AS forecast_precipitation,
                    fv.max_wind_speed AS forecast_max_wind_speed
                FROM forecast_values fv
                JOIN forecast_runs fr ON fr.id = fv.run_id
                WHERE {' AND '.join(latest_forecast_clauses)}
                ORDER BY {latest_forecast_order_by_sql()}
            )
            SELECT
                wd.observation_date,
                lf.source,
                lf.provider,
                lf.model,
                lf.run_at,
                lf.horizon_days,
                wd.avg_temp AS actual_avg_temp,
                lf.forecast_avg_temp,
                ROUND((lf.forecast_avg_temp - wd.avg_temp)::numeric, 2) AS error_avg_temp,
                wd.min_temp AS actual_min_temp,
                lf.forecast_min_temp,
                ROUND((lf.forecast_min_temp - wd.min_temp)::numeric, 2) AS error_min_temp,
                wd.max_temp AS actual_max_temp,
                lf.forecast_max_temp,
                ROUND((lf.forecast_max_temp - wd.max_temp)::numeric, 2) AS error_max_temp,
                wd.precipitation AS actual_precipitation,
                lf.forecast_precipitation,
                ROUND((lf.forecast_precipitation - wd.precipitation)::numeric, 2) AS error_precipitation,
                lf.forecast_max_wind_speed
            FROM weather_data wd
            LEFT JOIN latest_forecast lf
                ON lf.forecast_date = wd.observation_date
            WHERE wd.station_id = $1
              AND wd.observation_date BETWEEN $2 AND $3
            ORDER BY wd.observation_date, lf.horizon_days NULLS FIRST, lf.model NULLS FIRST, lf.source NULLS FIRST
            """,
            *latest_forecast_args,
        )

    return {
        "station": dict(station),
        "start_date": start_date,
        "end_date": end_date,
        "model": model,
        "source": source_filter,
        "horizon_days": horizon_days,
        "returned": len(rows),
        "items": [dict(row) for row in rows],
    }


@app.get("/api/analytics/coverage")
async def analytics_coverage(
    _: dict[str, Any] = Depends(get_current_admin_auth_context),
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM stations) AS stations_total,
                (SELECT COUNT(*) FROM stations WHERE latitude IS NOT NULL AND longitude IS NOT NULL)
                    AS stations_with_coordinates,
                (SELECT COUNT(*) FROM forecast_runs) AS forecast_runs_total,
                (SELECT COUNT(*) FROM forecast_values) AS forecast_values_total,
                (SELECT COUNT(*) FROM raw_forecast_events) AS raw_forecast_events_total,
                (SELECT COUNT(*) FROM raw_telemetry_events) AS raw_telemetry_events_total,
                (
                    SELECT COALESCE(EXTRACT(EPOCH FROM NOW() - MIN(ingested_at)), 0)
                    FROM raw_telemetry_events
                    WHERE processed_at IS NULL
                ) AS raw_telemetry_oldest_unprocessed_age_seconds,
                (
                    SELECT COALESCE(EXTRACT(EPOCH FROM NOW() - MIN(ingested_at)), 0)
                    FROM raw_forecast_events
                    WHERE processed_at IS NULL
                ) AS raw_forecast_oldest_unprocessed_age_seconds,
                (SELECT COUNT(*) FROM weather_data) AS weather_rows_total,
                (SELECT COUNT(*) FROM service_outbox) AS outbox_total,
                (SELECT COUNT(*) FROM service_outbox WHERE status = 'pending') AS outbox_pending_total,
                (SELECT COUNT(*) FROM service_outbox WHERE status = 'processing') AS outbox_processing_total,
                (SELECT COUNT(*) FROM service_outbox WHERE status = 'published') AS outbox_published_total,
                (SELECT COUNT(*) FROM service_outbox WHERE status = 'failed') AS outbox_failed_total,
                (
                    SELECT COALESCE(EXTRACT(EPOCH FROM NOW() - MIN(available_at)), 0)
                    FROM service_outbox
                    WHERE status = 'pending'
                      AND available_at <= NOW()
                ) AS outbox_oldest_pending_age_seconds,
                (SELECT COUNT(*) FROM atm8c_data) AS atm8c_rows_total,
                (SELECT COUNT(*) FROM srok8c_data) AS srok8c_rows_total,
                (SELECT MIN(observation_date) FROM weather_data) AS weather_start_date,
                (SELECT MAX(observation_date) FROM weather_data) AS weather_end_date,
                (SELECT MIN(forecast_date) FROM forecast_values) AS forecast_start_date,
                (SELECT MAX(forecast_date) FROM forecast_values) AS forecast_end_date
            """
        )
    return dict(row)


@app.get("/api/analytics/forecast-coverage")
async def forecast_coverage(
    start_date: date | None = None,
    end_date: date | None = None,
    model: str | None = None,
    source: str | None = None,
    horizon_days: int | None = Query(default=None, ge=1, le=7),
    _: dict[str, Any] = Depends(get_current_viewer_auth_context),
) -> dict[str, Any]:
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

    model = _normalize_optional_query_text(model)
    source_filter = _normalize_optional_forecast_source(source, blank_default=PUBLIC_FORECAST_SOURCE)
    clauses = ["fr.status IN ('success', 'partial_failed')"]
    args: list[Any] = []
    if start_date is not None:
        clauses.append(f"fv.forecast_date >= ${len(args) + 1}")
        args.append(start_date)
    if end_date is not None:
        clauses.append(f"fv.forecast_date <= ${len(args) + 1}")
        args.append(end_date)
    _append_station_series_filters(
        clauses,
        args,
        model=model,
        source=source_filter,
        horizon_days=horizon_days,
    )

    query = f"""
        SELECT
            fr.model,
            {FORECAST_SOURCE_SQL} AS source,
            fv.horizon_days,
            COUNT(*) AS forecast_rows,
            COUNT(DISTINCT fv.run_id) AS run_count,
            COUNT(DISTINCT fv.station_id) AS station_count,
            MIN(fv.forecast_date) AS forecast_start_date,
            MAX(fv.forecast_date) AS forecast_end_date,
            COUNT(*) FILTER (WHERE fv.avg_temp IS NOT NULL) AS avg_temp_rows,
            COUNT(*) FILTER (WHERE fv.min_temp IS NOT NULL) AS min_temp_rows,
            COUNT(*) FILTER (WHERE fv.max_temp IS NOT NULL) AS max_temp_rows,
            COUNT(*) FILTER (WHERE fv.precipitation IS NOT NULL) AS precipitation_rows,
            COUNT(*) FILTER (WHERE fv.max_wind_speed IS NOT NULL) AS max_wind_speed_rows
        FROM forecast_values fv
        JOIN forecast_runs fr ON fr.id = fv.run_id
        WHERE {' AND '.join(clauses)}
        GROUP BY fr.model, fv.horizon_days
        ORDER BY fr.model, source, fv.horizon_days
    """

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "model": model,
        "source": source_filter,
        "horizon_days": horizon_days,
        "returned": len(rows),
        "items": [dict(row) for row in rows],
    }
