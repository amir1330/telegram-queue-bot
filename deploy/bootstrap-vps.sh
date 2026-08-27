#!/bin/sh
# One-shot VPS bootstrap for hardened GitHub Actions deploys.
# Run as root: ssh root@HOST 'sh -s' < deploy/bootstrap-vps.sh
set -eu

USER_NAME=queuebot
APP_DIR=/home/queuebot/telegram-queue-bot
OLD_DIR=/root/telegram-queue-bot

if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$USER_NAME"
  echo "created user $USER_NAME"
fi

usermod -aG docker "$USER_NAME"

mkdir -p "$APP_DIR/deploy" "/home/$USER_NAME/.ssh" "/home/$USER_NAME/bin"
chmod 700 "/home/$USER_NAME/.ssh"

if [ -f "$OLD_DIR/.env" ]; then
  grep -E '^BOT_TOKEN=' "$OLD_DIR/.env" > "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
fi

chown -R "$USER_NAME:$USER_NAME" "/home/$USER_NAME"

echo "Bootstrap done. App dir: $APP_DIR"
