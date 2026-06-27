#!/usr/bin/env bash
set -euo pipefail

FAILED_UNIT="${1:?usage: emit_runtime_alert.sh <failed-unit>}"
SERVICE_NAME="${SERVICE_NAME:-personal_library}"
NGINX_SERVICE="${NGINX_SERVICE:-nginx}"
TAIL_LINES="${TAIL_LINES:-20}"
TAG="${ALERT_LOG_TAG:-personal_library_alert}"

timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
unit_state="$(systemctl is-active "$FAILED_UNIT" 2>/dev/null || true)"
unit_failed_state="$(systemctl is-failed "$FAILED_UNIT" 2>/dev/null || true)"

emit() {
  local level="$1"
  shift
  local message="$*"
  if command -v systemd-cat >/dev/null 2>&1; then
    printf '%s\n' "$message" | systemd-cat -t "$TAG" -p "$level"
  elif command -v logger >/dev/null 2>&1; then
    logger -t "$TAG" "$message"
  else
    printf '%s\n' "$message"
  fi
}

emit err "runtime_alert timestamp_utc=$timestamp failed_unit=$FAILED_UNIT active_state=${unit_state:-unknown} failed_state=${unit_failed_state:-unknown}"

if systemctl status "$FAILED_UNIT" --no-pager -l >/tmp/personal_library_alert_unit_status.txt 2>&1; then
  :
fi
while IFS= read -r line; do
  emit err "[$FAILED_UNIT] $line"
done < <(sed -n "1,30p" /tmp/personal_library_alert_unit_status.txt)
rm -f /tmp/personal_library_alert_unit_status.txt

if journalctl -u "$SERVICE_NAME" -n "$TAIL_LINES" --no-pager >/tmp/personal_library_alert_app_logs.txt 2>&1; then
  while IFS= read -r line; do
    emit err "[recent:$SERVICE_NAME] $line"
  done < /tmp/personal_library_alert_app_logs.txt
fi
rm -f /tmp/personal_library_alert_app_logs.txt

if journalctl -u "$NGINX_SERVICE" -n "$TAIL_LINES" --no-pager >/tmp/personal_library_alert_nginx_logs.txt 2>&1; then
  while IFS= read -r line; do
    emit err "[recent:$NGINX_SERVICE] $line"
  done < /tmp/personal_library_alert_nginx_logs.txt
fi
rm -f /tmp/personal_library_alert_nginx_logs.txt
