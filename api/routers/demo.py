import json
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis

from api.dependencies import require_api_key
from api.models.schemas import (
    DemoCascadeRequest,
    DemoCascadeResponse,
    DemoResetRequest,
    DemoResetResponse,
    DemoStartRequest,
    DemoStartResponse,
    DemoStatusResponse,
)
from core.redis_client import get_redis
from core.redis_keys import RedisKeys
from db.models import ApiKey

log = structlog.get_logger()
router = APIRouter()

_ACTIVE_PHASES = {"normal", "cascade"}


def _build_session_id() -> str:
    return f"demo-{datetime.now(UTC).isoformat()}"


@router.post("/start", response_model=DemoStartResponse)
async def start_demo(
    body: DemoStartRequest,
    redis: Redis = Depends(get_redis),
    api_key: ApiKey = Depends(require_api_key),
) -> DemoStartResponse:
    """
    Start normal background traffic from all producer services.
    Producers subscribe to the Redis pub/sub command channel and begin pushing events.
    """
    current_phase = await redis.hget(RedisKeys.DEMO_STATE, "phase")
    if current_phase in _ACTIVE_PHASES:
        raise HTTPException(
            status_code=409,
            detail=f"Demo already running (phase={current_phase}). Call POST /demo/reset first.",
        )

    session_id = _build_session_id()
    await redis.hset(
        RedisKeys.DEMO_STATE,
        mapping={"phase": "normal", "session_id": session_id, "auto_triggered": "0"},
    )
    await redis.publish(
        RedisKeys.DEMO_COMMANDS,
        json.dumps(
            {
                "command": "start_normal",
                "services": body.services,
                "duration_seconds": body.normal_duration_seconds,
            }
        ),
    )

    log.info("demo_started", session_id=session_id, services=body.services)
    return DemoStartResponse(
        demo_session_id=session_id,
        phase="normal",
        services=body.services,
        message="Normal traffic started. Call POST /demo/cascade to inject the failure.",
    )


_SCENARIO_SEQUENCES = {
    "pool_exhaustion": [
        {"service": "payment-service", "delay_seconds": 0, "error_type": "PoolTimeoutError"},
        {"service": "order-service", "delay_seconds": 1.2, "error_type": "UpstreamTimeoutError"},
        {"service": "api-gateway", "delay_seconds": 2.8, "error_type": "ServiceUnavailableError"},
    ],
    "memory_leak": [
        {"service": "payment-service", "delay_seconds": 0, "error_type": "OutOfMemoryError"},
        {"service": "order-service", "delay_seconds": 2.0, "error_type": "HighLatencyError"},
        {"service": "api-gateway", "delay_seconds": 4.0, "error_type": "GatewayTimeoutError"},
    ],
    "slow_query": [
        {"service": "payment-service", "delay_seconds": 0, "error_type": "DeadlockError"},
        {"service": "order-service", "delay_seconds": 1.5, "error_type": "LockWaitTimeoutError"},
        {"service": "api-gateway", "delay_seconds": 3.5, "error_type": "ServiceDegradedError"},
    ],
}


@router.post("/cascade", response_model=DemoCascadeResponse)
async def trigger_cascade(
    body: DemoCascadeRequest = DemoCascadeRequest(),
    redis: Redis = Depends(get_redis),
    api_key: ApiKey = Depends(require_api_key),
) -> DemoCascadeResponse:
    """
    Inject a failure cascade scenario.
    Scenarios: pool_exhaustion (default) | memory_leak | slow_query
    A shared trace_id is generated so LogTrace can correlate all three services.
    Stream Processor will auto-trigger within ~60 seconds.
    """
    current_phase = await redis.hget(RedisKeys.DEMO_STATE, "phase")
    if current_phase == "cascade":
        raise HTTPException(
            status_code=409,
            detail="A cascade is already in progress. Call POST /demo/reset first.",
        )

    scenario = body.scenario if body.scenario in _SCENARIO_SEQUENCES else "pool_exhaustion"
    trace_id = uuid.uuid4().hex
    await redis.hset(
        RedisKeys.DEMO_STATE,
        mapping={"phase": "cascade", "trace_id": trace_id, "scenario": scenario},
    )
    await redis.publish(
        RedisKeys.DEMO_COMMANDS,
        json.dumps({"command": "cascade", "trace_id": trace_id, "scenario": scenario}),
    )

    log.info("demo_cascade_triggered", trace_id=trace_id, scenario=scenario)
    return DemoCascadeResponse(
        phase="cascade",
        trace_id=trace_id,
        scenario=scenario,
        cascade_sequence=_SCENARIO_SEQUENCES[scenario],
        expected_trigger_in_seconds=60,
        message=f"Cascade '{scenario}' injected. Stream Processor will auto-trigger within 60s.",
    )


@router.get("/status", response_model=DemoStatusResponse)
async def demo_status(
    redis: Redis = Depends(get_redis),
    api_key: ApiKey = Depends(require_api_key),
) -> DemoStatusResponse:
    """Current demo phase, events pushed per service, and submission ID if triggered."""
    state = await redis.hgetall(RedisKeys.DEMO_STATE)

    events_pushed = {
        key.replace("events:", ""): int(val)
        for key, val in state.items()
        if key.startswith("events:")
    }
    phase = state.get("phase", "idle")
    auto_triggered = state.get("auto_triggered") == "1"
    raw_submission_id = state.get("submission_id")
    submission_id = uuid.UUID(raw_submission_id) if raw_submission_id else None

    message = None if auto_triggered else "Call POST /demo/cascade to inject the failure."
    if auto_triggered:
        message = "Stream Processor triggered. Analysis in progress."

    return DemoStatusResponse(
        phase=phase,
        events_pushed=events_pushed,
        auto_triggered=auto_triggered,
        submission_id=submission_id,
        message=message,
    )


@router.post("/reset", response_model=DemoResetResponse)
async def reset_demo(
    body: DemoResetRequest,
    redis: Redis = Depends(get_redis),
    api_key: ApiKey = Depends(require_api_key),
) -> DemoResetResponse:
    """
    Stop all producers, reset demo state to idle.
    Optionally flush Redis ingest streams so the Stream Processor starts clean.
    """
    await redis.publish(RedisKeys.DEMO_COMMANDS, json.dumps({"command": "stop"}))
    await redis.delete(RedisKeys.DEMO_STATE)
    await redis.set(RedisKeys.SP_RESET_SIGNAL, "1", ex=60)  # stream processor clears on next tick

    if body.clear_redis_streams:
        async for key in redis.scan_iter("stream:ingest:*"):
            await redis.delete(key)

    log.info("demo_reset", clear_streams=body.clear_redis_streams)
    return DemoResetResponse(
        phase="idle",
        redis_streams_cleared=body.clear_redis_streams,
        db_submissions_cleared=body.clear_db_submissions,
        message="Demo reset. Call POST /demo/start to begin a new run.",
    )
