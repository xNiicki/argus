"""Configuration: merge narrator.yml with environment overrides.
Dependency-light (pyyaml only)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from .models import Tier


@dataclass
class TierPolicy:
    """How a tier maps onto ntfy delivery."""
    priority: int                 # ntfy 1..5
    push: bool = True             # if False -> log only (Info)
    tags: list[str] = field(default_factory=list)
    repeat_until_ack: bool = False
    repeat_interval_s: int = 300


@dataclass
class UrgencyConfig:
    severity_points: dict[str, int]
    scope_points: dict[str, int]
    component_weights: dict[str, int]
    role_weights: dict[str, int]
    recurrence_bonus: int
    thresholds: dict[str, int]            # tier_name -> min score
    overrides: dict[str, str]             # alertname -> forced tier name

    def tier_for_score(self, score: int) -> Tier:
        # Highest threshold whose min <= score wins.
        chosen = Tier.INFO
        best_min = -10**9
        for name, minimum in self.thresholds.items():
            if score >= minimum and minimum >= best_min:
                best_min = minimum
                chosen = Tier[name.upper()]
        return chosen


@dataclass
class NtfyConfig:
    server: str
    topic: str
    token: str = ""


@dataclass
class LlmConfig:
    """Optional LLM-assisted root-cause hints via OpenRouter (OpenAI-compatible)."""
    enabled: bool
    base_url: str
    api_key: str
    model: str
    max_tokens: int = 220
    timeout_s: float = 20.0


@dataclass
class Config:
    site: str
    external_url: str
    ntfy: NtfyConfig
    prometheus_url: str
    peer_narrator_url: str
    peer_site: str
    watchdog_deadline_s: int
    flap_window_s: int
    flap_threshold: int
    urgency: UrgencyConfig
    tier_policies: dict[Tier, TierPolicy]
    llm: LlmConfig

    def policy(self, tier: Tier) -> TierPolicy:
        return self.tier_policies[tier]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def load(path: str | None = None) -> Config:
    path = path or _env("NARRATOR_CONFIG", "/app/config/narrator.yml")
    with open(path) as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return from_dict(raw)


def from_dict(raw: dict[str, Any]) -> Config:
    """Build Config from a dict (env overrides win). Split out from load() so
    tests can construct a Config without a file."""
    u = raw.get("urgency", {})
    urgency = UrgencyConfig(
        severity_points=u.get("severity_points", {"info": 0, "warning": 3, "critical": 6}),
        scope_points=u.get("scope_points", {"single": 0, "host": 2, "site": 3}),
        component_weights=u.get("component_weights", {}),
        role_weights=u.get("role_weights", {}),
        recurrence_bonus=u.get("recurrence_bonus", 1),
        thresholds=u.get("thresholds", {
            "info": 0, "notice": 2, "warning": 4, "critical": 7, "emergency": 10,
        }),
        overrides=u.get("overrides", {}),
    )

    tp_raw = raw.get("tier_policies", {})
    defaults = {
        Tier.INFO: TierPolicy(priority=1, push=False, tags=["mag"]),
        Tier.NOTICE: TierPolicy(priority=2, push=True, tags=["bell"]),
        Tier.WARNING: TierPolicy(priority=3, push=True, tags=["warning"]),
        Tier.CRITICAL: TierPolicy(priority=4, push=True, tags=["rotating_light"],
                                  repeat_until_ack=True, repeat_interval_s=300),
        Tier.EMERGENCY: TierPolicy(priority=5, push=True, tags=["rotating_light", "sos"],
                                   repeat_until_ack=True, repeat_interval_s=180),
    }
    for name, pol in tp_raw.items():
        tier = Tier[name.upper()]
        d = defaults[tier]
        defaults[tier] = TierPolicy(
            priority=pol.get("priority", d.priority),
            push=pol.get("push", d.push),
            tags=pol.get("tags", d.tags),
            repeat_until_ack=pol.get("repeat_until_ack", d.repeat_until_ack),
            repeat_interval_s=pol.get("repeat_interval_s", d.repeat_interval_s),
        )

    ntfy_raw = raw.get("ntfy", {})
    ntfy = NtfyConfig(
        server=_env("NTFY_SERVER", ntfy_raw.get("server", "https://ntfy.sh")),
        topic=_env("NTFY_TOPIC", ntfy_raw.get("topic", "argus")),
        token=_env("NTFY_TOKEN", ntfy_raw.get("token", "")),
    )

    llm_raw = raw.get("llm", {})
    llm_key = _env("OPENROUTER_API_KEY", llm_raw.get("api_key", ""))
    llm = LlmConfig(
        enabled=bool(llm_key) and str(_env("LLM_ENABLED", str(llm_raw.get("enabled", True)))).lower()
        not in ("0", "false", "no"),
        base_url=_env("OPENROUTER_BASE_URL", llm_raw.get("base_url", "https://openrouter.ai/api/v1")),
        api_key=llm_key,
        model=_env("OPENROUTER_MODEL", llm_raw.get("model", "anthropic/claude-3.5-sonnet")),
        max_tokens=int(llm_raw.get("max_tokens", 220)),
        timeout_s=float(llm_raw.get("timeout_s", 20.0)),
    )

    return Config(
        site=_env("ARGUS_SITE", raw.get("site", "homelab")),
        external_url=_env("ARGUS_EXTERNAL_URL", raw.get("external_url", "http://localhost:8088")),
        ntfy=ntfy,
        prometheus_url=_env("PROMETHEUS_URL", raw.get("prometheus_url", "http://prometheus:9090")),
        peer_narrator_url=_env("PEER_NARRATOR_URL", raw.get("peer_narrator_url", "")),
        peer_site=_env("PEER_SITE", raw.get("peer_site", "")),
        watchdog_deadline_s=int(_env("WATCHDOG_DEADLINE_SECONDS", str(raw.get("watchdog_deadline_s", 180)))),
        flap_window_s=int(raw.get("flap_window_s", 1800)),
        flap_threshold=int(raw.get("flap_threshold", 4)),
        urgency=urgency,
        tier_policies=defaults,
        llm=llm,
    )
