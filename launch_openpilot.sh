#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# On any failure, run the fallback launcher
trap 'exec ./launch_chffrplus.sh' ERR
C3_LAUNCH_SH="./sunnypilot/system/hardware/c3/launch_chffrplus.sh"
WATCHDOG_SH="/data/loggerd_watchdog/watchdog.sh"

MODEL="$(tr -d '\0' < "/sys/firmware/devicetree/base/model")"
export MODEL

# Start loggerd watchdog automatically on boot/power-on if installed.
if [ -x "$WATCHDOG_SH" ] && ! pgrep -f "$WATCHDOG_SH" >/dev/null 2>&1; then
  nohup "$WATCHDOG_SH" >/data/loggerd_watchdog/watchdog.out 2>&1 < /dev/null &
fi

if [ "$MODEL" = "comma tici" ]; then
  # Force a failure if the launcher doesn't exist
  [ -x "$C3_LAUNCH_SH" ] || false

  # If it exists, run it
  exec "$C3_LAUNCH_SH"
fi

exec ./launch_chffrplus.sh
