import uuid

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.dependencies import require_api_key, require_api_key_sse
from api.models.schemas import (
    IncidentListResponse,
    IncidentSummary,
    SubmissionResponse,
    SubmissionStatusResponse,
)
from core.config import get_settings
from core.database import get_db
from core.redis_client import get_redis
from core.redis_keys import RedisKeys
from core.storage import ObjectStorage, get_storage
from db.models import ApiKey, Incident, Submission

log = structlog.get_logger()
router = APIRouter()


@router.get("/config")
async def get_upload_config(
    api_key: ApiKey = Depends(require_api_key),
) -> dict:
    """Return upload limits so the portal can enforce them without hardcoding."""
    cfg = get_settings()
    return {
        "upload_max_files": cfg.upload_max_files,
        "upload_max_file_mb": cfg.upload_max_file_mb,
        "upload_max_total_mb": cfg.upload_max_total_mb,
    }


@router.get("/submissions/{submission_id}", response_model=SubmissionStatusResponse)
async def get_submission_status(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> SubmissionStatusResponse:
    result = await db.execute(select(Submission).where(Submission.submission_id == submission_id))
    submission = result.scalar_one_or_none()
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    count_result = await db.execute(
        select(func.count()).select_from(Incident).where(Incident.submission_id == submission_id)
    )
    incident_count = count_result.scalar_one()

    return SubmissionStatusResponse(
        submission_id=submission.submission_id,
        status=submission.raw_status,
        incident_count=incident_count,
        created_at=submission.submitted_at,
    )


@router.get("/submissions/{submission_id}/incidents", response_model=IncidentListResponse)
async def list_incidents(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> IncidentListResponse:
    result = await db.execute(
        select(Incident)
        .where(Incident.submission_id == submission_id)
        .options(selectinload(Incident.analysis))
    )
    incidents = result.scalars().all()

    summaries = [
        IncidentSummary(
            incident_id=i.incident_id,
            status=i.status,
            root_cause_service=i.analysis.root_cause_service if i.analysis else None,
            confidence_score=i.analysis.confidence_score if i.analysis else None,
        )
        for i in incidents
    ]
    return IncidentListResponse(incidents=summaries)


@router.get("/submissions/{submission_id}/stream")
async def stream_submission_progress(
    submission_id: str,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key_sse),
) -> StreamingResponse:
    """
    SSE stream of analysis progress for a submission.
    Stage-1 and Stage-2 jobs publish tokens to Redis pub/sub.
    This endpoint subscribes and forwards them to the client.
    Accepts auth via X-API-Key header or ?api_key= query param (for EventSource).
    """
    channel = RedisKeys.sse_channel(submission_id)

    # Check if the submission already finished before the client connected.
    # Redis pub/sub does not buffer — if __DONE__ was published before this
    # subscriber arrived, it is lost.  Detect that here and short-circuit.
    result = await db.execute(
        select(Submission.raw_status).where(Submission.submission_id == uuid.UUID(submission_id))
    )
    existing_status = result.scalar_one_or_none()

    async def event_generator():
        if existing_status in ("complete", "failed"):
            yield 'data: {"step": "complete", "progress_pct": 100}\n\n'
            yield "data: __DONE__\n\n"
            return

        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data = message["data"]
                if data == "__DONE__":
                    yield 'data: {"step": "complete", "progress_pct": 100}\n\n'
                    yield "data: __DONE__\n\n"
                    break
                yield f"data: {data}\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


_ALLOWED_MIME_PREFIXES = ("text/", "application/json", "application/x-ndjson")


@router.post("/submissions", response_model=SubmissionResponse, status_code=202)
async def create_submission(
    files: list[UploadFile] = File(...),
    time_window_seconds: int = Form(default=30),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    storage: ObjectStorage = Depends(get_storage),
    api_key: ApiKey = Depends(require_api_key),
) -> SubmissionResponse:
    """
    Upload log files for analysis.

    Accepts up to 20 text files (≤100 MB each). Files are streamed to object
    storage without loading into memory. Stage-1 is dispatched asynchronously.
    """
    cfg = get_settings()
    max_file_bytes = cfg.upload_max_file_mb * 1024 * 1024
    max_total_bytes = cfg.upload_max_total_mb * 1024 * 1024

    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")
    if len(files) > cfg.upload_max_files:
        raise HTTPException(
            status_code=422, detail=f"Maximum {cfg.upload_max_files} files per upload"
        )

    total_size = sum(f.size for f in files if f.size is not None)
    if total_size > max_total_bytes:
        raise HTTPException(
            status_code=422,
            detail=f"Total upload size {total_size // (1024*1024)} MB exceeds limit of {cfg.upload_max_total_mb} MB",
        )

    submission_id = uuid.uuid4()
    object_keys: list[str] = []
    file_names: list[str] = []

    for f in files:
        if f.size and f.size > max_file_bytes:
            raise HTTPException(
                status_code=422,
                detail=f"File {f.filename!r} is {f.size // (1024*1024)} MB, limit is {cfg.upload_max_file_mb} MB per file",
            )
        content_type = f.content_type or "text/plain"
        if not any(content_type.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
            raise HTTPException(
                status_code=422,
                detail=f"File {f.filename!r} has unsupported content type {content_type!r}",
            )
        key = f"submissions/{submission_id}/{f.filename}"
        await storage.upload_fileobj(f.file, key)
        object_keys.append(key)
        file_names.append(f.filename or key)

    submission = Submission(
        submission_id=submission_id,
        source_method="upload",
        file_names={"files": file_names},
        object_keys={"keys": object_keys},
        raw_status="received",
    )
    db.add(submission)
    await db.commit()

    # Enqueue Stage-1 via the analysis queue
    import json

    payload = json.dumps(
        {
            "submission_id": str(submission_id),
            "source_method": "upload",
            "time_window_seconds": time_window_seconds,
        }
    )
    await redis.xadd(RedisKeys.analysis_queue(), {"payload": payload})

    log.info("submission_created", submission_id=str(submission_id), files=len(files))
    return SubmissionResponse(submission_id=submission_id, status="received")
