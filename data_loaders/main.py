"""Weather data HTTP service."""

import os
from datetime import date
from typing import Optional

import asyncpg
from aiohttp import web

try:
    from .loader import run_initial_load
    from .migration import run_migration
except ImportError:
    from loader import run_initial_load
    from migration import run_migration


DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/weather")
PORT = int(os.getenv("PORT", "8080"))


async def init_db(pool: asyncpg.Pool) -> None:
    """Initialize database and run migrations."""
    await run_migration(pool)


async def get_weather_pool() -> asyncpg.Pool:
    """Get or create database pool."""
    if not hasattr(get_weather_pool, "pool"):
        get_weather_pool.pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=5)
    return get_weather_pool.pool


async def get_avg_temperature(request: web.Request) -> web.Response:
    """
    Get average temperature for stations on a specific date.

    Query params:
    - date: Date in YYYY-MM-DD format (required)
    """
    date_str = request.query.get("date")

    if not date_str:
        return web.json_response(
            {"error": "Missing required parameter: date"},
            status=400
        )

    try:
        query_date = date.fromisoformat(date_str)
    except ValueError:
        return web.json_response(
            {"error": "Invalid date format. Use YYYY-MM-DD"},
            status=400
        )

    pool = await get_weather_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.wmo_index, s.name, s.country, wd.avg_temp
            FROM weather_data wd
            JOIN stations s ON s.id = wd.station_id
            WHERE wd.observation_date = $1
            ORDER BY s.wmo_index
        """, query_date)

    if not rows:
        return web.json_response(
            {"date": date_str, "stations": [],
                "message": "No data found for this date"},
            status=200
        )

    stations = [
        {"wmo_index": row["wmo_index"], "name": row["name"],
            "country": row["country"], "avg_temp": float(row["avg_temp"])}
        for row in rows
    ]

    return web.json_response({
        "date": date_str,
        "stations": stations
    })


async def health_check(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({"status": "ok"})


async def on_startup(app: web.Application) -> None:
    """Initialize database and load data on startup."""
    print("[APP] Starting weather data service...", flush=True)
    pool = await get_weather_pool()
    print("[APP] Database connected", flush=True)
    await init_db(pool)
    print("[APP] Database schema initialized", flush=True)
    print("[APP] Loading initial data...", flush=True)
    await run_initial_load(pool)
    print("[APP] Service ready", flush=True)


def create_app() -> web.Application:
    """Create and configure the application."""
    app = web.Application()
    app.router.add_get("/health", health_check)
    app.router.add_get("/api/avg-temperature", get_avg_temperature)
    app.on_startup.append(on_startup)
    return app


def main() -> None:
    """Run the application."""
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
