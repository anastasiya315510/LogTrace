#!/usr/bin/env bash
# Deploy LogTrace to the Nebius VM via SSH.
# Reads VM_HOST, VM_USER, VM_SSH_KEY_PATH from .env
# Usage: bash scripts/deploy.sh
set -euo pipefail

# Load .env
set -a
source "$(dirname "$0")/../.env"
set +a

if [[ -z "${VM_HOST:-}" ]]; then
  echo "ERROR: VM_HOST is not set in .env — run scripts/create_vm.sh first"
  exit 1
fi

SSH_KEY="${VM_SSH_KEY_PATH:-$HOME/.ssh/id_ed25519}"
SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $VM_USER@$VM_HOST"

echo "── Deploying to $VM_USER@$VM_HOST ──────────────────────"

# Write .env to the VM (never touches git)
echo "── Syncing .env ─────────────────────────────────────────"
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
  "$(dirname "$0")/../.env" \
  "$VM_USER@$VM_HOST:~/logtrace/.env"

# Pull latest code and restart
$SSH bash <<'REMOTE'
set -euo pipefail
cd ~/logtrace

echo "── Pulling latest code ──────────────────────────────────"
git pull origin main

echo "── Building images ──────────────────────────────────────"
docker compose -f docker-compose.prod.yml build

echo "── Running migrations ───────────────────────────────────"
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head

echo "── Restarting services ──────────────────────────────────"
docker compose -f docker-compose.prod.yml up -d

echo "── Done ─────────────────────────────────────────────────"
REMOTE

echo ""
echo "✓ Deployed. Portal: http://$VM_HOST/portal"