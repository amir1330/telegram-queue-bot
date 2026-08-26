#!/bin/sh
set -eu
cd /root/telegram-queue-bot

if [ -z "${GHCR_TOKEN:-}" ]; then
  echo "GHCR_TOKEN is missing" >&2
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
# Force recreate even when only the :latest digest changed.
docker stop telegram-queue-bot 2>/dev/null || true
docker rm telegram-queue-bot 2>/dev/null || true
$DC $FILE up -d --no-build --force-recreate telegram-queue-bot

docker image prune -f
echo "Deploy complete."
