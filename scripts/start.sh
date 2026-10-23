#!/usr/bin/env bash
set -euo pipefail

# ── Pre-flight: required environment variables ────────────────────────────────
REQUIRED_VARS=(
    NEBIUS_API_KEY
    DATABASE_URL
    REDIS_URL
    NEBIUS_STORAGE_ACCESS_KEY_ID
    NEBIUS_STORAGE_SECRET_KEY
    TAVILY_API_KEY
    POSTGRES_USER
    POSTGRES_PASSWORD
    POSTGRES_DB
)

missing=0
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        echo "ERROR: required environment variable '$var' is not set." >&2
        missing=1
    fi
done

if [[ $missing -ne 0 ]]; then
    echo ""
    echo "Copy .env.example to .env and fill in all values, then re-run:" >&2
    echo "  cp .env.example .env && $0" >&2
    exit 1
fi

echo "✓ All required environment variables are set."

# ── Build images ──────────────────────────────────────────────────────────────
echo ""
echo "Building Docker images..."
docker compose -f docker-compose.prod.yml build

# ── Start infrastructure and wait for health ─────────────────────────────────
echo ""
echo "Starting postgres and redis..."
docker compose -f docker-compose.prod.yml up -d postgres redis

echo "Waiting for postgres and redis to be healthy..."
timeout 60 bash -c '
    until docker compose -f docker-compose.prod.yml ps postgres | grep -q "healthy"; do
        sleep 2
    done
'
timeout 60 bash -c '
    until docker compose -f docker-compose.prod.yml ps redis | grep -q "healthy"; do
        sleep 2
    done
'
echo "✓ Infrastructure is healthy."

# ── Run database migrations ───────────────────────────────────────────────────
echo ""
echo "Running database migrations..."
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
echo "✓ Migrations complete."

# ── Start the full stack ──────────────────────────────────────────────────────
echo ""
echo "Starting all services..."
docker compose -f docker-compose.prod.yml up -d

echo ""
echo "✓ NemoTrace is running."
echo "  Portal:  http://localhost/portal"
echo "  API:     http://localhost/api/v1"
echo "  Docs:    http://localhost/docs"
echo ""
echo "To run the demo producers:"
echo "  docker compose -f docker-compose.prod.yml --profile demo up -d demo-producers"
