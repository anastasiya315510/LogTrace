"""
tests/unit/test_ingest.py

Unit tests for POST /api/v1/ingest.

Isolation strategy:
  - Redis   → in-memory _FakeRedis; no running Redis required.
  - Auth    → require_api_key overridden with a stub; no DB required.
  - Settings→ api.routers.ingest.get_settings patched with a MagicMock
              that provides only the two fields the handler uses.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.dependencies import require_api_key
from api.main import create_app
from core.database import get_db
from core.redis_client import get_redis
from core.redis_keys import RedisKeys
from db.models import ApiKey

# ── In-memory Redis fake ───────────────────────────────────────────────────────


class _FakePipeline:
    """Records XADD ops, flushes them on execute()."""

    def __init__(self, streams: dict[str, list]) -> None:
        self._streams = streams
        self._pending: list[tuple[str, dict]] = []

    def xadd(self, stream: str, fields: dict, maxlen=None, approximate=False):
        self._pending.append((stream, dict(fields)))
        return self

    async def execute(self) -> list:
        for stream, fields in self._pending:
            self._streams.setdefault(stream, []).append(fields)
        results = [True] * len(self._pending)
        self._pending.clear()
        return results


class _FakeRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[dict]] = {}
        self._hashes: dict[str, dict] = {}

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        return _FakePipeline(self.streams)

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        bucket = self._hashes.setdefault(key, {})
        bucket[field] = bucket.get(field, 0) + amount
        return bucket[field]

    async def xlen(self, stream: str) -> int:
        return len(self.streams.get(stream, []))


class _FakeDB:
    """Minimal async DB stub — no real DB needed."""

    async def execute(self, stmt):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────


def _event(
    level: str = "INFO",
    message: str = "test event",
    trace_id: str | None = None,
) -> dict:
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "message": message,
        "trace_id": trace_id,
    }


def _minimal_event() -> dict:
    """Only the three required fields — no optional fields at all."""
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": "WARN",
        "message": "high latency detected",
    }


def _mock_settings(
    max_events: int = 500,
    stream_maxlen: int = 50_000,
) -> MagicMock:
    s = MagicMock()
    s.ingest_max_events_per_call = max_events
    s.ingest_stream_maxlen = stream_maxlen
    return s


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture()
def app(fake_redis: _FakeRedis):
    application = create_app()
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[require_api_key] = lambda: ApiKey(
        key_hash="stubhash", is_active=True
    )
    return application


@pytest.fixture()
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_accept_10_events(client: AsyncClient, fake_redis: _FakeRedis):
    """Core smoke test: POST 10 events → accepted=10, dropped=0, XLEN==10."""
    with patch("api.routers.ingest.get_settings", return_value=_mock_settings()):
        response = await client.post(
            "/api/v1/ingest",
            json={"service": "payment-service", "events": [_event() for _ in range(10)]},
            headers={"X-API-Key": "dev-demo-key"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 10
    assert body["dropped"] == 0

    # Drain the fire-and-forget background task before checking stream length.
    await asyncio.sleep(0)
    stream = RedisKeys.ingest_stream("payment-service")
    assert await fake_redis.xlen(stream) == 10


async def test_hard_cap_drops_excess(client: AsyncClient, fake_redis: _FakeRedis):
    """Events beyond the 500-per-call cap are reported as dropped, not silently lost."""
    with patch("api.routers.ingest.get_settings", return_value=_mock_settings()):
        response = await client.post(
            "/api/v1/ingest",
            json={"service": "order-service", "events": [_event() for _ in range(502)]},
            headers={"X-API-Key": "dev-demo-key"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 500
    assert body["dropped"] == 2

    await asyncio.sleep(0)
    stream = RedisKeys.ingest_stream("order-service")
    assert await fake_redis.xlen(stream) == 500


async def test_optional_fields_absent(client: AsyncClient, fake_redis: _FakeRedis):
    """Event with only the three required fields is accepted without error."""
    with patch("api.routers.ingest.get_settings", return_value=_mock_settings()):
        response = await client.post(
            "/api/v1/ingest",
            json={"service": "api-gateway", "events": [_minimal_event()]},
            headers={"X-API-Key": "dev-demo-key"},
        )

    assert response.status_code == 200
    assert response.json()["accepted"] == 1


async def test_level_normalised_to_uppercase(client: AsyncClient, fake_redis: _FakeRedis):
    """Level is stored as uppercase regardless of what the producer sends."""
    with patch("api.routers.ingest.get_settings", return_value=_mock_settings()):
        await client.post(
            "/api/v1/ingest",
            json={"service": "payment-service", "events": [_event(level="error")]},
            headers={"X-API-Key": "dev-demo-key"},
        )

    await asyncio.sleep(0)
    stream = RedisKeys.ingest_stream("payment-service")
    entries = fake_redis.streams.get(stream, [])
    assert len(entries) == 1
    assert entries[0]["level"] == "ERROR"


async def test_separate_stream_per_service(client: AsyncClient, fake_redis: _FakeRedis):
    """Each service name gets its own isolated Redis Stream key."""
    services = ["payment-service", "order-service", "api-gateway"]
    with patch("api.routers.ingest.get_settings", return_value=_mock_settings()):
        for service in services:
            await client.post(
                "/api/v1/ingest",
                json={"service": service, "events": [_event()]},
                headers={"X-API-Key": "dev-demo-key"},
            )

    await asyncio.sleep(0)
    for service in services:
        stream = RedisKeys.ingest_stream(service)
        assert (
            await fake_redis.xlen(stream) == 1
        ), f"Expected exactly 1 entry in stream for {service!r}"
    # Total events across all streams equals the number of services
    total = sum(len(v) for v in fake_redis.streams.values())
    assert total == len(services)


async def test_trace_id_stored_in_stream(client: AsyncClient, fake_redis: _FakeRedis):
    """trace_id is written to the stream entry so the Stream Processor can correlate."""
    tid = "4bf92f3577b34da6a3ce929d0e0e4736"
    with patch("api.routers.ingest.get_settings", return_value=_mock_settings()):
        await client.post(
            "/api/v1/ingest",
            json={"service": "payment-service", "events": [_event(trace_id=tid)]},
            headers={"X-API-Key": "dev-demo-key"},
        )

    await asyncio.sleep(0)
    stream = RedisKeys.ingest_stream("payment-service")
    entries = fake_redis.streams[stream]
    assert entries[0]["trace_id"] == tid


async def test_missing_api_key_header_rejected(app):
    """A request with no X-API-Key header is rejected before reaching the handler."""
    # Use a fresh app with only the real require_api_key (which declares the header
    # as required). FastAPI returns 422 at parameter validation — no DB needed.
    application = create_app()
    application.dependency_overrides[get_redis] = lambda: _FakeRedis()
    application.dependency_overrides[get_db] = lambda: _FakeDB()

    with patch("api.routers.ingest.get_settings", return_value=_mock_settings()):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as c:
            response = await c.post(
                "/api/v1/ingest",
                json={"service": "svc", "events": [_event()]},
                # Deliberately no X-API-Key header
            )

    assert response.status_code == 422
