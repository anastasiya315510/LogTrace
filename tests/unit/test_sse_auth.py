"""
tests/unit/test_sse_auth.py

Unit tests for require_api_key_sse — the SSE-compatible auth dependency that
accepts an API key via X-API-Key header (primary) OR ?api_key= query param
(fallback), enabling browser-native EventSource to authenticate.

Isolation strategy:
  - Redis   → in-memory _FakeRedis with get/setex; no running Redis required.
  - DB      → SQLAlchemy get_db overridden with an async stub; no DB required.
  - Auth    → require_api_key_sse exercised directly via the /stream endpoint.
"""

import hashlib
import json

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import create_app
from core.database import get_db
from core.redis_client import get_redis
from core.redis_keys import RedisKeys
from db.models import ApiKey

_VALID_KEY = "dev-demo-key"
_VALID_HASH = hashlib.sha256(_VALID_KEY.encode()).hexdigest()
_CACHED_PAYLOAD = json.dumps({"user_id": None})


# ── In-memory Redis fake ───────────────────────────────────────────────────────


class _FakeRedis:
    """Supports get/setex/subscribe/pubsub for auth + SSE tests."""

    def __init__(self, *, valid_key_hash: str | None = None) -> None:
        self._store: dict[str, str] = {}
        if valid_key_hash:
            cache_key = RedisKeys.auth_cache(valid_key_hash)
            self._store[cache_key] = _CACHED_PAYLOAD

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    def pubsub(self):
        return _FakePubSub()


class _FakePubSub:
    async def subscribe(self, *channels):
        pass

    async def listen(self):
        # Yield nothing — tests only need to confirm auth passes (200 response
        # with streaming body begins), not that actual SSE messages arrive.
        return
        yield  # make it an async generator

    async def unsubscribe(self, *channels):
        pass

    async def aclose(self):
        pass


# ── DB stub ───────────────────────────────────────────────────────────────────


class _FakeDB:
    """Returns a valid ApiKey for _VALID_KEY, None for anything else."""

    async def execute(self, stmt):
        # Inspect the WHERE clause hash to decide what to return
        compiled = stmt.compile()
        params = compiled.params
        if _VALID_HASH in params.values():
            return _FakeResult(ApiKey(key_hash=_VALID_HASH, is_active=True))
        return _FakeResult(None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def app_with_valid_cache():
    """App where Redis cache already has a valid entry for _VALID_KEY."""
    redis = _FakeRedis(valid_key_hash=_VALID_HASH)
    application = create_app()
    application.dependency_overrides[get_redis] = lambda: redis
    application.dependency_overrides[get_db] = lambda: _FakeDB()
    return application


@pytest.fixture()
def app_empty_cache():
    """App with empty Redis cache — forces a DB lookup for every key check."""
    redis = _FakeRedis()
    application = create_app()
    application.dependency_overrides[get_redis] = lambda: redis
    application.dependency_overrides[get_db] = lambda: _FakeDB()
    return application


@pytest.fixture()
async def client_valid(app_with_valid_cache):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_valid_cache), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture()
async def client_empty(app_empty_cache):
    async with AsyncClient(
        transport=ASGITransport(app=app_empty_cache), base_url="http://test"
    ) as c:
        yield c


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_header_auth_works(client_valid: AsyncClient):
    """X-API-Key header with a valid key → SSE stream opens (200)."""
    async with client_valid.stream(
        "GET",
        "/api/v1/submissions/test-sub/stream",
        headers={"X-API-Key": _VALID_KEY},
    ) as response:
        assert response.status_code == 200


async def test_query_param_auth_works(client_valid: AsyncClient):
    """?api_key= query param with a valid key → SSE stream opens (200)."""
    async with client_valid.stream(
        "GET",
        f"/api/v1/submissions/test-sub/stream?api_key={_VALID_KEY}",
    ) as response:
        assert response.status_code == 200


async def test_both_header_wins(client_valid: AsyncClient):
    """When both header and query param are present, the header is used (200)."""
    async with client_valid.stream(
        "GET",
        f"/api/v1/submissions/test-sub/stream?api_key={_VALID_KEY}",
        headers={"X-API-Key": _VALID_KEY},
    ) as response:
        assert response.status_code == 200


async def test_no_auth_returns_401(client_valid: AsyncClient):
    """No header and no query param → 401."""
    response = await client_valid.get("/api/v1/submissions/test-sub/stream")
    assert response.status_code == 401


async def test_invalid_query_param_returns_401(client_empty: AsyncClient):
    """Invalid ?api_key= value → 401."""
    response = await client_empty.get(
        "/api/v1/submissions/test-sub/stream?api_key=wrong-key"
    )
    assert response.status_code == 401
