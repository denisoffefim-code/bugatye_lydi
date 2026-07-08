"""Migration job entrypoint."""

from __future__ import annotations

import asyncio

from skycast.config import settings
from skycast.db import close_pool, init_pool
from skycast.logging_utils import configure_logging
from skycast.migrations import run_migrations


async def _main() -> None:
    configure_logging(
        service_name=f"{settings.app_name} Migrations",
        level=settings.log_level,
        json_logs=settings.log_json,
    )
    settings.validate()
    pool = await init_pool(settings)
    try:
        await run_migrations(pool)
    finally:
        await close_pool()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
