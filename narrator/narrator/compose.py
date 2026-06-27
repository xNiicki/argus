"""Compose the explanatory notification. Pure (stdlib only) and unit-tested.

Voice contract: every alert answers WHAT, WHEN, likely WHY, and the suggested
NEXT STEP, with a link to logs/context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import Alert, Tier, now_utc


@dataclass
class Notification:
    title: str
    message: str
    priority: int
    tags: list[str] = field(default_factory=list)
    click: str = ""                       # URL opened when the push is tapped
    actions: list[dict] = field(default_factory=list)  # ntfy action buttons
    tier: Tier = Tier.NOTICE
    dedup_key: str = ""


def _ago(then: datetime | None, now: datetime) -> str:
    if then is None:
        return "just now"
    secs = max(0, int((now - then).total_seconds()))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h {secs % 3600 // 60}m ago"
    return f"{secs // 86400}d ago"


# Tier -> a short emoji prefix so the iPhone glance is instantly readable.
_PREFIX = {
    Tier.INFO: "·",
    Tier.NOTICE: "🔵",
    Tier.WARNING: "🟠",
    Tier.CRITICAL: "🔴",
    Tier.EMERGENCY: "🚨",
}


def compose(
    alert: Alert,
    tier: Tier,
    priority: int,
    tags: list[str],
    *,
    external_url: str,
    site: str,
    enrichment: list[str] | None = None,
    is_recovery: bool = False,
    flapping: bool = False,
    ai_hint: str = "",
    now: datetime | None = None,
) -> Notification:
    now = now or now_utc()
    a = alert
    key = a.dedup_key()

    if is_recovery:
        title = f"✅ Resolved: {a.annotations.get('summary', a.alertname)}"
        when = _ago(a.starts_at, now)
        body = (
            f"WHAT: {a.subject()} has recovered ({a.alertname}).\n"
            f"WHEN: cleared {when if a.starts_at else 'now'}.\n"
            f"No action needed."
        )
        return Notification(
            title=title, message=body, priority=2, tags=["white_check_mark"],
            click=f"{external_url}/events", tier=Tier.NOTICE, dedup_key=key,
        )

    summary = a.annotations.get("summary") or a.alertname
    flap_tag = "⚡FLAPPING " if flapping else ""
    title = f"{_PREFIX.get(tier, '')} [{site}] {flap_tag}{summary}".strip()

    what = a.annotations.get("description") or summary
    when = _ago(a.starts_at, now)
    why = a.annotations.get("likely_cause", "").strip()
    nxt = a.annotations.get("next_step", "").strip()
    runbook = a.annotations.get("runbook", "").strip()

    lines = [f"WHAT: {what}", f"WHEN: started {when}."]
    if flapping:
        lines.append("NOTE: this alert is FLAPPING (firing/clearing repeatedly) — "
                     "likely an unstable resource or a threshold set too tight.")
    if enrichment:
        lines.append("CONTEXT: " + " ".join(enrichment))
    if why:
        lines.append(f"LIKELY WHY: {why}")
    if ai_hint:
        lines.append(f"AI HINT: {ai_hint}")
    if nxt:
        lines.append(f"NEXT STEP: {nxt}")
    message = "\n".join(lines)

    # Action buttons: acknowledge (stops repeat-until-ack) + open logs/runbook.
    actions: list[dict] = [{
        "action": "http",
        "label": "Acknowledge",
        "url": f"{external_url}/ack/{key}",
        "method": "POST",
        "clear": True,
    }]
    logs = a.annotations.get("logs", "").strip()
    click = logs or a.generator_url or f"{external_url}/events"
    if logs:
        actions.append({"action": "view", "label": "Logs", "url": logs})
    if runbook:
        actions.append({"action": "view", "label": "Runbook", "url": runbook})
    if a.generator_url:
        actions.append({"action": "view", "label": "Metrics", "url": a.generator_url})

    return Notification(
        title=title, message=message, priority=priority, tags=tags,
        click=click, actions=actions[:3], tier=tier, dedup_key=key,  # ntfy allows max 3
    )
