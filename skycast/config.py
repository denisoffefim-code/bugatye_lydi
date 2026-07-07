"""Application settings for SkyCast."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "SkyCast")
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = int(os.getenv("APP_PORT", os.getenv("PORT", "8080")))
    database_url: str = os.getenv("DATABASE_URL", "")
    open_meteo_base_url: str = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com")
    open_meteo_model: str = os.getenv("OPEN_METEO_MODEL", "best_match")
    noaa_igra_station_list_url: str = os.getenv(
        "NOAA_IGRA_STATION_LIST_URL",
        "https://www.ncei.noaa.gov/pub/data/igra/igra2-station-list.txt",
    )
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "45"))
    max_parallel_requests: int = int(os.getenv("MAX_PARALLEL_REQUESTS", "4"))
    rate_limit_per_second: float = float(os.getenv("RATE_LIMIT_PER_SECOND", "3"))
    startup_migrate: bool = _get_bool("STARTUP_MIGRATE", True)

    def validate(self) -> None:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required")


settings = Settings()
