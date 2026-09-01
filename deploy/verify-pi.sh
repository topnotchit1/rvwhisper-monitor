#!/usr/bin/env bash
set -u

FAILURES=0
INSTALL_ROOT="${INSTALL_ROOT:-/opt/minnie-dashboard}"
CONFIG_DIR="${CONFIG_DIR:-/etc/minnie-dashboard}"

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1" >&2; FAILURES=$((FAILURES + 1)); }
warn() { printf 'WARN  %s\n' "$1" >&2; }

CONFIGURE_PYTHON="$INSTALL_ROOT/current/backend/.venv/bin/python"
if [[ -x "$CONFIGURE_PYTHON" ]] && \
  "$CONFIGURE_PYTHON" -m rv_dashboard.configure \
    --env-file "$CONFIG_DIR/dashboard.env" \
    --profile-file "$CONFIG_DIR/dashboard-profile.json" \
    --check >/dev/null; then
  pass "dashboard configuration is valid"
else
  fail "dashboard configuration is missing or invalid"
fi

for service in minnie-dashboard-api.service minnie-dashboard-ui.service; do
  if systemctl is-active --quiet "$service"; then
    pass "$service is running"
  else
    fail "$service is not running"
  fi
done

if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/health >/dev/null; then
  pass "API health endpoint responded"
else
  fail "API health endpoint did not respond"
fi

if curl --fail --silent --show-error --max-time 10 http://127.0.0.1:3000/ >/dev/null; then
  pass "dashboard UI responded"
else
  fail "dashboard UI did not respond"
fi

if timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -qx yes; then
  pass "system clock is synchronized"
else
  warn "system clock is not yet synchronized"
fi

MEM_KB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [[ "${MEM_KB:-0}" -lt 900000 ]]; then
  warn "less than 1 GB RAM detected; monitor Chromium and build stability"
else
  pass "at least 1 GB RAM detected"
fi

ROOT_FREE_KB="$(df -Pk / | awk 'NR==2 {print $4}')"
if [[ "${ROOT_FREE_KB:-0}" -lt 1048576 ]]; then
  warn "less than 1 GB free on the root filesystem"
else
  pass "at least 1 GB disk space is free"
fi

if [[ "$FAILURES" -eq 0 ]]; then
  echo "Verification complete: dashboard is ready for demo-mode testing."
else
  echo "Verification found $FAILURES blocking problem(s)." >&2
fi
exit "$FAILURES"
