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

### Local development (all processes)
```bash
bash scripts/dev.sh start    # start API, stream processor, producers, portal dev server
bash scripts/dev.sh stop     # stop all
bash scripts/dev.sh restart  # restart all
bash scripts/dev.sh status   # show running PIDs
bash scripts/dev.sh logs     # tail all logs with color coding
bash scripts/dev.sh logs api # tail a single service log
```

Logs go to `/tmp/logtrace/*.log`. PIDs stored in `/tmp/logtrace/*.pid`.

### Environment
All config is loaded from `.env` via `pydantic-settings`. Required variables: `DATABASE_URL`, `REDIS_URL`, `NEBIUS_BASE_URL`, `NANO_MODEL_ID`, `ULTRA_MODEL_ID`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ENDPOINT`, `DEMO_API_KEY`. See `core/config.py` for all settings and their defaults.

The dev demo API key defaults to `dev-demo-key` and is auto-seeded into the DB on startup.

Upload limits (configurable, no hardcoded sizes in code):
- `UPLOAD_MAX_FILES` — max files per submission (default: 50)
- `UPLOAD_MAX_FILE_MB` — max size per file in MB (default: 50)
- `UPLOAD_MAX_TOTAL_MB` — max total upload size in MB (default: 200)

---

## Architecture

LogTrace is a FastAPI service that ingests microservice log events, detects anomaly spikes via a Redis Stream Processor, then runs a two-stage AI pipeline (classify → RCA) to produce structured incident reports.

### Request / data flow

**Auto-trigger (live demo):**
```
Log producer
    → POST /api/v1/ingest         (hot path, Redis Streams only, target p99 < 50ms)
    → stream:ingest:{service}     (Redis Stream, one per service)
    → Stream Processor            (XREADGROUP consumer, spike detector)
    → Submission created in PG    (source_method = "auto_trigger")
    → Stage-1 job                 (parse → correlate → build incidents)
    → Stage-2 job per incident    (classify with Nano 8B → RCA with Ultra 253B → Tavily fix suggestions)
    → SSE channel published       (sse:submission:{id} → GET /api/v1/submissions/{id}/stream)
    → Incident report in PG
```

**File upload:**
```
User uploads files via portal
    → POST /api/v1/submissions    (files validated against config limits, stored in Nebius S3)
    → Submission created in PG    (source_method = "upload")
    → Stage-1 job                 (reads files from S3, same parse/correlate/topology pipeline)
    → Stage-2 job per incident    (same AI pipeline — Nano classify → Ultra RCA → Tavily)
    → SSE channel published       (sse:submission:{id} → GET /api/v1/submissions/{id}/stream)
    → Incident report in PG
```

The two flows are fully isolated — no state sharing, different `source_method`, different storage backends.

### Key modules

| Module | Responsibility |
|--------|---------------|
| `api/` | FastAPI app. `main.py` is the app factory. All routers live under `api/routers/`. Pydantic schemas in `api/models/schemas.py`. |
| `core/` | Shared infrastructure: async SQLAlchemy engine (`database.py`), Redis pool (`redis_client.py`), S3-compatible Nebius storage (`storage.py`), all env config (`config.py`). |
| `core/redis_keys.py` | **Single source of truth** for every Redis key/channel name. Import from here — never hardcode key strings. |
| `db/models.py` | All 7 SQLAlchemy ORM tables: `Submission`, `LogEvent`, `Incident`, `EventClassification`, `IncidentAnalysis`, `FixSuggestion`, `ApiKey`. |
| `stream_processor/` | Long-running process. Reads Redis Streams with XREADGROUP, detects error spikes, creates Submissions and dispatches Stage-1. Watches `stream_processor:reset` Redis key to clear in-memory debounce state on demo reset. |
| `jobs/stage1/` | Parses raw log events, correlates them by trace_id or time window, infers service topology, creates Incident rows. Reads events from Redis (auto_trigger) or S3 (upload). |
| `jobs/stage2/` | Per-incident: batch-classifies events via Nemotron Nano 8B (`classifier.py`), runs multi-turn RCA via Nemotron Ultra 253B with SSE streaming (`rca.py`), fetches fix suggestions from Tavily (`fix_suggestions.py`). |
| `demo/` | Demo producers (`payment_service.py`, `order_service.py`, `api_gateway.py`) push synthetic events. Orchestrated via Redis pub/sub (`demo:commands` channel) from the `/demo/*` API endpoints. |
| `portal/` | React SPA investigation UI (Vite + Tailwind). Served at `/portal`. Tabs: **⚡ Live Demo** (auto-trigger flow) and **📂 Upload Logs** (file upload flow). Supports drag-and-drop, folder upload, SSE streaming, Markdown report download. |

### AI models

Both models are accessed through the **OpenAI-compatible client** (`openai==1.50.2`) pointed at **Nebius Token Factory** (`nebius_base_url`):
- **Nano 8B** (`nano_model_id`): fast batch event classification — `asyncio.gather` with up to `nano_parallel_calls` concurrent requests.
- **Ultra 253B** (`ultra_model_id`): multi-turn RCA conversation, streams tokens via SSE to the portal.

Nebius Object Storage uses **boto3** with a custom `endpoint_url` — it speaks the S3 API.

### Auth

`X-API-Key` header, validated in `api/dependencies.py`. Keys are SHA-256 hashed; valid results are cached in Redis for 5 minutes (`auth:key:{hash}`) to avoid per-request DB hits.

### Testing conventions

Unit tests use in-process fakes (`_FakeRedis` class pattern) and FastAPI `dependency_overrides` — no live Redis or DB required. `pytest-asyncio` is configured with `asyncio_mode = auto` so all async tests just work. Integration tests live under `tests/integration/`.