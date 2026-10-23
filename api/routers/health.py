import structlog
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.schemas import HealthResponse, ReadinessResponse
from core.database import get_db
from core.redis_client import get_redis

log = structlog.get_logger()
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """Liveness probe. Returns 200 if the process is alive."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> ReadinessResponse:
    """
    Readiness probe. Checks connectivity to PostgreSQL and Redis.
    Returns 200 if all dependencies are reachable, 503 if any are down.
    """
    from fastapi.responses import JSONResponse

    postgres_status = "ok"
    redis_status = "ok"

    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        log.warning("readiness_postgres_failed", error=str(exc))
        postgres_status = "unreachable"

    try:
        await redis.ping()
    except Exception as exc:
        log.warning("readiness_redis_failed", error=str(exc))
        redis_status = "unreachable"

    all_ok = postgres_status == "ok" and redis_status == "ok"
    status_code = 200 if all_ok else 503
    overall = "ready" if all_ok else "degraded"

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "checks": {"postgres": postgres_status, "redis": redis_status},
        },
    )
