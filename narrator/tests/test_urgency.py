"""Validates the shipped urgency policy (config/narrator.yml) maps real alerts
to the intended tiers."""
from narrator.models import Alert, Tier
from narrator.urgency import score_alert


def mk(alertname, severity, scope, component, role="", **labels):
    base = {"alertname": alertname, "severity": severity, "scope": scope,
            "component": component}
    if role:
        base["role"] = role
    base.update(labels)
    return Alert(status="firing", labels=base)


def tier(cfg, alert, flapping=False):
    return score_alert(alert, cfg.urgency, flapping=flapping).tier


def test_pve_host_down_is_emergency(cfg):
    a = mk("HostDown", "critical", "host", "host", role="hypervisor", host="pve1")
    assert tier(cfg, a) == Tier.EMERGENCY


def test_vps_edge_host_down_is_critical(cfg):
    a = mk("HostDown", "critical", "host", "host", role="edge", host="vps1")
    assert tier(cfg, a) == Tier.CRITICAL


def test_plain_service_host_down_is_critical(cfg):
    a = mk("HostDown", "critical", "host", "host", role="service", host="app1")
    assert tier(cfg, a) == Tier.CRITICAL


def test_single_http_endpoint_down_is_notice(cfg):
    a = mk("HttpEndpointDown", "warning", "single", "endpoint", role="service")
    assert tier(cfg, a) == Tier.NOTICE


def test_proxmox_guest_down_is_warning(cfg):
    a = mk("ProxmoxGuestDown", "warning", "single", "proxmox-guest")
    assert tier(cfg, a) == Tier.WARNING


def test_wan_down_is_critical(cfg):
    a = mk("WanDown", "critical", "site", "wan")
    assert tier(cfg, a) == Tier.CRITICAL


def test_cert_critical_is_warning(cfg):
    a = mk("CertExpiringCritical", "critical", "single", "cert")
    assert tier(cfg, a) == Tier.WARNING


def test_zfs_degraded_is_critical(cfg):
    a = mk("ZfsPoolDegraded", "critical", "host", "zfs", host="pve1")
    assert tier(cfg, a) == Tier.CRITICAL


def test_flapping_escalates_endpoint_to_warning(cfg):
    a = mk("HttpEndpointDown", "warning", "single", "endpoint", role="service")
    assert tier(cfg, a, flapping=False) == Tier.NOTICE
    assert tier(cfg, a, flapping=True) == Tier.WARNING


def test_ssh_bruteforce_is_warning(cfg):
    a = mk("SSHBruteForce", "warning", "host", "security", host="vps1")
    assert tier(cfg, a) == Tier.WARNING


def test_authorized_keys_change_is_warning(cfg):
    a = mk("AuthorizedKeysChanged", "warning", "host", "change", host="pve1")
    assert tier(cfg, a) == Tier.WARNING


def test_package_change_is_quiet_notice(cfg):
    a = mk("InstalledPackagesChanged", "info", "host", "change", host="app1")
    # info(0) + host(2) = 2 -> Notice (a quiet FYI push), not a loud alarm
    assert tier(cfg, a) == Tier.NOTICE


def test_watchdog_scores_to_info(cfg):
    a = mk("Watchdog", "info", "site", "watchdog")
    assert tier(cfg, a) == Tier.INFO


def test_override_forces_tier(cfg):
    cfg.urgency.overrides["HttpEndpointDown"] = "critical"
    a = mk("HttpEndpointDown", "warning", "single", "endpoint")
    s = score_alert(a, cfg.urgency)
    assert s.tier == Tier.CRITICAL and s.forced
