"""Core data types. Kept dependency-light (stdlib only) so urgency/dedup/compose
are unit-testable without FastAPI/httpx installed."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    # Alertmanager sends RFC3339; "0001-01-01T00:00:00Z" means unset.
    if value.startswith("0001-01-01"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Tier(IntEnum):
    """Five urgency tiers. Order matters: higher = more urgent."""
    INFO = 0       # log only, no push
    NOTICE = 1     # quiet push
    WARNING = 2    # push + sound
    CRITICAL = 3   # high priority, repeat until acked
    EMERGENCY = 4  # max priority, bypass DND

    @property
    def label(self) -> str:
        return self.name.capitalize()


@dataclass
class Alert:
    """One alert from Alertmanager (already de-grouped)."""
    status: str                       # "firing" | "resolved"
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    generator_url: str = ""
    fingerprint: str = ""

    # --- convenience accessors -------------------------------------------
    @property
    def alertname(self) -> str:
        return self.labels.get("alertname", "UnknownAlert")

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "warning")

    @property
    def scope(self) -> str:
        return self.labels.get("scope", "single")

    @property
    def component(self) -> str:
        return self.labels.get("component", "unknown")

    @property
    def role(self) -> str:
        return self.labels.get("role", "")

    @property
    def instance(self) -> str:
        return self.labels.get("instance", "")

    @property
    def host(self) -> str:
        return self.labels.get("host", "")

    @property
    def service(self) -> str:
        return self.labels.get("service", self.labels.get("target_name", ""))

    @property
    def site(self) -> str:
        return self.labels.get("site", "")

    @property
    def is_firing(self) -> bool:
        return self.status == "firing"

    @property
    def is_watchdog(self) -> bool:
        return self.alertname == "Watchdog" or self.component == "watchdog"

    def subject(self) -> str:
        """Best human label for the affected thing."""
        return self.host or self.service or self.instance or self.alertname

    def dedup_key(self) -> str:
        """Stable identity for de-duplication. Prefer the AM fingerprint;
        fall back to alertname+instance so tests/manual posts still dedup."""
        return self.fingerprint or f"{self.alertname}:{self.instance}:{self.host}:{self.service}"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Alert":
        return cls(
            status=d.get("status", "firing"),
            labels=dict(d.get("labels", {})),
            annotations=dict(d.get("annotations", {})),
            starts_at=_parse_ts(d.get("startsAt")),
            ends_at=_parse_ts(d.get("endsAt")),
            generator_url=d.get("generatorURL", ""),
            fingerprint=d.get("fingerprint", ""),
        )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
