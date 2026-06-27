"""LLM explainer gating + prompt assembly (no network)."""
from narrator.config import LlmConfig
from narrator.llm import LlmExplainer
from narrator.models import Alert


def cfg(enabled=True, key="sk-or-test"):
    return LlmConfig(enabled=enabled, base_url="https://openrouter.ai/api/v1",
                     api_key=key, model="anthropic/claude-3.5-sonnet")


def test_disabled_without_api_key():
    assert LlmExplainer.maybe(cfg(key="")) is None


def test_disabled_when_flag_off():
    assert LlmExplainer.maybe(cfg(enabled=False)) is None


def test_enabled_with_key():
    assert isinstance(LlmExplainer.maybe(cfg()), LlmExplainer)


def test_prompt_includes_alert_fields_and_context():
    ex = LlmExplainer(cfg())
    a = Alert(status="firing", labels={
        "alertname": "HostDown", "severity": "critical", "scope": "host",
        "component": "host", "host": "pve1", "site": "homelab"},
        annotations={"summary": "Host pve1 is unreachable", "description": "no response"})
    p = ex._prompt(a, ["3 guest(s) on pve1 also unreachable."])
    assert "HostDown" in p
    assert "pve1" in p
    assert "context: 3 guest(s)" in p
