"""The composed message honours the voice contract: what/when/why/next + links."""
from datetime import timedelta

from narrator.compose import compose
from narrator.models import Alert, Tier, now_utc


def mk_alert():
    return Alert(
        status="firing",
        labels={"alertname": "HostDown", "severity": "critical", "scope": "host",
                "component": "host", "role": "hypervisor", "host": "pve1",
                "instance": "192.168.1.10:9100"},
        annotations={
            "summary": "Host pve1 is unreachable",
            "description": "node_exporter on 192.168.1.10:9100 has not responded for >2m.",
            "likely_cause": "Host powered off or network down.",
            "next_step": "Check power & console.",
            "runbook": "https://example.com/runbooks/host-down.md",
        },
        starts_at=now_utc() - timedelta(minutes=3),
        generator_url="http://prometheus:9090/graph",
        fingerprint="abc123",
    )


def test_message_has_voice_contract_sections():
    n = compose(mk_alert(), Tier.EMERGENCY, 5, ["rotating_light"],
                external_url="http://argus.lan:8088", site="homelab",
                enrichment=["3 guest(s) on pve1 also unreachable."])
    assert "WHAT:" in n.message
    assert "WHEN: started" in n.message
    assert "LIKELY WHY:" in n.message
    assert "NEXT STEP:" in n.message
    assert "CONTEXT:" in n.message
    assert "3 guest(s)" in n.message


def test_title_carries_site_and_priority():
    n = compose(mk_alert(), Tier.EMERGENCY, 5, ["rotating_light"],
                external_url="http://argus.lan:8088", site="homelab")
    assert "[homelab]" in n.title
    assert n.priority == 5
    assert n.tier == Tier.EMERGENCY


def test_actions_include_ack_and_runbook():
    n = compose(mk_alert(), Tier.CRITICAL, 4, ["rotating_light"],
                external_url="http://argus.lan:8088", site="homelab")
    labels = [a["label"] for a in n.actions]
    assert "Acknowledge" in labels
    assert "Runbook" in labels
    ack = next(a for a in n.actions if a["label"] == "Acknowledge")
    assert ack["url"].endswith("/ack/abc123")


def test_logs_action_present_and_actions_capped_at_three():
    a = mk_alert()
    a.annotations["logs"] = "http://loki.lan:3100"
    n = compose(a, Tier.CRITICAL, 4, ["rotating_light"],
                external_url="http://argus.lan:8088", site="homelab")
    labels = [x["label"] for x in n.actions]
    assert "Logs" in labels
    assert labels[0] == "Acknowledge"      # ack always survives the cap
    assert len(n.actions) <= 3             # ntfy limit


def test_recovery_message_is_low_priority_and_positive():
    a = mk_alert()
    n = compose(a, Tier.NOTICE, 2, [], external_url="http://argus.lan:8088",
                site="homelab", is_recovery=True)
    assert n.priority == 2
    assert "Resolved" in n.title
    assert "recovered" in n.message
