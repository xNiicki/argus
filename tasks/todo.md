# Argus — Build Plan

## Phase 1 — metrics + uptime + certs + WAN → rule-based urgency → ntfy  ✅ DONE
- [x] Repo layout + docker-compose central stack
- [x] Prometheus: scrape config + file_sd targets + Alertmanager wiring
- [x] Blackbox exporter: http / tcp / icmp / ssl-cert / dns modules
- [x] prometheus-pve-exporter wiring (Proxmox node/VM/LXC/storage/backup/ZFS/quorum)
- [x] Alert rules: uptime, certs, resources, proxmox, network/WAN, watchdog (29 rules)
- [x] Alertmanager: route ALL alerts to narrator webhook (narrator owns tiering)
- [x] Narrator service (FastAPI):
  - [x] Alertmanager webhook receiver + models
  - [x] Urgency engine (severity × scope × component × role × recurrence → 5 tiers)
  - [x] Enrichment (query Prometheus for related context)
  - [x] Message composer (what / when / likely why / next step / logs link)
  - [x] ntfy notifier (tier → priority/sound/repeat/DND mapping)
  - [x] De-duplication + flap detection + ack
  - [x] Watchdog dead-man-switch + peer cross-watch
- [x] Unit tests: urgency, compose, store/dedup (23 passing)
- [x] Agent compose (node_exporter + cadvisor) + textfile collectors (ZFS/SMART/backup)
- [x] Validate configs (promtool, amtool, compose config) + run narrator tests

## Phase 2 — logs via Loki + Promtail  ✅ DONE
- [x] Loki (monolithic + ruler) in central compose; ruler -> Alertmanager -> narrator
- [x] LogQL alert rules (app/system error bursts, OOM kill)
- [x] Promtail on agents (journal + docker + varlogs)
- [x] Narrator: Logs action button for component=logs; ntfy 3-action cap
- [x] Verified: Loki config valid, ruler loaded rules, push+query round-trip works

## Phase 3 — security & change events (SSH, keys, packages, firewall, processes)  ✅ DONE
- [x] Loki rules: SSH brute-force, root login, sudo failures
- [x] Textfile collector: authorized_keys / firewall / listening-ports / packages state hashes
- [x] Prometheus rules: detect changes() in those state hashes
- [x] Verified: promtool OK (4 rules), Loki ruler loads 6 LogQL alerts, collector runs

## Phase 4 — LLM root-cause, flap detection, ack/snooze UI, dashboard  ✅ DONE
- [x] Flap detection surfaced in messages + flap dampening (suppress fire/resolve spam)
- [x] ack + snooze endpoints + state (snooze suppresses notifications & repeats)
- [x] LLM root-cause guesser — optional, via OpenRouter (OpenAI-compatible), best-effort
- [x] Dashboard (narrator-served HTML at / and /dashboard: active events, tiers, ack/snooze, heartbeat/peer status)
- [x] Verified: 33 tests pass; live dashboard + /api/state + snooze confirmed; llm=off when no key

## Review — Phases 2–4
**Status: complete & verified.** All four phases now build and run.
- Phase 2 (logs): Loki + ruler + Promtail; LogQL alerts flow ruler→Alertmanager→narrator;
  verified Loki loads rules and the push/query path works.
- Phase 3 (security/change): SSH brute-force/root-login/sudo LogQL rules; textfile collectors
  for authorized_keys/firewall/ports/packages → Prometheus changes() detection; promtool clean.
- Phase 4: flap dampening, ack/snooze, OpenRouter LLM hints (opt-in via OPENROUTER_API_KEY),
  and a self-contained dashboard. 33 unit tests green; live smoke tests pass.

Follow-ups: real runbook docs; confirm pve-exporter quorum/backup metric names against a live
PVE; tune OPENROUTER_MODEL to the user's preferred slug.

## Review — Phase 1
**Status: complete & verified.** Built the full central stack, a config-driven
rule set (29 alert rules across 6 groups), and the narrator service that owns all
tiering/dedup/voice.

Verification evidence:
- `promtool check config` → all 6 rule files + config valid (29 rules)
- `amtool check-config` → SUCCESS
- `docker compose config` → valid (exit 0)
- narrator unit tests → 23 passed (urgency policy, store/dedup/flap, compose voice)
- Live smoke test: built the image, POSTed real Alertmanager payloads →
  HostDown(hypervisor)=Emergency, HttpEndpointDown=Notice, Watchdog fed timer,
  ack + recovery worked; real ntfy delivery confirmed ("ntfy sent: [Critical] …").

Key design decisions:
- Alertmanager is "dumb": forwards ALL alerts to the narrator so policy lives in
  one tested place (Python), not scattered across AM routes.
- Urgency = severity + scope + component-weight + role-weight + recurrence → tier.
  Guest-down (Warning) is distinct from host-down (Critical/Emergency by role).
- Cross-watch: always-firing Watchdog → dead-man timer; peer narrators poll each
  other's /healthz so a dead site is reported by the survivor.

Follow-ups / notes for later phases:
- Runbook URLs in annotations point to a placeholder repo path — create real docs.
- pve_backup.sh task-id→guest mapping is best-effort; refine against real PVE tasks.
- ProxmoxClusterNoQuorum metric name depends on pve-exporter version; verify live.
