#!/usr/bin/env bash
# On-device: logs loggerd/encoderd health, tails swaglog for errors, and captures
# freeze snapshots. Total usage under $DATA_DIR is capped at $MAX_QUOTA_BYTES (default 1 GiB).
set -u

DATA_DIR="/data/loggerd_watchdog"
RING_LOG="${DATA_DIR}/ring.log"
HEALTH_LOG="${DATA_DIR}/health.log"
PID_FILE="${DATA_DIR}/watchdog.pid"
SEEN_FILE="${DATA_DIR}/seen_running.flag"
WATCHDOG_OUT="${DATA_DIR}/watchdog.out"

# Default: 1 GiB cap for the whole watchdog directory (not the whole drive).
: "${MAX_QUOTA_BYTES:=1073741824}"

# Truncate these if still over quota after snapshot deletion (keeps last N lines).
: "${HEALTH_MAX_LINES:=50000}"
: "${RING_MAX_LINES:=20000}"

mkdir -p "$DATA_DIR"
echo $$ > "$PID_FILE"

echo "=== watchdog start $(date -Iseconds) max_bytes=$MAX_QUOTA_BYTES ===" >> "$RING_LOG"
echo "=== watchdog start $(date -Iseconds) max_bytes=$MAX_QUOTA_BYTES ===" >> "$HEALTH_LOG"

dir_bytes() {
  du -sb "$DATA_DIR" 2>/dev/null | awk '{print $1}'
}

# Delete oldest snapshot_*.log files until under quota; then trim large ring/health if needed.
enforce_quota() {
  local cur b
  cur="$(dir_bytes)"
  b="${cur:-0}"
  while [ "${b:-0}" -gt "$MAX_QUOTA_BYTES" ]; do
    local old
    old="$(find "$DATA_DIR" -maxdepth 1 -name 'snapshot_*.log' -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | head -1 | cut -d' ' -f2-)"
    if [ -n "$old" ] && [ -f "$old" ]; then
      rm -f "$old"
      echo "[$(date -Iseconds)] enforce_quota: removed $old" >> "$RING_LOG"
    else
      break
    fi
    b="$(dir_bytes)" || b=0
  done
  b="$(dir_bytes)" || b=0
  if [ "${b:-0}" -gt "$MAX_QUOTA_BYTES" ]; then
    if [ -f "$HEALTH_LOG" ]; then
      tail -n "$HEALTH_MAX_LINES" "$HEALTH_LOG" > "${HEALTH_LOG}.tmp" 2>/dev/null && mv "${HEALTH_LOG}.tmp" "$HEALTH_LOG"
      echo "[$(date -Iseconds)] enforce_quota: trimmed health.log to last $HEALTH_MAX_LINES lines" >> "$RING_LOG"
    fi
    b="$(dir_bytes)" || b=0
  fi
  if [ "${b:-0}" -gt "$MAX_QUOTA_BYTES" ]; then
    if [ -f "$RING_LOG" ]; then
      tail -n "$RING_MAX_LINES" "$RING_LOG" > "${RING_LOG}.tmp" 2>/dev/null && mv "${RING_LOG}.tmp" "$RING_LOG"
      echo "[$(date -Iseconds)] enforce_quota: trimmed ring.log to last $RING_MAX_LINES lines" >> "$RING_LOG"
    fi
  fi
}

snapshot() {
  local reason="$1"
  local ts
  ts=$(date +%Y%m%d_%H%M%S)
  local f="${DATA_DIR}/snapshot_${ts}_${reason}.log"
  {
    echo "===== SNAPSHOT $ts reason=$reason ====="
    date -Iseconds
    echo "\n[git]"; (cd /data/openpilot && git rev-parse --short HEAD && git status -sb) 2>/dev/null || true
    echo "\n[uptime]"; uptime
    echo "\n[df -h]"; df -h
    echo "\n[processes]"; ps aux | grep -E './loggerd|./encoderd|manager.py|controlsd|selfdrived|camerad' | grep -v grep || true
    echo "\n[dmesg tail]"; dmesg 2>/dev/null | tail -n 120
    echo "\n[recent realdata]"; ls -lt /data/media/0/realdata 2>/dev/null | head -n 30
    echo "\n[recent swaglog files]"; ls -lt /data/log/swaglog.* 2>/dev/null | head -n 10
    echo "\n[swaglog grep]"; grep -hEi 'loggerd|encoderd|process_not_running|i/o error|no space left|segfault|traceback' /data/log/swaglog.* 2>/dev/null | tail -n 200
  } > "$f" 2>&1
  echo "[$(date -Iseconds)] snapshot saved: $f" >> "$RING_LOG"
  enforce_quota
}

health_loop() {
  local n=0
  while true; do
    {
      printf '[%s] ' "$(date -Iseconds)"
      pgrep -af './loggerd|./encoderd|manager.py' 2>/dev/null | tr '\n' '|' || true
      printf ' load='; cat /proc/loadavg 2>/dev/null | awk '{print $1","$2","$3}'
      printf ' mem_avail_kb='; awk '/MemAvailable/ {print $2}' /proc/meminfo 2>/dev/null
      printf ' watch_bytes='; dir_bytes
      echo
    } >> "$HEALTH_LOG"
    n=$((n + 1))
    if [ $((n % 30)) -eq 0 ]; then
      enforce_quota
    fi
    sleep 2
  done
}

error_watch_loop() {
  # shellcheck disable=SC2012
  tail -n 0 -F /data/log/swaglog.* 2>/dev/null | while IFS= read -r line; do
    lower=$(printf '%s' "$line" | tr '[:upper:]' '[:lower:]')
    if printf '%s' "$lower" | grep -Eq 'loggerd|encoderd|process_not_running|i/o error|no space left|segfault|traceback'; then
      echo "[$(date -Iseconds)] $line" >> "$RING_LOG"
      snapshot "error"
    fi
  done
}

freeze_watch_loop() {
  local miss=0
  while true; do
    if pgrep -f './loggerd' >/dev/null 2>&1 || pgrep -f './encoderd' >/dev/null 2>&1; then
      miss=0
      touch "$SEEN_FILE" 2>/dev/null
    else
      miss=$((miss + 1))
    fi
    if [ -f "$SEEN_FILE" ] && pgrep -f 'manager.py' >/dev/null 2>&1 && [ "$miss" -ge 10 ]; then
      echo "[$(date -Iseconds)] freeze-watch: loggerd/encoderd gone 20s after being seen" >> "$RING_LOG"
      snapshot "freeze"
      miss=0
    fi
    sleep 2
  done
}

health_loop &
H1=$!
error_watch_loop &
H2=$!
freeze_watch_loop &
H3=$!

wait "$H1" "$H2" "$H3"
