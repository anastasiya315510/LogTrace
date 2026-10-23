# Design

## Context

See proposal.md — Why.

Current auth architecture: `require_api_key` in `api/dependencies.py` reads exclusively from the `X-API-Key` header using FastAPI's `Header(...)`. The browser `EventSource` API spec (WHATWG) does not allow setting custom headers — the connection is always a plain `GET` with no programmatic header control. The portal already passes `?api_key=` in the EventSource URL (`portal/index.html:1505`); this silently fails because the dependency discards query parameters.

Deployment state: `docker-compose.yml` has all required services but mounts the source tree as a volume (`volumes: - .:/app`) and starts with `--reload`, making it unsuitable for production. No nginx config, no TLS, no startup script, no migration step.

## Goals / Non-Goals

**Goals:**
- Fix the SSE stream endpoint so the portal's live analysis progress view works in all browsers.
- Produce a docker-compose + nginx + startup script that gets the stack running on a Nebius VM with one command.
- Add a portal "Connected" badge so judges see API status immediately.

**Non-Goals:**
- Switching any other endpoint to query-param auth.
- Deploying to Nebius Serverless Endpoints or Serverless Jobs (deferred post-hackathon).
- Adding TLS certificate automation (Let's Encrypt / Certbot) — judges will accept self-signed for demo purposes, or use an IP with HTTP if TLS setup proves impractical in the time available.

## Decisions

### D1: New dependency `require_api_key_sse`, scoped to `/stream` only

Rather than modifying the existing `require_api_key` dependency (which would silently loosen auth on every endpoint), introduce `require_api_key_sse(x_api_key: Optional[str] = Header(None, ...), api_key: Optional[str] = Query(None))` in `api/dependencies.py`. It tries the header first; falls back to the query param; raises 401 if neither yields a valid key.

Swap `Depends(require_api_key)` → `Depends(require_api_key_sse)` on `stream_submission_progress` only. Every other endpoint keeps `require_api_key` unchanged.

**Alternative considered**: Modify `require_api_key` directly with an optional query param. Rejected — weakens the auth contract for the ingest hot path without any benefit.

### D2: `docker-compose.prod.yml` alongside the existing dev compose

Keep `docker-compose.yml` as-is for local dev (volume mount, hot reload). Add `docker-compose.prod.yml` that:
- Builds images from the Dockerfile (no volume mount)
- Sets `restart: unless-stopped` on all services
- Does not include `demo-producers` (started manually with `--profile demo`)
- Forwards port 80 from nginx to the host

The startup script (`scripts/start.sh`) runs:
1. Pre-flight check: verify required env vars are set
2. `docker compose -f docker-compose.prod.yml build`
3. `docker compose -f docker-compose.prod.yml up -d postgres redis` + wait for health
4. `docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head`
5. `docker compose -f docker-compose.prod.yml up -d`

### D3: nginx for reverse proxy (HTTP only as primary, TLS optional)

For demo purposes, use HTTP (port 80) as the primary route so the judge does not need to deal with a self-signed certificate warning. The nginx config proxies `/api/`, `/health`, `/portal/`, `/docs`, and `/openapi.json` to `api:8000`. A TLS section is commented out and documented for production use.

**Alternative considered**: Expose port 8000 directly (no nginx). Rejected — nginx also handles `client_max_body_size 110m` for file uploads and sets correct SSE headers (`X-Accel-Buffering: no`).

### D4: Portal health badge via `GET /health`

Add 20 lines of JavaScript to `portal/index.html` that:
1. On `DOMContentLoaded`, fetch `/health` with a 3-second timeout.
2. On success, show a green `●  Connected` badge in the top-right of the header bar.
3. On failure, show a red `●  Disconnected — check API_URL` badge.
4. Re-check every 30 seconds.

No new API endpoint needed — the `/health` endpoint already exists (`api/routers/health.py`).

## Risks / Trade-offs

| Risk | Likelihood | Mitigation |
|---|---|---|
| nginx SSE buffering causes tokens to batch instead of stream | Medium | Set `proxy_buffering off` and `X-Accel-Buffering: no` in nginx config |
| Nebius VM firewall blocks port 80 | Low | Document firewall rule in README and startup script output |
| `alembic upgrade head` fails on a non-empty DB (migration conflict) | Low | `docker-compose.prod.yml` mounts a named volume so DB persists across restarts; fresh VM always has an empty DB |
