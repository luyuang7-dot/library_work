#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

OPERATOR="${1:?usage: finalize_release_record.sh <operator> [base_url] [environment] [version]}"
BASE_URL="${2:-http://127.0.0.1:8000}"
ENVIRONMENT="${3:-prod}"
VERSION="${4:-$(<"$ROOT_DIR/VERSION")}"
EVIDENCE_DIR="${EVIDENCE_DIR:-$ROOT_DIR/post_release_evidence}"

/bin/bash "$SCRIPT_DIR/capture_post_release_evidence.sh" "$BASE_URL" "$EVIDENCE_DIR"

pushd "$ROOT_DIR" >/dev/null
record_path="$(
  python3 scripts/create_release_record.py \
    --version "$VERSION" \
    --environment "$ENVIRONMENT" \
    --operator "$OPERATOR" \
    --evidence-dir "$EVIDENCE_DIR"
)"
popd >/dev/null

echo "release_record=$record_path"
echo "release_record_complete=true"
