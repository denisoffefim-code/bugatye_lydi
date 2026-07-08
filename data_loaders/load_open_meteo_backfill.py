"""CLI backfill for Open-Meteo previous-runs forecast data."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import aiohttp
import asyncpg


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from .load_remote import (
        DEFAULT_ENV_PATH,
        load_env_file,
        non_negative_float,
        positive_float,
        positive_int,
    )
except ImportError:
    from load_remote import (  # type: ignore[no-redef]
        DEFAULT_ENV_PATH,
        load_env_file,
        non_negative_float,
        positive_float,
        positive_int,
    )


def iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO date: {value}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Open-Meteo previous-runs forecast data into PostgreSQL.",
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_PATH),
        help="Path to .env file with DATABASE_URL. Default: %(default)s",
    )
    parser.add_argument(
        "--start-date",
        type=iso_date,
        default=date(2021, 3, 1),
        help="Backfill start date in YYYY-MM-DD format. Default: %(default)s",
    )
    parser.add_argument(
        "--end-date",
        type=iso_date,
        default=date.today(),
        help="Backfill end date in YYYY-MM-DD format. Default: %(default)s",
    )
    parser.add_argument(
        "--model",
        default="best_match",
        help="Open-Meteo model name. Default: %(default)s",
    )
    parser.add_argument(
        "--horizon",
        dest="horizons",
        action="append",
        type=positive_int,
        choices=range(1, 8),
        help="Archive horizon day to backfill. Repeat to load multiple. Default: 1..7",
    )
    parser.add_argument(
        "--chunk-days",
        type=positive_int,
        default=366,
        help="Date chunk size per forecast run. Default: %(default)s",
    )
    parser.add_argument(
        "--station-id",
        dest="station_ids",
        action="append",
        type=positive_int,
        help="Restrict backfill to a station id. Repeatable.",
    )
    parser.add_argument(
        "--wmo-index",
        dest="wmo_indices",
        action="append",
        help="Restrict backfill to a WMO index. Repeatable.",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        help="Limit number of stations with coordinates. Default: all matching",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Do not apply schema migrations before backfill.",
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
        default=8,
        help="Maximum asyncpg pool size. Default: %(default)s",
    )
    parser.add_argument(
        "--db-connect-timeout",
        type=positive_float,
        default=30.0,
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
        default=180.0,
        help="Total aiohttp request timeout in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--http-connect-timeout",
        type=positive_float,
        default=30.0,
        help="aiohttp connect timeout in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--http-sock-read-timeout",
        type=positive_float,
        default=180.0,
        help="aiohttp socket read timeout in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--rate-limit-per-second",
        type=positive_float,
        default=3.0,
        help="Open-Meteo request rate limit. Default: %(default)s",
    )
    parser.add_argument(
        "--max-parallel-requests",
        type=positive_int,
        default=4,
        help="Concurrent station requests per chunk. Default: %(default)s",
    )
    parser.add_argument(
        "--retry-count",
        type=positive_int,
        default=3,
        help="Retries per station request. Default: %(default)s",
    )
    parser.add_argument(
        "--retry-base-delay",
        type=positive_float,
        default=1.0,
        help="Initial retry delay in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--skip-outbox",
        action="store_true",
        help="Persist forecast rows without creating forecast.accepted outbox messages.",
    )
    return parser.parse_args()


def normalize_horizons(raw_horizons: Sequence[int] | None) -> list[int]:
    if not raw_horizons:
        return list(range(1, 8))
    ordered: list[int] = []
    seen: set[int] = set()
    for horizon in raw_horizons:
        if horizon not in seen:
            ordered.append(horizon)
            seen.add(horizon)
    return ordered


def iter_date_chunks(start_date: date, end_date: date, chunk_days: int) -> Iterable[tuple[date, date]]:
    current = start_date
    step = timedelta(days=chunk_days - 1)
    while current <= end_date:
        chunk_end = min(current + step, end_date)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


async def main_async(args: argparse.Namespace) -> None:
    if args.end_date < args.start_date:
        raise SystemExit("end-date must be greater than or equal to start-date")

    load_env_file(args.env_file)

    from skycast.clients import (
        AsyncRateLimiter,
        fetch_open_meteo_previous_runs_forecast,
        with_retries,
    )
    from skycast.config import settings
    from skycast.main import (
        ForecastFetchRequest,
        _create_forecast_run,
        _determine_forecast_run_status,
        _enqueue_outbox_message,
        _fetch_stations_for_forecast,
        _finish_forecast_run,
        _save_forecast_values,
        _save_raw_forecast_events,
    )
    from skycast.migrations import run_migrations
    from skycast.pipeline import (
        build_forecast_dedupe_key,
        build_forecast_raw_payload,
    )

    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required")

    command_timeout = None if args.db_command_timeout == 0 else args.db_command_timeout
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"],
        min_size=args.pool_min_size,
        max_size=args.pool_max_size,
        timeout=args.db_connect_timeout,
        command_timeout=command_timeout,
    )

    try:
        if not args.skip_migrations:
            print("[OPEN_METEO] Applying migrations...", flush=True)
            await run_migrations(pool)
            print("[OPEN_METEO] Migrations complete.", flush=True)

        station_request = ForecastFetchRequest(
            start_date=args.start_date,
            end_date=args.end_date,
            model=args.model,
            source="previous_runs",
            archive_horizon_days=1,
            publish_outbox_events=not args.skip_outbox,
            station_ids=args.station_ids,
            wmo_indices=args.wmo_indices,
            limit=args.limit,
        )
        async with pool.acquire() as conn:
            stations = await _fetch_stations_for_forecast(conn, station_request)

        if not stations:
            raise SystemExit("No stations with coordinates matched the request")

        horizons = normalize_horizons(args.horizons)
        chunks = list(iter_date_chunks(args.start_date, args.end_date, args.chunk_days))
        total_requests = len(stations) * len(horizons) * len(chunks)
        print(
            "[OPEN_METEO] Runtime config: "
            f"stations={len(stations)}, horizons={horizons}, chunks={len(chunks)}, "
            f"station_requests={total_requests}, model={args.model}, "
            f"date_range={args.start_date.isoformat()}..{args.end_date.isoformat()}, "
            f"publish_outbox_events={not args.skip_outbox}",
            flush=True,
        )

        timeout = aiohttp.ClientTimeout(
            total=args.http_total_timeout,
            connect=args.http_connect_timeout,
            sock_read=args.http_sock_read_timeout,
        )
        rate_limiter = AsyncRateLimiter(args.rate_limit_per_second)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for horizon in horizons:
                for chunk_start, chunk_end in chunks:
                    request = ForecastFetchRequest(
                        start_date=chunk_start,
                        end_date=chunk_end,
                        model=args.model,
                        source="previous_runs",
                        archive_horizon_days=horizon,
                        publish_outbox_events=not args.skip_outbox,
                        station_ids=args.station_ids,
                        wmo_indices=args.wmo_indices,
                        limit=args.limit,
                    )
                    async with pool.acquire() as conn:
                        run_id = await _create_forecast_run(conn, request, len(stations))

                    print(
                        f"[OPEN_METEO] Run {run_id} started: "
                        f"horizon={horizon}, range={chunk_start.isoformat()}..{chunk_end.isoformat()}",
                        flush=True,
                    )

                    station_queue: asyncio.Queue[asyncpg.Record] = asyncio.Queue()
                    for station in stations:
                        station_queue.put_nowait(station)

                    saved_rows = 0
                    errors: list[str] = []
                    saved_lock = asyncio.Lock()
                    error_lock = asyncio.Lock()

                    async def worker() -> None:
                        nonlocal saved_rows
                        while True:
                            try:
                                station = station_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                return

                            try:
                                await rate_limiter.wait()
                                records, _payload = await with_retries(
                                    lambda: fetch_open_meteo_previous_runs_forecast(
                                        session,
                                        base_url=settings.open_meteo_previous_runs_base_url,
                                        latitude=station["latitude"],
                                        longitude=station["longitude"],
                                        start_date=chunk_start,
                                        end_date=chunk_end,
                                        model=args.model,
                                        horizon_days=horizon,
                                    ),
                                    retries=args.retry_count,
                                    base_delay=args.retry_base_delay,
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
                                if prepared:
                                    async with pool.acquire() as conn:
                                        await _save_raw_forecast_events(
                                            conn,
                                            run_id,
                                            station,
                                            args.model,
                                            prepared,
                                        )
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
                                                        "model": args.model,
                                                        "source": "previous_runs",
                                                        **value["raw_payload"],
                                                    },
                                                )
                                    async with saved_lock:
                                        saved_rows += len(prepared)
                            except Exception as exc:
                                async with error_lock:
                                    errors.append(f"{station['wmo_index']}: {exc}")
                            finally:
                                station_queue.task_done()

                    workers = [
                        asyncio.create_task(worker())
                        for _ in range(min(args.max_parallel_requests, len(stations)))
                    ]
                    await station_queue.join()
                    for task in workers:
                        await task

                    status = _determine_forecast_run_status(
                        saved_rows=saved_rows,
                        error_count=len(errors),
                    )
                    async with pool.acquire() as conn:
                        await _finish_forecast_run(
                            conn,
                            run_id,
                            status=status,
                            error_message="\n".join(errors[:20]) if errors else None,
                        )

                    print(
                        f"[OPEN_METEO] Run {run_id} complete: "
                        f"status={status}, saved_rows={saved_rows}, failed_stations={len(errors)}",
                        flush=True,
                    )
                    if errors:
                        print("[OPEN_METEO] Sample errors:", flush=True)
                        for error in errors[:5]:
                            print(f"  {error}", flush=True)
    finally:
        await pool.close()


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
