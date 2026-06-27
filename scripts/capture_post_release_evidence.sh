#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
OUTPUT_DIR="${2:-$(pwd)}"
SMOKE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SMOKE_SCRIPT="$SMOKE_SCRIPT_DIR/post_release_smoke_test.sh"
SNAPSHOT_SCRIPT="$SMOKE_SCRIPT_DIR/collect_runtime_snapshot.sh"
SMOKE_OUTPUT="$OUTPUT_DIR/post_release_smoke_test.txt"
SNAPSHOT_OUTPUT="$OUTPUT_DIR/runtime_snapshot.txt"

mkdir -p "$OUTPUT_DIR"

if [[ ! -f "$SMOKE_SCRIPT" ]]; then
  echo "Smoke test script not found: $SMOKE_SCRIPT"
  exit 1
fi

if [[ ! -f "$SNAPSHOT_SCRIPT" ]]; then
  echo "Runtime snapshot script not found: $SNAPSHOT_SCRIPT"
  exit 1
fi

/bin/bash "$SMOKE_SCRIPT" "$BASE_URL" >"$SMOKE_OUTPUT"
/bin/bash "$SNAPSHOT_SCRIPT" "$BASE_URL" >"$SNAPSHOT_OUTPUT"

echo "post_release_smoke_test=$SMOKE_OUTPUT"
echo "runtime_snapshot=$SNAPSHOT_OUTPUT"
echo "post_release_evidence_complete=true"
