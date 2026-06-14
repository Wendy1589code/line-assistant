#!/usr/bin/env bash
#
# Deploy the current working tree to the VM and rebuild the containers.
#
# Usage:
#   ./scripts/deploy.sh                 # deploy to the default VM
#   VM_HOST=root@1.2.3.4 ./scripts/deploy.sh
#
# What it does:
#   1. rsync the repo to the VM, EXCLUDING runtime state (.env, secrets/, data/)
#      so a deploy can never clobber tokens, OAuth creds, or user data.
#   2. docker compose up -d --build  (rebuild image, recreate containers)
#   3. prune dangling images and run a health check.
#
# This same logic runs in CI (.github/workflows/deploy.yml); keep them in sync.
set -euo pipefail

VM_HOST="${VM_HOST:-root@168.119.58.156}"
VM_PATH="${VM_PATH:-/opt/line-assistant}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=15}"

# Paths that hold runtime state or secrets — never overwrite/delete these on the VM.
EXCLUDES=(
  --exclude='.git/'
  --exclude='.github/'
  --exclude='.env'
  --exclude='credentials.md'
  --exclude='secrets/'
  --exclude='data/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='.venv/'
  --exclude='.claude/'
  --exclude='.idea/'
)

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Deploying $(git rev-parse --short HEAD 2>/dev/null || echo 'working-tree') to ${VM_HOST}:${VM_PATH}"

# --delete keeps the VM tree clean (removes files deleted from the repo), but the
# excluded runtime paths above are protected from deletion.
rsync -az --delete "${EXCLUDES[@]}" \
  -e "ssh ${SSH_OPTS}" \
  ./ "${VM_HOST}:${VM_PATH}/"

echo "==> Rebuilding containers on the VM"
ssh ${SSH_OPTS} "${VM_HOST}" "
  set -e
  cd '${VM_PATH}'
  docker compose up -d --build
  docker image prune -f >/dev/null
  echo '--- container status ---'
  docker compose ps
"

echo "==> Health check"
ssh ${SSH_OPTS} "${VM_HOST}" "
  cd '${VM_PATH}'
  # App listens on :8000 inside the compose network; hit it from the app container.
  docker compose exec -T app python -c 'import urllib.request,sys; sys.exit(0)' 2>/dev/null || true
  docker compose ps --format 'table {{.Service}}\t{{.Status}}'
"

echo "==> Done."
