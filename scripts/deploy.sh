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
REPO_URL=$(git -C "$(dirname "$0")/.." remote get-url origin 2>/dev/null || echo "https://github.com/esty315/Nemotrace.git")

echo "── Deploying to $VM_USER@$VM_HOST ──────────────────────"

# Bootstrap repo on first deploy, then sync .env
$SSH "REPO_URL='$REPO_URL'" bash <<'BOOTSTRAP'
set -euo pipefail
if [ ! -d ~/logtrace ]; then
  echo "── First deploy: cloning repository ─────────────────────"
  git clone "$REPO_URL" ~/logtrace
fi
BOOTSTRAP

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
docker compose -f docker-compose.prod.yml up -d --force-recreate
docker compose -f docker-compose.prod.yml --profile demo up -d demo-producers

echo "── Done ─────────────────────────────────────────────────"
REMOTE

echo ""
echo "✓ Deployed. Portal: http://$VM_HOST/portal"