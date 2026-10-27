# Proposal

## Why

The hackathon submission deadline is October 30, 2026. The backend pipeline, portal, and all unit tests are complete, but two blockers prevent a working live demo: (1) the portal's SSE-based progress stream is broken because browser `EventSource` cannot send custom HTTP headers, so the API key query param the portal passes is silently ignored and the stream endpoint returns 401; (2) there is no deployment configuration that produces a public, accessible URL for the judges.

## What Changes

- **Fix SSE authentication** — add `api_key` query parameter support to the stream progress endpoint so browser-native `EventSource` can authenticate without requiring non-standard header injection.
- **Add Nebius VM deployment configuration** — a production-oriented `docker-compose.prod.yml`, an nginx reverse proxy config for HTTPS termination, a one-command startup script, and an updated `.env.example` with all required Nebius production values. The HLD §2.8 and §3.5 deployment sections are updated to reflect docker-compose-on-VM as the submission deployment (not Serverless Endpoints, which is deferred post-hackathon).
- **Validate portal end-to-end connectivity** — add a health ping the portal runs on load to show the API connection status, so judges immediately see a "Connected" indicator and can identify configuration problems.

## Capabilities

### New Capabilities

- `sse-query-auth`: The SSE stream endpoint must accept the API key as an `?api_key=` query parameter in addition to the `X-API-Key` header. This unblocks `EventSource` usage in all browsers without any JavaScript workaround.
- `nebius-deployment`: Production deployment configuration targeting a Nebius AI Cloud VM — docker-compose with production env, nginx HTTPS termination, and a startup script that applies DB migrations and starts the full stack with a single command.

### Modified Capabilities

*(none — no existing specs exist in openspec/specs/)*

## Impact

- `api/dependencies.py` — new `require_api_key_sse` dependency that accepts both header and `?api_key=` query param; used only on the stream endpoint to avoid weakening header-only auth elsewhere.
- `api/routers/submissions.py` — swap `Depends(require_api_key)` → `Depends(require_api_key_sse)` on the `/stream` endpoint only.
- New files: `docker-compose.prod.yml`, `nginx/logtrace.conf`, `scripts/start.sh`.
- `HLD.md` §2.8 and §3.5 — update deployment approach description; add Nebius VM deployment instructions; mark Serverless Endpoints/Jobs as post-hackathon enhancement.
- `portal/index.html` — add a health-check ping on load that sets a "Connected / Disconnected" badge.
