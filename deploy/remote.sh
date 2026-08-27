#!/bin/sh
set -eu
APP_DIR="${QUEUEBOT_APP:-/home/queuebot/telegram-queue-bot}"
cd "$APP_DIR"

# Prefer env from CI (sync-deploy); else optional GHCR_TOKEN in .env for manual runs.
if [ -z "${GHCR_TOKEN:-}" ] && [ -f .env ]; then
  # shellcheck disable=SC1091
  GHCR_TOKEN=$(grep -E '^GHCR_TOKEN=' .env | tail -n1 | cut -d= -f2- || true)
  GHCR_USER=$(grep -E '^GHCR_USER=' .env | tail -n1 | cut -d= -f2- || true)
  export GHCR_TOKEN GHCR_USER
fi

if [ -z "${GHCR_TOKEN:-}" ]; then
  echo "GHCR_TOKEN is missing (pass via CI or set in .env)" >&2
  exit 1
fi

printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:-amir1330}" --password-stdin >/dev/null

if docker compose version >/dev/null 2>&1; then
  DC="docker compose --compatibility"
else
  DC="docker-compose"
fi
FILE="-f docker-compose.prod.yml"

echo "Pulling images..."
$DC $FILE pull telegram-queue-bot
docker logout ghcr.io >/dev/null 2>&1 || true

echo "Recreating telegram-queue-bot..."
docker stop telegram-queue-bot 2>/dev/null || true
docker rm telegram-queue-bot 2>/dev/null || true
$DC $FILE up -d --no-build --force-recreate telegram-queue-bot

docker image prune -f
echo "Deploy complete."
