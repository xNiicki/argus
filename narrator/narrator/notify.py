"""Deliver a composed Notification to ntfy using JSON publishing (so action
buttons and click URLs travel cleanly)."""
from __future__ import annotations

import logging

import httpx

from .compose import Notification
from .config import NtfyConfig

log = logging.getLogger("narrator.notify")


def build_payload(n: Notification, topic: str) -> dict:
    payload: dict = {
        "topic": topic,
        "title": n.title,
        "message": n.message,
        "priority": n.priority,
        "tags": n.tags,
    }
    if n.click:
        payload["click"] = n.click
    if n.actions:
        payload["actions"] = n.actions
    return payload


async def send(n: Notification, cfg: NtfyConfig, client: httpx.AsyncClient) -> bool:
    payload = build_payload(n, cfg.topic)
    headers = {}
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"
    try:
        r = await client.post(cfg.server, json=payload, headers=headers, timeout=10.0)
        r.raise_for_status()
        log.info("ntfy sent: [%s] %s", n.tier.label, n.title)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("ntfy send failed: %s", e)
        return False
