# LogTrace

**AI-powered log intelligence for microservice environments.**

LogTrace ingests raw log streams from your services, automatically detects anomaly spikes, and runs a two-stage AI pipeline to produce structured incident reports — complete with root cause, cascade timeline, fix suggestions, and an interactive Q&A chat.

Built for the [NVIDIA × Nebius Global AI Hackathon](https://nebius.com/hackathon) — **Best Apps and Agents Track**.

---

## How It Uses NVIDIA + Nebius

| Component | Model / Service |
|---|---|
| Event classification | **NVIDIA Nemotron Nano 8B** via Nebius Token Factory |
| Root Cause Analysis | **NVIDIA Nemotron Ultra 253B** via Nebius Token Factory |
| Log file storage | **Nebius Object Storage** (S3-compatible) |
| LLM serving | **Nebius Token Factory** (OpenAI-compatible endpoint) |

Nemotron Nano handles fast, batched event triage (20 events per call, up to 10 parallel). Nemotron Ultra does the deep multi-turn reasoning for RCA, streaming tokens in real time to the investigation portal via Server-Sent Events.

---

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full system diagram.

---

## Quick Start

### Prerequisites
- Docker and Docker Compose
- [Nebius Token Factory](https://studio.nebius.ai) API key
- [Nebius Object Storage](https://nebius.com/services/storage) bucket + access keys
- [Tavily](https://tavily.com) API key

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

Required variables:
```
NEBIUS_API_KEY=          # Nebius Token Factory key
NEBIUS_BASE_URL=https://api.studio.nebius.ai/v1
NEBIUS_STORAGE_ACCESS_KEY_ID=
NEBIUS_STORAGE_SECRET_KEY=
OBJECT_STORAGE_BUCKET=logtrace-submissions
OBJECT_STORAGE_ENDPOINT=https://storage.eu-north1.nebius.cloud
TAVILY_API_KEY=
DEMO_API_KEY=dev-demo-key
DATABASE_URL=postgresql+asyncpg://logtrace:logtrace@postgres:5432/logtrace
REDIS_URL=redis://redis:6379/0
```

### 2. Start the stack

```bash
# Full stack (API + Stream Processor + infrastructure)
docker compose up

# With demo producers (synthetic cascade for the live demo)
docker compose --profile demo up
```

### 3. Open the portal

```
http://localhost:8000/portal
```

Enter `dev-demo-key` as the API key. The portal auto-discovers incidents after the demo cascade fires.

### 4. Trigger a demo cascade

From the portal header, click **▶ Start Demo** then **⚡ Inject Cascade**. Within ~60 seconds:
1. The stream processor detects the spike and resets its debounce state automatically
2. Stage-1 parses events, correlates by `trace_id`, infers service topology
3. Stage-2 runs Nano classification + Ultra RCA (tokens stream live to the portal)
4. The investigation view shows root cause, confidence score, cascade chain, and fix suggestions
5. Click **↓ Download Report** to export a Markdown report of the incident

The portal auto-navigates to the new incident. Click **↺ Reset** to clear everything and run again.

### 5. Upload your own logs

Switch to the **📂 Upload Logs** tab in the portal. Drag-and-drop files or select a folder. Analysis runs completely independently from the live demo — no state is shared.

Upload limits (configurable via `.env`):
- Up to `UPLOAD_MAX_FILES` files (default: 50)
- `UPLOAD_MAX_FILE_MB` per file (default: 50 MB)
- `UPLOAD_MAX_TOTAL_MB` total per submission (default: 200 MB)

---

## Local Development

Use `scripts/dev.sh` to manage all local processes:

```bash
bash scripts/dev.sh start    # start API, stream processor, producers, portal
bash scripts/dev.sh stop     # stop all
bash scripts/dev.sh restart  # restart all
bash scripts/dev.sh status   # show running PIDs
bash scripts/dev.sh logs     # tail all logs with color coding
bash scripts/dev.sh logs api # tail a single service log
```

Logs are written to `/tmp/logtrace/*.log`. PIDs are stored in `/tmp/logtrace/*.pid`.

---

## API

Full OpenAPI spec at `http://localhost:8000/docs`.

Key endpoints:

| Endpoint | Description |
|---|---|
| `POST /api/v1/ingest` | Ingest log events (hot path, < 50 ms p99) |
| `POST /api/v1/submissions` | Upload log files for analysis |
| `GET /api/v1/submissions/{id}` | Submission status and incident count |
| `GET /api/v1/submissions/{id}/incidents` | List incidents for a submission |
| `GET /api/v1/submissions/{id}/stream` | SSE stream of live analysis progress |
| `GET /api/v1/incidents/{id}` | Full incident report |
| `GET /api/v1/config` | Upload limits (read from server config) |

All endpoints require `X-API-Key` header.

---

## Running Tests

```bash
pytest tests/unit/ -v
```

40 unit tests, zero external dependencies required (in-process fakes for Redis and DB).

---

## Deployment on Nebius

For a production deployment on Nebius AI Cloud:

```bash
# On a Nebius VM with Docker installed:
git clone <this-repo>
cd logtrace
cp .env.example .env  # fill in your keys
docker compose up -d

# The portal is live at http://<vm-public-ip>:8000/portal
```

The API and stream processor are co-located in Docker Compose. For higher scale, the API can be deployed to Nebius Serverless Endpoints and the Stage-1/Stage-2 jobs can be dispatched as Nebius Serverless Jobs.

---

## Project Structure

```
api/            FastAPI app — routers, schemas, dependencies
core/           Shared infrastructure — DB, Redis, storage, config
db/             SQLAlchemy models, Alembic migrations
jobs/stage1/    Log parsing, event correlation, topology inference
jobs/stage2/    AI classification (Nano), RCA streaming (Ultra), Tavily fix suggestions
stream_processor/  Redis Streams consumer, spike detection
portal/         Single-page investigation UI (served at /portal)
demo/           Synthetic log producers for live demo
prompts/        Prompt templates for Nano and Ultra
tests/          Unit test suite
```

---

## Nebius Token Factory Usage

Both models are accessed through an OpenAI-compatible client pointed at Nebius Token Factory:

```python
from openai import AsyncOpenAI
from core.config import get_settings

settings = get_settings()
client = AsyncOpenAI(
    api_key=settings.nebius_api_key,
    base_url=settings.nebius_base_url,  # https://api.studio.nebius.ai/v1
)

# Fast batch classification — Nemotron Nano 8B
response = await client.chat.completions.create(
    model="nvidia/Llama-3.1-Nemotron-Nano-8B-Instruct",
    messages=[{"role": "user", "content": prompt}],
)

# Deep reasoning with streaming — Nemotron Ultra 253B
stream = await client.chat.completions.create(
    model="nvidia/Llama-3.1-Nemotron-Ultra-253B-v1",
    messages=messages,
    stream=True,
)
```

---

## License

MIT — see [LICENSE](LICENSE).
