#!/usr/bin/env bash
# Emit ZFS pool health + scrub age as node_exporter textfile metrics.
# Install on the PVE/ZFS host. Run from cron every few minutes:
#   */5 * * * * /opt/argus/zfs_health.sh
# Writes atomically to the node_exporter textfile directory.
set -euo pipefail

OUT_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile}"
OUT="${OUT_DIR}/argus_zfs.prom"
TMP="$(mktemp)"
# Note: no `host` label here — Prometheus adds it from the scrape target
# (prometheus/targets/nodes.yml), avoiding an exported_host collision.

{
  echo "# HELP argus_zfs_pool_health 0=ONLINE, 1=DEGRADED, 2=FAULTED/other"
  echo "# TYPE argus_zfs_pool_health gauge"
  echo "# HELP argus_zfs_scrub_age_seconds Seconds since last completed scrub"
  echo "# TYPE argus_zfs_scrub_age_seconds gauge"
} >>"$TMP"

if command -v zpool >/dev/null 2>&1; then
  while read -r pool health; do
    case "$health" in
      ONLINE) code=0 ;;
      DEGRADED) code=1 ;;
      *) code=2 ;;
    esac
    echo "argus_zfs_pool_health{pool=\"${pool}\"} ${code}" >>"$TMP"

    # Best-effort scrub age: parse "scrub repaired ... on <date>".
    scrub_line="$(zpool status "$pool" 2>/dev/null | grep -E 'scrub (repaired|in progress|canceled)' || true)"
    when="$(echo "$scrub_line" | sed -n 's/.* on \(.*\)$/\1/p')"
    if [ -n "$when" ]; then
      if epoch="$(date -d "$when" +%s 2>/dev/null)"; then
        age=$(( $(date +%s) - epoch ))
        echo "argus_zfs_scrub_age_seconds{pool=\"${pool}\"} ${age}" >>"$TMP"
      fi
    fi
  done < <(zpool list -H -o name,health 2>/dev/null)
fi

mv "$TMP" "$OUT"
