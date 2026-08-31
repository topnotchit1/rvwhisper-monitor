#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG_DIR="${CONFIG_DIR:-/etc/minnie-dashboard}"
ENV_FILE="$CONFIG_DIR/dashboard.env"
PROFILE_FILE="$CONFIG_DIR/dashboard-profile.json"
SERVICE_USER="${SERVICE_USER:-rvdashboard}"
RESTART=1
[[ "${1:-}" == "--no-restart" ]] && RESTART=0

fail() {
  echo "Configuration failed: $*" >&2
  exit 1
}

[[ "${EUID:-$(id -u)}" -eq 0 ]] || fail "run this configuration tool with sudo"
command -v python3 >/dev/null || fail "python3 is required"
[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE does not exist; run deploy/install-pi.sh first"
[[ -f "$PROFILE_FILE" ]] || fail "$PROFILE_FILE does not exist; run deploy/install-pi.sh first"

current_name="$(python3 - "$PROFILE_FILE" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["vehicle"]["name"])
PY
)"
current_subtitle="$(python3 - "$PROFILE_FILE" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["vehicle"]["subtitle"])
PY
)"
current_monogram="$(python3 - "$PROFILE_FILE" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["vehicle"]["monogram"])
PY
)"

read -r -p "RV display name [$current_name]: " vehicle_name
vehicle_name="${vehicle_name:-$current_name}"
read -r -p "Subtitle [$current_subtitle]: " vehicle_subtitle
vehicle_subtitle="${vehicle_subtitle:-$current_subtitle}"
read -r -p "Short monogram, 1-4 characters [$current_monogram]: " vehicle_monogram
vehicle_monogram="${vehicle_monogram:-$current_monogram}"

echo
echo "Enter the direct RVM3 address shown by the router or RVM3 network page."
echo "Use a DHCP reservation or stable hostname so this address does not change."
read -r -p "RVM3 LAN URL (example: http://192.168.1.50): " rvm_base_url
[[ "$rvm_base_url" =~ ^https?://[A-Za-z0-9._:-]+$ ]] || fail "enter an http:// or https:// address without a path"
read -r -p "RVM identifier (optional for local access): " rvm_id
[[ "$rvm_id" =~ ^[A-Za-z0-9._-]*$ ]] || fail "RVM identifier may contain only letters, numbers, dots, underscores, and hyphens"
read -r -p "RVM dashboard path [root]: " rvm_system_path
[[ "$rvm_system_path" =~ ^/?[A-Za-z0-9._/-]*$ ]] || fail "dashboard path contains unsupported characters"

python3 - "$PROFILE_FILE" "$vehicle_name" "$vehicle_subtitle" "$vehicle_monogram" <<'PY'
import json, os, sys, tempfile
from pathlib import Path

path = Path(sys.argv[1])
name, subtitle, monogram = (value.strip() for value in sys.argv[2:5])
if not name or len(name) > 60:
    raise SystemExit("RV display name must contain 1-60 characters")
if not subtitle or len(subtitle) > 80:
    raise SystemExit("Subtitle must contain 1-80 characters")
if not monogram or len(monogram) > 4:
    raise SystemExit("Monogram must contain 1-4 characters")
profile = json.loads(path.read_text(encoding="utf-8"))
profile["vehicle"] = {"name": name, "subtitle": subtitle, "monogram": monogram.upper()}
fd, temporary = tempfile.mkstemp(prefix="dashboard-profile-", suffix=".json", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(profile, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

python3 - "$ENV_FILE" "$rvm_base_url" "$rvm_id" "$rvm_system_path" <<'PY'
import os, sys, tempfile
from pathlib import Path

path = Path(sys.argv[1])
updates = {
    "RVW_ACCESS_MODE": "local",
    "RVW_BASE_URL": sys.argv[2],
    "RVW_SYSTEM_PATH": sys.argv[4],
    "RVW_ID": sys.argv[3],
    "RVW_USERNAME": "",
    "RVW_PASSWORD": "",
}
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
output = []
for line in lines:
    key, separator, _ = line.partition("=")
    if separator and key in updates:
        output.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        output.append(line)
for key, value in updates.items():
    if key not in seen:
        output.append(f"{key}={value}")
fd, temporary = tempfile.mkstemp(prefix="dashboard-env-", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(output) + "\n")
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

chown root:"$SERVICE_USER" "$ENV_FILE" "$PROFILE_FILE"
chmod 0640 "$ENV_FILE" "$PROFILE_FILE"

if [[ "$RESTART" -eq 1 ]] && systemctl is-enabled minnie-dashboard-api.service >/dev/null 2>&1; then
  systemctl restart minnie-dashboard-api.service minnie-dashboard-ui.service
fi

echo
echo "Dashboard identity and direct RVM3 address saved."
echo "Wi-Fi credentials remain managed by Raspberry Pi OS and are not stored in the dashboard configuration."
echo "Sensor labels and counts can be adjusted in $PROFILE_FILE after private sensor discovery."
