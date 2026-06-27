"""De-duplication, flap detection, escalation, recovery and ack."""
from datetime import timedelta

from narrator.models import Alert, Tier, now_utc
from narrator.store import Store


def mk(name="HostDown", status="firing", **labels):
    base = {"alertname": name}
    base.update(labels)
    return Alert(status=status, labels=base, fingerprint=f"fp-{name}-{labels.get('host','')}")


def test_first_fire_notifies_then_duplicate_suppressed():
    s = Store()
    t0 = now_utc()
    a = mk(host="app1")
    d1 = s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300, now=t0)
    assert d1.notify and d1.reason == "new"
    d2 = s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300,
                          now=t0 + timedelta(seconds=30))
    assert not d2.notify and d2.reason == "suppressed-duplicate"


def test_escalation_notifies():
    s = Store()
    t0 = now_utc()
    a = mk(host="app1")
    s.observe_firing(a, Tier.WARNING, repeat=False, repeat_interval_s=300, now=t0)
    d = s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300,
                         now=t0 + timedelta(seconds=30))
    assert d.notify and "escalated" in d.reason


def test_repeat_until_ack_after_interval():
    s = Store()
    t0 = now_utc()
    a = mk(host="app1")
    s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300, now=t0)
    # Within interval -> no repeat.
    d_soon = s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300,
                              now=t0 + timedelta(seconds=120))
    assert not d_soon.notify
    # After interval -> repeat.
    d_late = s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300,
                              now=t0 + timedelta(seconds=400))
    assert d_late.notify and d_late.reason == "repeat-until-ack"


def test_ack_stops_repeats():
    s = Store()
    t0 = now_utc()
    a = mk(host="app1")
    s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300, now=t0)
    assert s.ack(a.dedup_key())
    d = s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300,
                         now=t0 + timedelta(seconds=400))
    assert not d.notify


def test_resolved_after_firing_is_recovery_once():
    s = Store()
    t0 = now_utc()
    a = mk(host="app1")
    s.observe_firing(a, Tier.WARNING, repeat=False, repeat_interval_s=300, now=t0)
    rec = s.observe_resolved(mk(host="app1", status="resolved"), now=t0 + timedelta(minutes=5))
    assert rec and rec.is_recovery and rec.notify
    # Second resolve -> nothing.
    again = s.observe_resolved(mk(host="app1", status="resolved"), now=t0 + timedelta(minutes=6))
    assert again is None


def test_resolved_without_prior_firing_is_ignored():
    s = Store()
    rec = s.observe_resolved(mk(host="ghost", status="resolved"))
    assert rec is None


def test_flap_detection():
    s = Store(flap_window_s=1800, flap_threshold=4)
    t0 = now_utc()
    a = mk(host="flappy")
    key = a.dedup_key()
    for i in range(4):
        s.observe_firing(a, Tier.NOTICE, repeat=False, repeat_interval_s=300,
                         now=t0 + timedelta(minutes=i))
    assert s.is_flapping(key, t0 + timedelta(minutes=4))


def test_flapping_reopen_is_dampened_not_renotified_as_new():
    s = Store(flap_window_s=1800, flap_threshold=2)
    t0 = now_utc()
    a = mk(host="flappy")
    a_res = mk(host="flappy", status="resolved")
    # First fire + recovery (not yet flapping).
    d1 = s.observe_firing(a, Tier.WARNING, repeat=False, repeat_interval_s=300, now=t0)
    assert d1.notify and d1.reason == "new"
    rec1 = s.observe_resolved(a_res, now=t0 + timedelta(seconds=30))
    assert rec1 and rec1.notify and rec1.reason == "recovered"
    # Re-fire while flapping -> NOT a fresh "new"; emitted once as "flapping".
    d2 = s.observe_firing(a, Tier.WARNING, repeat=False, repeat_interval_s=300,
                          now=t0 + timedelta(seconds=60), flapping=True)
    assert d2.notify and d2.reason == "flapping"
    # Recovery while flapping is suppressed (avoids resolve/fire spam).
    rec2 = s.observe_resolved(a_res, now=t0 + timedelta(seconds=90))
    assert rec2 and not rec2.notify and rec2.reason == "recovery-suppressed"


def test_snooze_suppresses_notifications():
    s = Store()
    t0 = now_utc()
    a = mk(host="app1")
    s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300, now=t0)
    assert s.snooze(a.dedup_key(), minutes=15, now=t0)
    d = s.observe_firing(a, Tier.CRITICAL, repeat=True, repeat_interval_s=300,
                         now=t0 + timedelta(seconds=400))
    assert not d.notify and d.reason == "snoozed"


def test_old_fires_fall_out_of_flap_window():
    s = Store(flap_window_s=600, flap_threshold=3)
    t0 = now_utc()
    a = mk(host="flappy")
    key = a.dedup_key()
    s.observe_firing(a, Tier.NOTICE, repeat=False, repeat_interval_s=300, now=t0)
    # 20 minutes later, the first fire is outside the 10-minute window.
    assert s.flap_count(key, t0 + timedelta(minutes=20)) == 0
