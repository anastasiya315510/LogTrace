# LogTrace — Implementation Plan

**Timeline:** September 19 – October 30, 2026 (41 calendar days, solo developer)
**Strategy:** Demo-first. Happy path (ingest → auto-trigger → portal with topology + streaming RCA) must work by end of Week 3.

---

## Project Layout

```
logtrace/
├── api/
│   ├── main.py                      # app factory, lifespan, router registration
│   ├── routers/
│   │   ├── ingest.py                # POST /api/v1/ingest
│   │   ├── submissions.py           # POST /api/v1/submissions, GET status, SSE
│   │   ├── incidents.py             # GET incident, list, chat, export
│   │   ├── health.py                # /health, /ready
│   │   └── demo.py                  # POST /demo/start, /demo/cascade, GET /demo/status, POST /demo/reset
│   ├── dependencies.py              # API key auth, DB session, Redis client
│   └── models/
│       └── schemas.py               # Pydantic request/response models
├── core/
│   ├── config.py                    # Settings (pydantic-settings, all env vars)
│   ├── database.py                  # SQLAlchemy async engine + session factory
│   ├── redis_client.py              # Redis connection pool
│   └── storage.py                   # Nebius Object Storage S3 client (boto3)
├── db/
│   ├── models.py                    # SQLAlchemy ORM models (all 7 tables)
│   └── migrations/
│       ├── env.py
│       └── versions/
│           └── 001_initial_schema.py
├── stream_processor/
│   └── processor.py                 # long-running XREADGROUP consumer + spike detector
├── jobs/
│   ├── stage1/
│   │   ├── entrypoint.py            # reads SUBMISSION_ID env var, orchestrates
│   │   ├── parser.py                # BaseParser, JsonLineParser, PlaintextParser
│   │   ├── correlator.py            # BaseCorrelator, TraceIdCorrelator, TimeWindowCorrelator
│   │   └── topology.py              # TopologyInferrer
│   └── stage2/
│       ├── entrypoint.py            # reads INCIDENT_ID env var, orchestrates
│       ├── classifier.py            # batch_classify() → Nano 8B, asyncio.gather
│       ├── rca.py                   # stream_rca() → Ultra 253B, SSE forward
│       └── fix_suggestions.py       # dual Tavily queries, dedup by URL
├── portal/
│   ├── app.py
│   ├── pages/
│   │   ├── 01_home.py               # upload + demo mode
│   │   ├── 02_dashboard.py          # submissions table
│   │   ├── 03_incident.py           # topology + RCA + Q&A
│   │   └── 04_api_keys.py
│   └── components/
│       ├── topology_graph.py        # streamlit-agraph wrapper
│       ├── fix_cards.py             # fix suggestion card renderer
│       └── rca_stream.py            # st.write_stream() wrapper for SSE
├── prompts/
│   ├── nano_classify.prompt
│   └── ultra_rca.prompt
├── demo/
│   ├── producers/
│   │   ├── base_producer.py         # shared HTTP push logic, retry, trace ID propagation
│   │   ├── payment_service.py       # simulates payment-service: normal ops → PoolTimeoutError cascade
│   │   ├── order_service.py         # simulates order-service: normal ops → UpstreamTimeoutError
│   │   └── api_gateway.py           # simulates api-gateway: normal ops → 503 cascade
│   └── Dockerfile.producers         # all three producers in one image, SERVICE_NAME env var selects which
├── tests/
│   ├── unit/
│   │   ├── test_parser.py
│   │   ├── test_correlator.py
│   │   ├── test_topology.py
│   │   └── test_classifier_prompt.py
│   └── integration/
│       └── test_full_pipeline.py
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.jobs
│   └── Dockerfile.portal
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Week 1 (Sep 19–25): Foundation — Infrastructure, Ingest, DB

**Deliverable:** `POST /api/v1/ingest` accepts events and writes to Redis Streams. DB schema live. `docker-compose up` starts all infrastructure. Smoke test passes.

### Day 1–2: Project scaffold + infrastructure

`pyproject.toml` — declare all dependencies up front:
```
fastapi, uvicorn[standard], pydantic-settings, sqlalchemy[asyncio], asyncpg,
alembic, redis[hiredis], boto3, openai, tavily-python, streamlit,
streamlit-agraph, httpx, weasyprint, ruff, pytest, pytest-asyncio, anyio
```

`docker-compose.yml` — five services: `postgres:15-alpine`, `redis:7-alpine`, `api` (`--reload`), `portal` (Streamlit), `stream_processor` (heartbeat stub for now).

`core/config.py`:
```python
class Settings(BaseSettings):
    database_url: str
    redis_url: str
    nebius_api_key: str
    nebius_base_url: str = "https://api.studio.nebius.ai/v1"
    nano_model_id: str = "nvidia/Llama-3.1-Nemotron-Nano-8B-Instruct"
    ultra_model_id: str = "nvidia/Llama-3.1-Nemotron-Ultra-253B-v1"
    object_storage_bucket: str = "logtrace-submissions"
    object_storage_endpoint: str
    aws_access_key_id: str
    aws_secret_access_key: str
    tavily_api_key: str
    time_window_seconds: int = 30
    error_spike_threshold: int = 10
    error_spike_window_seconds: int = 60
    nano_batch_size: int = 20
    nano_parallel_calls: int = 10
    qa_max_turns: int = 20
```

### Day 3: DB schema + migrations

`db/models.py` — seven SQLAlchemy models matching the ERD exactly:
- `log_events.metadata` → `JSONB`
- `incidents.service_topology_json` → `JSONB`
- `incident_analyses.conversation_history_json` → `JSONB`
- All UUID PKs use `server_default=text("gen_random_uuid()")`

`db/migrations/versions/001_initial_schema.py` — Alembic autogenerate. Add indexes manually in `upgrade()`:
```sql
CREATE INDEX idx_log_events_submission_level_ts
    ON log_events (submission_id, level, timestamp DESC);
CREATE INDEX idx_log_events_trace_id
    ON log_events (trace_id) WHERE trace_id IS NOT NULL;
```

### Day 4: Ingest endpoint (critical — must be < 50ms p99)

`api/routers/ingest.py`:
```python
@router.post("/api/v1/ingest")
async def ingest_events(
    payload: IngestPayload,         # service: str, events: list[RawEvent]
    redis: Redis = Depends(get_redis),
    api_key: ApiKey = Depends(require_api_key),
) -> IngestResponse:
    stream_key = f"stream:ingest:{payload.service}"
    pipe = redis.pipeline()
    accepted = 0
    for event in payload.events[:500]:           # hard cap per call
        pipe.xadd(stream_key, {
            "service": payload.service,
            "timestamp": event.timestamp,
            "level": event.level,
            "message": event.message,
            "trace_id": event.trace_id or "",
            "span_id": event.span_id or "",
            "error_type": event.error_type or "",
            "stack_trace": event.stack_trace or "",
        }, maxlen=50_000, approximate=True)
        accepted += 1
    await pipe.execute()
    return IngestResponse(accepted=accepted, dropped=len(payload.events) - accepted)
```

No DB write in this path. `maxlen=50_000` prevents unbounded Redis memory growth.

`api/dependencies.py` — `require_api_key`: checks `api_keys` table with 5-min Redis TTL cache.

### Day 5: Health endpoint + `/demo` router + Demo Producers

```python
GET /health  →  {"status": "ok"}
GET /ready   →  SELECT 1 (DB) + PING (Redis); 503 if either fails
```

`tests/unit/test_ingest.py` — POST 10 events, assert `accepted=10`, assert `XLEN == 10`.

#### `/demo` Router (`api/routers/demo.py`)

Four thin endpoints that control producer containers via Redis pub/sub. No business logic lives here — the router only publishes commands and reads state from a Redis Hash `demo:state`. Producers subscribe to `demo:commands` channel and handle `start_normal`, `cascade`, `stop` commands in their own loop — the API never calls producer code directly (dependency inversion).

```python
DEMO_STATE_KEY = "demo:state"
DEMO_COMMAND_CHANNEL = "demo:commands"

@router.post("/demo/start")
async def start_demo(body: DemoStartRequest, redis: Redis = Depends(get_redis)):
    current = await redis.hget(DEMO_STATE_KEY, "phase")
    if current in (b"normal", b"cascade"):
        raise HTTPException(409, "Demo already running. Call POST /demo/reset first.")
    session_id = f"demo-{datetime.utcnow().isoformat()}"
    await redis.hset(DEMO_STATE_KEY, mapping={"phase": "normal", "session_id": session_id})
    await redis.publish(DEMO_COMMAND_CHANNEL, json.dumps({
        "command": "start_normal", "services": body.services,
        "duration_seconds": body.normal_duration_seconds,
    }))
    return {"demo_session_id": session_id, "phase": "normal"}

@router.post("/demo/cascade")
async def trigger_cascade(redis: Redis = Depends(get_redis)):
    current = await redis.hget(DEMO_STATE_KEY, "phase")
    if current == b"cascade":
        raise HTTPException(409, "Cascade already in progress.")
    trace_id = uuid4().hex
    await redis.hset(DEMO_STATE_KEY, mapping={"phase": "cascade", "trace_id": trace_id})
    await redis.publish(DEMO_COMMAND_CHANNEL, json.dumps({"command": "cascade", "trace_id": trace_id}))
    return {"phase": "cascade", "trace_id": trace_id, "expected_trigger_in_seconds": 60}

@router.get("/demo/status")
async def demo_status(redis: Redis = Depends(get_redis)):
    state = await redis.hgetall(DEMO_STATE_KEY)
    events_pushed = {
        k.decode().replace("events:", ""): int(v)
        for k, v in state.items() if k.startswith(b"events:")
    }
    return {
        "phase": (state.get(b"phase") or b"idle").decode(),
        "events_pushed": events_pushed,
        "auto_triggered": state.get(b"auto_triggered") == b"1",
        "submission_id": (state.get(b"submission_id") or b"").decode() or None,
    }

@router.post("/demo/reset")
async def reset_demo(body: DemoResetRequest, redis: Redis = Depends(get_redis)):
    await redis.publish(DEMO_COMMAND_CHANNEL, json.dumps({"command": "stop"}))
    await redis.delete(DEMO_STATE_KEY)
    if body.clear_redis_streams:
        async for key in redis.scan_iter("stream:ingest:*"):
            await redis.delete(key)
    return {"phase": "idle", "redis_streams_cleared": body.clear_redis_streams}
```

#### Demo Producers — spec

Three simulated microservices that push real log events to `POST /api/v1/ingest`. They are the primary demo vehicle — judges see a live cascade unfold and the system react autonomously, not a file being uploaded.

**`demo/producers/base_producer.py`**

Shared logic for all three producers:

```python
import asyncio, httpx, uuid, time, random, json
from datetime import datetime, timezone

class BaseProducer:
    def __init__(self, service_name: str, ingest_url: str, api_key: str):
        self.service_name = service_name
        self.ingest_url = ingest_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=5.0)
        self._active_trace_id: str | None = None   # shared across services during cascade

    async def push(self, events: list[dict]) -> None:
        payload = {"service": self.service_name, "events": events}
        try:
            await self.client.post(
                self.ingest_url,
                json=payload,
                headers={"X-API-Key": self.api_key},
            )
        except httpx.RequestError:
            pass   # producers never crash due to ingest failure

    def make_event(
        self,
        level: str,
        message: str,
        error_type: str | None = None,
        stack_trace: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "service": self.service_name,
            "message": message,
            "trace_id": trace_id or self._active_trace_id or "",
            "error_type": error_type or "",
            "stack_trace": stack_trace or "",
        }

    async def run_normal(self, duration_seconds: int) -> None:
        """Push realistic background traffic for `duration_seconds`."""
        raise NotImplementedError

    async def run_cascade(self, trace_id: str) -> None:
        """Inject the failure scenario. Called with a shared trace_id."""
        raise NotImplementedError
```

**`demo/producers/payment_service.py`** — root cause of the cascade

```python
NORMAL_MESSAGES = [
    ("INFO",  "Payment processed successfully",           None),
    ("INFO",  "Payment validated for order {order_id}",   None),
    ("DEBUG", "DB connection acquired from pool",         None),
    ("DEBUG", "Redis cache hit for session {session}",    None),
    ("INFO",  "Refund initiated for order {order_id}",    None),
    ("WARN",  "Payment retry attempt 1 for order {oid}", None),
]

CASCADE_ERRORS = [
    # 15 errors in ~25 seconds — crosses the 10-errors-in-60s auto-trigger threshold
    ("ERROR", "Connection pool exhausted after 30s timeout",
     "PoolTimeoutError",
     "Traceback (most recent call last):\n  File \"payment.py\", line 142\n    conn = await pool.acquire(timeout=30)\npg_pool.PoolTimeoutError: connection pool exhausted\n"),
    ("ERROR", "Failed to acquire DB connection for payment {pid}",
     "PoolTimeoutError", None),
    ("ERROR", "processPayment() exceeded max retries (3)",
     "MaxRetriesExceeded", None),
    # ... 12 more variants
]

class PaymentServiceProducer(BaseProducer):
    def __init__(self, **kwargs):
        super().__init__(service_name="payment-service", **kwargs)

    async def run_normal(self, duration_seconds: int = 60) -> None:
        end = time.monotonic() + duration_seconds
        while time.monotonic() < end:
            level, msg, err = random.choice(NORMAL_MESSAGES)
            event = self.make_event(level, msg.format(
                order_id=f"ORD-{random.randint(1000,9999)}",
                session=uuid.uuid4().hex[:8],
                oid=f"ORD-{random.randint(1000,9999)}",
            ))
            await self.push([event])
            await asyncio.sleep(random.uniform(0.5, 2.0))   # 0.5–2 events/sec

    async def run_cascade(self, trace_id: str) -> None:
        self._active_trace_id = trace_id
        # Push 15 errors over ~25 seconds
        for i, (level, msg, err_type, stack) in enumerate(CASCADE_ERRORS):
            event = self.make_event(
                level,
                msg.format(pid=f"PAY-{random.randint(100,999)}"),
                error_type=err_type,
                stack_trace=stack,
                trace_id=trace_id,
            )
            await self.push([event])
            await asyncio.sleep(random.uniform(1.5, 2.5))
```

**`demo/producers/order_service.py`** — propagated error (starts 1.2s after payment failures begin)

```python
NORMAL_MESSAGES = [
    ("INFO",  "Order {oid} created successfully",          None),
    ("INFO",  "Order status updated to CONFIRMED",         None),
    ("DEBUG", "Inventory check passed for SKU {sku}",      None),
    ("INFO",  "Order dispatched to fulfillment",           None),
    ("DEBUG", "Notification sent to customer",             None),
]

CASCADE_ERRORS = [
    ("ERROR", "Payment service call failed: upstream timeout after 30s",
     "UpstreamTimeoutError",
     "Traceback (most recent call last):\n  File \"order.py\", line 89\n    result = await payment_client.charge(order_id)\nhttpx.ReadTimeout: payment-service timed out\n"),
    ("ERROR", "Order {oid} stuck in PAYMENT_PENDING — aborting",
     "OrderProcessingError", None),
    ("ERROR", "Compensation rollback failed for order {oid}",
     "RollbackError", None),
    # ... 7 more variants
]

class OrderServiceProducer(BaseProducer):
    def __init__(self, **kwargs):
        super().__init__(service_name="order-service", **kwargs)

    async def run_cascade(self, trace_id: str) -> None:
        await asyncio.sleep(1.2)   # 1.2s delay — payment fails first
        self._active_trace_id = trace_id
        for level, msg, err_type, stack in CASCADE_ERRORS:
            event = self.make_event(
                level,
                msg.format(oid=f"ORD-{random.randint(1000,9999)}"),
                error_type=err_type, stack_trace=stack, trace_id=trace_id,
            )
            await self.push([event])
            await asyncio.sleep(random.uniform(2.0, 3.5))
```

**`demo/producers/api_gateway.py`** — symptom (starts 2.8s after payment failures)

```python
NORMAL_MESSAGES = [
    ("INFO",  "GET /orders/{oid} 200 OK 45ms",   None),
    ("INFO",  "POST /payments 200 OK 120ms",      None),
    ("DEBUG", "Rate limit check passed",          None),
    ("INFO",  "Health check OK",                  None),
]

CASCADE_ERRORS = [
    ("ERROR", "POST /payments 503 Service Unavailable — payment-service unreachable",
     "ServiceUnavailableError", None),
    ("ERROR", "POST /orders 503 — dependency failure: payment-service",
     "ServiceUnavailableError", None),
    ("WARN",  "Circuit breaker OPEN for payment-service after 5 consecutive failures",
     None, None),
    # ... 2 more
]

class ApiGatewayProducer(BaseProducer):
    def __init__(self, **kwargs):
        super().__init__(service_name="api-gateway", **kwargs)

    async def run_cascade(self, trace_id: str) -> None:
        await asyncio.sleep(2.8)
        self._active_trace_id = trace_id
        for level, msg, err_type, stack in CASCADE_ERRORS:
            event = self.make_event(
                level, msg.format(oid=f"ORD-{random.randint(1000,9999)}"),
                error_type=err_type, stack_trace=stack, trace_id=trace_id,
            )
            await self.push([event])
            await asyncio.sleep(random.uniform(3.0, 5.0))
```

**Cascade orchestrator** — run all three producers together:

```python
# demo/producers/run_demo.py
async def main():
    ingest_url = os.environ["INGEST_URL"]      # e.g. http://api:8000/api/v1/ingest
    api_key    = os.environ["DEMO_API_KEY"]

    payment = PaymentServiceProducer(ingest_url=ingest_url, api_key=api_key)
    order   = OrderServiceProducer(ingest_url=ingest_url, api_key=api_key)
    gateway = ApiGatewayProducer(ingest_url=ingest_url, api_key=api_key)

    # Phase 1: normal background traffic for 60 seconds
    print("[demo] Normal traffic phase — 60s...")
    await asyncio.gather(
        payment.run_normal(60),
        order.run_normal(60),
        gateway.run_normal(60),
    )

    # Phase 2: inject cascade with a shared trace_id
    trace_id = uuid.uuid4().hex
    print(f"[demo] CASCADE STARTING — trace_id={trace_id}")
    await asyncio.gather(
        payment.run_cascade(trace_id),
        order.run_cascade(trace_id),
        gateway.run_cascade(trace_id),
    )
    print("[demo] Cascade injected — Stream Processor should trigger within 60s")

if __name__ == "__main__":
    asyncio.run(main())
```

**`demo/Dockerfile.producers`:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install httpx
COPY demo/producers/ ./producers/
CMD ["python", "-m", "producers.run_demo"]
```

**`docker-compose.yml` addition:**
```yaml
  demo-producers:
    build:
      context: .
      dockerfile: demo/Dockerfile.producers
    environment:
      INGEST_URL: http://api:8000/api/v1/ingest
      DEMO_API_KEY: ${DEMO_API_KEY}
    depends_on:
      api:
        condition: service_healthy
    profiles: ["demo"]    # only starts with: docker-compose --profile demo up
```

The `profiles: ["demo"]` key means producers only run when explicitly requested — they don't start during normal development or tests. For the demo: `docker-compose --profile demo up`.

**What the demo looks like for judges:**

```
t=0s    docker-compose --profile demo up
t=5s    Portal opens — empty dashboard
t=10s   Normal traffic begins — no incidents (background noise)
t=70s   CASCADE STARTS — payment-service fires 15 ERRORs
t=100s  Stream Processor auto-triggers (10 ERRORs in 60s threshold crossed)
t=102s  Dashboard shows new incident: "auto_trigger — processing..."
t=105s  Topology graph renders: payment-service [RED] → order-service [ORANGE] → api-gateway [YELLOW]
t=110s  Nemotron Ultra starts streaming RCA word-by-word
t=155s  Full report: confidence 87%, fix suggestions from Tavily
```

No clicks required until the engineer opens the portal. The system finds the incident itself.

**Integration checkpoint W1 (updated):** `docker-compose up` → `docker-compose --profile demo up` → watch Redis `XLEN stream:ingest:payment-service` grow → `GET /ready` returns 200 → confirm events appear in Redis Streams before Stream Processor is built.

---

## Design Principles Applied Throughout

### SOLID

Every component in LogTrace maps to a SOLID rule. Violating any of these is a code smell to catch in review.

**Single Responsibility Principle**
Each class does exactly one thing. The line to draw: if you can describe what a class does without using "and", it has one responsibility.

| Class | Single responsibility |
|---|---|
| `JsonLineParser` | Parse a single JSON log line into a `LogEvent` |
| `PlaintextParser` | Parse a single plaintext log line into a `LogEvent` |
| `TraceIdCorrelator` | Group events by shared `trace_id` |
| `TimeWindowCorrelator` | Group events by time-window proximity |
| `TopologyInferrer` | Build a directed service dependency graph from an event list |
| `batch_classify()` | Send events to Nemotron Nano and return classifications |
| `stream_rca()` | Stream a root cause analysis from Nemotron Ultra |
| `fetch_fix_suggestions()` | Query Tavily and return deduplicated fix suggestions |
| `PaymentServiceProducer` | Push payment-service log events to the ingest endpoint |

**Open/Closed Principle**
New log formats, correlators, and producers are added by writing new classes — never by modifying existing ones.

```python
# Adding a logfmt parser: write LogfmtParser(BaseParser), register it in detect_format()
# Adding a new service producer: write DatabaseServiceProducer(BaseProducer)
# Adding a new correlator: write SpanParentCorrelator(BaseCorrelator)
# The pipeline code (entrypoint.py, select_correlator()) never changes
```

**Liskov Substitution Principle**
Any `BaseParser` can replace any other `BaseParser` without breaking Stage-1. Any `BaseCorrelator` can replace any other. Enforce this by keeping the abstract interface minimal — one method each:

```python
class BaseParser(ABC):
    @abstractmethod
    def parse_line(self, line: str, service_name: str, submission_id: UUID) -> LogEvent | None: ...

class BaseCorrelator(ABC):
    @abstractmethod
    def correlate(self, events: list[LogEvent]) -> list[Incident]: ...
```

If a subclass raises on input the parent would handle silently (e.g. crash on empty lines instead of returning `None`), it violates LSP.

**Interface Segregation Principle**
No class is forced to implement a method it doesn't use. `BaseParser` has one method. `BaseProducer` has `run_normal()` and `run_cascade()` — two small methods, not a fat interface mixing parsing, correlation, and HTTP calls.

If a future producer doesn't need a `run_cascade()` (e.g. a read-only log replayer), split `BaseProducer` into `NormalProducer` and `CascadeProducer` rather than leaving `run_cascade()` as a stub.

**Dependency Inversion Principle**
High-level modules depend on abstractions, not concretions.

```python
# Stage-1 entrypoint depends on BaseParser and BaseCorrelator — not JsonLineParser or TimeWindowCorrelator
# The /demo router publishes to Redis pub/sub — it never imports or calls producer classes directly
# The API depends on get_redis() and get_db() dependencies — never on concrete clients
# All external API calls (Nebius, Tavily, S3) are wrapped behind interfaces with mock implementations for tests
```

---

### Uncle Bob — Clean Code Rules

Applied to every function and class written in this project:

**Functions do one thing.** If a function parses, correlates, and writes to the DB, split it. The test for this: can you name it with a single verb phrase? `parse_line()`, `correlate_by_trace_id()`, `infer_topology()` — yes. `process_submission_and_call_llm_and_save()` — no.

**Functions are small.** Target < 20 lines per function. If it's longer, extract. `batch_classify()` calls `build_nano_prompt()`, `parse_nano_response()`, and `asyncio.gather()` — those three are separate functions, not inlined.

**No surprises — functions do what their name says.** `parse_line()` returns a `LogEvent | None`. It does not write to a DB, log a warning, or raise on bad input — it returns `None`. Side effects belong in the caller.

**Descriptive names — no abbreviations.**

```python
# Wrong
def proc_evt(e, sid):  ...

# Right
def parse_log_line(line: str, submission_id: UUID) -> LogEvent | None: ...
```

**Error handling is separate from business logic.** Each external call (Nano, Ultra, Tavily, S3) has its own try/except. The pipeline orchestrator (`entrypoint.py`) never wraps entire phases in a single broad `except Exception`.

```python
# Wrong — hides which step failed
try:
    events = parse_all(lines)
    incidents = correlate(events)
    await insert_incidents(incidents)
except Exception as e:
    log.error("stage1 failed", error=str(e))

# Right — each failure is handled and logged at its source
events = parse_all(lines)                   # raises ParseError with context
incidents = correlate(events)               # raises CorrelationError with context
await insert_incidents(incidents)           # raises DatabaseError with context
```

**No dead code.** If a function, class, or import is not used, delete it. Do not comment it out.

**The scout rule.** Leave the code cleaner than you found it. If you touch a function and notice it's doing two things, split it before moving on.

---

### Logging Best Practices (for Demo Producers and All Components)

All log output — both from LogTrace components and from demo producers — uses **structured JSON** via `structlog`. Every log line is a machine-readable event, not a string.

**Standard fields on every event (producer output format):**

```json
{
  "timestamp": "2026-09-19T10:00:00.123Z",
  "level": "INFO",
  "service": "payment-service",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "message": "Payment processed successfully",
  "error_type": null,
  "duration_ms": 42,
  "order_id": "ORD-8821"
}
```

**Level discipline — what goes where:**

| Level | Use for | Example |
|---|---|---|
| `DEBUG` | Internal state useful for tracing, never shown in production | `"DB connection acquired from pool"` |
| `INFO` | Normal business events | `"Payment processed for order ORD-8821"` |
| `WARN` | Recoverable issues, degraded performance | `"Payment retry attempt 2/3"`, `"Circuit breaker half-open"` |
| `ERROR` | Failures that require attention | `"PoolTimeoutError: connection pool exhausted"` |
| `CRITICAL` | Service is non-functional | `"Cannot connect to DB — all retries exhausted"` |

**Rules:**
- Always include `trace_id` on every event when one is active. The `trace_id` is what makes LogTrace's correlation work — producers must propagate it on every event during a cascade, not just the first one.
- Include `stack_trace` on `ERROR` and `CRITICAL` events. Nano classifies better when the stack trace is present, and Ultra produces a more accurate RCA.
- Never log credentials, tokens, or PII (customer names, card numbers, emails). Use IDs only (`order_id`, `user_id`).
- Include `duration_ms` on any event that involves a timed operation (DB call, HTTP call, cache lookup) — this is what reveals timeout patterns to Nemotron Ultra.
- Log the failure at the point it occurs. Do not catch, swallow, and re-raise a generic exception three layers up. The log event at the source is what LogTrace reads.

**Producer normal-mode event variety** — the demo logs must look real, not repetitive:

```python
# Good: varied messages, realistic field values
NORMAL_PAYMENT_EVENTS = [
    {"level": "INFO",  "message": "Payment processed",       "duration_ms": lambda: random.randint(20, 80)},
    {"level": "INFO",  "message": "Payment validated",       "duration_ms": lambda: random.randint(5, 20)},
    {"level": "DEBUG", "message": "DB connection acquired",  "duration_ms": lambda: random.randint(1, 5)},
    {"level": "DEBUG", "message": "Cache hit for session",   "duration_ms": lambda: random.randint(1, 3)},
    {"level": "WARN",  "message": "Payment retry attempt",   "duration_ms": lambda: random.randint(200, 500)},
]
# Vary duration_ms on every event — static values look fake
```

The 340 INFO/DEBUG events in the demo dataset are what Nemotron Nano filters out. They must be realistic enough that Nano classifies them as `noise` — not ERROR events disguised as INFO.

---

## Week 2 (Sep 26 – Oct 2): Stream Processor + Stage-1 Job

**Deliverable:** Stream Processor detects ERROR spike and writes submission record. Stage-1 job parses, correlates, infers topology, writes to DB. Driven from CLI: `SUBMISSION_ID=<uuid> python -m jobs.stage1.entrypoint`.

### Stream Processor (`stream_processor/processor.py`)

```python
class StreamProcessor:
    def __init__(self, redis, db_session_factory):
        self.redis = redis
        self.db = db_session_factory
        self.windows: dict[str, deque] = defaultdict(deque)
        self.last_triggered: dict[str, float] = {}   # debounce per service

    async def run(self):
        # SCAN MATCH stream:ingest:* every 30s to discover new services
        # XREADGROUP COUNT 200 BLOCK 1000 GROUP logtrace-sp consumer-1
        while True:
            streams = await self._discover_streams()
            messages = await self.redis.xreadgroup(
                "logtrace-sp", "sp-consumer-1",
                {s: ">" for s in streams}, count=200, block=1000
            )
            for stream_name, entries in messages:
                service = stream_name.split(":")[-1]
                for entry_id, fields in entries:
                    await self._process_event(service, fields)
                    await self.redis.xack(stream_name, "logtrace-sp", entry_id)

    async def _check_spike_conditions(self, now: float):
        # Condition 1: single-service ERROR spike (≥ threshold in window_seconds)
        # Condition 2: same error_type in 3+ services within 30s
        # Condition 3: any CRITICAL level
        # Debounce: skip if last_triggered[service] < 120s ago
```

On trigger: snapshot `ingest_window_start/end`, INSERT submission (`source_method="auto_trigger"`), XADD to `analysis-queue`.

### Parser (`jobs/stage1/parser.py`)

```python
class BaseParser(ABC):
    @abstractmethod
    def parse_line(self, line: str, service_name: str, submission_id: UUID) -> LogEvent | None: ...

class JsonLineParser(BaseParser):
    # json.loads(line) → map known fields → extras to metadata JSONB
    # normalise level: uppercase, "warning"→"WARN"
    # parse timestamp: ISO8601 → datetime

class PlaintextParser(BaseParser):
    PATTERNS = [
        r"^\[(?P<ts>[^\]]+)\]\s+(?P<level>ERROR|WARN|INFO|DEBUG)\s+(?P<svc>\S+):\s+(?P<msg>.*)$",
        r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*)\s+(?P<level>\w+)\s+(?P<msg>.*)$",
    ]

def detect_format(first_line: str) -> type[BaseParser]:
    try:
        json.loads(first_line)
        return JsonLineParser
    except json.JSONDecodeError:
        return PlaintextParser
```

### Correlator (`jobs/stage1/correlator.py`)

```python
class TraceIdCorrelator(BaseCorrelator):
    def correlate(self, events):
        # group by trace_id → one Incident per group
        # events without trace_id fall through to TimeWindowCorrelator

class TimeWindowCorrelator(BaseCorrelator):
    def correlate(self, events):
        # 1. Filter to ERROR/CRITICAL, sort by timestamp
        # 2. Sliding window merge (union-find or interval merge)
        # 3. For each window, collect all events within ±window_seconds
        # 4. Dedup: same service+message within 1s → keep first

def select_correlator(events: list[LogEvent]) -> BaseCorrelator:
    has_trace_ids = any(e.trace_id for e in events if e.level in ("ERROR", "CRITICAL"))
    return TraceIdCorrelator() if has_trace_ids else TimeWindowCorrelator()
```

### Topology Inferrer (`jobs/stage1/topology.py`)

```python
class TopologyInferrer:
    def infer(self, events: list[LogEvent]) -> dict:
        # Step 1: sort ERROR/CRITICAL events by timestamp ASC
        sorted_events = sorted(
            [e for e in events if e.level in ("ERROR", "WARN", "CRITICAL")],
            key=lambda e: e.timestamp
        )
        # Step 2: 5s sliding window edge detection
        edges: dict[tuple[str, str], int] = defaultdict(int)
        for i, event_a in enumerate(sorted_events):
            for event_b in sorted_events[i+1:]:
                if (event_b.timestamp - event_a.timestamp).total_seconds() > 5.0:
                    break
                if event_b.service_name != event_a.service_name:
                    edges[(event_a.service_name, event_b.service_name)] += 1
        # Step 3: overlay span-parent edges if trace_id+span_id available
        # Step 4: build adjacency list
        # Step 5: cycle detection (DFS) → break lowest-weight edge
        # Step 6: root = in-degree 0 OR earliest ERROR timestamp
        # Step 7: role assignment
        return {
            "adjacency": dict(graph),
            "edge_weights": {f"{s}→{d}": w for (s,d), w in edge_weights.items()},
            "node_roles": roles,   # service_name → root_cause|propagated_error|symptom|unaffected
        }
```

### Stage-1 Entrypoint

```python
async def main():
    submission_id = UUID(os.environ["SUBMISSION_ID"])
    source_method = os.environ.get("SOURCE_METHOD", "upload")

    if source_method == "auto_trigger":
        raw_events = await read_events_from_redis_streams(submission)
    else:
        raw_events = await read_events_from_object_storage(submission)

    parsed = parse_all(raw_events, submission_id)
    await batch_insert_events(parsed)

    correlator = select_correlator(parsed)
    incidents = correlator.correlate(parsed)

    for incident in incidents:
        topology = TopologyInferrer().infer(incident.events)
        incident.service_topology_json = topology
        await insert_incident(session, incident)
        await enqueue_stage2(redis, incident.incident_id)

    if source_method != "auto_trigger":
        await delete_s3_files(submission.object_keys)
```

**Integration checkpoint W2:** `SUBMISSION_ID=x python -m jobs.stage1.entrypoint` with pre-seeded Redis stream → `incidents` table has a row with `service_topology_json` populated.

### CI Bootstrap (`.github/workflows/ci.yml`)

Set this up in Week 2 — not Week 5. Unit tests exist from Week 1 and CI must catch regressions from the moment Stage-1 code lands. No running infrastructure required: all unit tests use in-memory fakes.

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          version: "latest"
      - name: Install dependencies
        run: uv sync --extra dev
      - name: Lint
        run: uv run ruff check .
      - name: Unit tests
        run: uv run pytest tests/unit/ -v --tb=short
```

The `deploy` job (build images + push to Nebius Container Registry) is added to this same file in Week 5, triggered only on `main`. Integration tests (testcontainers) are also added in Week 5 once the full pipeline exists.

---

## Week 3 (Oct 3–9): Stage-2 AI Pipeline + SSE + Portal MVP

**This is the critical milestone.** By end of Week 3: full happy path runs — ingest → auto-trigger → Nano + Ultra streaming → portal shows topology graph + streaming RCA + Q&A.

### Classifier (`jobs/stage2/classifier.py`)

```python
async def batch_classify(
    events: list[LogEvent],
    client: openai.AsyncOpenAI,
    batch_size: int = 20,
    parallel: int = 10,
) -> list[EventClassification]:
    batches = [events[i:i+batch_size] for i in range(0, len(events), batch_size)]
    semaphore = asyncio.Semaphore(parallel)

    async def classify_batch(batch):
        async with semaphore:
            prompt = build_nano_prompt(batch)    # loads prompts/nano_classify.prompt
            response = await client.chat.completions.create(
                model=settings.nano_model_id,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            return parse_nano_response(response.choices[0].message.content, batch)

    results = await asyncio.gather(*[classify_batch(b) for b in batches])
    return [r for batch_result in results for r in batch_result]
```

`parse_nano_response()`: if JSON is malformed or array length mismatches, mark all as `noise`/`unknown` — never raise. Log a warning.

### RCA (`jobs/stage2/rca.py`)

```python
async def stream_rca(
    incident: Incident,
    events: list[LogEvent],
    classifications: list[EventClassification],
    client: openai.AsyncOpenAI,
    progress_callback: Callable[[str], Awaitable[None]],
) -> IncidentAnalysis:
    prompt = build_ultra_prompt(incident, events, classifications)
    full_text = ""
    async with await client.chat.completions.create(
        model=settings.ultra_model_id,
        messages=[{"role": "user", "content": prompt}],
        stream=True, temperature=0.3,
    ) as stream:
        async for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            full_text += token
            await progress_callback(token)    # publishes to Redis pub/sub

    return parse_ultra_response(full_text, incident.incident_id)
```

The prompt instructs Ultra to end with a `<ANALYSIS_JSON>` block containing structured fields. `parse_ultra_response()` extracts that block; the preceding text becomes `cascade_explanation`.

### SSE Forwarding via Redis Pub/Sub

Stage 2 publishes tokens to `sse:submission:{submission_id}`. FastAPI SSE endpoint subscribes:

```python
@router.get("/api/v1/submissions/{submission_id}/stream")
async def stream_progress(submission_id: UUID, redis: Redis = Depends(get_redis)):
    async def event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"sse:submission:{submission_id}")
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if data == "__DONE__":
                    break
                yield f"data: {data}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Stage 2 publishes `__DONE__` sentinel on completion.

### Fix Suggestions (`jobs/stage2/fix_suggestions.py`)

```python
async def fetch_fix_suggestions(analysis, incident) -> list[FixSuggestion]:
    client = TavilyClient(api_key=settings.tavily_api_key)
    q1 = f"{analysis.root_cause_service} {analysis.error_category} fix solution"
    q2 = f"{analysis.error_type} CVE known bug {analysis.root_cause_service}"

    results = await asyncio.gather(
        asyncio.to_thread(client.search, q1, max_results=5),
        asyncio.to_thread(client.search, q2, max_results=5),
        return_exceptions=True,
    )
    # Dedup by URL, sort by tavily_score DESC, take top 3
    # Both exceptions → return [] gracefully (report delivered without suggestions)
```

### Topology Graph Component (`portal/components/topology_graph.py`)

```python
from streamlit_agraph import agraph, Node, Edge, Config
import math

ROLE_COLORS = {
    "root_cause": "#E53935",
    "propagated_error": "#FB8C00",
    "symptom": "#FDD835",
    "unaffected": "#78909C",
}

def render_topology(topology_json: dict) -> str | None:
    """Returns clicked node ID or None."""
    nodes, edges = [], []
    error_counts = topology_json.get("error_counts", {})

    for service, role in topology_json["node_roles"].items():
        count = error_counts.get(service, 0)
        size = max(35, min(120, 40 + count * 2))   # proportional sizing
        nodes.append(Node(
            id=service,
            label=f"{service}\n{'ROOT CAUSE' if role == 'root_cause' else str(count) + ' errors'}",
            color=ROLE_COLORS.get(role, "#78909C"),
            size=70 if role == "root_cause" else size,
            font={"color": "white", "size": 14},
            borderWidth=3 if role == "root_cause" else 2,
            borderWidthSelected=4,
        ))

    for edge_label, weight in topology_json.get("edge_weights", {}).items():
        src, dst = edge_label.split("→")
        edges.append(Edge(
            source=src, target=dst,
            width=1 + math.log2(max(weight, 1)),
            label=topology_json.get("edge_latencies", {}).get(edge_label, ""),
        ))

    config = Config(
        width=900, height=500, directed=True,
        physics=False, hierarchical=True,
        hierarchical_sort_method="directed",
    )
    return agraph(nodes=nodes, edges=edges, config=config)
```

Root cause node gets a pulsing ring via `st.components.html` CSS injection:
```python
st.components.v1.html("""
<style>
@keyframes pulse { 0% { box-shadow: 0 0 0 0 #E5393580; } 70% { box-shadow: 0 0 0 20px #E5393500; } 100% { box-shadow: 0 0 0 0 #E5393500; } }
</style>
""", height=0)
```

Clicking a node: the `agraph()` return value is the clicked node ID → display that service's events in `st.expander()`.

### Demo Data (`demo/cascade_demo.json`)

420 events across 3 services:
- 340 INFO/DEBUG (noise — Nano filters these)
- 15 ERROR in `payment-service` (`PoolTimeoutError`, `error_type: "connection_pool_exhausted"`)
- 10 ERROR in `order-service` (`UpstreamTimeoutError`, downstream of payment)
- 5 ERROR in `api-gateway` (`503 Service Unavailable`)
- `trace_id` present on 80% of ERROR events (tests both correlators)
- Cascade timing: payment errors at t=0, order errors at t+1.2s, gateway errors at t+2.8s

**Integration checkpoint W3 (critical milestone):** `docker-compose up` → click "Load Demo Logs" → within 90 seconds: topology graph shows red `payment-service` → orange `order-service` → yellow `api-gateway` → streaming RCA appears word-by-word → Q&A panel accepts a question and streams a response.

---

## Week 4 (Oct 10–16): File Upload + Portal Polish + Q&A + Unit Tests

**Deliverable:** Historical file upload works end-to-end; fix suggestion cards rendered prominently; unit test suite passes; progress SSE shows step messages.

### File Upload (`api/routers/submissions.py`)

```python
@router.post("/api/v1/submissions")
async def create_submission(
    files: list[UploadFile],
    time_window_seconds: int = Form(30),
    storage: ObjectStorage = Depends(get_storage),
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(require_api_key),
) -> SubmissionResponse:
    # Validate: MIME type text-based only; each file ≤ 100 MB; max 20 files
    submission_id = uuid4()
    object_keys = []
    for f in files[:20]:
        key = f"submissions/{submission_id}/{f.filename}"
        await storage.upload_fileobj_streaming(f.file, key)   # never loads full file into memory
        object_keys.append(key)
    await insert_submission(db, submission_id, source_method="upload", object_keys=object_keys)
    await enqueue_stage1(redis, submission_id, source_method="upload")
    return SubmissionResponse(submission_id=submission_id, status="received")
```

`core/storage.py` — `upload_fileobj_streaming()` uses boto3 multipart upload in `asyncio.to_thread`, 8 MB chunks.

### Q&A Endpoint

```python
@router.post("/api/v1/incidents/{incident_id}/chat")
async def chat(incident_id: UUID, body: ChatRequest) -> StreamingResponse:
    analysis = await get_analysis(db, incident_id)
    # 400 if incident not complete
    history = analysis.conversation_history_json or []
    messages = build_qa_messages(analysis, history, body.question)

    async def token_stream():
        full_answer = ""
        async with await client.chat.completions.create(
            model=settings.ultra_model_id, messages=messages, stream=True
        ) as stream:
            async for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                full_answer += token
                yield f"data: {json.dumps({'token': token})}\n\n"
        # Persist: cap history at 20 turns (40 messages)
        history.append({"role": "user", "content": body.question})
        history.append({"role": "assistant", "content": full_answer})
        await update_conversation_history(db, incident_id, history[-40:])
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(token_stream(), media_type="text/event-stream")
```

### Fix Suggestion Cards (`portal/components/fix_cards.py`)

Displayed immediately below the Root Cause Box — before the full RCA text:

```python
def render_fix_suggestions(suggestions: list[dict]) -> None:
    remediation = [s for s in suggestions if s["query_type"] == "remediation"]
    vulnerabilities = [s for s in suggestions if s["query_type"] == "vulnerability"]

    if not suggestions:
        st.info("No fix suggestions found — check service documentation manually.")
        return

    st.subheader("Fix Suggestions")
    if remediation:
        st.caption("Remediation guides")
        for s in remediation:
            with st.container(border=True):
                st.markdown(f"**[{s['source_title']}]({s['source_url']})**")
                st.caption(s["excerpt"])
                col1, col2 = st.columns([3, 1])
                col1.badge("Remediation", color="green")
                col2.write(f"Score: {'★' * round(s['tavily_score'] * 5)}")

    if vulnerabilities:
        st.caption("Known vulnerabilities / CVEs")
        for s in vulnerabilities:
            with st.container(border=True):
                st.markdown(f"**[{s['source_title']}]({s['source_url']})**")
                st.caption(s["excerpt"])
                col1, col2 = st.columns([3, 1])
                col1.badge("Vulnerability", color="red")
                col2.write(f"Score: {'★' * round(s['tavily_score'] * 5)}")
```

### Unit Tests

`tests/unit/test_parser.py`:
- `test_json_line_parser_full_schema()` — all fields present → correct mapping
- `test_json_line_parser_partial()` — missing `trace_id` → None, no exception
- `test_plaintext_parser_standard_format()` — standard pattern → correct parse
- `test_format_detection()` — JSON first line → `JsonLineParser`; else → `PlaintextParser`

`tests/unit/test_correlator.py`:
- `test_trace_id_correlation()` — 10 events sharing trace_id → 1 incident
- `test_time_window_correlation()` — 6 ERRORs within 30s → 1 incident
- `test_time_window_two_incidents()` — 4 ERRORs at t=0, 4 ERRORs at t=120s → 2 incidents
- `test_dedup()` — 3 identical events within 1s → 1 retained

`tests/unit/test_topology.py`:
- `test_simple_chain()` — A→B→C → correct adjacency, A is `root_cause`
- `test_cycle_detection()` — A→B→A → cycle broken at lower-weight edge
- `test_single_service()` — all events one service → 1 node, no edges
- `test_role_assignment()` — in-degree-0 → `root_cause`; depth-1 → `propagated_error`; depth-2+ → `symptom`

`tests/unit/test_classifier_prompt.py`:
- `test_batch_prompt_construction()` — 20 events → all 20 in prompt
- `test_nano_response_malformed()` — invalid JSON → 20 `noise`/`unknown`, no exception

---

## Week 5 (Oct 17–30): Deployment, Export, Demo Prep

**Deliverable:** Deployed on Nebius Serverless Endpoints; CI deploy job live; Markdown export works; demo rehearsed; README usable by a stranger.

### Oct 17–23: Deploy from Scratch on Nebius

#### Step 1 — Write Dockerfiles

`docker/Dockerfile.api`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY . .
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker/Dockerfile.jobs`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY . .
# CMD is set at job submission time — one image, two entry points:
#   Stage 1: python -m jobs.stage1.entrypoint
#   Stage 2: python -m jobs.stage2.entrypoint
# Target image size ≤ 300 MB (no GPU deps — Nebius Token Factory serves the models).
```

`docker/Dockerfile.portal`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml .
RUN uv sync --no-dev
COPY . .
EXPOSE 8501
CMD ["uv", "run", "streamlit", "run", "portal/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
```

#### Step 2 — Build and push to Nebius Container Registry

```bash
# Authenticate — get an OAuth token from Nebius Console → Container Registry
docker login cr.nebius.cloud --username oauth --password <token>

# Build all three images (run from repo root)
docker build -f docker/Dockerfile.api   -t cr.nebius.cloud/<REGISTRY_ID>/logtrace-api:latest   .
docker build -f docker/Dockerfile.jobs  -t cr.nebius.cloud/<REGISTRY_ID>/logtrace-jobs:latest  .
docker build -f docker/Dockerfile.portal -t cr.nebius.cloud/<REGISTRY_ID>/logtrace-portal:latest .

# Push
docker push cr.nebius.cloud/<REGISTRY_ID>/logtrace-api:latest
docker push cr.nebius.cloud/<REGISTRY_ID>/logtrace-jobs:latest
docker push cr.nebius.cloud/<REGISTRY_ID>/logtrace-portal:latest
```

#### Step 3 — Provision managed infrastructure on Nebius

| Resource | Service | Notes |
|---|---|---|
| PostgreSQL | Nebius Managed PostgreSQL | Note the connection string; run `alembic upgrade head` from a one-off container or local machine pointed at the managed DB |
| Redis | Nebius Managed Redis | Note host + port; no password in dev |
| Object Storage | Nebius Object Storage | Create bucket `logtrace-submissions`; create service account with `storage.uploader` role; generate static access key |

Run the migration against the managed DB before starting the API:
```bash
DATABASE_URL=postgresql+asyncpg://... uv run alembic upgrade head
```

#### Step 4 — Deploy API as Nebius Serverless Endpoint

Create a Serverless Container (Nebius Console → Serverless → Containers):

| Setting | Value |
|---|---|
| Image | `cr.nebius.cloud/<REGISTRY_ID>/logtrace-api:latest` |
| Port | `8000` |
| Min instances | `1` (avoid cold start during the demo) |
| Memory | `512 MB` |
| Concurrency | `16` |

Set all env vars from `.env.example`. The endpoint URL becomes `LOGTRACE_BASE_URL` for the portal.

#### Step 5 — Deploy portal as Nebius Serverless Endpoint

Same process with `logtrace-portal:latest`, port `8501`, env var `LOGTRACE_API_URL=<API endpoint URL>`.

#### Step 6 — Wire Nebius Serverless Jobs (replace direct-call stub)

Replace the direct `python -m jobs.stage1.entrypoint` call in the Stream Processor with a real Nebius Jobs API call:

```python
async def trigger_analysis_job(
    submission_id: str,
    stage: int,
    source_method: str,
    nebius_jobs_api_key: str,
    jobs_image: str,
) -> str:
    """Submit a Nebius Serverless Job; return the job ID."""
    cmd = f"python -m jobs.stage{stage}.entrypoint"
    payload = {
        "name": f"logtrace-stage{stage}-{submission_id[:8]}",
        "container": {
            "image": jobs_image,
            "command": cmd.split(),
            "env": {
                "SUBMISSION_ID": submission_id,
                "SOURCE_METHOD": source_method,
                # All other env vars injected via Nebius secret references
            },
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://serverless-jobs.api.nebius.cloud/jobs",
            json=payload,
            headers={"Authorization": f"Bearer {nebius_jobs_api_key}"},
        )
        resp.raise_for_status()
        return resp.json()["id"]
    # exit_code 0 = success → XACK; non-zero → leave in XPENDING for retry
```

Validate: submit a no-op container (`CMD ["echo", "ok"]`) to Nebius Jobs and confirm the actual execution time limit before assuming anything about job duration.

#### Step 7 — Add `deploy` job to CI

Extend `.github/workflows/ci.yml` — runs only on pushes to `main`, after `lint-and-test` passes:

```yaml
  deploy:
    needs: lint-and-test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Log in to Nebius Container Registry
        run: |
          echo "${{ secrets.NEBIUS_CR_TOKEN }}" | \
          docker login cr.nebius.cloud --username oauth --password-stdin

      - name: Build and push API image
        run: |
          docker build -f docker/Dockerfile.api \
            -t cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-api:${{ github.sha }} \
            -t cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-api:latest .
          docker push cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-api:${{ github.sha }}
          docker push cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-api:latest

      - name: Build and push Jobs image
        run: |
          docker build -f docker/Dockerfile.jobs \
            -t cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-jobs:${{ github.sha }} \
            -t cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-jobs:latest .
          docker push cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-jobs:${{ github.sha }}
          docker push cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-jobs:latest

      - name: Build and push Portal image
        run: |
          docker build -f docker/Dockerfile.portal \
            -t cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-portal:${{ github.sha }} \
            -t cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-portal:latest .
          docker push cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-portal:${{ github.sha }}
          docker push cr.nebius.cloud/${{ vars.REGISTRY_ID }}/logtrace-portal:latest
```

**GitHub secrets required:**
- `NEBIUS_CR_TOKEN` — Nebius OAuth token with Container Registry push access

**GitHub repository variables required:**
- `REGISTRY_ID` — Nebius Container Registry ID (not secret, just a config value)

#### Step 8 — Integration tests against live infra

```bash
# tests/integration/test_full_pipeline.py
# Real PostgreSQL + Redis via testcontainers (local) OR pointed at Nebius managed infra
```

- Mock openai client: Nano → hardcoded 20-item JSON array; Ultra → 5 tokens + `<ANALYSIS_JSON>` block
- POST 30 events across 3 services → wait for auto-trigger → wait for Stage 1 + Stage 2 → assert `incidents` has 1 row, `incident_analyses.confidence_score > 0`, `fix_suggestions` has ≥ 1 row

Add as a separate CI job (`integration-test`) that runs on `main` only, after `deploy` completes, using testcontainers (no Nebius credentials needed):

```yaml
  integration-test:
    needs: deploy
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_USER: logtrace
          POSTGRES_PASSWORD: logtrace
          POSTGRES_DB: logtrace
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-retries 10
      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          version: "latest"
      - run: uv sync --extra dev
      - name: Run migrations
        run: uv run alembic upgrade head
        env:
          DATABASE_URL: postgresql+asyncpg://logtrace:logtrace@localhost/logtrace
      - name: Integration tests
        run: uv run pytest tests/integration/ -v --tb=short
        env:
          DATABASE_URL: postgresql+asyncpg://logtrace:logtrace@localhost/logtrace
          REDIS_URL: redis://localhost:6379/0
```

### Oct 24–30: Export + Demo Rehearsal

**Markdown export:**
```python
@router.get("/api/v1/incidents/{incident_id}/export")
async def export_report(incident_id: UUID, format: str = "md"):
    # Build markdown from incident + analysis + topology + fix_suggestions
    # Return StreamingResponse with Content-Disposition: attachment
```

Template:
```markdown
# LogTrace Incident Report — {incident_id}
**Root Cause:** {root_cause_service} / {root_cause_method}
**Confidence:** {confidence_score}%
**Services Involved:** {services_involved}

## Cascade Timeline
{cascade_chain as numbered list}

## Analysis (Nemotron Ultra 253B via Nebius Token Factory)
{cascade_explanation}

## Fix Suggestions (Tavily)
{fix suggestions as numbered list with URLs}
```

PDF: implement last, or skip if time is short. Markdown is sufficient for judges.

**Demo script (rehearse 3× before submission):**
1. Open portal — show empty dashboard
2. Click "Load Demo Logs" — watch progress bar: `parsing → correlating → classifying 420 events → analysing → fix suggestions`
3. Topology graph appears first (before RCA is done) — explain: red = root cause, cascade flows downward
4. RCA streams word-by-word — point out "Nemotron Ultra 253B via Nebius Token Factory" label
5. Show fix suggestion cards prominently above the full analysis text
6. Type live Q&A question: "What would happen if we doubled the connection pool size?"
7. Show streaming answer
8. Download Markdown report

**README quick start:**
```markdown
## Quick Start
1. cp .env.example .env   # add Nebius Token Factory key, Tavily key, Object Storage creds
2. docker-compose up
3. Open http://localhost:8501

## Architecture
See HLD.md for full design documentation.

## NVIDIA Nemotron models used
- Nemotron Nano 8B (nvidia/Llama-3.1-Nemotron-Nano-8B-Instruct) — batched event classification
- Nemotron Ultra 253B (nvidia/Llama-3.1-Nemotron-Ultra-253B-v1) — streaming RCA and Q&A
Both served via Nebius Token Factory (OpenAI-compatible API).
```

---

## Stubbing Strategy

| Component | Week 1 | Week 2 | Week 3 | Week 4–5 |
|-----------|--------|--------|--------|----------|
| Nebius Token Factory (Nano) | Mock (fixed JSON) | Mock | Real API | Real + error handling |
| Nebius Token Factory (Ultra) | Mock | Mock | Real API (stream=True) | Real + Q&A |
| Nebius Serverless Jobs | Skip (call Stage 1/2 directly) | Direct call | Direct call | Real Jobs API |
| Tavily API | Skip | Skip | Stub (2 hardcoded results) | Real API |
| Nebius Object Storage | Skip (local filesystem) | Local filesystem | Local filesystem | Real S3 |
| Stream Processor trigger | Manual CLI call | Real trigger | Real trigger | Real trigger |
| SSE progress | No-op | Log to stdout | Redis pub/sub | Redis pub/sub |

Rule: **never let an external API block the critical path.** Wrap every external call behind an interface with a mock and a real implementation. Test with mocks; swap to real when the pipeline is otherwise working.

---

## Scope Cuts (if timeline slips)

Cut in this order — the happy path is non-negotiable:
1. PDF export → stays cut (Markdown is sufficient)
2. `04_api_keys.py` portal page → replaced with hardcoded demo key in `.env`
3. Historical file upload → replaced with "Load Demo Logs" button only
4. Prometheus metrics → skip entirely
5. `streamlit-agraph` pulsing CSS animation → replace with plain red fill

---

## Weekly Milestone Summary

| Week | Dates | Must-Have Deliverable |
|------|-------|-----------------------|
| 1 | Sep 19–25 | `POST /api/v1/ingest` → Redis Streams; DB schema live; `docker-compose up` works |
| 2 | Sep 26–Oct 2 | Stream Processor triggers; Stage-1 parses + correlates + topology → DB; CI running on GitHub Actions |
| 3 | Oct 3–9 | **Full happy path**: ingest → auto-trigger → Nano + Ultra streaming → portal topology + RCA + Q&A |
| 4 | Oct 10–16 | File upload; fix suggestion cards; unit test suite; portal polish |
| 5 | Oct 17–30 | Dockerfiles built + pushed to Nebius CR; API + portal deployed as Serverless Endpoints; Nebius Jobs wired for Stage 1/2; CI deploy job live; integration tests in CI; Markdown export; demo rehearsed; README done |
