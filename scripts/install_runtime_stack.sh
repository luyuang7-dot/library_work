#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/personal_library}"
CURRENT_LINK="${CURRENT_LINK:-$APP_ROOT/current}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
NGINX_AVAILABLE_DIR="${NGINX_AVAILABLE_DIR:-/etc/nginx/sites-available}"
NGINX_ENABLED_DIR="${NGINX_ENABLED_DIR:-/etc/nginx/sites-enabled}"
SERVICE_NAME="${SERVICE_NAME:-personal_library}"
ENABLE_AI_AGENT_TIMER="${ENABLE_AI_AGENT_TIMER:-false}"
ENABLE_HEALTHCHECK_TIMER="${ENABLE_HEALTHCHECK_TIMER:-true}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8000/healthz}"

if [[ ! -d "$CURRENT_LINK/deploy" ]]; then
  echo "Deploy assets not found under: $CURRENT_LINK/deploy"
  exit 1
fi

install -m 0644 \
  "$CURRENT_LINK/deploy/personal_library.service" \
  "$SYSTEMD_DIR/personal_library.service"
install -m 0644 \
  "$CURRENT_LINK/deploy/personal_library-ai-agent-rollup.service" \
  "$SYSTEMD_DIR/personal_library-ai-agent-rollup.service"
install -m 0644 \
  "$CURRENT_LINK/deploy/personal_library-ai-agent-rollup.timer" \
  "$SYSTEMD_DIR/personal_library-ai-agent-rollup.timer"
install -m 0644 \
  "$CURRENT_LINK/deploy/personal_library-healthcheck.service" \
  "$SYSTEMD_DIR/personal_library-healthcheck.service"
install -m 0644 \
  "$CURRENT_LINK/deploy/personal_library-healthcheck.timer" \
  "$SYSTEMD_DIR/personal_library-healthcheck.timer"
install -m 0644 \
  "$CURRENT_LINK/deploy/personal_library-alert@.service" \
  "$SYSTEMD_DIR/personal_library-alert@.service"

install -m 0644 \
  "$CURRENT_LINK/deploy/personal_library.nginx" \
  "$NGINX_AVAILABLE_DIR/personal_library"
ln -sfn \
  "$NGINX_AVAILABLE_DIR/personal_library" \
  "$NGINX_ENABLED_DIR/personal_library"

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

if [[ "$ENABLE_AI_AGENT_TIMER" == "true" ]]; then
  sudo systemctl enable --now personal_library-ai-agent-rollup.timer
fi

if [[ "$ENABLE_HEALTHCHECK_TIMER" == "true" ]]; then
  sudo systemctl enable --now personal_library-healthcheck.timer
fi

sudo nginx -t
sudo systemctl reload nginx
curl --fail --silent --show-error "$HEALTHCHECK_URL" >/dev/null

echo "Runtime stack installed from: $CURRENT_LINK"
