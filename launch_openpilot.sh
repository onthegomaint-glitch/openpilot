#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# On any failure, run the fallback launcher
trap 'exec ./launch_chffrplus.sh' ERR
C3_LAUNCH_SH="./sunnypilot/system/hardware/c3/launch_chffrplus.sh"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Prefer in-repo script (1 GiB cap under /data/loggerd_watchdog); legacy path if missing.
WATCHDOG_SH="${HERE}/scripts/loggerd_watchdog.sh"
[ ! -f "$WATCHDOG_SH" ] && WATCHDOG_SH="/data/loggerd_watchdog/watchdog.sh"

MODEL="$(tr -d '\0' < "/sys/firmware/devicetree/base/model")"
export MODEL

# Start loggerd watchdog automatically on boot/power-on if installed.
# Run with bash so the script need not be chmod +x (e.g. after checkout).
if [ -f "$WATCHDOG_SH" ] && ! pgrep -f "loggerd_watchdog.sh" >/dev/null 2>&1; then
  mkdir -p /data/loggerd_watchdog
  nohup bash "$WATCHDOG_SH" >>/data/loggerd_watchdog/watchdog.out 2>&1 < /dev/null &
fi

if [ "$MODEL" = "comma tici" ]; then
  # Force a failure if the launcher doesn't exist
  [ -x "$C3_LAUNCH_SH" ] || false

  # If it exists, run it
  exec "$C3_LAUNCH_SH"
fi

exec ./launch_chffrplus.sh
