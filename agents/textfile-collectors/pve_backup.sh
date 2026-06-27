#!/usr/bin/env bash
# Emit Proxmox backup status per guest as node_exporter textfile metrics.
# Reads the vzdump task logs Proxmox keeps under /var/log/pve/tasks.
# Install on the PVE host, run from cron after your backup window, e.g.:
#   30 4 * * * /opt/argus/pve_backup.sh
#
# Metrics:
#   argus_pve_backup_last_status{guest,job}             0=OK, 1=failed
#   argus_pve_backup_last_success_timestamp{guest}      unix ts of last success
set -euo pipefail

OUT_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile}"
OUT="${OUT_DIR}/argus_pve_backup.prom"
TMP="$(mktemp)"

{
  echo "# HELP argus_pve_backup_last_status 0=success, non-zero=failed (most recent backup)"
  echo "# TYPE argus_pve_backup_last_status gauge"
  echo "# HELP argus_pve_backup_last_success_timestamp Unix time of last successful backup"
  echo "# TYPE argus_pve_backup_last_success_timestamp gauge"
} >>"$TMP"

# Use `pvesh` to read recent vzdump tasks if available (most reliable).
if command -v pvesh >/dev/null 2>&1; then
  node="$(hostname -s)"
  # List recent tasks, filter vzdump, take the latest per guest.
  pvesh get "/nodes/${node}/tasks" --typefilter vzdump --limit 200 --output-format json 2>/dev/null \
    | python3 - "$TMP" <<'PY' || true
import json, sys, re
tmp = sys.argv[1]
try:
    tasks = json.load(sys.stdin)
except Exception:
    tasks = []
latest = {}
for t in tasks:
    # task id often encodes the guest; fall back to 'id' field
    guest = str(t.get("id") or t.get("worker_id") or "unknown")
    end = t.get("endtime") or 0
    if guest not in latest or end > latest[guest]["endtime"]:
        latest[guest] = {"endtime": end, "status": t.get("status", "")}
with open(tmp, "a") as fh:
    for guest, info in latest.items():
        ok = 0 if str(info["status"]).upper() in ("OK", "") else 1
        fh.write(f'argus_pve_backup_last_status{{guest="{guest}",job="vzdump"}} {ok}\n')
        if ok == 0 and info["endtime"]:
            fh.write(f'argus_pve_backup_last_success_timestamp{{guest="{guest}"}} {info["endtime"]}\n')
PY
fi

mv "$TMP" "$OUT"
