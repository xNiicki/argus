"""Urgency engine: severity × scope × component × role × recurrence -> Tier.

Pure functions, no I/O — this is the policy core and is unit-tested directly.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import UrgencyConfig
from .models import Alert, Tier


@dataclass
class Scoring:
    """Explainable breakdown of how a tier was reached (shown in debug/dashboard)."""
    tier: Tier
    score: int
    parts: dict[str, int]
    forced: bool = False

    def explain(self) -> str:
        bits = ", ".join(f"{k}={v:+d}" for k, v in self.parts.items() if v)
        return f"{self.tier.label} (score {self.score}: {bits or 'base'})"


def score_alert(alert: Alert, cfg: UrgencyConfig, flapping: bool = False) -> Scoring:
    """Compute the urgency tier for a single firing alert.

    `flapping` is decided by the caller (alert fired >= flap_threshold times in
    the flap window); when true we add the recurrence bonus so a persistent,
    repeatedly-firing problem escalates.
    """
    # Hard override by alertname wins outright.
    forced = cfg.overrides.get(alert.alertname)
    if forced:
        return Scoring(tier=Tier[forced.upper()], score=0, parts={"override": 0}, forced=True)

    parts: dict[str, int] = {
        "severity": cfg.severity_points.get(alert.severity, 0),
        "scope": cfg.scope_points.get(alert.scope, 0),
        "component": cfg.component_weights.get(alert.component, 0),
        "role": cfg.role_weights.get(alert.role, 0),
        "recurrence": cfg.recurrence_bonus if flapping else 0,
    }
    score = sum(parts.values())
    return Scoring(tier=cfg.tier_for_score(score), score=score, parts=parts)
