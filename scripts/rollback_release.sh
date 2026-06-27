#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/personal_library}"
RELEASES_DIR="${RELEASES_DIR:-$APP_ROOT/releases}"
CURRENT_LINK="${CURRENT_LINK:-$APP_ROOT/current}"
SHARED_DIR="${SHARED_DIR:-$APP_ROOT/shared}"
SHARED_UPLOADS_DIR="${SHARED_UPLOADS_DIR:-$SHARED_DIR/uploads}"
SHARED_INSTANCE_DIR="${SHARED_INSTANCE_DIR:-$SHARED_DIR/instance}"
SERVICE_NAME="${SERVICE_NAME:-personal_library}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8000/healthz}"
RUN_RUNTIME_SNAPSHOT="${RUN_RUNTIME_SNAPSHOT:-true}"
RUN_SMOKE_TEST="${RUN_SMOKE_TEST:-true}"
TARGET_VERSION="${1:?usage: rollback_release.sh <previous-version>}"
TARGET_DIR="$RELEASES_DIR/$TARGET_VERSION"

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Required file not found: $path"
    exit 1
  fi
}

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Target release does not exist: $TARGET_DIR"
  exit 1
fi

require_file "$TARGET_DIR/scripts/check_release_readiness.py"
require_file "$TARGET_DIR/scripts/post_release_smoke_test.sh"
require_file "$TARGET_DIR/scripts/collect_runtime_snapshot.sh"

mkdir -p "$SHARED_UPLOADS_DIR" "$SHARED_INSTANCE_DIR"

target_uploads_dir="$TARGET_DIR/uploads"
target_instance_dir="$TARGET_DIR/instance"

if [[ -d "$target_uploads_dir" ]] && [[ -z "$(find "$SHARED_UPLOADS_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
  cp -a "$target_uploads_dir/." "$SHARED_UPLOADS_DIR/"
fi

if [[ -d "$target_instance_dir" ]] && [[ -z "$(find "$SHARED_INSTANCE_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
  cp -a "$target_instance_dir/." "$SHARED_INSTANCE_DIR/"
fi

rm -rf "$target_uploads_dir" "$target_instance_dir"
ln -sfn "$SHARED_UPLOADS_DIR" "$target_uploads_dir"
ln -sfn "$SHARED_INSTANCE_DIR" "$target_instance_dir"

pushd "$TARGET_DIR" >/dev/null
python3 scripts/check_release_readiness.py
popd >/dev/null

ln -sfn "$TARGET_DIR" "$CURRENT_LINK"
sudo systemctl restart "$SERVICE_NAME"
curl --fail --silent --show-error "$HEALTHCHECK_URL" >/dev/null

SMOKE_SCRIPT="$TARGET_DIR/scripts/post_release_smoke_test.sh"
SMOKE_OUTPUT="$TARGET_DIR/post_release_smoke_test_after_rollback.txt"
if [[ "$RUN_SMOKE_TEST" == "true" && -f "$SMOKE_SCRIPT" ]]; then
  if /bin/bash "$SMOKE_SCRIPT" "${HEALTHCHECK_URL%/healthz}" >"$SMOKE_OUTPUT"; then
    echo "Smoke test saved to: $SMOKE_OUTPUT"
  else
    echo "Smoke test failed; see: $SMOKE_OUTPUT"
    exit 1
  fi
fi

SNAPSHOT_SCRIPT="$TARGET_DIR/scripts/collect_runtime_snapshot.sh"
SNAPSHOT_OUTPUT="$TARGET_DIR/runtime_snapshot_post_rollback.txt"
if [[ "$RUN_RUNTIME_SNAPSHOT" == "true" && -f "$SNAPSHOT_SCRIPT" ]]; then
  if /bin/bash "$SNAPSHOT_SCRIPT" "${HEALTHCHECK_URL%/healthz}" >"$SNAPSHOT_OUTPUT"; then
    echo "Runtime snapshot saved to: $SNAPSHOT_OUTPUT"
  else
    echo "Warning: runtime snapshot failed; continue with manual investigation."
  fi
fi

echo "Rollback succeeded: $TARGET_VERSION"
