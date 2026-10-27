"""
stream_processor/processor.py

Long-running process: reads Redis Streams, detects error spikes, creates Submissions,
dispatches Stage-1 jobs.

Entry point: `python -m stream_processor.processor`

Spike conditions (any one triggers):
1. Single service: ≥ error_spike_threshold ERRORs/CRITICALs within error_spike_window_seconds
2. CRITICAL level event (immediate)
3. Same error_type in ≥ 3 services within 30 s

Debounce: suppress re-trigger for the same service within trigger_debounce_seconds.
"""

import asyncio
import contextlib
import os
import sys
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime

import structlog

from core.config import get_settings
from core.database import get_session_factory
from core.redis_client import get_redis_pool
from core.redis_keys import RedisKeys
from db.models import Submission

log = structlog.get_logger()

_CROSS_SERVICE_WINDOW_SECONDS = 30
_CROSS_SERVICE_MIN_SERVICES = 3


class StreamProcessor:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis = None
        self._session_factory = None

        # per-service sliding window of (timestamp_float, level) tuples
        self._windows: dict[str, deque] = defaultdict(deque)
        # per-service last trigger time (monotonic)
        self._last_triggered: dict[str, float] = {}
        # cross-service: recent error_type → [(service, timestamp_float)]
        self._error_type_window: dict[str, list[tuple[str, float]]] = defaultdict(list)

    async def run(self) -> None:
        self._redis = get_redis_pool()
        self._session_factory = get_session_factory()

        log.info("stream_processor_started")

        await self._ensure_consumer_group_exists()

        while True:
            try:
                await self._process_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("stream_processor_error")
                await asyncio.sleep(1)

    async def _ensure_consumer_group_exists(self) -> None:
        """Create consumer groups on all known streams (idempotent)."""
        streams = await self._discover_streams()
        for stream in streams:
            with contextlib.suppress(Exception):  # BUSYGROUP means group already exists
                await self._redis.xgroup_create(
                    stream,
                    RedisKeys.SP_CONSUMER_GROUP,
                    id="0",
                    mkstream=True,
                )

    async def _check_reset_signal(self) -> None:
        """Clear in-memory state if demo reset was requested."""
        if await self._redis.getdel(RedisKeys.SP_RESET_SIGNAL):
            self._windows.clear()
            self._last_triggered.clear()
            self._error_type_window.clear()
            log.info("stream_processor_state_reset")

    async def _process_once(self) -> None:
        await self._check_reset_signal()

        streams = await self._discover_streams()
        if not streams:
            await asyncio.sleep(1)
            return

        # Ensure consumer group exists on any new streams discovered mid-run.
        # id="0" reads from the beginning so events pushed before the group
        # was created are not silently skipped.
        for stream in streams:
            with contextlib.suppress(Exception):
                await self._redis.xgroup_create(
                    stream,
                    RedisKeys.SP_CONSUMER_GROUP,
                    id="0",
                    mkstream=True,
                )

        stream_dict = {s: ">" for s in streams}
        try:
            messages = await self._redis.xreadgroup(
                RedisKeys.SP_CONSUMER_GROUP,
                RedisKeys.SP_CONSUMER_NAME,
                stream_dict,
                count=200,
                block=1000,
            )
        except Exception as exc:
            log.warning("xreadgroup_error", error=str(exc))
            await asyncio.sleep(1)
            return

        if not messages:
            return

        for stream_name, entries in messages:
            service = self._extract_service(stream_name)
            for entry_id, fields in entries:
                await self._process_entry(service, fields, stream_name, entry_id)

    async def _process_entry(
        self,
        service: str,
        fields: dict,
        stream_name: str | bytes,
        entry_id: str | bytes,
    ) -> None:
        def _decode(v):
            return v.decode() if isinstance(v, bytes) else str(v)

        level = _decode(fields.get(b"level") or fields.get("level") or "INFO").upper()
        error_type = _decode(fields.get(b"error_type") or fields.get("error_type") or "")

        now = datetime.now(UTC).timestamp()

        # Add to sliding window
        window = self._windows[service]
        window.append((now, level, error_type))

        # Add to cross-service error_type window
        if error_type:
            self._error_type_window[error_type].append((service, now))

        # Trim windows
        spike_window = self._settings.error_spike_window_seconds
        cross_window = _CROSS_SERVICE_WINDOW_SECONDS
        while window and now - window[0][0] > spike_window:
            window.popleft()
        for etype, entries in list(self._error_type_window.items()):
            self._error_type_window[etype] = [e for e in entries if now - e[1] <= cross_window]

        # Check spike conditions
        await self._check_spike_conditions(service, level, error_type, now)

        # ACK the message
        stream_key = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
        entry_key = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
        with contextlib.suppress(Exception):
            await self._redis.xack(stream_key, RedisKeys.SP_CONSUMER_GROUP, entry_key)

    async def _check_spike_conditions(
        self,
        service: str,
        level: str,
        error_type: str,
        now: float,
    ) -> bool:
        # Debounce check
        last = self._last_triggered.get(service, 0)
        if now - last < self._settings.trigger_debounce_seconds:
            return False

        triggered = False
        trigger_reason = None

        # Condition 1: CRITICAL event
        if level == "CRITICAL":
            triggered = True
            trigger_reason = "critical_event"

        # Condition 2: single-service spike
        if not triggered:
            error_count = sum(
                1 for _, lvl, _ in self._windows[service] if lvl in ("ERROR", "CRITICAL")
            )
            if error_count >= self._settings.error_spike_threshold:
                triggered = True
                trigger_reason = f"single_service_spike:{error_count}"

        # Condition 3: same error_type in 3+ services
        if not triggered and error_type:
            recent_services = {svc for svc, _ in self._error_type_window.get(error_type, [])}
            if len(recent_services) >= _CROSS_SERVICE_MIN_SERVICES:
                triggered = True
                trigger_reason = f"cross_service_spike:{error_type}"

        if triggered:
            self._last_triggered[service] = now
            log.info(
                "spike_detected",
                service=service,
                reason=trigger_reason,
            )
            await self._trigger_analysis(service)

        return triggered

    async def _trigger_analysis(self, service: str) -> None:
        """Insert a Submission and dispatch Stage-1."""
        now = datetime.now(UTC)
        submission_id = uuid.uuid4()

        # Compute ingest window (last spike_window_seconds)
        window_start_ts = now.timestamp() - self._settings.error_spike_window_seconds
        window_start = datetime.fromtimestamp(window_start_ts, tz=UTC)

        submission = Submission(
            submission_id=submission_id,
            source_method="auto_trigger",
            ingest_window_start=window_start,
            ingest_window_end=now,
            raw_status="received",
        )

        try:
            async with self._session_factory() as session:
                session.add(submission)
                await session.commit()
        except Exception:
            log.exception("submission_insert_failed")
            return

        # Update demo state
        with contextlib.suppress(Exception):
            await self._redis.hset(
                RedisKeys.DEMO_STATE,
                mapping={
                    "auto_triggered": "1",
                    "submission_id": str(submission_id),
                },
            )

        log.info("submission_created", submission_id=str(submission_id))

        # Dispatch Stage-1 as a subprocess
        await self._dispatch_stage1(submission_id)

    async def _dispatch_stage1(self, submission_id: uuid.UUID) -> None:
        env = {**os.environ, "SUBMISSION_ID": str(submission_id), "SOURCE_METHOD": "auto_trigger"}
        log_path = f"/tmp/nemotrace/stage1_{str(submission_id)[:8]}.log"
        os.makedirs("/tmp/nemotrace", exist_ok=True)
        try:
            with open(log_path, "w") as log_fh:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "jobs.stage1.entrypoint",
                    env=env,
                    stdout=log_fh,
                    stderr=log_fh,
                )
            log.info(
                "stage1_dispatched", submission_id=str(submission_id), pid=proc.pid, log=log_path
            )
            # Fire-and-forget; the subprocess manages its own lifecycle
        except Exception:
            log.exception("stage1_dispatch_failed", submission_id=str(submission_id))

    async def _discover_streams(self) -> list[str]:
        """Return all stream:ingest:* keys present in Redis."""
        streams = []
        try:
            async for key in self._redis.scan_iter("stream:ingest:*"):
                streams.append(key.decode() if isinstance(key, bytes) else key)
        except Exception as exc:
            log.warning("stream_discovery_error", error=str(exc))
        return streams

    @staticmethod
    def _extract_service(stream_name: str | bytes) -> str:
        name = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
        parts = name.split(":")
        return parts[-1] if parts else name


async def _main() -> None:
    processor = StreamProcessor()
    await processor.run()


if __name__ == "__main__":
    asyncio.run(_main())
