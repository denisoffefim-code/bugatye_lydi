"""Best-effort Redis-backed caching helpers."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from skycast.config import settings

try:
    import redis.asyncio as redis_async
except ModuleNotFoundError:  # pragma: no cover - helper tests may run without runtime deps
    redis_async = None  # type: ignore[assignment]


logger = logging.getLogger("skycast.cache")
_redis_client: Any | None = None
_redis_disabled = False
_ANALYTICS_CACHE_VERSION_KEY = "skycast:analytics:cache-version"
_ANALYTICS_CACHE_PREFIX = "skycast:analytics:response"


async def get_redis_client() -> Any | None:
    """Return a shared Redis client or `None` when caching is unavailable."""
    global _redis_client, _redis_disabled

    if not settings.analytics_cache_enabled or _redis_disabled:
        return None
    if redis_async is None:
        _redis_disabled = True
        logger.warning("analytics_cache_disabled_missing_dependency")
        return None
    if _redis_client is None:
        try:
            _redis_client = redis_async.from_url(settings.redis_url, decode_responses=True)
        except Exception:
            _redis_disabled = True
            logger.exception("analytics_cache_client_init_failed")
            return None
    return _redis_client


async def close_redis_client() -> None:
    """Close the shared Redis client if it was initialized."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def invalidate_analytics_cache() -> None:
    """Bump the analytics cache version so old responses stop matching."""
    client = await get_redis_client()
    if client is None:
        return
    try:
        await client.incr(_ANALYTICS_CACHE_VERSION_KEY)
    except Exception:
        logger.exception("analytics_cache_invalidate_failed")


async def maybe_cached_json_response(
    request: Request | None,
    *,
    namespace: str,
    loader: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any] | JSONResponse:
    """Cache GET JSON responses for analytics endpoints without breaking direct function calls."""
    if request is None or request.method != "GET" or not settings.analytics_cache_enabled:
        return await loader()

    client = await get_redis_client()
    if client is None:
        return await loader()

    request_key = f"{request.url.path}?{request.url.query}"
    try:
        version = await client.get(_ANALYTICS_CACHE_VERSION_KEY) or "1"
        cache_key = f"{_ANALYTICS_CACHE_PREFIX}:{namespace}:v{version}:{request_key}"
        cached_payload = await client.get(cache_key)
    except Exception:
        logger.exception("analytics_cache_read_failed")
        return await loader()

    if cached_payload is not None:
        response = JSONResponse(content=json.loads(cached_payload))
        response.headers["x-skycast-cache"] = "hit"
        return response

    payload = await loader()
    encoded_payload = jsonable_encoder(payload)
    response = JSONResponse(content=encoded_payload)
    response.headers["x-skycast-cache"] = "miss"
    try:
        await client.set(
            cache_key,
            json.dumps(encoded_payload, separators=(",", ":"), ensure_ascii=False),
            ex=settings.analytics_cache_ttl_seconds,
        )
    except Exception:
        logger.exception("analytics_cache_write_failed")
    return response
