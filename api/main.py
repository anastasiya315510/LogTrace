import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routers import demo, health, incidents, ingest, logs, submissions
from core.config import get_settings
from core.database import Base, get_engine, get_session_factory
from core.redis_client import close_redis, get_redis_pool

log = structlog.get_logger()


async def _seed_demo_api_key() -> None:
    """Insert the demo API key on startup if it doesn't exist (dev only)."""
    from sqlalchemy import select

    from db.models import ApiKey

    settings = get_settings()
    key_hash = hashlib.sha256(settings.demo_api_key.encode()).hexdigest()

    async with get_session_factory()() as session:
        existing = await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        if existing.scalar_one_or_none() is None:
            session.add(ApiKey(key_hash=key_hash, key_plain=settings.demo_api_key))
            await session.commit()
            log.info("demo_api_key_seeded")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log.info("logtrace_starting", env=settings.model_config.get("env_file"))

    # Create tables (idempotent in dev; production uses Alembic migrations)
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _seed_demo_api_key()

    # Warm up Redis connection pool
    redis = get_redis_pool()
    await redis.ping()

    log.info("redis_connected")

    yield

    await close_redis()
    await get_engine().dispose()
    log.info("logtrace_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="LogTrace API",
        description=(
            "AI-powered log intelligence for microservice environments. "
            "Uses NVIDIA Nemotron Nano 8B and Ultra 253B via Nebius Token Factory."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router, tags=["Health"])
    app.include_router(ingest.router, prefix="/api/v1", tags=["Ingestion"])
    app.include_router(submissions.router, prefix="/api/v1", tags=["Submissions"])
    app.include_router(incidents.router, prefix="/api/v1", tags=["Incidents"])
    app.include_router(logs.router, prefix="/api/v1", tags=["Logs"])
    app.include_router(demo.router, prefix="/demo", tags=["Demo"])

    portal_dir = Path(__file__).parent.parent / "portal" / "dist"
    if portal_dir.exists():
        app.mount("/portal", StaticFiles(directory=str(portal_dir), html=True), name="portal")

    return app


app = create_app()
