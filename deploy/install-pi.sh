#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/minnie-dashboard}"
SERVICE_USER="${SERVICE_USER:-rvdashboard}"
CONFIG_DIR="${CONFIG_DIR:-/etc/minnie-dashboard}"
DATA_DIR="${DATA_DIR:-/var/lib/minnie-dashboard}"
ENV_FILE="$CONFIG_DIR/dashboard.env"
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RELEASE_DIR="$INSTALL_ROOT/releases/$RELEASE_ID"

fail() {
  echo "Install failed: $*" >&2
  exit 1
}

[[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run this installer with sudo"
[[ -f "$SOURCE_DIR/package-lock.json" ]] || fail "run the installer from a complete dashboard checkout"
[[ -f "$SOURCE_DIR/backend/pyproject.toml" ]] || fail "backend package is missing"
command -v apt-get >/dev/null || fail "Raspberry Pi OS or another apt-based Debian system is required"
command -v systemctl >/dev/null || fail "systemd is required"

echo "Installing operating-system prerequisites..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl python3 python3-pip python3-venv rsync

command -v node >/dev/null || fail "Node.js 22 or later is required; install it from nodejs.org, then rerun"
command -v npm >/dev/null || fail "npm is required"
NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
[[ "$NODE_MAJOR" -ge 22 ]] || fail "Node.js 22 or later is required; found $(node --version)"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || fail "Python 3.11 or later is required"

MEM_KB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [[ "${MEM_KB:-0}" -lt 900000 ]]; then
  echo "WARNING: less than 1 GB RAM detected. Chromium kiosk operation is experimental on this device." >&2
  echo "         Build on a quiet system and keep a larger Pi available as a fallback." >&2
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_ROOT/releases" "$RELEASE_DIR"
install -d -m 0750 -o root -g "$SERVICE_USER" "$CONFIG_DIR"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR" "$DATA_DIR/captures"

echo "Copying application into release $RELEASE_ID..."
rsync -a \
  --exclude '.git/' \
  --exclude 'node_modules/' \
  --exclude '.next/' \
  --exclude '.vinext/' \
  --exclude '.wrangler/' \
  --exclude 'dist/' \
  --exclude 'outputs/' \
  --exclude 'work/' \
  --exclude 'backend/.venv/' \
  --exclude 'backend/data/' \
  --exclude 'backend/captures/' \
  "$SOURCE_DIR/" "$RELEASE_DIR/"

python3 -m venv "$RELEASE_DIR/backend/.venv"
"$RELEASE_DIR/backend/.venv/bin/python" -m pip install --upgrade pip
"$RELEASE_DIR/backend/.venv/bin/python" -m pip install "$RELEASE_DIR/backend"

echo "Installing and building the touchscreen UI..."
(
  cd "$RELEASE_DIR"
  NEXT_PUBLIC_DASHBOARD_API_URL=http://127.0.0.1:8080 npm ci
  NEXT_PUBLIC_DASHBOARD_API_URL=http://127.0.0.1:8080 npm run build
)
chmod 0755 "$RELEASE_DIR/deploy/install-pi.sh" "$RELEASE_DIR/deploy/configure-dashboard.sh" "$RELEASE_DIR/deploy/install-kiosk.sh" "$RELEASE_DIR/deploy/verify-pi.sh"

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0640 -o root -g "$SERVICE_USER" "$RELEASE_DIR/deploy/minnie-dashboard.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE in demo mode."
else
  echo "Preserved existing $ENV_FILE."
fi

if [[ ! -f "$CONFIG_DIR/sensor-map.json" ]]; then
  install -m 0640 -o root -g "$SERVICE_USER" "$RELEASE_DIR/backend/config/sensor-map.example.json" "$CONFIG_DIR/sensor-map.json"
  echo "Created a placeholder sensor map; replace it only after capturing real payloads."
fi

if [[ ! -f "$CONFIG_DIR/dashboard-profile.json" ]]; then
  install -m 0640 -o root -g "$SERVICE_USER" "$RELEASE_DIR/backend/config/dashboard-profile.example.json" "$CONFIG_DIR/dashboard-profile.json"
  echo "Created a generic dashboard profile."
fi

if [[ -t 0 && "${SKIP_INTERACTIVE_CONFIG:-0}" != "1" ]]; then
  read -r -p "Configure the RV name and direct RVM3 LAN address now? [Y/n] " configure_now
  if [[ ! "$configure_now" =~ ^[Nn]$ ]]; then
    "$RELEASE_DIR/deploy/configure-dashboard.sh" --no-restart
  fi
fi

ln -sfn "$RELEASE_DIR" "$INSTALL_ROOT/current"
install -m 0644 "$RELEASE_DIR/deploy/minnie-dashboard-api.service" /etc/systemd/system/minnie-dashboard-api.service
install -m 0644 "$RELEASE_DIR/deploy/minnie-dashboard-ui.service" /etc/systemd/system/minnie-dashboard-ui.service

systemctl daemon-reload
systemctl enable --now minnie-dashboard-api.service minnie-dashboard-ui.service

echo
echo "Dashboard installation complete."
echo "  Local display: http://localhost:3000"
echo "  API health:    http://localhost:8080/health"
echo "  Verify:        sudo $INSTALL_ROOT/current/deploy/verify-pi.sh"
echo "  Live setup:    $INSTALL_ROOT/current/docs/pi-installation.md"
echo "  Reconfigure:   sudo $INSTALL_ROOT/current/deploy/configure-dashboard.sh"
