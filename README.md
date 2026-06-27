# Argus 👁️

Self-hosted observability **+ plain-English alerting** for a homelab + Hetzner VPS,
including the network path between them. Proxmox is a first-class target.

Argus pairs proven collectors (Prometheus, node_exporter, cAdvisor, blackbox,
prometheus-pve-exporter) with a custom **narrator** service that turns raw alerts
into tiered, explanatory notifications over **ntfy** — every message answers
**what / when / likely why / next step**, with a link to logs.

```
   hosts ──node_exporter/cAdvisor──┐
 endpoints ──blackbox(http/tcp/icmp/ssl/dns)──┤
  Proxmox ──pve-exporter + textfile collectors──┤
                                                ▼
                                         Prometheus ──rules──▶ Alertmanager
                                                                    │ (ALL alerts)
                                                                    ▼
                                                               narrator
                                          dedup · urgency · enrich · compose
                                                                    │
                                                                    ▼
                                                                  ntfy  ──▶ 📱⌚💻
```

## Why the narrator owns tiering

Alertmanager is deliberately "dumb" — it forwards **every** alert to the narrator.
All policy (urgency, repeat-until-ack, dedup, message voice) lives in **one place**,
in Python, and is unit-tested. The narrator scores each alert:

```
score = severity + scope + component-weight + role-weight + recurrence
score → tier → ntfy delivery
```

| Tier | ntfy | Behaviour |
|---|---|---|
| **Info** | — | log only, no push |
| **Notice** | prio 2 | quiet push |
| **Warning** | prio 3 | push + sound |
| **Critical** | prio 4 | high priority, **repeat until acked** |
| **Emergency** | prio 5 | max priority, bypass DND |

Examples from the shipped policy: PVE **host** down → *Emergency*; a single VM/LXC
down → *Warning* (a guest dying is distinct from the host dying); a single HTTP
endpoint down → *Notice*; WAN down → *Critical*; ZFS pool degraded → *Critical*.
Tune everything in [`narrator/config/narrator.yml`](narrator/config/narrator.yml).

## Cross-watching (an outage can't silence its own alarm)

- **Dead-man's switch**: an always-firing `Watchdog` alert feeds a timer in the
  narrator. If the local pipeline dies and the heartbeat stops, the narrator
  self-alarms.
- **Peer cross-watch**: each site's narrator polls the other's `/healthz`. If a
  whole site (incl. its narrator) goes dark, the **surviving** site raises the
  alarm for it. Run one full stack per site (`ARGUS_SITE=homelab` / `hetzner`)
  and set `PEER_NARRATOR_URL` on each.

## Quick start

Every config is baked into the images — the **only** file you touch is `.env`.

```bash
git clone https://github.com/xNiicki/argus.git && cd argus
cp .env.example .env          # set ARGUS_SITE, NTFY_*, ARGUS_*_TARGETS, PVE_*
docker compose up -d          # pulls all images from GHCR + starts the stack
```

(Or hand someone just `docker-compose.yml` + a filled-in `.env`, or paste both into
Portainer/Dockge — no repo folders required.)

### Configure what to monitor — in `.env`

Targets are comma-separated lists. Each entry is `host:port`, or `name=host:port`
for a friendly label; append `!insecure` to skip TLS verification (self-signed):

```bash
ARGUS_NODE_TARGETS=web1=10.0.0.5:9100,db1=10.0.0.6:9100   # node_exporter hosts
ARGUS_HTTP_TARGETS=site=https://acme.com                  # HTTP up + cert expiry
ARGUS_ICMP_TARGETS=gw=10.0.0.1,wan=1.1.1.1                # ping/reachability
ARGUS_SSL_TARGETS=pve=https://10.0.0.10:8006!insecure     # cert tracking (self-signed)
ARGUS_PVE_TARGET=10.0.0.10                                # Proxmox via pve-exporter
```

An entrypoint renders the Prometheus scrape config from these at startup. To pin a
version, set `ARGUS_TAG=v1.2.3`. To build the images locally instead of pulling,
`make build`.

Install the [agents](agents/README.md) (node_exporter + cAdvisor) on each host you
list, then point the targets above at them.

## Images

All images are built by CI (multi-arch amd64/arm64) and published to GHCR; configs
are baked in, so the stack pulls and runs with no mounted files:

`argus-prometheus` · `argus-alertmanager` · `argus-blackbox` · `argus-loki` · `argus-narrator`
(all under `ghcr.io/xniicki/`). Only the **narrator** is custom code; the rest are
upstream images with the Argus config baked on top. `pve-exporter` is upstream,
configured purely via `PVE_*` env vars.

## Layout

| Path | What |
|---|---|
| `docker-compose.yml` | the whole stack — images + env only, no bind mounts |
| `.env.example` | the one file a deployer fills in |
| `prometheus/` | `prometheus.yml`, `alerts/*.yml`, and `docker-entrypoint.sh` (renders targets from env) |
| `blackbox/` | http/tcp/icmp/ssl/dns probe modules + Dockerfile |
| `alertmanager/` | routes ALL alerts → narrator + Dockerfile |
| `loki/` | Loki config + LogQL rules + Dockerfile |
| `narrator/` | the brain (FastAPI); policy in `config/narrator.yml`, tests in `tests/` |
| `agents/` | per-host node_exporter + cAdvisor + textfile collectors |

## Narrator API

| Endpoint | Purpose |
|---|---|
| `POST /alerts/alertmanager` | Alertmanager webhook (the main intake) |
| `POST /alerts/loki` | Loki ruler webhook (Phase 2) |
| `GET\|POST /ack/{key}` | acknowledge — stops repeat-until-ack (ntfy action button) |
| `GET /events` | recent decisions (firing/tier/reason/notified) |
| `GET /healthz` / `GET /readyz` | liveness / readiness (peer cross-watch hits `/healthz`) |

## Roadmap

- **Phase 1 ✅** metrics + uptime + certs + WAN → rule-based urgency → ntfy
- **Phase 2** logs via Loki + Promtail/Alloy (narrator already has `/alerts/loki`)
- **Phase 3** security & change events (SSH logins, new keys, package/firewall/process changes)
- **Phase 4** LLM-assisted root-cause, flap detection, ack/snooze UI, dashboard

See [`tasks/todo.md`](tasks/todo.md) for detailed status.
