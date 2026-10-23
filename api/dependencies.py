import hashlib
import json

import structlog
from fastapi import Depends, Header, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.redis_client import get_redis
from core.redis_keys import RedisKeys
from db.models import ApiKey

log = structlog.get_logger()

_AUTH_CACHE_TTL = 300  # 5 minutes


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def _validate_key(raw_key: str, redis: Redis, db: AsyncSession) -> ApiKey:
    """Shared key validation: SHA-256 hash → Redis cache → DB lookup."""
    key_hash = _hash_key(raw_key)
    cache_key = RedisKeys.auth_cache(key_hash)

    cached = await redis.get(cache_key)

    if cached == "invalid":
        raise HTTPException(status_code=401, detail="Missing or invalid API key")

    if cached is not None:
        data = json.loads(cached)
        return ApiKey(
            user_id=data["user_id"],
            key_hash=key_hash,
            is_active=True,
        )

    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active.is_(True),
        )
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        await redis.setex(cache_key, _AUTH_CACHE_TTL, "invalid")
        raise HTTPException(status_code=401, detail="Missing or invalid API key")

    await redis.setex(
        cache_key,
        _AUTH_CACHE_TTL,
        json.dumps(
            {
                "user_id": str(api_key.user_id) if api_key.user_id is not None else None,
            }
        ),
    )
    return api_key


async def require_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """
    Validate X-API-Key header. Redis cache (5 min TTL) avoids a DB hit on
    every ingest request. Cache stores 'invalid' for bad keys, or a JSON
    blob with {user_id} for valid ones so the full ApiKey can be reconstructed
    without another DB round-trip.

    Note: deactivated keys stay valid until the TTL expires (≤ 5 min).
    """
    return await _validate_key(x_api_key, redis, db)


async def require_api_key_sse(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    api_key: str | None = Query(None),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """
    SSE-compatible auth: accepts X-API-Key header (primary) or ?api_key= query
    parameter (fallback). The header takes precedence when both are present.

    Used only on the SSE stream endpoint because browsers' native EventSource
    cannot send custom HTTP headers.
    """
    raw_key = x_api_key or api_key
    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    return await _validate_key(raw_key, redis, db)
