"""
jobs/stage2/entrypoint.py

Stage-2 job: classify events → stream RCA → fetch fix suggestions → persist → done.

Entry point: `python -m jobs.stage2.entrypoint`
Required env var: INCIDENT_ID (UUID string)
Optional env var: SUBMISSION_ID (UUID string) — for SSE channel routing
"""

import asyncio
import json
import os
import uuid

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select, update

from core.config import get_settings
from core.database import get_session_factory
from core.redis_client import get_redis_pool
from core.redis_keys import RedisKeys
from db.models import Incident, LogEvent
from jobs.stage2.classifier import batch_classify
from jobs.stage2.fix_suggestions import fetch_fix_suggestions
from jobs.stage2.rca import stream_rca

log = structlog.get_logger()


async def main() -> None:
    incident_id = uuid.UUID(os.environ["INCIDENT_ID"])
    submission_id_str = os.environ.get("SUBMISSION_ID")
    submission_id = uuid.UUID(submission_id_str) if submission_id_str else None

    log.info("stage2_starting", incident_id=str(incident_id))

    settings = get_settings()
    session_factory = get_session_factory()
    redis = get_redis_pool()

    client = AsyncOpenAI(
        api_key=settings.nebius_api_key,
        base_url=settings.nebius_base_url,
    )

    # Load incident + events
    async with session_factory() as session:
        result = await session.execute(select(Incident).where(Incident.incident_id == incident_id))
        incident = result.scalar_one_or_none()
        if incident is None:
            log.error("incident_not_found", incident_id=str(incident_id))
            return

        # Derive submission_id if not provided via env
        if submission_id is None:
            submission_id = incident.submission_id

        # Load events for this incident via submission
        events_result = await session.execute(
            select(LogEvent).where(LogEvent.submission_id == incident.submission_id)
        )
        events: list[LogEvent] = list(events_result.scalars().all())

    sse_channel = RedisKeys.sse_channel(str(submission_id))

    async def publish_token(token: str) -> None:
        await redis.publish(sse_channel, json.dumps({"token": token}))

    async def publish_step(step: str, pct: int) -> None:
        await redis.publish(
            sse_channel,
            json.dumps({"step": step, "progress_pct": pct}),
        )

    try:
        # Step 1: classify events with Nano
        await publish_step("classifying", 10)
        async with session_factory() as session:
            await session.execute(
                update(Incident)
                .where(Incident.incident_id == incident_id)
                .values(status="classifying")
            )
            await session.commit()

        classifications = await batch_classify(
            events=events,
            client=client,
            model_id=settings.nano_model_id,
            batch_size=settings.nano_batch_size,
            parallel=settings.nano_parallel_calls,
        )

        async with session_factory() as session:
            for c in classifications:
                session.add(c)
            await session.commit()

        log.info("classification_complete", count=len(classifications))

        # Step 2: RCA with Ultra
        await publish_step("analyzing", 30)
        async with session_factory() as session:
            await session.execute(
                update(Incident)
                .where(Incident.incident_id == incident_id)
                .values(status="analyzing")
            )
            await session.commit()

        analysis = await stream_rca(
            incident=incident,
            events=events,
            classifications=classifications,
            client=client,
            model_id=settings.ultra_model_id,
            progress_callback=publish_token,
        )

        async with session_factory() as session:
            session.add(analysis)
            await session.commit()

        log.info("rca_complete", incident_id=str(incident_id))

        # Step 3: fetch fix suggestions
        await publish_step("fetching_fixes", 85)
        suggestions = await fetch_fix_suggestions(
            analysis=analysis,
            incident_id=incident_id,
            tavily_api_key=settings.tavily_api_key,
        )

        async with session_factory() as session:
            for s in suggestions:
                session.add(s)
            await session.execute(
                update(Incident)
                .where(Incident.incident_id == incident_id)
                .values(status="complete")
            )
            await session.commit()

        log.info("stage2_complete", incident_id=str(incident_id), suggestions=len(suggestions))

        # Publish done sentinel
        await publish_step("complete", 100)
        await redis.publish(sse_channel, "__DONE__")

    except Exception:
        log.exception("stage2_failed", incident_id=str(incident_id))
        async with session_factory() as session:
            await session.execute(
                update(Incident).where(Incident.incident_id == incident_id).values(status="failed")
            )
            await session.commit()
        await redis.publish(sse_channel, "__DONE__")
        raise


if __name__ == "__main__":
    asyncio.run(main())
