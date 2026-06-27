"""Enrich an alert with related context from Prometheus.

Best-effort: any failure returns no context rather than blocking the alert.
Each branch answers "what else should I know before acting on this?".
"""
from __future__ import annotations

import logging

import httpx

from .models import Alert

log = logging.getLogger("narrator.enrich")


async def _query(client: httpx.AsyncClient, prom_url: str, expr: str) -> list[dict]:
    try:
        r = await client.get(f"{prom_url}/api/v1/query", params={"query": expr}, timeout=5.0)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            return []
        return data["data"]["result"]
    except Exception as e:  # noqa: BLE001 - enrichment must never raise
        log.debug("enrichment query failed (%s): %s", expr, e)
        return []


def _scalar(result: list[dict]) -> float | None:
    if not result:
        return None
    try:
        return float(result[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return None


async def enrich(alert: Alert, prom_url: str, client: httpx.AsyncClient) -> list[str]:
    comp = alert.component
    out: list[str] = []
    try:
        if comp == "host":
            # Which guests/endpoints on this host are also affected right now?
            host = alert.host
            guests = await _query(client, prom_url, f'pve_up{{node="{host}"}} == 0')
            if guests:
                out.append(f"{len(guests)} guest(s) on {host} also unreachable.")
            downeps = await _query(client, prom_url, f'probe_success{{host="{host}"}} == 0')
            if downeps:
                out.append(f"{len(downeps)} probe(s) for {host} failing.")

        elif comp == "cert":
            days = _scalar(await _query(
                client, prom_url,
                f'(probe_ssl_earliest_cert_expiry{{instance="{alert.instance}"}} - time()) / 86400',
            ))
            if days is not None:
                out.append(f"~{days:.0f} days until expiry.")

        elif comp in ("disk", "proxmox-storage"):
            pct = _scalar(await _query(
                client, prom_url,
                f'100 * (node_filesystem_avail_bytes{{instance="{alert.instance}"}} '
                f'/ node_filesystem_size_bytes{{instance="{alert.instance}"}})',
            ))
            if pct is not None:
                out.append(f"{pct:.0f}% free now.")

        elif comp == "proxmox-guest":
            # Is the underlying host healthy? (distinguishes guest fault vs host fault)
            node = alert.labels.get("node", "")
            if node:
                up = _scalar(await _query(client, prom_url, f'up{{job="node",host="{node}"}}'))
                if up == 1.0:
                    out.append(f"Host {node} itself is up — looks guest-specific.")
                elif up == 0.0:
                    out.append(f"Host {node} is also down — likely a host-level fault.")

        elif comp in ("wan", "gateway", "cross-site"):
            loss = await _query(
                client, prom_url,
                f'probe_success{{component="{comp}"}} == 0',
            )
            if loss:
                out.append(f"{len(loss)} {comp} target(s) currently failing.")
    except Exception as e:  # noqa: BLE001
        log.debug("enrich() unexpected: %s", e)
    return out
