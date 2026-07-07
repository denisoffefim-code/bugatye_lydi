"""External data clients used by SkyCast."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence

import aiohttp


class AsyncRateLimiter:
    """Tiny async rate limiter based on minimal spacing between requests."""

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 0.0 if requests_per_second <= 0 else 1.0 / requests_per_second
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            delay = self._min_interval - (now - self._last_call)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_call = asyncio.get_running_loop().time()


@dataclass(frozen=True)
class NoaaStationMetadata:
    wmo_index: str
    noaa_station_id: str
    name: str
    latitude: Decimal
    longitude: Decimal
    elevation_m: Decimal | None


@dataclass(frozen=True)
class ForecastRecord:
    forecast_date: date
    horizon_days: int
    avg_temp: Decimal | None
    min_temp: Decimal | None
    max_temp: Decimal | None
    precipitation: Decimal | None
    max_wind_speed: Decimal | None


def _to_decimal(value: Any, digits: int) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(digits * "0").scaleb(-digits))


def _parse_igra_station_list(content: str) -> dict[str, NoaaStationMetadata]:
    stations: dict[str, NoaaStationMetadata] = {}
    for line in content.splitlines():
        if len(line) < 71:
            continue
        noaa_station_id = line[0:11].strip()
        wmo_index = noaa_station_id[-5:]
        latitude = line[12:20].strip()
        longitude = line[21:30].strip()
        elevation = line[31:37].strip()
        name = line[41:71].strip()

        if latitude in {"", "-98.8888"} or longitude in {"", "-998.8888"}:
            continue

        stations[wmo_index] = NoaaStationMetadata(
            wmo_index=wmo_index,
            noaa_station_id=noaa_station_id,
            name=name,
            latitude=Decimal(latitude),
            longitude=Decimal(longitude),
            elevation_m=None if not elevation else Decimal(elevation),
        )
    return stations


async def fetch_noaa_station_metadata(
    session: aiohttp.ClientSession,
    url: str,
) -> dict[str, NoaaStationMetadata]:
    """Download and parse NOAA IGRA station metadata."""
    async with session.get(url) as response:
        response.raise_for_status()
        content = await response.text()
    return _parse_igra_station_list(content)


async def with_retries(coro_factory, *, retries: int = 3, base_delay: float = 1.0):
    """Retry a coroutine with exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return await coro_factory()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = exc
            if attempt == retries - 1:
                break
            await asyncio.sleep(base_delay * (2 ** attempt))
    if last_error is None:
        raise RuntimeError("Retry loop failed without an exception")
    raise last_error


async def fetch_open_meteo_forecast(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    latitude: Decimal,
    longitude: Decimal,
    start_date: date,
    end_date: date,
    model: str,
) -> tuple[list[ForecastRecord], dict[str, Any]]:
    """Fetch daily forecast aggregates for a single station."""
    params = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "timezone": "UTC",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "models": model,
        "daily": ",".join(
            [
                "temperature_2m_mean",
                "temperature_2m_min",
                "temperature_2m_max",
                "precipitation_sum",
                "wind_speed_10m_max",
            ]
        ),
    }

    async with session.get(f"{base_url}/v1/forecast", params=params) as response:
        response.raise_for_status()
        payload = await response.json()

    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    avg_values = daily.get("temperature_2m_mean") or []
    min_values = daily.get("temperature_2m_min") or []
    max_values = daily.get("temperature_2m_max") or []
    precipitation_values = daily.get("precipitation_sum") or []
    wind_values = daily.get("wind_speed_10m_max") or []
    run_date = datetime.now(timezone.utc).date()

    records: list[ForecastRecord] = []
    for index, raw_date in enumerate(dates):
        forecast_date = date.fromisoformat(raw_date)
        records.append(
            ForecastRecord(
                forecast_date=forecast_date,
                horizon_days=(forecast_date - run_date).days,
                avg_temp=_to_decimal(avg_values[index] if index < len(avg_values) else None, 1),
                min_temp=_to_decimal(min_values[index] if index < len(min_values) else None, 1),
                max_temp=_to_decimal(max_values[index] if index < len(max_values) else None, 1),
                precipitation=_to_decimal(
                    precipitation_values[index] if index < len(precipitation_values) else None,
                    1,
                ),
                max_wind_speed=_to_decimal(
                    wind_values[index] if index < len(wind_values) else None,
                    1,
                ),
            )
        )

    return records, payload
