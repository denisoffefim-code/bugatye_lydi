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


def _get_csv(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    return items or default


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "SkyCast")
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = int(os.getenv("APP_PORT", os.getenv("PORT", "8080")))
    cors_allowed_origins: tuple[str, ...] = _get_csv(
        "CORS_ALLOWED_ORIGINS",
        (
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ),
    )
    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_stream_prefix: str = os.getenv("REDIS_STREAM_PREFIX", "skycast")
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    kafka_topic_prefix: str = os.getenv("KAFKA_TOPIC_PREFIX", "skycast")
    kafka_client_id: str = os.getenv("KAFKA_CLIENT_ID", "skycast-outbox-worker")
    kafka_security_protocol: str = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    kafka_ssl_cafile: str | None = os.getenv("KAFKA_SSL_CAFILE")
    kafka_ssl_certfile: str | None = os.getenv("KAFKA_SSL_CERTFILE")
    kafka_ssl_keyfile: str | None = os.getenv("KAFKA_SSL_KEYFILE")
    kafka_sasl_mechanism: str | None = os.getenv("KAFKA_SASL_MECHANISM")
    kafka_sasl_username: str | None = os.getenv("KAFKA_SASL_USERNAME")
    kafka_sasl_password: str | None = os.getenv("KAFKA_SASL_PASSWORD")
    open_meteo_base_url: str = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com")
    open_meteo_previous_runs_base_url: str = os.getenv(
        "OPEN_METEO_PREVIOUS_RUNS_BASE_URL",
        "https://previous-runs-api.open-meteo.com",
    )
    open_meteo_model: str = os.getenv("OPEN_METEO_MODEL", "best_match")
    noaa_igra_station_list_url: str = os.getenv(
        "NOAA_IGRA_STATION_LIST_URL",
        "https://www.ncei.noaa.gov/pub/data/igra/igra2-station-list.txt",
    )
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "45"))
    max_parallel_requests: int = int(os.getenv("MAX_PARALLEL_REQUESTS", "4"))
    rate_limit_per_second: float = float(os.getenv("RATE_LIMIT_PER_SECOND", "3"))
    startup_migrate: bool = _get_bool("STARTUP_MIGRATE", True)
    outbox_batch_size: int = int(os.getenv("OUTBOX_BATCH_SIZE", "100"))
    outbox_poll_seconds: float = float(os.getenv("OUTBOX_POLL_SECONDS", "2"))
    outbox_retry_base_seconds: float = float(os.getenv("OUTBOX_RETRY_BASE_SECONDS", "5"))
    outbox_max_retry_delay_seconds: float = float(os.getenv("OUTBOX_MAX_RETRY_DELAY_SECONDS", "300"))
    outbox_max_attempts: int = int(os.getenv("OUTBOX_MAX_ATTEMPTS", "8"))
    outbox_spool_enabled: bool = _get_bool("OUTBOX_SPOOL_ENABLED", True)
    outbox_spool_dir: str = os.getenv("OUTBOX_SPOOL_DIR", ".skycast-outbox-spool")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_json: bool = _get_bool("LOG_JSON", True)
    analytics_cache_enabled: bool = _get_bool("ANALYTICS_CACHE_ENABLED", True)
    analytics_cache_ttl_seconds: int = int(os.getenv("ANALYTICS_CACHE_TTL_SECONDS", "300"))
    auth_session_ttl_hours: int = int(os.getenv("AUTH_SESSION_TTL_HOURS", "24"))
    auth_password_hash_iterations: int = int(os.getenv("AUTH_PASSWORD_HASH_ITERATIONS", "390000"))

    def validate(self) -> None:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required")
        if not self.redis_url:
            raise RuntimeError("REDIS_URL is required")
        if not self.kafka_bootstrap_servers:
            raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS is required")
        if self.kafka_security_protocol not in {"PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"}:
            raise RuntimeError("KAFKA_SECURITY_PROTOCOL must be one of PLAINTEXT, SSL, SASL_PLAINTEXT, SASL_SSL")
        if self.kafka_security_protocol.startswith("SASL"):
            if not self.kafka_sasl_mechanism:
                raise RuntimeError("KAFKA_SASL_MECHANISM is required for SASL Kafka")
            if not self.kafka_sasl_username or not self.kafka_sasl_password:
                raise RuntimeError("KAFKA_SASL_USERNAME and KAFKA_SASL_PASSWORD are required for SASL Kafka")
        if self.outbox_batch_size < 1:
            raise RuntimeError("OUTBOX_BATCH_SIZE must be >= 1")
        if self.outbox_poll_seconds <= 0:
            raise RuntimeError("OUTBOX_POLL_SECONDS must be > 0")
        if self.outbox_retry_base_seconds <= 0:
            raise RuntimeError("OUTBOX_RETRY_BASE_SECONDS must be > 0")
        if self.outbox_max_retry_delay_seconds <= 0:
            raise RuntimeError("OUTBOX_MAX_RETRY_DELAY_SECONDS must be > 0")
        if self.outbox_max_attempts < 1:
            raise RuntimeError("OUTBOX_MAX_ATTEMPTS must be >= 1")
        if self.outbox_spool_enabled and not self.outbox_spool_dir:
            raise RuntimeError("OUTBOX_SPOOL_DIR is required when OUTBOX_SPOOL_ENABLED=true")
        if self.analytics_cache_enabled and self.analytics_cache_ttl_seconds < 1:
            raise RuntimeError("ANALYTICS_CACHE_TTL_SECONDS must be >= 1 when ANALYTICS_CACHE_ENABLED=true")
        if self.auth_session_ttl_hours < 1:
            raise RuntimeError("AUTH_SESSION_TTL_HOURS must be >= 1")
        if self.auth_password_hash_iterations < 100000:
            raise RuntimeError("AUTH_PASSWORD_HASH_ITERATIONS must be >= 100000")


settings = Settings()
