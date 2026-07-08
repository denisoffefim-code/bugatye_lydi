"""Data loader for weather data from S3."""

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import date, time as dt_time
from typing import Dict, List, Optional, Tuple

import asyncpg
import aiohttp


#URLs
STATIONS_URL = "https://storage.yandexcloud.net/ds-2607-data/tttr/statlist378320a2.txt"
FIELDS_URL = "https://storage.yandexcloud.net/ds-2607-data/tttr/fld378320a2.txt"
DATA_URL = "https://storage.yandexcloud.net/ds-2607-data/tttr/wr378320a2.txt"

FIELDS_URL_ATM8C = "https://storage.yandexcloud.net/ds-2607-data/atm8c/fld378320a4.txt"
DATA_URL_ATM8C = "https://storage.yandexcloud.net/ds-2607-data/atm8c/wr378320a4.txt"

FIELDS_URL_SROK8C = "https://storage.yandexcloud.net/ds-2607-data/srok8c/fld378320a5.txt"
DATA_URL_SROK8C = "https://storage.yandexcloud.net/ds-2607-data/srok8c/wr378320a5.txt"

DEFAULT_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DEFAULT_WEATHER_BATCH_SIZE = 25000
DEFAULT_ATM8C_BATCH_SIZE = 50000
DEFAULT_SROK8C_BATCH_SIZE = 10000
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_RETRY_DELAY_SECONDS = 5
DEFAULT_HTTP_TOTAL_TIMEOUT_SECONDS = 7200
DEFAULT_HTTP_CONNECT_TIMEOUT_SECONDS = 60
DEFAULT_HTTP_SOCK_READ_TIMEOUT_SECONDS = 600
RETRYABLE_LOADER_ERRORS = (
    aiohttp.ClientPayloadError,
    aiohttp.ClientConnectionError,
    aiohttp.ClientError,
    asyncio.TimeoutError,
    asyncpg.PostgresConnectionError,
    asyncpg.InterfaceError,
)


# Shared helper functions

@dataclass
class LoaderRuntimeConfig:
    download_chunk_size: int = DEFAULT_DOWNLOAD_CHUNK_SIZE
    weather_batch_size: int = DEFAULT_WEATHER_BATCH_SIZE
    atm8c_batch_size: int = DEFAULT_ATM8C_BATCH_SIZE
    srok8c_batch_size: int = DEFAULT_SROK8C_BATCH_SIZE
    max_retries: int = DEFAULT_MAX_RETRIES
    initial_retry_delay_seconds: int = DEFAULT_INITIAL_RETRY_DELAY_SECONDS


LOADER_CONFIG = LoaderRuntimeConfig()


def _require_positive_int(name: str, value: int) -> int:
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")
    return value


def configure_loader(
    *,
    download_chunk_size: Optional[int] = None,
    weather_batch_size: Optional[int] = None,
    atm8c_batch_size: Optional[int] = None,
    srok8c_batch_size: Optional[int] = None,
    max_retries: Optional[int] = None,
    initial_retry_delay_seconds: Optional[int] = None,
) -> LoaderRuntimeConfig:
    updates = {}
    if download_chunk_size is not None:
        updates["download_chunk_size"] = _require_positive_int("download_chunk_size", download_chunk_size)
    if weather_batch_size is not None:
        updates["weather_batch_size"] = _require_positive_int("weather_batch_size", weather_batch_size)
    if atm8c_batch_size is not None:
        updates["atm8c_batch_size"] = _require_positive_int("atm8c_batch_size", atm8c_batch_size)
    if srok8c_batch_size is not None:
        updates["srok8c_batch_size"] = _require_positive_int("srok8c_batch_size", srok8c_batch_size)
    if max_retries is not None:
        updates["max_retries"] = _require_positive_int("max_retries", max_retries)
    if initial_retry_delay_seconds is not None:
        updates["initial_retry_delay_seconds"] = _require_positive_int(
            "initial_retry_delay_seconds",
            initial_retry_delay_seconds,
        )

    for key, value in updates.items():
        setattr(LOADER_CONFIG, key, value)

    return LOADER_CONFIG

def parse_field_definitions(content: str) -> Dict[str, int]:
    fields = {}
    for line in content.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 4:
            width_str = parts[2].replace(',', '.')
            width = int(float(width_str))
            name = " ".join(parts[3:])
            fields[name] = width
    return fields


def parse_field_widths(content: str) -> List[int]:
    widths = []
    for line in content.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 3:
            width_str = parts[2].replace(",", ".")
            widths.append(int(float(width_str)))
    return widths


def parse_stations(content: str) -> List[Tuple[str, str, Optional[str]]]:
    stations = []
    for line in content.strip().split("\n"):
        if line.strip():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                name_country = parts[1].strip()
                segments = re.split(r'\s{2,}', name_country)
                if len(segments) >= 2:
                    name = segments[0].strip()
                    country = segments[-1].strip()
                else:
                    name = name_country
                    country = None
                stations.append((parts[0], name, country))
    return stations


def _compute_positions(field_names: List[str], field_widths: Dict[str, int]) -> List[Tuple[int, int]]:
    positions = []
    pos = 0
    for name in field_names:
        width = field_widths.get(name, 5)
        positions.append((pos, pos + width))
        pos += width + 1
    return positions


def _compute_positions_from_widths(widths: List[int], expected_count: int) -> List[Tuple[int, int]]:
    if len(widths) != expected_count:
        raise RuntimeError(
            f"Field definition count mismatch: expected {expected_count}, got {len(widths)}"
        )

    positions = []
    pos = 0
    for width in widths:
        positions.append((pos, pos + width))
        pos += width + 1
    return positions


def _parse_time_from_str(s: str) -> Optional[dt_time]:
    if not s or s.strip() == '':
        return None
    parts = s.replace(',', ' ').split()
    if len(parts) < 2:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
        return dt_time(hour=h, minute=m)
    except ValueError:
        return None


def _normalize_optional_token(value: str) -> Optional[str]:
    token = value.strip()
    if not token:
        return None
    if set(token) == {"/"}:
        return None
    return token


def _parse_optional_int(value: str) -> Optional[int]:
    token = _normalize_optional_token(value)
    if token is None:
        return None
    return int(token)


def _parse_optional_float(value: str) -> Optional[float]:
    token = _normalize_optional_token(value)
    if token is None:
        return None
    return float(token.replace(",", "."))


async def fetch_url(session, url: str) -> str:
    async with session.get(url) as response:
        return await response.text()


# Progress helpers

async def get_load_progress(conn: asyncpg.Connection, source: str) -> int:
    row = await conn.fetchrow(
        "SELECT byte_offset FROM load_progress WHERE source_name = $1",
        source
    )
    return row["byte_offset"] if row else 0


async def update_load_progress(conn: asyncpg.Connection, source: str, byte_offset: int) -> None:
    await conn.execute("""
        INSERT INTO load_progress (source_name, byte_offset, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (source_name)
        DO UPDATE SET byte_offset = $2, updated_at = NOW()
    """, source, byte_offset)


async def is_source_loaded(conn: asyncpg.Connection, source: str) -> bool:
    row = await conn.fetchrow(
        "SELECT loaded FROM load_progress WHERE source_name = $1",
        source
    )
    return row["loaded"] if row else False


async def mark_source_loaded(conn: asyncpg.Connection, source: str) -> None:
    await conn.execute("""
        INSERT INTO load_progress (source_name, byte_offset, loaded, updated_at)
        VALUES ($1, 0, TRUE, NOW())
        ON CONFLICT (source_name)
        DO UPDATE SET loaded = TRUE, updated_at = NOW()
    """, source)


async def ensure_stations_loaded(conn: asyncpg.Connection) -> None:
    stations_count = await conn.fetchval("SELECT COUNT(*) FROM stations")
    if not stations_count:
        raise RuntimeError(
            "Stations table is empty. Load 'stations' before loading weather, ATM8C, or SROK8C data."
        )


# Stations load

async def load_stations(pool: asyncpg.Pool, session) -> None:
    print("[LOADER] Loading stations...", flush=True)
    content = await fetch_url(session, STATIONS_URL)
    stations = parse_stations(content)

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO stations (wmo_index, name, country)
            VALUES ($1, $2, $3)
            ON CONFLICT (wmo_index) DO NOTHING
            """,
            stations
        )
        await mark_source_loaded(conn, "stations")

    print(f"[LOADER] Stations loaded: {len(stations)}", flush=True)


# Weather (tttr)

async def insert_weather_batch(conn: asyncpg.Connection, batch: List) -> None:
    if not batch:
        return
    records = []
    for wmo_index, year, month, day, quality, min_temp, avg_temp, max_temp, precip in batch:
        obs_date = date(year, month, day)
        records.append((wmo_index, obs_date, quality, min_temp, avg_temp, max_temp, precip))
    await conn.copy_records_to_table(
        "temp_weather",
        records=records,
        columns=["wmo_index", "obs_date", "quality_flag", "min_temp", "avg_temp", "max_temp", "precipitation"],
    )
    await conn.execute("""
        INSERT INTO weather_data (station_id, observation_date, quality_flag,
                                  min_temp, avg_temp, max_temp, precipitation)
        SELECT s.id, t.obs_date, t.quality_flag,
               t.min_temp, t.avg_temp, t.max_temp, t.precipitation
        FROM temp_weather t
        JOIN stations s ON s.wmo_index = t.wmo_index
    """)


async def ensure_temp_weather_table(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TEMP TABLE IF NOT EXISTS temp_weather (
            wmo_index VARCHAR(5),
            obs_date DATE,
            quality_flag VARCHAR(1),
            min_temp DECIMAL(5,1),
            avg_temp DECIMAL(5,1),
            max_temp DECIMAL(5,1),
            precipitation DECIMAL(5,1)
        ) ON COMMIT DELETE ROWS
    """)


async def flush_weather_batch(pool: asyncpg.Pool, batch: List, bytes_processed: int) -> None:
    if not batch:
        return
    async with pool.acquire() as conn:
        await ensure_temp_weather_table(conn)
        async with conn.transaction():
            await insert_weather_batch(conn, batch)
            await update_load_progress(conn, "weather_data", bytes_processed)


async def load_weather_data(pool: asyncpg.Pool, session) -> None:
    fields_content = await fetch_url(session, FIELDS_URL)
    field_widths = parse_field_widths(fields_content)

    field_names = ["Индекс ВМО", "Год", "Месяц", "День", "Общий признак качества температур",
                   "Минимальная температура воздуха", "Средняя температура воздуха",
                   "Максимальная температура воздуха", "Количество осадков"]
    positions = _compute_positions_from_widths(field_widths, len(field_names))

    async with pool.acquire() as conn:
        await ensure_stations_loaded(conn)
        last_byte_offset = await get_load_progress(conn, "weather_data")
        if await is_source_loaded(conn, "weather_data"):
            print("[LOADER] Weather data already loaded, skipping.", flush=True)
            return

    chunk_size = LOADER_CONFIG.download_chunk_size
    batch_size = LOADER_CONFIG.weather_batch_size
    max_retries = LOADER_CONFIG.max_retries
    retry_delay = LOADER_CONFIG.initial_retry_delay_seconds

    for attempt in range(max_retries):
        start_time = time.time()
        last_report_time = start_time

        try:
            headers = {}
            if last_byte_offset > 0:
                headers["Range"] = f"bytes={last_byte_offset}-"
                print(f"[LOADER] Resuming weather from byte {last_byte_offset} (attempt {attempt+1})", flush=True)
            else:
                print(f"[LOADER] Starting fresh weather download (attempt {attempt+1})", flush=True)

            async with session.get(DATA_URL, headers=headers) as response:
                if response.status == 416:
                    print("[LOADER] File already fully downloaded, marking loaded.", flush=True)
                    async with pool.acquire() as conn:
                        await mark_source_loaded(conn, "weather_data")
                    return

                if response.status not in (200, 206):
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")

                batch = []
                bytes_processed = last_byte_offset
                buffer = b""
                lines_processed = 0
                content_length = int(response.headers.get('content-length', 0))

                async for chunk in response.content.iter_chunked(chunk_size):
                    buffer += chunk
                    while b'\n' in buffer:
                        line_bytes, buffer = buffer.split(b'\n', 1)
                        bytes_processed += len(line_bytes) + 1
                        try:
                            line_str = line_bytes.decode('utf-8')
                        except UnicodeDecodeError:
                            continue
                        if not line_str.strip():
                            continue

                        lines_processed += 1
                        try:
                            values = []
                            for start, end in positions:
                                values.append(line_str[start:end].strip())

                            wmo_index = values[0]
                            year = int(values[1])
                            month = int(values[2])
                            day = int(values[3])
                            quality = values[4]
                            min_temp = _parse_optional_float(values[5])
                            avg_temp = _parse_optional_float(values[6])
                            max_temp = _parse_optional_float(values[7])
                            precip = _parse_optional_float(values[8])

                            batch.append((wmo_index, year, month, day, quality, min_temp, avg_temp, max_temp, precip))
                        except (ValueError, IndexError):
                            continue

                        if len(batch) >= batch_size:
                            await flush_weather_batch(pool, batch, bytes_processed)
                            batch = []

                    if time.time() - last_report_time >= 1.0:
                        elapsed = time.time() - start_time
                        rate = lines_processed / elapsed if elapsed > 0 else 0
                        progress = f" {bytes_processed}/{content_length} bytes" if content_length > 0 else ""
                        print(f"[LOADER] Weather: {lines_processed} lines, {bytes_processed} bytes{progress}, {rate:.0f} lines/sec", flush=True)
                        last_report_time = time.time()

                if buffer:
                    line_str = ""
                    try:
                        line_str = buffer.decode('utf-8')
                        if line_str.strip():
                            lines_processed += 1
                            values = []
                            for start, end in positions:
                                values.append(line_str[start:end].strip())
                            wmo_index = values[0]
                            year = int(values[1])
                            month = int(values[2])
                            day = int(values[3])
                            quality = values[4]
                            min_temp = _parse_optional_float(values[5])
                            avg_temp = _parse_optional_float(values[6])
                            max_temp = _parse_optional_float(values[7])
                            precip = _parse_optional_float(values[8])
                            batch.append((wmo_index, year, month, day, quality, min_temp, avg_temp, max_temp, precip))
                    except (ValueError, IndexError, UnicodeDecodeError):
                        pass

                if batch:
                    await flush_weather_batch(pool, batch, bytes_processed)

                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await mark_source_loaded(conn, "weather_data")
                elapsed = time.time() - start_time
                rate = lines_processed / elapsed if elapsed > 0 else 0
                print(f"[LOADER] Weather loading complete: {lines_processed} lines, {bytes_processed} bytes, {rate:.0f} lines/sec", flush=True)
                break

        except RETRYABLE_LOADER_ERRORS as e:
            print(f"[LOADER] Weather connection/timeout error: {e}", flush=True)
            if attempt < max_retries - 1:
                print(f"[LOADER] Retrying in {retry_delay} seconds...", flush=True)
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
                async with pool.acquire() as conn:
                    last_byte_offset = await get_load_progress(conn, "weather_data")
            else:
                raise
        except Exception as e:
            print(f"[LOADER] Unexpected weather error: {e}", flush=True)
            raise


# ATM8C

async def insert_atm8c_batch(conn: asyncpg.Connection, batch: List) -> None:
    if not batch:
        return
    await conn.copy_records_to_table("temp_atm8c", records=batch, columns=[
        "wmo_index", "year_gmt", "month_gmt", "day_gmt", "hour_gmt",
        "year_src", "month_src", "day_src", "hour_src",
        "period_number", "local_time", "timezone", "day_start",
        "phen_code", "phen_type", "intensity",
        "start_time", "end_time",
    ])
    await conn.execute("""
        INSERT INTO atm8c_data (
            station_id, year_gmt, month_gmt, day_gmt, hour_gmt,
            year_src, month_src, day_src, hour_src,
            period_number, local_time, timezone, day_start,
            phenomenon_code, phenomenon_type, intensity,
            start_time, end_time
        )
        SELECT s.id, t.year_gmt, t.month_gmt, t.day_gmt, t.hour_gmt,
               t.year_src, t.month_src, t.day_src, t.hour_src,
               t.period_number, t.local_time, t.timezone, t.day_start,
               t.phen_code, t.phen_type, t.intensity,
               t.start_time, t.end_time
        FROM temp_atm8c t
        JOIN stations s ON s.wmo_index = t.wmo_index
    """)


async def ensure_temp_atm8c_table(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TEMP TABLE IF NOT EXISTS temp_atm8c (
            wmo_index VARCHAR(5),
            year_gmt INTEGER, month_gmt INTEGER, day_gmt INTEGER, hour_gmt INTEGER,
            year_src INTEGER, month_src INTEGER, day_src INTEGER, hour_src INTEGER,
            period_number INTEGER, local_time INTEGER, timezone INTEGER, day_start INTEGER,
            phen_code INTEGER, phen_type INTEGER, intensity INTEGER,
            start_time TIME, end_time TIME
        ) ON COMMIT DELETE ROWS
    """)


async def flush_atm8c_batch(pool: asyncpg.Pool, batch: List, bytes_processed: int) -> None:
    if not batch:
        return
    async with pool.acquire() as conn:
        await ensure_temp_atm8c_table(conn)
        async with conn.transaction():
            await insert_atm8c_batch(conn, batch)
            await update_load_progress(conn, "atm8c_data", bytes_processed)


async def load_atm8c_data(pool: asyncpg.Pool, session) -> None:
    fields_content = await fetch_url(session, FIELDS_URL_ATM8C)
    field_widths = parse_field_widths(fields_content)

    field_names = [
        "Синоптический индекс станции",
        "Год по Гринвичу",
        "Месяц по Гринвичу",
        "День по Гринвичу",
        "Срок по Гринвичу",
        "Год источника (местный)",
        "Месяц источника (местный)",
        "День источника (местный)",
        "Срок источника",
        "Номер срока в сутках по ПДЗВ",
        "Время местное",
        "Номер часового пояса",
        "Начало метеорологических суток по ПДЗВ",
        "Номер атмосферного явления",
        "Шифр атмосферного явления",
        "Интенсивность атмосферного явления",
        "Время начала АЯ (нат.значение часы, мин)",
        "Время окончания АЯ (нат.значение часы, мин)"
    ]
    positions = _compute_positions_from_widths(field_widths, len(field_names))

    async with pool.acquire() as conn:
        await ensure_stations_loaded(conn)
        last_byte_offset = await get_load_progress(conn, "atm8c_data")
        if await is_source_loaded(conn, "atm8c_data"):
            print("[LOADER] ATM8C data already loaded, skipping.", flush=True)
            return

    chunk_size = LOADER_CONFIG.download_chunk_size
    batch_size = LOADER_CONFIG.atm8c_batch_size
    max_retries = LOADER_CONFIG.max_retries
    retry_delay = LOADER_CONFIG.initial_retry_delay_seconds

    for attempt in range(max_retries):
        start_time = time.time()
        last_report_time = start_time

        try:
            headers = {}
            if last_byte_offset > 0:
                headers["Range"] = f"bytes={last_byte_offset}-"
                print(f"[LOADER] Resuming ATM8C from byte {last_byte_offset} (attempt {attempt+1})", flush=True)
            else:
                print(f"[LOADER] Starting fresh ATM8C download (attempt {attempt+1})", flush=True)

            async with session.get(DATA_URL_ATM8C, headers=headers) as response:
                if response.status == 416:
                    print("[LOADER] ATM8C file already fully downloaded, marking loaded.", flush=True)
                    async with pool.acquire() as conn:
                        await mark_source_loaded(conn, "atm8c_data")
                    return

                if response.status not in (200, 206):
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")

                batch = []
                bytes_processed = last_byte_offset
                buffer = b""
                lines_processed = 0
                content_length = int(response.headers.get('content-length', 0))

                async for chunk in response.content.iter_chunked(chunk_size):
                    buffer += chunk
                    while b'\n' in buffer:
                        line_bytes, buffer = buffer.split(b'\n', 1)
                        bytes_processed += len(line_bytes) + 1
                        try:
                            line_str = line_bytes.decode('utf-8')
                        except UnicodeDecodeError:
                            continue
                        if not line_str.strip():
                            continue

                        lines_processed += 1
                        try:
                            values = []
                            for start, end in positions:
                                values.append(line_str[start:end].strip())

                            wmo = values[0]
                            year_gmt = int(values[1])
                            month_gmt = int(values[2])
                            day_gmt = int(values[3])
                            hour_gmt = int(values[4])
                            year_src = int(values[5])
                            month_src = int(values[6])
                            day_src = int(values[7])
                            hour_src = int(values[8])
                            period_num = _parse_optional_int(values[9])
                            local_time = _parse_optional_int(values[10])
                            timezone = _parse_optional_int(values[11])
                            day_start = _parse_optional_int(values[12])
                            phen_code = _parse_optional_int(values[13])
                            phen_type = _parse_optional_int(values[14])
                            intensity = _parse_optional_int(values[15])
                            phen_start = _parse_time_from_str(values[16])
                            phen_end = _parse_time_from_str(values[17])

                            batch.append((wmo, year_gmt, month_gmt, day_gmt, hour_gmt,
                                          year_src, month_src, day_src, hour_src,
                                          period_num, local_time, timezone, day_start,
                                          phen_code, phen_type, intensity,
                                          phen_start, phen_end))
                        except (ValueError, IndexError):
                            continue

                        if len(batch) >= batch_size:
                            await flush_atm8c_batch(pool, batch, bytes_processed)
                            batch = []

                    if time.time() - last_report_time >= 1.0:
                        elapsed = time.time() - start_time
                        rate = lines_processed / elapsed if elapsed > 0 else 0
                        progress = f" {bytes_processed}/{content_length} bytes" if content_length > 0 else ""
                        print(f"[LOADER] ATM8C: {lines_processed} lines, {bytes_processed} bytes{progress}, {rate:.0f} lines/sec", flush=True)
                        last_report_time = time.time()

                if buffer:
                    line_str = ""
                    try:
                        line_str = buffer.decode('utf-8')
                        if line_str.strip():
                            lines_processed += 1
                            values = []
                            for start, end in positions:
                                values.append(line_str[start:end].strip())
                            wmo = values[0]
                            year_gmt = int(values[1])
                            month_gmt = int(values[2])
                            day_gmt = int(values[3])
                            hour_gmt = int(values[4])
                            year_src = int(values[5])
                            month_src = int(values[6])
                            day_src = int(values[7])
                            hour_src = int(values[8])
                            period_num = _parse_optional_int(values[9])
                            local_time = _parse_optional_int(values[10])
                            timezone = _parse_optional_int(values[11])
                            day_start = _parse_optional_int(values[12])
                            phen_code = _parse_optional_int(values[13])
                            phen_type = _parse_optional_int(values[14])
                            intensity = _parse_optional_int(values[15])
                            phen_start = _parse_time_from_str(values[16])
                            phen_end = _parse_time_from_str(values[17])
                            batch.append((wmo, year_gmt, month_gmt, day_gmt, hour_gmt,
                                          year_src, month_src, day_src, hour_src,
                                          period_num, local_time, timezone, day_start,
                                          phen_code, phen_type, intensity,
                                          phen_start, phen_end))
                    except (ValueError, IndexError, UnicodeDecodeError):
                        pass

                if batch:
                    await flush_atm8c_batch(pool, batch, bytes_processed)

                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await mark_source_loaded(conn, "atm8c_data")
                elapsed = time.time() - start_time
                rate = lines_processed / elapsed if elapsed > 0 else 0
                print(f"[LOADER] ATM8C loading complete: {lines_processed} lines, {bytes_processed} bytes, {rate:.0f} lines/sec", flush=True)
                break

        except RETRYABLE_LOADER_ERRORS as e:
            print(f"[LOADER] ATM8C connection/timeout error: {e}", flush=True)
            if attempt < max_retries - 1:
                print(f"[LOADER] Retrying in {retry_delay} seconds...", flush=True)
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
                async with pool.acquire() as conn:
                    last_byte_offset = await get_load_progress(conn, "atm8c_data")
            else:
                raise
        except Exception as e:
            print(f"[LOADER] Unexpected ATM8C error: {e}", flush=True)
            raise


# SROK8C

async def insert_srok8c_batch(conn: asyncpg.Connection, batch: List) -> int:
    if not batch:
        return 0
    await conn.copy_records_to_table("temp_srok8c", records=batch, columns=[
        "wmo_index",
        "year_gmt", "month_gmt", "day_gmt", "hour_gmt",
        "year_src", "month_src", "day_src", "hour_src",
        "period_number", "local_time", "timezone", "day_start",
        "visibility", "total_cloud", "low_cloud",
        "cloud_form_high", "cloud_form_mid", "cloud_form_vert",
        "cloud_st_str", "cloud_ns", "cloud_base_height",
        "cloud_below_station", "weather_past", "weather_now",
        "wind_dir", "wind_speed_avg", "wind_speed_max",
        "precip_sum",
        "soil_temp", "soil_temp_min", "soil_temp_min_period",
        "soil_temp_max_period", "soil_temp_max_after",
        "air_temp_dry", "air_temp_wet", "air_temp_min",
        "air_temp_min_period", "air_temp_max_period",
        "air_temp_max_after",
        "vapor_pressure", "humidity", "saturation_deficit",
        "dew_point", "station_pressure", "sea_level_pressure",
        "pressure_trend_code", "pressure_trend_value",
    ])
    status = await conn.execute("""
        INSERT INTO srok8c_data (
            station_id, year_gmt, month_gmt, day_gmt, hour_gmt,
            year_src, month_src, day_src, hour_src,
            period_number, local_time, timezone, day_start,
            visibility, total_cloud, low_cloud,
            cloud_form_high, cloud_form_mid, cloud_form_vert,
            cloud_st_str, cloud_ns, cloud_base_height,
            cloud_below_station, weather_past, weather_now,
            wind_dir, wind_speed_avg, wind_speed_max,
            precip_sum,
            soil_temp, soil_temp_min, soil_temp_min_period,
            soil_temp_max_period, soil_temp_max_after,
            air_temp_dry, air_temp_wet, air_temp_min,
            air_temp_min_period, air_temp_max_period,
            air_temp_max_after,
            vapor_pressure, humidity, saturation_deficit,
            dew_point, station_pressure, sea_level_pressure,
            pressure_trend_code, pressure_trend_value
        )
        SELECT s.id,
               t.year_gmt, t.month_gmt, t.day_gmt, t.hour_gmt,
               t.year_src, t.month_src, t.day_src, t.hour_src,
               t.period_number, t.local_time, t.timezone, t.day_start,
               t.visibility, t.total_cloud, t.low_cloud,
               t.cloud_form_high, t.cloud_form_mid, t.cloud_form_vert,
               t.cloud_st_str, t.cloud_ns, t.cloud_base_height,
               t.cloud_below_station, t.weather_past, t.weather_now,
               t.wind_dir, t.wind_speed_avg, t.wind_speed_max,
               t.precip_sum,
               t.soil_temp, t.soil_temp_min, t.soil_temp_min_period,
               t.soil_temp_max_period, t.soil_temp_max_after,
               t.air_temp_dry, t.air_temp_wet, t.air_temp_min,
               t.air_temp_min_period, t.air_temp_max_period,
               t.air_temp_max_after,
               t.vapor_pressure, t.humidity, t.saturation_deficit,
               t.dew_point, t.station_pressure, t.sea_level_pressure,
               t.pressure_trend_code, t.pressure_trend_value
        FROM temp_srok8c t
        JOIN stations s ON s.wmo_index = t.wmo_index
    """)
    inserted_rows = int(status.split()[-1])
    if inserted_rows == 0:
        sample_codes = ", ".join(sorted({row[0] for row in batch})[:5])
        raise RuntimeError(
            f"SROK8C batch parsed {len(batch)} records but inserted 0 rows. "
            f"Sample station codes: {sample_codes}"
        )
    return inserted_rows


async def ensure_temp_srok8c_table(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TEMP TABLE IF NOT EXISTS temp_srok8c (
            wmo_index VARCHAR(5),
            year_gmt INTEGER, month_gmt INTEGER, day_gmt INTEGER, hour_gmt INTEGER,
            year_src INTEGER, month_src INTEGER, day_src INTEGER, hour_src INTEGER,
            period_number INTEGER, local_time INTEGER, timezone INTEGER, day_start INTEGER,
            visibility INTEGER, total_cloud INTEGER, low_cloud INTEGER,
            cloud_form_high INTEGER, cloud_form_mid INTEGER, cloud_form_vert INTEGER,
            cloud_st_str INTEGER, cloud_ns INTEGER, cloud_base_height INTEGER,
            cloud_below_station INTEGER, weather_past INTEGER, weather_now INTEGER,
            wind_dir INTEGER, wind_speed_avg INTEGER, wind_speed_max INTEGER,
            precip_sum DECIMAL(6,1),
            soil_temp DECIMAL(5,1), soil_temp_min DECIMAL(5,1),
            soil_temp_min_period DECIMAL(5,1), soil_temp_max_period DECIMAL(5,1),
            soil_temp_max_after DECIMAL(5,1),
            air_temp_dry DECIMAL(5,1), air_temp_wet DECIMAL(5,1),
            air_temp_min DECIMAL(5,1), air_temp_min_period DECIMAL(5,1),
            air_temp_max_period DECIMAL(5,1), air_temp_max_after DECIMAL(5,1),
            vapor_pressure DECIMAL(5,2), humidity INTEGER,
            saturation_deficit DECIMAL(7,2), dew_point DECIMAL(5,1),
            station_pressure DECIMAL(6,1), sea_level_pressure DECIMAL(6,1),
            pressure_trend_code INTEGER, pressure_trend_value DECIMAL(4,1)
        ) ON COMMIT DELETE ROWS
    """)


async def flush_srok8c_batch(pool: asyncpg.Pool, batch: List, bytes_processed: int) -> int:
    if not batch:
        return 0
    async with pool.acquire() as conn:
        await ensure_temp_srok8c_table(conn)
        async with conn.transaction():
            inserted_rows = await insert_srok8c_batch(conn, batch)
            await update_load_progress(conn, "srok8c_data", bytes_processed)
            return inserted_rows


async def load_srok8c_data(pool: asyncpg.Pool, session) -> None:
    fields_content = await fetch_url(session, FIELDS_URL_SROK8C)
    field_widths = parse_field_widths(fields_content)

    field_names = [
        "Синоптический индекс станции",
        "Год   по Гринвичу",
        "Месяц по Гринвичу",
        "День  по Гринвичу",
        "Срок  по Гринвичу",
        "Год   источника (местный)",
        "Месяц источника (местный)",
        "День  источника (местный)",
        "Срок  источника (местный)",
        "Номер срока в сутках по ПДЗВ",
        "Время местное",
        "Номер часового пояса",
        "Начало метеорологических суток по ПДЗВ",
        "Горизонтальная дальность видимости",
        "Общее количество облачности",
        "Количество облачности нижнего яруса",
        "Форма облаков верхнего яруса",
        "Форма облаков среднего яруса",
        "Форма облаков вертикального развития",
        "Слоистые и слоисто-кучевые облака",
        "Слоисто-дожд,разорванно-дождевые облака",
        "Высота нижней границы облачности",
        "Признак наличия облачности ниже уровня станции",
        "Погода между сроками",
        "Погода в срок наблюдения",
        "Направление ветра",
        "Средняя скорость ветра",
        "Максимальная скорость ветра",
        "Сумма осадков",
        "Температура поверхности почвы",
        "Температура пов. почвы по мин. терм-ру",
        "Мин. температура пов-сти почвы между сроками",
        "Макс. температура пов-сти почвы между сроками",
        "Температура пов-сти почвы по макс. терм-ру п/встр.",
        "Температура воздуха по сухому терм-ру",
        "Темп.воздуха по смоченному терм-ру",
        "Температура воздуха по мин. терм-ру",
        "Мин.температура воздуха между сроками",
        "Макс. темперура воздуха между сроками",
        "Темпера воздуха по макс. терм-ру после встрях.",
        "Парциальное давление водяного пара",
        "Относительная влажность воздуха",
        "Дефицит насыщения водяного пара",
        "Температура точки росы",
        "Атмосферное давление на уровне станции",
        "Атмосферное давление на уровне моря",
        "Характеристика барической тенденции",
        "Величина барической тенденции"
    ]
    positions = _compute_positions_from_widths(field_widths, len(field_names))

    async with pool.acquire() as conn:
        await ensure_stations_loaded(conn)
        last_byte_offset = await get_load_progress(conn, "srok8c_data")
        if await is_source_loaded(conn, "srok8c_data"):
            print("[LOADER] SROK8C data already loaded, skipping.", flush=True)
            return

    chunk_size = LOADER_CONFIG.download_chunk_size
    batch_size = LOADER_CONFIG.srok8c_batch_size
    max_retries = LOADER_CONFIG.max_retries
    retry_delay = LOADER_CONFIG.initial_retry_delay_seconds

    for attempt in range(max_retries):
        start_time = time.time()
        last_report_time = start_time

        try:
            headers = {}
            if last_byte_offset > 0:
                headers["Range"] = f"bytes={last_byte_offset}-"
                print(f"[LOADER] Resuming SROK8C from byte {last_byte_offset} (attempt {attempt+1})", flush=True)
            else:
                print(f"[LOADER] Starting fresh SROK8C download (attempt {attempt+1})", flush=True)

            async with session.get(DATA_URL_SROK8C, headers=headers) as response:
                if response.status == 416:
                    print("[LOADER] SROK8C file already fully downloaded, marking loaded.", flush=True)
                    async with pool.acquire() as conn:
                        await mark_source_loaded(conn, "srok8c_data")
                    return

                if response.status not in (200, 206):
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")

                batch = []
                bytes_processed = last_byte_offset
                buffer = b""
                lines_processed = 0
                parsed_records = 0
                inserted_records = 0
                skipped_lines = 0
                first_parse_error: Optional[str] = None
                content_length = int(response.headers.get('content-length', 0))

                async for chunk in response.content.iter_chunked(chunk_size):
                    buffer += chunk
                    while b'\n' in buffer:
                        line_bytes, buffer = buffer.split(b'\n', 1)
                        bytes_processed += len(line_bytes) + 1
                        try:
                            line_str = line_bytes.decode('utf-8')
                        except UnicodeDecodeError:
                            continue
                        if not line_str.strip():
                            continue

                        lines_processed += 1
                        try:
                            values = []
                            for start, end in positions:
                                values.append(line_str[start:end].strip())

                            wmo = values[0]
                            year_gmt = int(values[1])
                            month_gmt = int(values[2])
                            day_gmt = int(values[3])
                            hour_gmt = int(values[4])
                            year_src = int(values[5])
                            month_src = int(values[6])
                            day_src = int(values[7])
                            hour_src = int(values[8])
                            period_num = _parse_optional_int(values[9])
                            local_time = _parse_optional_int(values[10])
                            timezone = _parse_optional_int(values[11])
                            day_start = _parse_optional_int(values[12])
                            visibility = _parse_optional_int(values[13])
                            total_cloud = _parse_optional_int(values[14])
                            low_cloud = _parse_optional_int(values[15])
                            cloud_form_high = _parse_optional_int(values[16])
                            cloud_form_mid = _parse_optional_int(values[17])
                            cloud_form_vert = _parse_optional_int(values[18])
                            cloud_st_str = _parse_optional_int(values[19])
                            cloud_ns = _parse_optional_int(values[20])
                            cloud_base_height = _parse_optional_int(values[21])
                            cloud_below = _parse_optional_int(values[22])
                            weather_past = _parse_optional_int(values[23])
                            weather_now = _parse_optional_int(values[24])
                            wind_dir = _parse_optional_int(values[25])
                            wind_speed_avg = _parse_optional_int(values[26])
                            wind_speed_max = _parse_optional_int(values[27])
                            precip_sum = _parse_optional_float(values[28])
                            soil_temp = _parse_optional_float(values[29])
                            soil_temp_min = _parse_optional_float(values[30])
                            soil_temp_min_period = _parse_optional_float(values[31])
                            soil_temp_max_period = _parse_optional_float(values[32])
                            soil_temp_max_after = _parse_optional_float(values[33])
                            air_temp_dry = _parse_optional_float(values[34])
                            air_temp_wet = _parse_optional_float(values[35])
                            air_temp_min = _parse_optional_float(values[36])
                            air_temp_min_period = _parse_optional_float(values[37])
                            air_temp_max_period = _parse_optional_float(values[38])
                            air_temp_max_after = _parse_optional_float(values[39])
                            vapor_pressure = _parse_optional_float(values[40])
                            humidity = _parse_optional_int(values[41])
                            saturation_deficit = _parse_optional_float(values[42])
                            dew_point = _parse_optional_float(values[43])
                            station_pressure = _parse_optional_float(values[44])
                            sea_level_pressure = _parse_optional_float(values[45])
                            pressure_trend_code = _parse_optional_int(values[46])
                            pressure_trend_value = _parse_optional_float(values[47])

                            batch.append((
                                wmo,
                                year_gmt, month_gmt, day_gmt, hour_gmt,
                                year_src, month_src, day_src, hour_src,
                                period_num, local_time, timezone, day_start,
                                visibility, total_cloud, low_cloud,
                                cloud_form_high, cloud_form_mid, cloud_form_vert,
                                cloud_st_str, cloud_ns, cloud_base_height,
                                cloud_below, weather_past, weather_now,
                                wind_dir, wind_speed_avg, wind_speed_max,
                                precip_sum,
                                soil_temp, soil_temp_min, soil_temp_min_period,
                                soil_temp_max_period, soil_temp_max_after,
                                air_temp_dry, air_temp_wet, air_temp_min,
                                air_temp_min_period, air_temp_max_period,
                                air_temp_max_after,
                                vapor_pressure, humidity, saturation_deficit,
                                dew_point, station_pressure, sea_level_pressure,
                                pressure_trend_code, pressure_trend_value
                            ))
                            parsed_records += 1
                        except (ValueError, IndexError):
                            skipped_lines += 1
                            if first_parse_error is None:
                                first_parse_error = line_str[:240]
                            continue

                        if len(batch) >= batch_size:
                            inserted_records += await flush_srok8c_batch(pool, batch, bytes_processed)
                            batch = []

                    if time.time() - last_report_time >= 1.0:
                        elapsed = time.time() - start_time
                        rate = lines_processed / elapsed if elapsed > 0 else 0
                        progress = f" {bytes_processed}/{content_length} bytes" if content_length > 0 else ""
                        print(f"[LOADER] SROK8C: {lines_processed} lines, {bytes_processed} bytes{progress}, {rate:.0f} lines/sec", flush=True)
                        last_report_time = time.time()

                if buffer:
                    line_str = ""
                    try:
                        line_str = buffer.decode('utf-8')
                        if line_str.strip():
                            lines_processed += 1
                            values = []
                            for start, end in positions:
                                values.append(line_str[start:end].strip())
                            wmo = values[0]
                            year_gmt = int(values[1])
                            month_gmt = int(values[2])
                            day_gmt = int(values[3])
                            hour_gmt = int(values[4])
                            year_src = int(values[5])
                            month_src = int(values[6])
                            day_src = int(values[7])
                            hour_src = int(values[8])
                            period_num = _parse_optional_int(values[9])
                            local_time = _parse_optional_int(values[10])
                            timezone = _parse_optional_int(values[11])
                            day_start = _parse_optional_int(values[12])
                            visibility = _parse_optional_int(values[13])
                            total_cloud = _parse_optional_int(values[14])
                            low_cloud = _parse_optional_int(values[15])
                            cloud_form_high = _parse_optional_int(values[16])
                            cloud_form_mid = _parse_optional_int(values[17])
                            cloud_form_vert = _parse_optional_int(values[18])
                            cloud_st_str = _parse_optional_int(values[19])
                            cloud_ns = _parse_optional_int(values[20])
                            cloud_base_height = _parse_optional_int(values[21])
                            cloud_below = _parse_optional_int(values[22])
                            weather_past = _parse_optional_int(values[23])
                            weather_now = _parse_optional_int(values[24])
                            wind_dir = _parse_optional_int(values[25])
                            wind_speed_avg = _parse_optional_int(values[26])
                            wind_speed_max = _parse_optional_int(values[27])
                            precip_sum = _parse_optional_float(values[28])
                            soil_temp = _parse_optional_float(values[29])
                            soil_temp_min = _parse_optional_float(values[30])
                            soil_temp_min_period = _parse_optional_float(values[31])
                            soil_temp_max_period = _parse_optional_float(values[32])
                            soil_temp_max_after = _parse_optional_float(values[33])
                            air_temp_dry = _parse_optional_float(values[34])
                            air_temp_wet = _parse_optional_float(values[35])
                            air_temp_min = _parse_optional_float(values[36])
                            air_temp_min_period = _parse_optional_float(values[37])
                            air_temp_max_period = _parse_optional_float(values[38])
                            air_temp_max_after = _parse_optional_float(values[39])
                            vapor_pressure = _parse_optional_float(values[40])
                            humidity = _parse_optional_int(values[41])
                            saturation_deficit = _parse_optional_float(values[42])
                            dew_point = _parse_optional_float(values[43])
                            station_pressure = _parse_optional_float(values[44])
                            sea_level_pressure = _parse_optional_float(values[45])
                            pressure_trend_code = _parse_optional_int(values[46])
                            pressure_trend_value = _parse_optional_float(values[47])
                            batch.append((
                                wmo,
                                year_gmt, month_gmt, day_gmt, hour_gmt,
                                year_src, month_src, day_src, hour_src,
                                period_num, local_time, timezone, day_start,
                                visibility, total_cloud, low_cloud,
                                cloud_form_high, cloud_form_mid, cloud_form_vert,
                                cloud_st_str, cloud_ns, cloud_base_height,
                                cloud_below, weather_past, weather_now,
                                wind_dir, wind_speed_avg, wind_speed_max,
                                precip_sum,
                                soil_temp, soil_temp_min, soil_temp_min_period,
                                soil_temp_max_period, soil_temp_max_after,
                                air_temp_dry, air_temp_wet, air_temp_min,
                                air_temp_min_period, air_temp_max_period,
                                air_temp_max_after,
                                vapor_pressure, humidity, saturation_deficit,
                                dew_point, station_pressure, sea_level_pressure,
                                pressure_trend_code, pressure_trend_value
                            ))
                            parsed_records += 1
                    except (ValueError, IndexError, UnicodeDecodeError):
                        skipped_lines += 1
                        if first_parse_error is None:
                            first_parse_error = line_str[:240]

                if batch:
                    inserted_records += await flush_srok8c_batch(pool, batch, bytes_processed)

                if lines_processed > 0 and parsed_records == 0:
                    error_suffix = f" First failed line sample: {first_parse_error}" if first_parse_error else ""
                    raise RuntimeError(
                        f"SROK8C loader parsed 0 records out of {lines_processed} lines.{error_suffix}"
                    )

                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await mark_source_loaded(conn, "srok8c_data")
                elapsed = time.time() - start_time
                rate = lines_processed / elapsed if elapsed > 0 else 0
                print(
                    f"[LOADER] SROK8C loading complete: {lines_processed} lines, "
                    f"{parsed_records} parsed, {inserted_records} inserted, "
                    f"{skipped_lines} skipped, {bytes_processed} bytes, {rate:.0f} lines/sec",
                    flush=True,
                )
                break

        except RETRYABLE_LOADER_ERRORS as e:
            print(f"[LOADER] SROK8C connection/timeout error: {e}", flush=True)
            if attempt < max_retries - 1:
                print(f"[LOADER] Retrying in {retry_delay} seconds...", flush=True)
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
                async with pool.acquire() as conn:
                    last_byte_offset = await get_load_progress(conn, "srok8c_data")
            else:
                raise
        except Exception as e:
            print(f"[LOADER] Unexpected SROK8C error: {e}", flush=True)
            raise


# Combined initial load

async def is_initial_load_complete(conn: asyncpg.Connection) -> bool:
    sources = ["stations", "weather_data", "atm8c_data", "srok8c_data"]
    for src in sources:
        if not await is_source_loaded(conn, src):
            return False
    return True


async def run_initial_load(
    pool: asyncpg.Pool,
    *,
    total_timeout_seconds: int = DEFAULT_HTTP_TOTAL_TIMEOUT_SECONDS,
    connect_timeout_seconds: int = DEFAULT_HTTP_CONNECT_TIMEOUT_SECONDS,
    sock_read_timeout_seconds: int = DEFAULT_HTTP_SOCK_READ_TIMEOUT_SECONDS,
) -> None:
    timeout = aiohttp.ClientTimeout(
        total=total_timeout_seconds,
        connect=connect_timeout_seconds,
        sock_read=sock_read_timeout_seconds,
    )
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with pool.acquire() as conn:
            if await is_initial_load_complete(conn):
                print("[LOADER] All data already loaded, skipping.", flush=True)
                return

        await load_stations(pool, session)
        await load_weather_data(pool, session)
        await load_atm8c_data(pool, session)
        await load_srok8c_data(pool, session)
