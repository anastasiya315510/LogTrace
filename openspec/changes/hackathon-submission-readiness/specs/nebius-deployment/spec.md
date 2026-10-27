# Spec: Nebius Deployment

## Purpose

LogTrace must be deployable to a Nebius AI Cloud VM with a single command, producing a publicly accessible HTTPS URL that judges can use as the working demo.

## Requirements

### Deployment target

- The deployment target is a **Nebius AI Cloud VM** (Ubuntu 22.04, Docker + Docker Compose pre-installed).
- All services (API, stream processor, PostgreSQL, Redis) run as Docker containers via Docker Compose.
- The full stack must start with one command after environment variables are configured.

### Public access

- The API and portal MUST be reachable over HTTPS on port 443 at the VM's public IP or DNS name.
- An nginx reverse proxy handles TLS termination and forwards to the FastAPI container on port 8000.
- The portal is accessible at `https://<host>/portal`.
- The API is accessible at `https://<host>/api/v1/...`.

### Environment configuration

- A `.env.example` file documents every required variable with comments.
- A production Docker Compose file (`docker-compose.prod.yml`) uses the `.env` file and does NOT volume-mount the source tree (no `volumes: - .:/app`), so the running container uses the built image.
- The production compose file does NOT include `demo-producers` (those are started separately when needed).

### Database migrations

- The startup script MUST apply Alembic migrations (`alembic upgrade head`) before starting the API container, so the schema is always current on a fresh VM.

### Demo API key

- On startup the API seeds `DEMO_API_KEY` into the `api_keys` table (existing behaviour). The `.env.example` documents that `DEMO_API_KEY` is the key judges enter in the portal.

### Portal connection status

- The portal MUST display a visible "Connected" / "Disconnected" badge that reflects whether it can reach the API at startup.
- The badge is shown in the portal header and does not block any other portal functionality.
- It calls `GET /health` to determine connectivity status.

## Scenarios

- **Fresh VM setup**: clone repo, copy `.env.example` → `.env`, fill in keys, run `./scripts/start.sh` → stack healthy, portal accessible at `https://<host>/portal`.
- **Missing env var**: startup script detects missing required variables and prints a clear error before attempting to start Docker Compose.
- **DB migrations on restart**: running `./scripts/start.sh` a second time applies any pending migrations and restarts containers cleanly.
- **Portal connected badge**: opening the portal shows a green "Connected" badge within 2 seconds if the API is reachable.
- **Portal disconnected badge**: if the API is unreachable the portal shows a red "Disconnected" badge and a message indicating the API URL.
