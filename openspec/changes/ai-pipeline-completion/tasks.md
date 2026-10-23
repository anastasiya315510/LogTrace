# Tasks

## 1. Bug Fix & Prompts

- [x] 1.1 Fix ingest counter bug: in `api/routers/ingest.py:55` change `hincrby(..., 1)` to `hincrby(..., accepted)`. Verify by running `pytest tests/unit/test_ingest.py -v` — the demo counter test should pass cleanly.

- [x] 1.2 Create `prompts/nano_classify.prompt`: write the Nano 8B classification prompt that takes a batch of log events as JSON and returns a JSON array of `{event_index, category, severity}` objects. Verify the prompt template renders correctly for a 20-event batch.

- [x] 1.3 Create `prompts/ultra_rca.prompt`: write the Ultra 253B RCA prompt that takes incident metadata, topology JSON, and event summaries, and ends with instructions to close with `<ANALYSIS_JSON>{...}</ANALYSIS_JSON>`. Verify the prompt includes all required output fields: `root_cause_service`, `root_cause_method`, `confidence_score`, `cascade_chain`, `alternative_hypotheses`.

## 2. Stage-1: Log Processing Pipeline

- [x] 2.1 Implement `jobs/stage1/parser.py`: `BaseParser` ABC with `parse_line()`, `JsonLineParser`, `PlaintextParser` (2+ regex patterns), `detect_format()`. Verify: `JsonLineParser` correctly maps all fields for a full-schema event and returns `None` (not an exception) for a malformed JSON line.

- [x] 2.2 Implement `jobs/stage1/correlator.py`: `BaseCorrelator` ABC, `TraceIdCorrelator` (group by `trace_id`), `TimeWindowCorrelator` (sliding window, dedup same message+service within 1s), `select_correlator()`. Verify: 10 events sharing `trace_id` → 1 Incident; 4 events at t=0 and 4 at t=120s → 2 Incidents.

- [x] 2.3 Implement `jobs/stage1/topology.py`: `TopologyInferrer.infer()` with 5s sliding edge detection, cycle breaking (remove lowest-weight edge), role assignment (`root_cause`/`propagated_error`/`symptom`/`unaffected`). Verify: `payment→order→gateway` chain produces correct roles; a cycle A→B→A is broken cleanly.

- [x] 2.4 Implement `jobs/stage1/entrypoint.py`: orchestrate read events (Redis Streams for `auto_trigger`, S3 for `upload`) → parse → batch insert LogEvents → select correlator → correlate → infer topology → insert Incidents → enqueue Stage-2 → update Submission status. Verify: run with a pre-seeded Redis stream and confirm an Incident row with `service_topology_json` is created in the DB.

- [x] 2.5 Write `tests/unit/test_parser.py`: `test_json_line_parser_full_schema`, `test_json_line_parser_partial`, `test_plaintext_parser_standard_format`, `test_format_detection`. Verify: `pytest tests/unit/test_parser.py -v` — all 4 pass.

- [x] 2.6 Write `tests/unit/test_correlator.py`: `test_trace_id_correlation`, `test_time_window_correlation`, `test_time_window_two_incidents`, `test_dedup`. Verify: `pytest tests/unit/test_correlator.py -v` — all 4 pass.

- [x] 2.7 Write `tests/unit/test_topology.py`: `test_simple_chain`, `test_cycle_detection`, `test_single_service`, `test_role_assignment`. Verify: `pytest tests/unit/test_topology.py -v` — all 4 pass.

## 3. Stage-2: AI Analysis Pipeline

- [x] 3.1 Implement `jobs/stage2/classifier.py`: `batch_classify()` using semaphore-bounded `asyncio.gather` (batch size 20, parallelism 10), `build_nano_prompt()`, `parse_nano_response()` with graceful JSON-parse fallback (mark batch as `noise`/`unknown` on failure). Verify: `parse_nano_response()` with deliberately malformed JSON returns a list with `unknown` categories and raises no exception.

- [x] 3.2 Write `tests/unit/test_classifier_prompt.py`: `test_batch_prompt_construction` (20 events → all 20 in prompt), `test_nano_response_malformed` (invalid JSON → 20 `noise`/`unknown`, no exception). Verify: `pytest tests/unit/test_classifier_prompt.py -v` — both pass.

- [x] 3.3 Implement `jobs/stage2/rca.py`: `stream_rca()` that streams Ultra 253B response token-by-token, publishes each token to `sse:submission:{submission_id}` via Redis pub/sub, and extracts the `<ANALYSIS_JSON>` block at completion. Verify: with a mock `AsyncOpenAI` that yields 5 tokens + a `<ANALYSIS_JSON>` block, confirm all tokens are published and structured fields are correctly parsed.

- [x] 3.4 Implement `jobs/stage2/fix_suggestions.py`: `fetch_fix_suggestions()` with dual Tavily queries (remediation + vulnerability), URL dedup, top-3 by score. Both-fail path returns `[]` gracefully. Verify: mock both Tavily calls to raise exceptions → function returns `[]` with no exception raised.

- [x] 3.5 Implement `jobs/stage2/entrypoint.py`: orchestrate load incident + events → `batch_classify()` → `stream_rca()` → `fetch_fix_suggestions()` → INSERT EventClassifications, FixSuggestions, IncidentAnalysis → UPDATE Incident status to `complete` → publish `__DONE__` sentinel. Verify: run with mocked Nano/Ultra/Tavily → Incident row transitions to `complete` and `sse:submission:{id}` receives `__DONE__`.

## 4. Stream Processor

- [x] 4.1 Add Redis key constants to `core/redis_keys.py`: `RedisKeys.analysis_queue` (for Stage-1 dispatch), `RedisKeys.sp_consumer_group` (consumer group name). Verify: constants importable from both Stream Processor and job entrypoints.

- [x] 4.2 Implement `stream_processor/processor.py`: `StreamProcessor` class with `run()` main loop (XREADGROUP, XACK), `_discover_streams()` (SCAN MATCH `stream:ingest:*` every 30 s), per-service sliding `deque` window, `_check_spike_conditions()` (single-service ≥10 errors/60s, CRITICAL event, cross-service same error_type in 3+ services/30s), per-service debounce dict (120 s), trigger action (INSERT Submission, mark demo state, dispatch Stage-1 subprocess). Verify: seed a Redis stream with 10 ERROR events within 60 s, run the processor for 65 s, and confirm a Submission row appears in the DB.

- [x] 4.3 Add `stream_processor` service to `docker-compose.yml` (non-demo profile) so it starts automatically with `docker-compose up`. Verify: `docker-compose up` → `docker-compose ps` shows `stream_processor` running.

## 5. Missing API Endpoints

- [x] 5.1 Add `POST /api/v1/submissions` to `api/routers/submissions.py`: multipart file upload (max 20 files, 100 MB each, text MIME only) → stream each file to S3 via `storage.upload_fileobj()` → INSERT Submission (`source_method="upload"`) → enqueue Stage-1. Verify: upload a 3-file test payload and confirm a Submission row with `source_method="upload"` and `object_keys` populated appears in the DB.

- [x] 5.2 Add `POST /api/v1/incidents/{incident_id}/chat` to `api/routers/incidents.py`: validate incident is `complete` (400 otherwise), build conversation messages from `analysis.conversation_history_json`, stream Ultra 253B response as SSE, persist updated history capped at 20 turns. Verify: POST a question to a completed incident → SSE stream returns tokens → history row updated in DB.

- [x] 5.3 Add `GET /api/v1/incidents/{incident_id}/export` to `api/routers/incidents.py`: render Markdown report (root cause, confidence, cascade chain, analysis, fix suggestions) and return as `StreamingResponse` with `Content-Disposition: attachment; filename=incident-{id}.md`. Verify: call the endpoint for a complete incident and confirm a `.md` file is returned with expected sections.

## 6. Integration Smoke Test

- [ ] 6.1 Full happy-path check: `docker-compose --profile demo up` → wait for cascade → confirm within 120 s that a Submission appears, Stage-1 runs (Incident row with topology), Stage-2 runs (IncidentAnalysis row with `confidence_score > 0` and ≥1 FixSuggestion), and the portal analysis tab shows the incident report.

- [x] 6.2 Run full unit test suite: `pytest tests/unit/ -v` — all tests pass with no warnings.

## Workflow follow-up

- Run `ruff check . && ruff format .` and fix any lint issues before archiving.
- Archive the change once the full happy-path demo fires end-to-end: `openspec archive ai-pipeline-completion`.