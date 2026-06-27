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

## Quick start (central stack, per site)

```bash
git clone https://github.com/xNiicki/argus.git && cd argus
cp .env.example .env          # set ARGUS_SITE, NTFY_*, PVE_TARGET, PEER_NARRATOR_URL
cp pve-exporter/pve.yml.example pve-exporter/pve.yml   # PVE API token
# edit prometheus/targets/*.yml -> your hosts/endpoints
make up                       # pulls narrator image from GHCR + starts the stack
make validate                 # promtool + amtool + compose checks
make test                     # narrator unit tests
```

The custom **narrator** image is built by CI and published to
`ghcr.io/xniicki/argus-narrator` (tags: `latest`, `v*`, short SHA). Pin a version
with `ARGUS_TAG=v1.2.3` in `.env`. To build it from local source instead — e.g.
when hacking on the narrator — use `make dev` (which layers `docker-compose.build.yml`).

Then install the [agents](agents/README.md) on each host and point the central
Prometheus targets at them.

### Paste-anywhere deploy (single file)

`docker-compose.portable.yml` is a **self-contained** version of the stack: every
config (Prometheus rules, alerts, blackbox modules, narrator policy, …) is inlined
via Compose `configs:`, so there are **no sibling folders** to clone. Drop it into
Portainer / Dockge / a bare host, supply env vars, and go:

```bash
ARGUS_SITE=homelab NTFY_TOPIC=argus PVE_TOKEN_VALUE=... \
  docker compose -f docker-compose.portable.yml up -d
```

Secrets are never baked in — `NTFY_TOKEN`, `PVE_TOKEN_VALUE`, `OPENROUTER_API_KEY`,
etc. come from the environment (Portainer's env UI, an `.env`, or `-e`). The file is
generated from the source configs (single source of truth) — never edit it by hand;
run `make portable` after changing any config. CI fails if it drifts.

## Layout

| Path | What |
|---|---|
| `docker-compose.yml` | central stack: prometheus, alertmanager, blackbox, pve-exporter, narrator |
| `prometheus/prometheus.yml` | scrape jobs (file_sd) + alertmanager wiring |
| `prometheus/targets/*.yml` | **edit these** to add hosts/endpoints |
| `prometheus/alerts/*.yml` | rules: uptime, certs, resources, proxmox, network, watchdog |
| `blackbox/blackbox.yml` | http/tcp/icmp/ssl/dns probe modules |
| `alertmanager/alertmanager.yml` | routes ALL alerts → narrator |
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
