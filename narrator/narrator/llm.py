"""Optional LLM-assisted root-cause hint via OpenRouter (OpenAI-compatible).

Best-effort and fully optional: if no OPENROUTER_API_KEY is configured, or the
call fails/times out, we return an empty hint and the templated message stands
on its own. The LLM only *adds* a one-line "likely cause" guess — it never
gates or delays the alert.
"""
from __future__ import annotations

import logging

import httpx

from .config import LlmConfig
from .models import Alert

log = logging.getLogger("narrator.llm")

_SYSTEM = (
    "You are Argus, an SRE assistant. Given one monitoring alert and a little "
    "context, reply with a SINGLE short sentence (max ~30 words) naming the most "
    "likely root cause and, if obvious, the fastest check. No preamble, no lists, "
    "no restating the alert. If you cannot add anything useful, reply exactly: none"
)


class LlmExplainer:
    def __init__(self, cfg: LlmConfig):
        self.cfg = cfg

    @classmethod
    def maybe(cls, cfg: LlmConfig) -> "LlmExplainer | None":
        return cls(cfg) if cfg.enabled and cfg.api_key else None

    def _prompt(self, alert: Alert, enrichment: list[str]) -> str:
        lines = [
            f"alert: {alert.alertname}",
            f"severity: {alert.severity}  scope: {alert.scope}  component: {alert.component}",
            f"subject: {alert.subject()}  site: {alert.site}",
            f"summary: {alert.annotations.get('summary', '')}",
            f"description: {alert.annotations.get('description', '')}",
        ]
        if enrichment:
            lines.append("context: " + " ".join(enrichment))
        return "\n".join(lines)

    async def explain(self, alert: Alert, enrichment: list[str], client: httpx.AsyncClient) -> str:
        try:
            r = await client.post(
                f"{self.cfg.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.cfg.api_key}",
                    "HTTP-Referer": "https://github.com/your-org/argus",
                    "X-Title": "Argus narrator",
                },
                json={
                    "model": self.cfg.model,
                    "max_tokens": self.cfg.max_tokens,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": self._prompt(alert, enrichment)},
                    ],
                },
                timeout=self.cfg.timeout_s,
            )
            r.raise_for_status()
            data = r.json()
            text = (data["choices"][0]["message"]["content"] or "").strip()
            if not text or text.lower() == "none":
                return ""
            return text
        except Exception as e:  # noqa: BLE001 - hints must never raise
            log.debug("llm explain failed: %s", e)
            return ""
