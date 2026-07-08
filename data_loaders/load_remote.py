"""CLI loader that ingests source files directly into the remote PostgreSQL DB."""

import argparse
import asyncio
import os
from pathlib import Path
from typing import Iterable

import aiohttp
import asyncpg

try:
    from .loader import (
        DEFAULT_ATM8C_BATCH_SIZE,
        DEFAULT_DOWNLOAD_CHUNK_SIZE,
        DEFAULT_HTTP_CONNECT_TIMEOUT_SECONDS,
        DEFAULT_HTTP_SOCK_READ_TIMEOUT_SECONDS,
        DEFAULT_HTTP_TOTAL_TIMEOUT_SECONDS,
        DEFAULT_INITIAL_RETRY_DELAY_SECONDS,
        DEFAULT_MAX_RETRIES,
        DEFAULT_SROK8C_BATCH_SIZE,
        DEFAULT_WEATHER_BATCH_SIZE,
        configure_loader,
        load_atm8c_data,
        load_srok8c_data,
        load_stations,
        load_weather_data,
    )
    from .migration import run_migration
except ImportError:
    from loader import (
        DEFAULT_ATM8C_BATCH_SIZE,
        DEFAULT_DOWNLOAD_CHUNK_SIZE,
        DEFAULT_HTTP_CONNECT_TIMEOUT_SECONDS,
        DEFAULT_HTTP_SOCK_READ_TIMEOUT_SECONDS,
        DEFAULT_HTTP_TOTAL_TIMEOUT_SECONDS,
        DEFAULT_INITIAL_RETRY_DELAY_SECONDS,
        DEFAULT_MAX_RETRIES,
        DEFAULT_SROK8C_BATCH_SIZE,
        DEFAULT_WEATHER_BATCH_SIZE,
        configure_loader,
        load_atm8c_data,
        load_srok8c_data,
        load_stations,
        load_weather_data,
    )
    from migration import run_migration


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_SOURCES = ("stations", "tttr", "atm8c", "srok8c")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Value must be >= 1")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Value must be > 0")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Value must be >= 0")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load weather source files directly into the remote PostgreSQL database."
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_PATH),
        help="Path to .env file with DATABASE_URL. Default: %(default)s",
    )
    parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        choices=("all", "stations", "tttr", "atm8c", "srok8c"),
        help="Which dataset to load. Can be passed multiple times. Default: all",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Do not apply schema migrations before loading.",
    )
    parser.add_argument(
        "--pool-min-size",
        type=positive_int,
        default=1,
        help="Minimum asyncpg pool size. Default: %(default)s",
    )
    parser.add_argument(
        "--pool-max-size",
        type=positive_int,
        default=5,
        help="Maximum asyncpg pool size. Default: %(default)s",
    )
    parser.add_argument(
        "--db-connect-timeout",
        type=positive_float,
        default=DEFAULT_HTTP_CONNECT_TIMEOUT_SECONDS,
        help="Timeout in seconds for opening a PostgreSQL connection. Default: %(default)s",
    )
    parser.add_argument(
        "--db-command-timeout",
        type=non_negative_float,
        default=0,
        help="Per-command asyncpg timeout in seconds. Use 0 to disable. Default: %(default)s",
    )
    parser.add_argument(
        "--http-total-timeout",
        type=positive_float,
        default=DEFAULT_HTTP_TOTAL_TIMEOUT_SECONDS,
        help="Total aiohttp request timeout in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--http-connect-timeout",
        type=positive_float,
        default=DEFAULT_HTTP_CONNECT_TIMEOUT_SECONDS,
        help="aiohttp connect timeout in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--http-sock-read-timeout",
        type=positive_float,
        default=DEFAULT_HTTP_SOCK_READ_TIMEOUT_SECONDS,
        help="aiohttp socket read timeout in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--download-chunk-size",
        type=positive_int,
        default=DEFAULT_DOWNLOAD_CHUNK_SIZE,
        help="HTTP chunk size in bytes for streaming source files. Default: %(default)s",
    )
    parser.add_argument(
        "--weather-batch-size",
        type=positive_int,
        default=DEFAULT_WEATHER_BATCH_SIZE,
        help="Rows per DB batch for TTTR weather data. Default: %(default)s",
    )
    parser.add_argument(
        "--atm8c-batch-size",
        type=positive_int,
        default=DEFAULT_ATM8C_BATCH_SIZE,
        help="Rows per DB batch for ATM8C data. Default: %(default)s",
    )
    parser.add_argument(
        "--srok8c-batch-size",
        type=positive_int,
        default=DEFAULT_SROK8C_BATCH_SIZE,
        help="Rows per DB batch for SROK8C data. Default: %(default)s",
    )
    parser.add_argument(
        "--loader-max-retries",
        type=positive_int,
        default=DEFAULT_MAX_RETRIES,
        help="How many times a loader retries after network or DB connection errors. Default: %(default)s",
    )
    parser.add_argument(
        "--loader-retry-delay",
        type=positive_int,
        default=DEFAULT_INITIAL_RETRY_DELAY_SECONDS,
        help="Initial retry delay in seconds before exponential backoff. Default: %(default)s",
    )
    return parser.parse_args()


def load_env_file(env_path: str) -> None:
    path = Path(env_path).expanduser()
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def normalize_sources(raw_sources: list[str] | None) -> tuple[str, ...]:
    if not raw_sources or "all" in raw_sources:
        return DEFAULT_SOURCES

    ordered_sources: list[str] = []
    seen: set[str] = set()
    for source in raw_sources:
        if source not in seen:
            ordered_sources.append(source)
            seen.add(source)
    return tuple(ordered_sources)


async def run_selected_sources(
    pool: asyncpg.Pool,
    session: aiohttp.ClientSession,
    sources: Iterable[str],
) -> None:
    for source in sources:
        print(f"[LOAD_REMOTE] Starting source: {source}", flush=True)
        if source == "stations":
            await load_stations(pool, session)
        elif source == "tttr":
            await load_weather_data(pool, session)
        elif source == "atm8c":
            await load_atm8c_data(pool, session)
        elif source == "srok8c":
            await load_srok8c_data(pool, session)
        else:
            raise ValueError(f"Unsupported source: {source}")
        print(f"[LOAD_REMOTE] Finished source: {source}", flush=True)


async def main_async(args: argparse.Namespace) -> None:
    load_env_file(args.env_file)

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Pass --env-file or export DATABASE_URL before running."
        )

    if args.pool_min_size < 1 or args.pool_max_size < args.pool_min_size:
        raise ValueError("Invalid pool sizes: pool-max-size must be >= pool-min-size >= 1")

    sources = normalize_sources(args.sources)
    loader_config = configure_loader(
        download_chunk_size=args.download_chunk_size,
        weather_batch_size=args.weather_batch_size,
        atm8c_batch_size=args.atm8c_batch_size,
        srok8c_batch_size=args.srok8c_batch_size,
        max_retries=args.loader_max_retries,
        initial_retry_delay_seconds=args.loader_retry_delay,
    )

    print("[LOAD_REMOTE] Connecting to PostgreSQL...", flush=True)
    pool = await asyncpg.create_pool(
        database_url,
        min_size=args.pool_min_size,
        max_size=args.pool_max_size,
        timeout=args.db_connect_timeout,
        command_timeout=args.db_command_timeout or None,
    )

    try:
        if not args.skip_migrations:
            print("[LOAD_REMOTE] Applying migrations...", flush=True)
            await run_migration(pool)
            print("[LOAD_REMOTE] Migrations complete.", flush=True)

        print(
            "[LOAD_REMOTE] Runtime config: "
            f"chunk={loader_config.download_chunk_size}B, "
            f"tttr_batch={loader_config.weather_batch_size}, "
            f"atm8c_batch={loader_config.atm8c_batch_size}, "
            f"srok8c_batch={loader_config.srok8c_batch_size}, "
            f"retries={loader_config.max_retries}, "
            f"retry_delay={loader_config.initial_retry_delay_seconds}s, "
            f"db_connect_timeout={args.db_connect_timeout}s, "
            f"db_command_timeout={'disabled' if args.db_command_timeout == 0 else f'{args.db_command_timeout}s'}",
            flush=True,
        )

        timeout = aiohttp.ClientTimeout(
            total=args.http_total_timeout,
            connect=args.http_connect_timeout,
            sock_read=args.http_sock_read_timeout,
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await run_selected_sources(pool, session, sources)
    finally:
        await pool.close()
        print("[LOAD_REMOTE] Pool closed.", flush=True)


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
