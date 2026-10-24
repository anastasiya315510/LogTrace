"""
BaseProducer — shared HTTP push logic for all demo microservice simulators.

Single responsibility: push a batch of log events to POST /api/v1/ingest.
All error handling is isolated here so individual producers never crash on network errors.
"""

import asyncio
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import httpx
import structlog

log = structlog.get_logger()


class BaseProducer(ABC):
    """
    Abstract base for a simulated microservice that pushes log events to NemoTrace.

    Subclasses implement:
        run_normal(duration_seconds)  — push background traffic
        run_cascade(trace_id)         — inject service-specific failure events
    """

    def __init__(self, service_name: str, ingest_url: str, api_key: str) -> None:
        self.service_name = service_name
        self.ingest_url = ingest_url
        self.api_key = api_key
        self._active_trace_id: str | None = None
        self._client = httpx.AsyncClient(timeout=5.0)

    # ── Public interface ──────────────────────────────────────────────────────

    @abstractmethod
    async def run_normal(self, duration_seconds: int) -> None:
        """Push realistic background traffic for the given duration."""

    @abstractmethod
    async def run_cascade(self, trace_id: str, scenario: str = "pool_exhaustion") -> None:
        """Inject service-specific failure events with the shared trace_id."""

    # ── Shared helpers ────────────────────────────────────────────────────────

    def make_event(
        self,
        level: str,
        message: str,
        *,
        error_type: str | None = None,
        stack_trace: str | None = None,
        trace_id: str | None = None,
        duration_ms: int | None = None,
        extra: dict | None = None,
    ) -> dict:
        """Build a single log event dict in NemoTrace's recommended JSON schema."""
        event: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "service": self.service_name,
            "message": message,
            "trace_id": trace_id or self._active_trace_id or "",
            "error_type": error_type or "",
            "stack_trace": stack_trace or "",
            "duration_ms": duration_ms,
        }
        if extra:
            event.update(extra)
        return event

    async def push(self, events: list[dict]) -> None:
        """
        POST events to /api/v1/ingest. Never raises — producers must not crash on network errors.
        Logs a warning if the push fails so failures are visible without stopping the demo.
        """
        try:
            response = await self._client.post(
                self.ingest_url,
                json={"service": self.service_name, "events": events},
                headers={"X-API-Key": self.api_key},
            )
            if response.status_code != 200:
                log.warning(
                    "ingest_push_failed",
                    service=self.service_name,
                    status=response.status_code,
                    body=response.text[:200],
                )
            else:
                levels = [e.get("level", "?") for e in events]
                log.debug(
                    "ingest_push_ok",
                    service=self.service_name,
                    count=len(events),
                    levels=levels,
                )
        except httpx.RequestError as exc:
            log.warning(
                "ingest_push_network_error",
                service=self.service_name,
                error=str(exc),
            )

    async def close(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()

    # ── Command listener ──────────────────────────────────────────────────────

    async def listen_for_commands(self, redis_url: str) -> None:
        """
        Subscribe to the demo:commands Redis pub/sub channel.
        Drives the producer lifecycle from the /demo API endpoints.
        """
        import json

        import redis.asyncio as aioredis

        # Fresh httpx client for each session so a previous close doesn't linger.
        self._client = httpx.AsyncClient(timeout=5.0)

        r = aioredis.from_url(redis_url, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe("demo:commands")

        log.info("producer_listening", service=self.service_name)

        _tasks: list[asyncio.Task] = []

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            cmd = json.loads(message["data"])
            command = cmd.get("command")

            if command == "start_normal":
                duration = cmd.get("duration_seconds", 60)
                log.info("producer_cmd_start_normal", service=self.service_name, duration=duration)
                _tasks.append(asyncio.create_task(self.run_normal(duration)))

            elif command == "cascade":
                trace_id = cmd.get("trace_id", uuid.uuid4().hex)
                scenario = cmd.get("scenario", "pool_exhaustion")
                log.info("producer_cmd_cascade", service=self.service_name, scenario=scenario, trace_id=trace_id)
                _tasks.append(asyncio.create_task(self.run_cascade(trace_id, scenario)))

            elif command == "stop":
                log.info("producer_stopping", service=self.service_name)
                # Cancel any still-running normal/cascade tasks so they don't
                # try to push events after the httpx client is closed.
                for t in _tasks:
                    t.cancel()
                if _tasks:
                    await asyncio.gather(*_tasks, return_exceptions=True)
                break

        await pubsub.unsubscribe("demo:commands")
        await pubsub.aclose()
        await r.aclose()
        await self.close()
