from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis

from api.dependencies import require_api_key
from core.redis_client import get_redis
from core.redis_keys import RedisKeys
from db.models import ApiKey

router = APIRouter()

_KNOWN_SERVICES = ["payment-service", "order-service", "api-gateway"]


@router.get("/logs/services")
async def list_services(
    redis: Redis = Depends(get_redis),
    api_key: ApiKey = Depends(require_api_key),
) -> dict:
    """Return services that have log data in Redis streams."""
    services = []
    for svc in _KNOWN_SERVICES:
        length = await redis.xlen(RedisKeys.ingest_stream(svc))
        if length > 0:
            services.append({"service": svc, "event_count": length})
    return {"services": services}


@router.get("/logs/{service}")
async def get_service_logs(
    service: str,
    limit: int = Query(default=200, ge=1, le=1000),
    level: str | None = Query(
        default=None, description="Filter by level: ERROR, WARN, INFO, DEBUG"
    ),
    redis: Redis = Depends(get_redis),
    api_key: ApiKey = Depends(require_api_key),
) -> dict:
    """Read recent log events from the Redis stream for a service."""
    stream = RedisKeys.ingest_stream(service)
    raw = await redis.xrevrange(stream, count=limit * 3 if level else limit)

    events = []
    for entry_id, fields in raw:
        ev_level = (fields.get("level") or "").upper()
        if level and ev_level != level.upper():
            continue
        events.append(
            {
                "id": entry_id,
                "timestamp": fields.get("timestamp", ""),
                "level": ev_level,
                "message": fields.get("message", ""),
                "trace_id": fields.get("trace_id") or None,
                "span_id": fields.get("span_id") or None,
                "error_type": fields.get("error_type") or None,
                "stack_trace": fields.get("stack_trace") or None,
                "duration_ms": fields.get("duration_ms") or None,
            }
        )
        if len(events) >= limit:
            break

    return {"service": service, "total": len(events), "events": events}
