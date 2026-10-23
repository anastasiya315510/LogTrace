import asyncio

import structlog
from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from api.dependencies import require_api_key
from api.models.schemas import IngestPayload, IngestResponse
from core.config import get_settings
from core.redis_client import get_redis
from core.redis_keys import RedisKeys
from db.models import ApiKey

log = structlog.get_logger()
router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest_events(
    payload: IngestPayload,
    redis: Redis = Depends(get_redis),
    api_key: ApiKey = Depends(require_api_key),
) -> IngestResponse:
    """
    Receive a batch of log events from a microservice or log shipper.

    Hot path — writes only to Redis Streams, no DB write. Target p99 < 50ms.
    Events are capped at INGEST_MAX_EVENTS_PER_CALL (default 500) per call.
    The Stream Processor watches all per-service streams for anomaly patterns.
    """
    settings = get_settings()
    stream = RedisKeys.ingest_stream(payload.service)
    events_to_accept = payload.events[: settings.ingest_max_events_per_call]
    dropped = len(payload.events) - len(events_to_accept)

    pipe = redis.pipeline(transaction=False)
    for event in events_to_accept:
        fields: dict[str, str] = {
            "service": payload.service,
            "timestamp": event.timestamp,
            "level": event.level.upper(),
            "message": event.message,
            "trace_id": event.trace_id or "",
            "span_id": event.span_id or "",
            "error_type": event.error_type or "",
            "stack_trace": event.stack_trace or "",
            "duration_ms": str(event.duration_ms or ""),
        }
        pipe.xadd(stream, fields, maxlen=settings.ingest_stream_maxlen, approximate=True)

    await pipe.execute()

    accepted = len(events_to_accept)

    # Update per-service demo event counters in the background.
    # Fire-and-forget: demo counters are best-effort and must not block the hot path.
    asyncio.create_task(redis.hincrby(RedisKeys.DEMO_STATE, f"events:{payload.service}", accepted))
    log.debug("events_ingested", service=payload.service, accepted=accepted, dropped=dropped)

    return IngestResponse(accepted=accepted, dropped=dropped)
