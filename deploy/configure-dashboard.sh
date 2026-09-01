#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${CONFIG_DIR:-/etc/minnie-dashboard}"
ENV_FILE="$CONFIG_DIR/dashboard.env"
PROFILE_FILE="$CONFIG_DIR/dashboard-profile.json"
SERVICE_USER="${SERVICE_USER:-rvdashboard}"
RESTART=1

fail() {
  echo "Configuration failed: $*" >&2
  exit 1
}

case "${1:-}" in
  "") ;;
  --no-restart) RESTART=0 ;;
  *) fail "unknown option: $1" ;;
esac

[[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run this configuration tool with sudo"
[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE does not exist; run deploy/install-pi.sh first"
[[ -f "$PROFILE_FILE" ]] || fail "$PROFILE_FILE does not exist; run deploy/install-pi.sh first"

APP_PYTHON="${DASHBOARD_PYTHON:-$SCRIPT_DIR/../backend/.venv/bin/python}"
[[ -x "$APP_PYTHON" ]] || fail "dashboard Python environment not found at $APP_PYTHON"

"$APP_PYTHON" -m rv_dashboard.configure \
  --env-file "$ENV_FILE" \
  --profile-file "$PROFILE_FILE"

chown root:"$SERVICE_USER" "$ENV_FILE" "$PROFILE_FILE"
chmod 0640 "$ENV_FILE" "$PROFILE_FILE"

if [[ "$RESTART" -eq 1 ]] && systemctl is-enabled minnie-dashboard-api.service >/dev/null 2>&1; then
  systemctl restart minnie-dashboard-api.service minnie-dashboard-ui.service
fi

echo
echo "Configuration complete."
echo "Wi-Fi credentials remain managed by Raspberry Pi OS and are not stored here."
echo "Sensor mappings remain private and separate in $CONFIG_DIR/sensor-map.json."
