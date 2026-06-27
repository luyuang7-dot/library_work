#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
tmp_headers="$(mktemp)"
trap 'rm -f "$tmp_headers"' EXIT

print_request_id() {
  local request_id
  request_id="$(
    awk 'BEGIN{IGNORECASE=1} /^X-Request-ID:/ {gsub("\r", "", $2); print $2}' "$tmp_headers"
  )"
  if [[ -n "$request_id" ]]; then
    echo "request_id=$request_id"
  fi
}

echo "Checking health endpoint..."
curl --fail --silent --show-error -D "$tmp_headers" "$BASE_URL/healthz" >/dev/null
print_request_id

echo "Checking login page..."
curl --fail --silent --show-error -D "$tmp_headers" "$BASE_URL/auth/login" >/dev/null
print_request_id

echo "Checking home redirect..."
curl --fail --silent --show-error -D "$tmp_headers" -I "$BASE_URL/" >/dev/null
print_request_id

echo "Smoke test passed for $BASE_URL"
