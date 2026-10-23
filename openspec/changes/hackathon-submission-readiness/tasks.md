# Tasks

## 1. SSE Query Auth Fix

- [x] 1.1 Add `require_api_key_sse` dependency to `api/dependencies.py`: accepts `X-API-Key` header (primary) OR `?api_key=` query parameter (fallback); raises HTTP 401 when neither is present or both are invalid; uses the same SHA-256 hash + Redis cache + DB lookup as `require_api_key`. Verify: unit test — call with header only → 200; call with query param only → 200; call with both (header wins) → 200; call with neither → 401; call with invalid query param → 401.

- [x] 1.2 Swap the stream endpoint's dependency in `api/routers/submissions.py:81`: replace `Depends(require_api_key)` with `Depends(require_api_key_sse)` on `stream_submission_progress`. Verify: all other endpoints in the file still use `Depends(require_api_key)` (grep confirms no accidental changes).

- [x] 1.3 Write `tests/unit/test_sse_auth.py`: `test_header_auth_works`, `test_query_param_auth_works`, `test_both_header_wins`, `test_no_auth_returns_401`, `test_invalid_query_param_returns_401`. Verify: `pytest tests/unit/test_sse_auth.py -v` — all 5 pass.

## 2. Production Deployment Config

- [x] 2.1 Create `docker-compose.prod.yml`: same services as `docker-compose.yml` but (a) no `volumes: - .:/app` source mount, (b) API command is `uvicorn api.main:app --host 0.0.0.0 --port 8000` (no `--reload`), (c) `restart: unless-stopped` on all services, (d) nginx service added (see 2.2), (e) demo-producers only under `profiles: [demo]`. Verify: `docker compose -f docker-compose.prod.yml config` reports no errors.

- [x] 2.2 Create `nginx/nemotrace.conf`: reverse proxy on port 80 → `api:8000`; `proxy_buffering off` + `X-Accel-Buffering: no` on the `/api/v1/submissions` location block for SSE; `client_max_body_size 110m` for file uploads; proxy `/portal/`, `/docs`, `/openapi.json`, `/health`. Verify: after `docker compose -f docker-compose.prod.yml up -d`, `curl http://localhost/health` returns 200.

- [x] 2.3 Create `scripts/start.sh` (executable): (1) check that `NEBIUS_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `NEBIUS_STORAGE_ACCESS_KEY_ID`, `NEBIUS_STORAGE_SECRET_KEY`, `TAVILY_API_KEY` are non-empty — print a descriptive error and exit 1 if any are missing; (2) `docker compose -f docker-compose.prod.yml build`; (3) start postgres + redis and wait for health; (4) run `docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head`; (5) `docker compose -f docker-compose.prod.yml up -d`. Verify: run with a missing env var → script exits 1 with clear message naming the missing variable.

- [x] 2.4 Update `.env.example`: add a `# ── Production deployment ──` section with `DEMO_API_KEY` description clarifying it is the key judges enter in the portal UI, and note that the portal is at `http://<host>/portal` after deploy. Verify: `cp .env.example .env.test && grep DEMO_API_KEY .env.test` shows the key with comment.

## 3. Portal Connection Badge

- [x] 3.1 Add health-check badge to `portal/index.html`: in the header bar add a `<span id="api-status">` element; on `DOMContentLoaded` fetch `/health` with a 3-second timeout; on success set the span to `● Connected` (green); on failure set to `● Disconnected` (red) with tooltip showing the full error; re-check every 30 seconds. Verify: open portal with API running → green badge appears within 3 seconds; stop the API container → badge turns red within 35 seconds.

## 4. HLD Update

- [x] 4.1 Update `HLD.md` §2.8 (Deployment): replace the Nebius Serverless Endpoints + Serverless Jobs deployment description with the Nebius VM + docker-compose approach; add the one-command startup procedure (`./scripts/start.sh`); mark Serverless Endpoints/Jobs as a post-hackathon enhancement. Verify: the section accurately describes `scripts/start.sh`, `docker-compose.prod.yml`, and nginx; no reference to Serverless as the submission deployment path.

## 5. Smoke Test

- [x] 5.1 End-to-end verification: start the full stack with `docker-compose.prod.yml`; open the portal → green "Connected" badge; trigger the demo cascade → SSE progress bar advances from 0% to 100% in the portal (confirms the SSE auth fix works); incident report appears with confidence score > 0. Verify: all three checkpoints pass without 401 errors in the browser console.
