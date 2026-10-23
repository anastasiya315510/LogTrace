# Design

## Context

See `proposal.md — Why` for motivation. Key constraints that shape decisions here:

- **14 days left** (Oct 17–30). Every design choice trades implementation speed against
  correctness. The demo must fire end-to-end automatically within ~110 seconds.
- **Existing foundation is SOLID and clean.** API, DB models, Redis infra, and demo
  producers are production-quality. This design extends them without disruption.
- **No GPU locally.** Nano 8B and Ultra 253B run via Nebius Token Factory OpenAI-
  compatible endpoint. Client code uses `openai.AsyncOpenAI` pointed at `nebius_base_url`.
- **Jobs run in-process for now** (direct `python -m jobs.stage1.entrypoint` call from
  the Stream Processor). Nebius Serverless Jobs wire-up is a Week 5 item.

### SOLID & code-quality notes on the existing codebase

The existing API layer adheres well to SOLID. Two minor deviations to fix during
implementation:

1. **`ingest.py:55` — counter bug.** `redis.hincrby(DEMO_STATE, f"events:{service}", 1)`
   increments by 1 per batch call instead of by the number of accepted events. Replace
   `1` with `accepted`.

2. **`ingest.py:31` — `get_settings()` inside route handler.** Calling `get_settings()`
   inside the handler couples the handler to the global singleton rather than receiving
   the dependency injected. Inject via `Depends(get_settings)` for testability, or
   (simpler) read settings once at module level since Settings is cached anyway. This is
   low priority but noted for cleanliness.

3. **Stream Processor design — DIP.** The Stream Processor must not import concrete Job
   runner logic. It publishes the `submission_id` on a queue; the job runner reads it.
   This keeps the Stream Processor decoupled from Stage-1 internals.

---

## Goals / Non-Goals

**Goals:**
- Stream Processor that detects spikes and fires Stage-1 without human action
- Stage-1 pipeline: format-agnostic parsing → trace-id or time-window correlation →
  topology inference → Incident rows → Stage-2 dispatch
- Stage-2 pipeline: Nano batch classification → Ultra streaming RCA → Tavily fix
  suggestions → DB persist → SSE completion
- Q&A chat endpoint (POST /incidents/{id}/chat) and Markdown export endpoint
- File upload endpoint (POST /submissions) to support the demo "Load Demo Logs" button
- All four unit test modules from the implementation plan

**Non-Goals:**
- Nebius Serverless Jobs integration (Week 5 scope; design stub is sufficient)
- PDF export (cut per implementation plan)
- Prometheus metrics (cut per implementation plan)
- Additional log formats beyond JSON and plaintext (logfmt deferred)
- Multi-tenant API key management portal page (replaced with hardcoded demo key)

---

## Decisions

### D1 — Stage-1 and Stage-2 run as separate asyncio processes, not FastAPI background tasks

**Decision:** Each stage runs as `python -m jobs.stageN.entrypoint` launched by the
Stream Processor via `asyncio.create_subprocess_exec`. The Stream Processor reads
`SUBMISSION_ID` from the environment and passes it to the child.

**Why:** FastAPI background tasks share the API event loop. A long Stage-1 or Stage-2
run (Ultra 253B can take 60+ seconds) would compete with ingest for the loop, risking
p99 > 50 ms. Separate subprocesses fully isolate the AI pipeline from the hot path.
Nebius Serverless Jobs replaces the subprocess call in Week 5 without changing the job
interface.

**Alternative considered:** Celery/ARQ task queue. Adds a broker dependency and
significant setup time. Subprocess call is simpler and sufficient for a solo hackathon.

---

### D2 — Stage-1: run both correlators sequentially, not in parallel

**Decision:** `select_correlator()` inspects events and picks one correlator.
`TraceIdCorrelator` runs first if ≥ 1 ERROR/CRITICAL event has a `trace_id`; remaining
events (those without a trace_id) fall through to `TimeWindowCorrelator`.

**Why:** The demo dataset has `trace_id` on ~80 % of ERROR events. Running both
correlators in parallel would produce overlapping incidents for the same events. The
sequential hand-off preserves the single-responsibility of each correlator while
handling heterogeneous data cleanly.

---

### D3 — Topology inference uses a 5-second sliding edge window, not span-parent tracing

**Decision:** Edges are inferred from temporal proximity (errors in two different
services within 5 seconds of each other), not from explicit `span_id / parent_span_id`
relationships.

**Why:** Demo producers propagate `trace_id` but not structured span-parent IDs.
Temporal proximity still produces the correct `payment→order→gateway` chain because the
cascade delays (1.2s, 2.8s) are well within the 5-second window. Span-parent overlay is
additive and can be layered in as an enhancement without changing the algorithm contract.

---

### D4 — Ultra RCA prompt ends with a `<ANALYSIS_JSON>` sentinel block

**Decision:** The Ultra prompt instructs the model to conclude its response with a
delimited JSON block:
```
<ANALYSIS_JSON>
{"root_cause_service": "...", "root_cause_method": "...", ...}
</ANALYSIS_JSON>
```
`parse_ultra_response()` splits on this delimiter. Text before it becomes
`cascade_explanation`; text inside it is parsed into structured fields.

**Why:** Ultra 253B is a reasoning model — asking it to emit structured JSON inline
disrupts the prose reasoning. Appending JSON at the end after free-form reasoning gives
better quality output. The delimiter approach is simple and reliable; no output parser
library is needed.

**Fallback:** If the delimiter is absent (model compliance failure), the full text is
stored as `cascade_explanation` and structured fields are left NULL. The incident is
still delivered.

---

### D5 — SSE channel key is `sse:submission:{submission_id}`, not per-incident

**Decision:** Stage-2 publishes tokens on `sse:submission:{submission_id}` even though
it processes per-incident. The submission ID is the natural frontend key (the UI polls
`/submissions/{id}/stream` from the moment of upload).

**Why:** Multiple incidents from one submission are processed sequentially. Publishing
on the submission channel means the portal needs only one SSE connection and sees all
incidents stream through in order. This matches the existing `submissions.py` SSE route.

---

### D6 — File upload streams to S3; full file never loaded into memory

**Decision:** `POST /api/v1/submissions` accepts `multipart/form-data`. Each file is
piped via boto3 multipart upload in `asyncio.to_thread` with 8 MB chunks. Cap: 20 files,
100 MB each.

**Why:** Matches existing `storage.py` design and the implementation plan. Loading full
files into FastAPI memory would cause OOM on large uploads.

---

### D7 — Q&A conversation history capped at 20 turns (40 messages)

**Decision:** After each assistant answer, the history JSONB is sliced to the last 40
messages. Ultra's context window is large but not unlimited; 20 turns is enough for a
demo Q&A session without risking context overflow.

---

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Ultra 253B call takes > 60 s during demo | Stream Processor debounce is 120 s so no double-trigger; portal shows streaming tokens so judges see activity within seconds |
| Tavily search fails or is rate-limited | `fetch_fix_suggestions()` returns `[]` gracefully; incident is still complete |
| Nano returns malformed JSON | `parse_nano_response()` marks all events in the batch as `noise`; no exception propagates |
| Redis stream grows unbounded | `maxlen=50_000` approximate trimming is already set in `ingest.py`; Stream Processor XACK on every message |
| Subprocess Stage-1/2 process leak | Wrap launch in try/finally; log exit code; mark submission `failed` if exit ≠ 0 |
| Ultra response lacks `<ANALYSIS_JSON>` | Fallback: full text as `cascade_explanation`, structured fields NULL — incident delivered |

---

## Migration Plan

1. All new code is additive — no schema changes, no breaking API changes.
2. Apply schema migration first: `alembic upgrade head` (already done; 001 is the only migration).
3. Deploy Stream Processor process alongside the API (`docker-compose up stream_processor`).
4. No rollback complexity: if Stage-1 or Stage-2 fail, submissions remain in `processing` status and can be retried by re-dispatching the Stage-1 job manually.

---

## Open Questions

- **Nebius Jobs API payload format** (Week 5): The exact `container.command` schema for
  Nebius Serverless Jobs needs verification against the live API before wiring. This does
  not affect any Stage-1/2 implementation; the subprocess stub is a drop-in replacement.