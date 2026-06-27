#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
LOGIN_URL="$BASE_URL/auth/login"
HEALTH_URL="$BASE_URL/healthz"

tmp_headers="$(mktemp)"
tmp_body="$(mktemp)"
trap 'rm -f "$tmp_headers" "$tmp_body"' EXIT

timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

curl --fail --silent --show-error \
  -D "$tmp_headers" \
  -o "$tmp_body" \
  "$HEALTH_URL"

request_id="$(
  awk 'BEGIN{IGNORECASE=1} /^X-Request-ID:/ {gsub("\r", "", $2); print $2}' "$tmp_headers"
)"

curl --fail --silent --show-error "$LOGIN_URL" >/dev/null

echo "health_probe timestamp_utc=$timestamp base_url=$BASE_URL request_id=${request_id:--} status=ok"
cat "$tmp_body"
