#!/usr/bin/env bash
set -Eeuo pipefail

[[ "${EUID:-$(id -u)}" -ne 0 ]] || {
  echo "Run this as the Raspberry Pi desktop user, not with sudo." >&2
  exit 1
}

if command -v chromium >/dev/null 2>&1; then
  CHROMIUM="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  CHROMIUM="$(command -v chromium-browser)"
else
  echo "Chromium was not found. Install Raspberry Pi OS with Desktop or install Chromium first." >&2
  exit 1
fi

AUTOSTART_DIR="$HOME/.config/labwc"
AUTOSTART_FILE="$AUTOSTART_DIR/autostart"
MARKER="# Minnie Winnie dashboard kiosk"
mkdir -p "$AUTOSTART_DIR"
touch "$AUTOSTART_FILE"

if grep -Fq "$MARKER" "$AUTOSTART_FILE"; then
  echo "Kiosk autostart is already configured in $AUTOSTART_FILE"
  exit 0
fi

{
  printf '\n%s\n' "$MARKER"
  printf '%q http://localhost:3000 --kiosk --noerrdialogs --disable-infobars --no-first-run --enable-features=OverlayScrollbar --start-maximized &\n' "$CHROMIUM"
} >> "$AUTOSTART_FILE"

echo "Kiosk autostart added to $AUTOSTART_FILE"
echo "Reboot after the dashboard services pass verification."
