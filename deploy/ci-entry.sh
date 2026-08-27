#!/bin/sh
# Runs only via forced-command SSH from GitHub Actions.
# Allowed original commands: sync-deploy | deploy
set -eu

APP="${QUEUEBOT_APP:-/home/queuebot/telegram-queue-bot}"
ENTRY_CMD="${SSH_ORIGINAL_COMMAND:-}"

case "$ENTRY_CMD" in
  sync-deploy)
    # stdin: line1=GHCR_USER, line2=GHCR_TOKEN, then tar.gz of compose + deploy scripts
    IFS= read -r GHCR_USER
    IFS= read -r GHCR_TOKEN
    export GHCR_USER GHCR_TOKEN
    mkdir -p "$APP/deploy"
    tar xzf - -C "$APP"
    chmod +x "$APP/deploy/"*.sh 2>/dev/null || true
    cd "$APP"
    exec ./deploy/remote.sh
    ;;
  deploy|"")
    cd "$APP"
    exec ./deploy/remote.sh
    ;;
  *)
    echo "forbidden command: $ENTRY_CMD" >&2
    exit 1
    ;;
esac
