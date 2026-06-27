#!/usr/bin/env bash
# Emit SMART overall-health per disk as a node_exporter textfile metric.
# Requires smartmontools (`smartctl`). Run from cron (needs root):
#   */15 * * * * /opt/argus/smart_health.sh
#
# Metric: node_smartmon_device_smart_healthy{disk,host} 1=PASSED, 0=FAILED
set -euo pipefail

OUT_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile}"
OUT="${OUT_DIR}/argus_smart.prom"
TMP="$(mktemp)"

{
  echo "# HELP node_smartmon_device_smart_healthy 1=SMART overall-health PASSED, 0=FAILED"
  echo "# TYPE node_smartmon_device_smart_healthy gauge"
} >>"$TMP"

if command -v smartctl >/dev/null 2>&1; then
  for dev in $(lsblk -dno NAME,TYPE | awk '$2=="disk"{print $1}'); do
    path="/dev/${dev}"
    health="$(smartctl -H "$path" 2>/dev/null | grep -Ei 'overall-health|SMART Health Status' || true)"
    if echo "$health" | grep -qiE 'PASSED|OK'; then
      val=1
    elif [ -n "$health" ]; then
      val=0
    else
      continue   # device doesn't support SMART / not readable
    fi
    echo "node_smartmon_device_smart_healthy{disk=\"${dev}\"} ${val}" >>"$TMP"
  done
fi

mv "$TMP" "$OUT"
