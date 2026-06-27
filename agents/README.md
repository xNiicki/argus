# Argus Agents

What runs on **each monitored host** (homelab hosts, the Proxmox host, and the Hetzner VPS).

## Install

```bash
# on each host
docker compose -f docker-compose.agent.yml up -d
```

This starts:
- **node-exporter** (`:9100`) — CPU/RAM/disk/load/temps/SMART + textfile collectors
- **cAdvisor** (`:8080`) — per-container resource & health

Then add the host's `IP:9100` / `IP:8080` to the central Prometheus's
`prometheus/targets/{nodes,cadvisor}.yml`, set a `host`/`role`/`site` label, and
`make reload` on the central side.

## Textfile collectors (Proxmox / ZFS / SMART hosts)

These emit the metrics no exporter provides natively. Install on the relevant host:

```bash
sudo mkdir -p /var/lib/node_exporter/textfile /opt/argus
sudo cp textfile-collectors/*.sh /opt/argus/
sudo crontab -e
```

```cron
*/5  * * * * TEXTFILE_DIR=/var/lib/node_exporter/textfile /opt/argus/zfs_health.sh
*/15 * * * * TEXTFILE_DIR=/var/lib/node_exporter/textfile /opt/argus/smart_health.sh
30   4 * * * TEXTFILE_DIR=/var/lib/node_exporter/textfile /opt/argus/pve_backup.sh
```

| Script | Metrics | Powers alert |
|---|---|---|
| `zfs_health.sh` | `argus_zfs_pool_health`, `argus_zfs_scrub_age_seconds` | `ZfsPoolDegraded`, `ZfsScrubOverdue` |
| `pve_backup.sh` | `argus_pve_backup_last_status`, `argus_pve_backup_last_success_timestamp` | `ProxmoxBackupFailed`, `ProxmoxBackupStale` |
| `smart_health.sh` | `node_smartmon_device_smart_healthy` | `SmartFailurePredicted` |

> The node-exporter container mounts `/` so it reads `/var/lib/node_exporter/textfile`
> from the host via `--collector.textfile.directory=/host/var/lib/node_exporter/textfile`.
