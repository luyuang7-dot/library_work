#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/personal_library}"
RELEASES_DIR="${RELEASES_DIR:-$APP_ROOT/releases}"
CURRENT_LINK="${CURRENT_LINK:-$APP_ROOT/current}"
SHARED_DIR="${SHARED_DIR:-$APP_ROOT/shared}"
SHARED_UPLOADS_DIR="${SHARED_UPLOADS_DIR:-$SHARED_DIR/uploads}"
SHARED_INSTANCE_DIR="${SHARED_INSTANCE_DIR:-$SHARED_DIR/instance}"
SERVICE_NAME="${SERVICE_NAME:-personal_library}"
ENV_FILE="${ENV_FILE:-$APP_ROOT/.env}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8000/healthz}"
RUN_RUNTIME_SNAPSHOT="${RUN_RUNTIME_SNAPSHOT:-true}"
RUN_SMOKE_TEST="${RUN_SMOKE_TEST:-true}"
RETAIN_RELEASES_COUNT="${RETAIN_RELEASES_COUNT:-3}"
VERSION="${1:?usage: deploy_release.sh <version>}"
ARCHIVE_PATH="${2:-$APP_ROOT/artifacts/personal_library-${VERSION}.tar.gz}"
RELEASE_DIR="$RELEASES_DIR/$VERSION"

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Required file not found: $path"
    exit 1
  fi
}

prune_old_releases() {
  local keep_count="$1"
  if ! [[ "$keep_count" =~ ^[0-9]+$ ]] || (( keep_count < 1 )); then
    echo "Skip release pruning: invalid RETAIN_RELEASES_COUNT=$keep_count"
    return
  fi

  mapfile -t release_dirs < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | awk '{print $2}')
  if (( ${#release_dirs[@]} <= keep_count )); then
    echo "Release pruning not needed; keeping ${#release_dirs[@]} release(s)."
    return
  fi

  for old_release in "${release_dirs[@]:keep_count}"; do
    if [[ "$old_release" == "$CURRENT_LINK" ]]; then
      continue
    fi
    real_old_release="$(readlink -f "$old_release")"
    if [[ "$real_old_release" == "$RELEASE_DIR" ]]; then
      continue
    fi
    if [[ "$real_old_release" != "$RELEASES_DIR"/* ]]; then
      echo "Skip suspicious release path: $old_release"
      continue
    fi
    rm -rf "$real_old_release"
    echo "Pruned old release: $real_old_release"
  done
}

mkdir -p "$RELEASES_DIR"

if [[ -d "$RELEASE_DIR" ]]; then
  echo "Release already exists: $RELEASE_DIR"
  exit 1
fi

if [[ ! -f "$ARCHIVE_PATH" ]]; then
  echo "Archive not found: $ARCHIVE_PATH"
  exit 1
fi

require_file "$ENV_FILE"

mkdir -p "$RELEASE_DIR" "$SHARED_UPLOADS_DIR" "$SHARED_INSTANCE_DIR"
tar -xzf "$ARCHIVE_PATH" -C "$RELEASE_DIR" --strip-components=1

require_file "$RELEASE_DIR/requirements.txt"
require_file "$RELEASE_DIR/scripts/check_release_readiness.py"
require_file "$RELEASE_DIR/scripts/post_release_smoke_test.sh"
require_file "$RELEASE_DIR/scripts/collect_runtime_snapshot.sh"

release_uploads_dir="$RELEASE_DIR/uploads"
release_instance_dir="$RELEASE_DIR/instance"

if [[ -d "$release_uploads_dir" ]] && [[ -z "$(find "$SHARED_UPLOADS_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
  cp -a "$release_uploads_dir/." "$SHARED_UPLOADS_DIR/"
fi

if [[ -d "$release_instance_dir" ]] && [[ -z "$(find "$SHARED_INSTANCE_DIR" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
  cp -a "$release_instance_dir/." "$SHARED_INSTANCE_DIR/"
fi

rm -rf "$release_uploads_dir" "$release_instance_dir"
ln -sfn "$SHARED_UPLOADS_DIR" "$release_uploads_dir"
ln -sfn "$SHARED_INSTANCE_DIR" "$release_instance_dir"

python3 -m venv "$RELEASE_DIR/.venv"
source "$RELEASE_DIR/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$RELEASE_DIR/requirements.txt"

ln -sfn "$ENV_FILE" "$RELEASE_DIR/.env"

pushd "$RELEASE_DIR" >/dev/null
python3 scripts/check_release_readiness.py
FLASK_ENV=prod FLASK_SKIP_DB_CHECKS=1 "$RELEASE_DIR/.venv/bin/flask" --app wsgi:app init-db
popd >/dev/null

ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
if [[ -x "$RELEASE_DIR/scripts/install_runtime_stack.sh" ]]; then
  /bin/bash "$RELEASE_DIR/scripts/install_runtime_stack.sh"
fi
sudo systemctl restart "$SERVICE_NAME"
curl --fail --silent --show-error "$HEALTHCHECK_URL" >/dev/null

SMOKE_SCRIPT="$RELEASE_DIR/scripts/post_release_smoke_test.sh"
SMOKE_OUTPUT="$RELEASE_DIR/post_release_smoke_test.txt"
if [[ "$RUN_SMOKE_TEST" == "true" && -f "$SMOKE_SCRIPT" ]]; then
  if /bin/bash "$SMOKE_SCRIPT" "${HEALTHCHECK_URL%/healthz}" >"$SMOKE_OUTPUT"; then
    echo "Smoke test saved to: $SMOKE_OUTPUT"
  else
    echo "Smoke test failed; see: $SMOKE_OUTPUT"
    exit 1
  fi
fi

SNAPSHOT_SCRIPT="$RELEASE_DIR/scripts/collect_runtime_snapshot.sh"
SNAPSHOT_OUTPUT="$RELEASE_DIR/runtime_snapshot_post_deploy.txt"
if [[ "$RUN_RUNTIME_SNAPSHOT" == "true" && -f "$SNAPSHOT_SCRIPT" ]]; then
  if /bin/bash "$SNAPSHOT_SCRIPT" "${HEALTHCHECK_URL%/healthz}" >"$SNAPSHOT_OUTPUT"; then
    echo "Runtime snapshot saved to: $SNAPSHOT_OUTPUT"
  else
    echo "Warning: runtime snapshot failed; continue with manual investigation."
  fi
fi

prune_old_releases "$RETAIN_RELEASES_COUNT"

echo "Deployment succeeded: $VERSION"
