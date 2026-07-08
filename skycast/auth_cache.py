"""Redis-backed auth session cache."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from skycast.cache import get_redis_client
from skycast.config import settings

logger = logging.getLogger(__name__)


def _auth_session_cache_key(token_hash: str) -> str:
    return f"skycast:auth:session:{token_hash}"


def _auth_user_sessions_key(user_id: int) -> str:
    return f"skycast:auth:user-sessions:{user_id}"


def _auth_last_used_throttle_key(session_id: int) -> str:
    return f"skycast:auth:last-used:{session_id}"


def _cache_ttl_seconds(expires_at: datetime) -> int:
    remaining_seconds = int((expires_at - datetime.now(UTC)).total_seconds())
    if remaining_seconds <= 0:
        return 0
    return min(remaining_seconds, settings.auth_cache_ttl_seconds)


async def get_cached_auth_session(token_hash: str) -> dict[str, Any] | None:
    if not settings.auth_cache_enabled:
        return None
    client = await get_redis_client()
    if client is None:
        return None
    try:
        payload = await client.get(_auth_session_cache_key(token_hash))
    except Exception:
        logger.exception("auth_session_cache_read_failed", extra={"token_hash": token_hash})
        return None
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("auth_session_cache_payload_invalid", extra={"token_hash": token_hash})
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


async def cache_auth_session(
    token_hash: str,
    *,
    session_id: int,
    user_id: int,
    user_payload: dict[str, Any],
    expires_at: datetime,
) -> None:
    if not settings.auth_cache_enabled:
        return
    ttl_seconds = _cache_ttl_seconds(expires_at)
    if ttl_seconds < 1:
        return
    client = await get_redis_client()
    if client is None:
        return

    payload = {
        "session_id": session_id,
        "token_hash": token_hash,
        "user": user_payload,
        "expires_at": expires_at.astimezone(UTC).isoformat(),
    }
    try:
        await client.set(
            _auth_session_cache_key(token_hash),
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            ex=ttl_seconds,
        )
        await client.sadd(_auth_user_sessions_key(user_id), token_hash)
        await client.expire(_auth_user_sessions_key(user_id), ttl_seconds)
        await mark_auth_session_touched(session_id)
    except Exception:
        logger.exception(
            "auth_session_cache_write_failed",
            extra={"token_hash": token_hash, "session_id": session_id, "user_id": user_id},
        )


async def mark_auth_session_touched(session_id: int) -> None:
    if not settings.auth_cache_enabled:
        return
    client = await get_redis_client()
    if client is None:
        return
    try:
        await client.set(
            _auth_last_used_throttle_key(session_id),
            "1",
            ex=settings.auth_last_used_throttle_seconds,
        )
    except Exception:
        logger.exception("auth_session_touch_mark_failed", extra={"session_id": session_id})


async def should_touch_auth_session(session_id: int) -> bool:
    if not settings.auth_cache_enabled:
        return True
    client = await get_redis_client()
    if client is None:
        return True
    try:
        did_set = await client.set(
            _auth_last_used_throttle_key(session_id),
            "1",
            ex=settings.auth_last_used_throttle_seconds,
            nx=True,
        )
    except Exception:
        logger.exception("auth_session_touch_throttle_failed", extra={"session_id": session_id})
        return True
    return bool(did_set)


async def invalidate_auth_session(token_hash: str, *, user_id: int | None = None) -> None:
    if not settings.auth_cache_enabled:
        return
    client = await get_redis_client()
    if client is None:
        return
    try:
        await client.delete(_auth_session_cache_key(token_hash))
        if user_id is not None:
            await client.srem(_auth_user_sessions_key(user_id), token_hash)
    except Exception:
        logger.exception(
            "auth_session_cache_invalidate_failed",
            extra={"token_hash": token_hash, "user_id": user_id},
        )


async def invalidate_user_sessions(user_id: int) -> None:
    if not settings.auth_cache_enabled:
        return
    client = await get_redis_client()
    if client is None:
        return
    try:
        session_key = _auth_user_sessions_key(user_id)
        token_hashes = await client.smembers(session_key)
        if token_hashes:
            await client.delete(*[_auth_session_cache_key(token_hash) for token_hash in token_hashes])
        await client.delete(session_key)
    except Exception:
        logger.exception("auth_user_sessions_cache_invalidate_failed", extra={"user_id": user_id})
