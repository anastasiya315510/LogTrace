# Proposal

## Why

Today is October 16 — 14 days before the hackathon deadline. The NemoTrace foundation
(API, DB schema, Redis infra, demo producers, portal) is solid and production-quality.
However the three modules that make the system actually work — the Stream Processor,
Stage-1 log pipeline, and Stage-2 AI pipeline — are empty stubs. Without them the demo
produces no incident reports, which means no hackathon win. Everything must ship by
October 30.

## What Changes

**Stream Processor (new)**
- Implement `stream_processor/processor.py`: XREADGROUP consumer that reads all
  `stream:ingest:{service}` streams, maintains per-service sliding error windows, and
  auto-triggers a submission when ≥ 10 errors occur within 60 seconds (or any CRITICAL
  event, or the same error type across 3+ services within 30 s).
- Debounce: skip re-trigger if the same service fired within 120 s.
- On trigger: INSERT Submission (`source_method="auto_trigger"`), mark
  `demo:state.auto_triggered=1`, dispatch Stage-1.

**Stage-1 Log Processing Pipeline (new)**
- `jobs/stage1/parser.py` — `BaseParser` ABC, `JsonLineParser`, `PlaintextParser`,
  `detect_format()`.
- `jobs/stage1/correlator.py` — `BaseCorrelator` ABC, `TraceIdCorrelator`,
  `TimeWindowCorrelator`, `select_correlator()`.
- `jobs/stage1/topology.py` — `TopologyInferrer` (5-second sliding edge detection,
  cycle breaker, role assignment: root\_cause / propagated\_error / symptom).
- `jobs/stage1/entrypoint.py` — orchestrates parse → correlate → topology → INSERT
  incidents → dispatch Stage-2; reads events from Redis Streams (auto\_trigger) or S3
  (upload).
- `prompts/nano_classify.prompt` (Stage-2 input, created alongside classifier).

**Stage-2 AI Analysis Pipeline (new)**
- `jobs/stage2/classifier.py` — `batch_classify()` with Nemotron Nano 8B; semaphore-
  bounded asyncio.gather; graceful JSON-parse fallback.
- `jobs/stage2/rca.py` — `stream_rca()` with Nemotron Ultra 253B; token-by-token SSE
  forwarding via Redis pub/sub; structured `<ANALYSIS_JSON>` extraction.
- `jobs/stage2/fix_suggestions.py` — `fetch_fix_suggestions()` dual Tavily queries;
  dedup by URL; graceful failure returns empty list.
- `jobs/stage2/entrypoint.py` — orchestrates classify → RCA → fix suggestions → UPDATE
  incident status to `complete`; publishes `__DONE__` sentinel.
- `prompts/nano_classify.prompt`, `prompts/ultra_rca.prompt` — prompt templates.

**Missing API endpoints (new)**
- `POST /api/v1/submissions` — multipart file upload → S3 → enqueue Stage-1.
- `POST /api/v1/incidents/{id}/chat` — Q&A streaming endpoint backed by Ultra 253B with
  conversation history.
- `GET /api/v1/incidents/{id}/export` — Markdown incident report download.

**Ingest counter bug fix**
- `api/routers/ingest.py:55` increments the demo counter by `1` per batch call instead
  of `accepted`. Replace `hincrby(..., 1)` with `hincrby(..., accepted)`.

**Unit tests (new)**
- `tests/unit/test_parser.py`, `test_correlator.py`, `test_topology.py`,
  `test_classifier_prompt.py` — all four test modules from the implementation plan.

## Capabilities

### New Capabilities

- `stream-spike-detection`: Redis Streams XREADGROUP consumer with multi-condition
  spike detection, per-service debounce, and automatic submission creation.
- `log-processing-pipeline`: Stage-1 job — format-agnostic log parsing, trace-id and
  time-window correlation, service topology inference with role assignment.
- `ai-incident-analysis`: Stage-2 job — batched Nano 8B event classification, streaming
  Ultra 253B root-cause analysis, dual Tavily fix-suggestion queries, interactive Q&A,
  and Markdown export.

### Modified Capabilities

*(none — all three capabilities are new; no existing spec-level requirements change)*

## Impact

| Area | Files |
|------|-------|
| New modules | `stream_processor/processor.py`, `jobs/stage1/{parser,correlator,topology,entrypoint}.py`, `jobs/stage2/{classifier,rca,fix_suggestions,entrypoint}.py` |
| New prompts | `prompts/nano_classify.prompt`, `prompts/ultra_rca.prompt` |
| API additions | `api/routers/submissions.py` (POST route), `api/routers/incidents.py` (chat + export routes) |
| Bug fix | `api/routers/ingest.py` line 55 |
| New tests | `tests/unit/test_parser.py`, `test_correlator.py`, `test_topology.py`, `test_classifier_prompt.py` |
| External deps | Nebius Token Factory (Nano + Ultra), Tavily API, Nebius Object Storage |
| No schema changes | DB models and migrations are already complete |