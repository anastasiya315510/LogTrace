# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running the API (local dev)
```bash
# Start infrastructure (Postgres + Redis)
docker compose up postgres redis -d

# Run the API with hot-reload
uvicorn api.main:app --reload

# Run with demo producers (separate profile)
docker compose --profile demo up
```

### Tests
```bash
# All tests
pytest

# Single test file
pytest tests/unit/test_ingest.py

# Single test by name
pytest tests/unit/test_ingest.py::test_accept_10_events -v
```

### Linting
```bash
ruff check .
ruff format .
```

### Database migrations
```bash
# Generate a new migration from ORM changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

### Environment
All config is loaded from `.env` via `pydantic-settings`. Required variables: `DATABASE_URL`, `REDIS_URL`, `NEBIUS_BASE_URL`, `NANO_MODEL_ID`, `ULTRA_MODEL_ID`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ENDPOINT`, `DEMO_API_KEY`. See `core/config.py` for all settings and their defaults.

The dev demo API key defaults to `dev-demo-key` and is auto-seeded into the DB on startup.

---

## Architecture

NemoTrace is a FastAPI service that ingests microservice log events, detects anomaly spikes via a Redis Stream Processor, then runs a two-stage AI pipeline (classify → RCA) to produce structured incident reports.

### Request / data flow

```
Log producer
    → POST /api/v1/ingest       (hot path, Redis Streams only, target p99 < 50ms)
    → stream:ingest:{service}   (Redis Stream, one per service)
    → Stream Processor          (XREADGROUP consumer, spike detector)
    → Submission created in PG  (source_method = auto_trigger)
    → Stage-1 job               (parse → correlate → build incidents)
    → Stage-2 job per incident  (classify with Nano 8B → RCA with Ultra 253B → Tavily fix suggestions)
    → SSE channel published     (sse:submission:{id} → GET /api/v1/submissions/{id}/stream)
    → Incident report in PG
```

### Key modules

| Module | Responsibility |
|--------|---------------|
| `api/` | FastAPI app. `main.py` is the app factory. All routers live under `api/routers/`. Pydantic schemas in `api/models/schemas.py`. |
| `core/` | Shared infrastructure: async SQLAlchemy engine (`database.py`), Redis pool (`redis_client.py`), S3-compatible Nebius storage (`storage.py`), all env config (`config.py`). |
| `core/redis_keys.py` | **Single source of truth** for every Redis key/channel name. Import from here — never hardcode key strings. |
| `db/models.py` | All 7 SQLAlchemy ORM tables: `Submission`, `LogEvent`, `Incident`, `EventClassification`, `IncidentAnalysis`, `FixSuggestion`, `ApiKey`. |
| `stream_processor/` | Long-running process. Reads Redis Streams with XREADGROUP, detects error spikes, creates Submissions and dispatches Stage-1. |
| `jobs/stage1/` | Parses raw log events, correlates them by trace_id or time window, infers service topology, creates Incident rows. |
| `jobs/stage2/` | Per-incident: batch-classifies events via Nemotron Nano 8B (`classifier.py`), runs multi-turn RCA via Nemotron Ultra 253B with SSE streaming (`rca.py`), fetches fix suggestions from Tavily (`fix_suggestions.py`). |
| `demo/` | Demo producers (`payment_service.py`, `order_service.py`, `api_gateway.py`) push synthetic events. Orchestrated via Redis pub/sub (`demo:commands` channel) from the `/demo/*` API endpoints. |
| `portal/` | Streamlit investigation UI (Week 4, not yet implemented). |

### AI models

Both models are accessed through the **OpenAI-compatible client** (`openai==1.50.2`) pointed at **Nebius Token Factory** (`nebius_base_url`):
- **Nano 8B** (`nano_model_id`): fast batch event classification — `asyncio.gather` with up to `nano_parallel_calls` concurrent requests.
- **Ultra 253B** (`ultra_model_id`): multi-turn RCA conversation, streams tokens via SSE to the portal.

Nebius Object Storage uses **boto3** with a custom `endpoint_url` — it speaks the S3 API.

### Auth

`X-API-Key` header, validated in `api/dependencies.py`. Keys are SHA-256 hashed; valid results are cached in Redis for 5 minutes (`auth:key:{hash}`) to avoid per-request DB hits.

### Testing conventions

Unit tests use in-process fakes (`_FakeRedis` class pattern) and FastAPI `dependency_overrides` — no live Redis or DB required. `pytest-asyncio` is configured with `asyncio_mode = auto` so all async tests just work. Integration tests live under `tests/integration/`.