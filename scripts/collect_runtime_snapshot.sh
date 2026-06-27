#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
SERVICE_NAME="${SERVICE_NAME:-personal_library}"
NGINX_SERVICE="${NGINX_SERVICE:-nginx}"
TAIL_LINES="${TAIL_LINES:-20}"

tmp_headers="$(mktemp)"
tmp_body="$(mktemp)"
trap 'rm -f "$tmp_headers" "$tmp_body"' EXIT

timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

echo "== Personal Library Runtime Snapshot =="
echo "timestamp_utc=$timestamp"
echo "base_url=$BASE_URL"
echo "service_name=$SERVICE_NAME"
echo "nginx_service=$NGINX_SERVICE"
echo

echo "## Health Check"
curl --fail --silent --show-error \
  -D "$tmp_headers" \
  -o "$tmp_body" \
  "$BASE_URL/healthz"
request_id="$(
  awk 'BEGIN{IGNORECASE=1} /^X-Request-ID:/ {gsub("\r", "", $2); print $2}' "$tmp_headers"
)"
if [[ -n "$request_id" ]]; then
  echo "request_id=$request_id"
fi
cat "$tmp_body"
echo
echo

echo "## Service Status ($SERVICE_NAME)"
systemctl status "$SERVICE_NAME" --no-pager -l | sed -n "1,20p"
echo

echo "## Nginx Status ($NGINX_SERVICE)"
systemctl status "$NGINX_SERVICE" --no-pager -l | sed -n "1,20p"
echo

echo "## Recent App Logs"
journalctl -u "$SERVICE_NAME" -n "$TAIL_LINES" --no-pager
echo

echo "## Recent Nginx Logs"
journalctl -u "$NGINX_SERVICE" -n "$TAIL_LINES" --no-pager
echo

if [[ -n "$request_id" ]]; then
  echo "## Request Trace ($request_id)"
  journalctl -u "$SERVICE_NAME" --no-pager | grep -F "request_id=$request_id" | tail -n "$TAIL_LINES" || true
  echo
fi

echo "snapshot_complete=true"
