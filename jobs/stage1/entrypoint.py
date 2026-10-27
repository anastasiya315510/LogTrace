"""
jobs/stage1/entrypoint.py

Stage-1 job: parse events → correlate → infer topology → insert incidents → dispatch Stage-2.

Entry point: `python -m jobs.stage1.entrypoint`
Required env var: SUBMISSION_ID (UUID string)
Optional env var: SOURCE_METHOD (auto_trigger | upload) — defaults to upload
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC

import structlog
from sqlalchemy import select, update

from core.config import get_settings
from core.database import get_session_factory
from core.redis_client import get_redis_pool
from core.redis_keys import RedisKeys
from db.models import LogEvent, Submission
from jobs.stage1.correlator import IncidentGroup, select_correlator
from jobs.stage1.parser import BaseParser, detect_format
from jobs.stage1.topology import TopologyInferrer

log = structlog.get_logger()


async def _read_events_from_redis(
    submission_id: uuid.UUID,
    submission: Submission,
    redis,
) -> list[dict]:
    """Read raw event dicts from Redis Streams captured in the ingest window."""
    services_to_read: list[str] = []

    # Discover all ingest streams
    async for key in redis.scan_iter("stream:ingest:*"):
        service = key.split(b":")[-1].decode() if isinstance(key, bytes) else key.split(":")[-1]
        services_to_read.append(service)

    raw_events: list[dict] = []
    for service in services_to_read:
        stream_key = RedisKeys.ingest_stream(service)
        # Read up to 50k entries; apply time window filter if available
        entries = await redis.xrange(stream_key, count=50_000)
        for _entry_id, fields in entries:
            event = {
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in fields.items()
            }
            # Apply ingest window filter when available
            if submission.ingest_window_start and submission.ingest_window_end:
                try:
                    from dateutil import parser as dp

                    ts = dp.parse(event.get("timestamp", ""))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    if not (submission.ingest_window_start <= ts <= submission.ingest_window_end):
                        continue
                except Exception:
                    pass
            raw_events.append(event)
    return raw_events


async def _read_events_from_s3(submission: Submission) -> list[dict]:
    """Read raw events from S3 object keys stored on the submission."""
    from core.storage import get_storage

    storage = get_storage()

    raw_events: list[dict] = []
    object_keys = submission.object_keys or {}
    keys = object_keys if isinstance(object_keys, list) else list(object_keys.values())

    for key in keys:
        content = b""
        async for chunk in storage.stream_object(key):
            content += chunk
        for line in content.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                raw_events.append({"_raw_line": line, "_key": key})
    return raw_events


def _parse_raw_events(
    raw_events: list[dict],
    submission_id: uuid.UUID,
) -> list[LogEvent]:
    """Convert raw dicts from Redis Streams or S3 into LogEvent objects."""
    parsed: list[LogEvent] = []

    for raw in raw_events:
        # Redis Streams entries already have structured fields
        if "message" in raw and "_raw_line" not in raw:
            from db.models import LogEvent as LE
            from jobs.stage1.parser import _normalise_level, _parse_timestamp

            parsed.append(
                LE(
                    event_id=uuid.uuid4(),
                    submission_id=submission_id,
                    service_name=raw.get("service", "unknown"),
                    event_timestamp=_parse_timestamp(raw.get("timestamp")),
                    level=_normalise_level(raw.get("level", "INFO")),
                    message=raw.get("message", ""),
                    trace_id=raw.get("trace_id") or None,
                    span_id=raw.get("span_id") or None,
                    error_type=raw.get("error_type") or None,
                    stack_trace=raw.get("stack_trace") or None,
                    raw_line=json.dumps(raw),
                )
            )
        else:
            # S3 / file upload: parse raw line with format detection
            line = raw.get("_raw_line", "")
            service = raw.get("_key", "").split("/")[-1].replace(".log", "")
            parser_class = detect_format(line)
            parser: BaseParser = parser_class()
            event = parser.parse_line(line, service, submission_id)
            if event:
                parsed.append(event)

    return parsed


async def _batch_insert_events(
    session,
    events: list[LogEvent],
) -> None:
    for event in events:
        session.add(event)
    await session.flush()


async def _insert_incident(
    session,
    group: IncidentGroup,
) -> None:
    session.add(group.incident)
    await session.flush()


async def _enqueue_stage2(redis, incident_id: uuid.UUID, submission_id: uuid.UUID) -> None:
    """Push stage-2 job to the analysis queue and dispatch as subprocess."""
    payload = json.dumps(
        {
            "incident_id": str(incident_id),
            "submission_id": str(submission_id),
        }
    )
    await redis.xadd(RedisKeys.analysis_queue(), {"payload": payload})
    log.info("stage2_enqueued", incident_id=str(incident_id))

    env = {
        **os.environ,
        "INCIDENT_ID": str(incident_id),
        "SUBMISSION_ID": str(submission_id),
    }
    log_path = f"/tmp/logtrace/stage2_{str(incident_id)[:8]}.log"
    try:
        # start_new_session=True detaches Stage 2 from Stage 1's process group
        # so it survives when Stage 1's event loop closes.
        with open(log_path, "w") as log_fh:
            proc = subprocess.Popen(
                [sys.executable, "-m", "jobs.stage2.entrypoint"],
                env=env,
                stdout=log_fh,
                stderr=log_fh,
                start_new_session=True,
            )
        log.info("stage2_dispatched", incident_id=str(incident_id), pid=proc.pid, log=log_path)
    except Exception:
        log.exception("stage2_dispatch_failed", incident_id=str(incident_id))


async def _update_submission_status(session, submission_id: uuid.UUID, status: str) -> None:
    await session.execute(
        update(Submission)
        .where(Submission.submission_id == submission_id)
        .values(raw_status=status)
    )


async def main() -> None:
    submission_id = uuid.UUID(os.environ["SUBMISSION_ID"])
    source_method = os.environ.get("SOURCE_METHOD", "upload")

    log.info("stage1_starting", submission_id=str(submission_id), source_method=source_method)

    settings = get_settings()
    session_factory = get_session_factory()
    redis = get_redis_pool()

    async with session_factory() as session:
        # Load submission
        result = await session.execute(
            select(Submission).where(Submission.submission_id == submission_id)
        )
        submission = result.scalar_one_or_none()
        if submission is None:
            log.error("submission_not_found", submission_id=str(submission_id))
            return

        await _update_submission_status(session, submission_id, "processing")
        await session.commit()

    try:
        # Read raw events
        if source_method == "auto_trigger":
            async with session_factory() as session:
                result = await session.execute(
                    select(Submission).where(Submission.submission_id == submission_id)
                )
                submission = result.scalar_one()
            raw_events = await _read_events_from_redis(submission_id, submission, redis)
        else:
            async with session_factory() as session:
                result = await session.execute(
                    select(Submission).where(Submission.submission_id == submission_id)
                )
                submission = result.scalar_one()
            raw_events = await _read_events_from_s3(submission)

        log.info("events_read", count=len(raw_events))

        if not raw_events:
            async with session_factory() as session:
                await _update_submission_status(session, submission_id, "no_incidents")
                await session.commit()
            return

        # Parse events
        events = _parse_raw_events(raw_events, submission_id)
        log.info("events_parsed", count=len(events))

        if not events:
            async with session_factory() as session:
                await _update_submission_status(session, submission_id, "no_incidents")
                await session.commit()
            return

        # Insert LogEvents
        async with session_factory() as session:
            await _batch_insert_events(session, events)
            await session.commit()

        # Correlate
        correlator = select_correlator(events, window_seconds=settings.time_window_seconds)
        incident_groups = correlator.correlate(events)
        log.info("incidents_correlated", count=len(incident_groups))

        if not incident_groups:
            async with session_factory() as session:
                await _update_submission_status(session, submission_id, "no_incidents")
                await session.commit()
            return

        # Insert incidents and dispatch Stage-2
        inferrer = TopologyInferrer()
        for group in incident_groups:
            topology = inferrer.infer(group.events)
            group.incident.service_topology_json = topology

            async with session_factory() as session:
                await _insert_incident(session, group)
                await session.commit()

            await _enqueue_stage2(redis, group.incident.incident_id, submission_id)

        async with session_factory() as session:
            await _update_submission_status(session, submission_id, "processing")
            await session.commit()

        log.info(
            "stage1_complete", submission_id=str(submission_id), incidents=len(incident_groups)
        )

    except Exception:
        log.exception("stage1_failed", submission_id=str(submission_id))
        async with session_factory() as session:
            await _update_submission_status(session, submission_id, "failed")
            await session.commit()
        raise


if __name__ == "__main__":
    asyncio.run(main())
