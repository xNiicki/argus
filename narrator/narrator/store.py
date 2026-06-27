"""In-memory event state: de-duplication, flap detection, ack, and the
notify decision. Time is injected (`now`) so it is deterministic in tests.

Phase 4 can swap this for a persisted store without touching callers.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import Alert, Tier, now_utc


@dataclass
class EventState:
    key: str
    alertname: str
    status: str = "firing"               # firing | resolved
    tier: Tier = Tier.INFO
    acked: bool = False
    snooze_until: datetime | None = None
    flap_notified_at: datetime | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    last_notified: datetime | None = None
    notify_count: int = 0
    fire_times: deque[datetime] = field(default_factory=lambda: deque(maxlen=64))

    def snoozed(self, now: datetime) -> bool:
        return self.snooze_until is not None and now < self.snooze_until


@dataclass
class NotifyDecision:
    notify: bool
    reason: str
    state: EventState
    is_recovery: bool = False


class Store:
    def __init__(self, flap_window_s: int = 1800, flap_threshold: int = 4):
        self._events: dict[str, EventState] = {}
        self.flap_window = timedelta(seconds=flap_window_s)
        self.flap_threshold = flap_threshold

    # --- queries ----------------------------------------------------------
    def get(self, key: str) -> EventState | None:
        return self._events.get(key)

    def flap_count(self, key: str, now: datetime) -> int:
        st = self._events.get(key)
        if not st:
            return 0
        cutoff = now - self.flap_window
        return sum(1 for t in st.fire_times if t >= cutoff)

    def is_flapping(self, key: str, now: datetime) -> bool:
        return self.flap_count(key, now) >= self.flap_threshold

    def active(self) -> list[EventState]:
        return [s for s in self._events.values() if s.status == "firing"]

    # --- mutations --------------------------------------------------------
    def observe_firing(
        self, alert: Alert, tier: Tier, repeat: bool, repeat_interval_s: int,
        now: datetime | None = None, flapping: bool = False,
    ) -> NotifyDecision:
        now = now or now_utc()
        key = alert.dedup_key()
        st = self._events.get(key)
        created = st is None
        reopened = (not created) and st.status == "resolved"
        if created:
            st = EventState(key=key, alertname=alert.alertname)
            self._events[key] = st

        # A reopen while flapping is NOT treated as new — that's what causes spam.
        is_new = created or (reopened and not flapping)
        if is_new:
            st.acked = False
            st.notify_count = 0
            st.flap_notified_at = None
        st.first_seen = st.first_seen or now

        st.fire_times.append(now)
        st.last_seen = now
        st.status = "firing"
        prev_tier = st.tier
        st.tier = tier

        # Decide whether to (re)notify.
        notify = False
        reason = "suppressed-duplicate"
        if st.snoozed(now):
            notify, reason = False, "snoozed"
        elif is_new:
            notify, reason = True, "new"
        elif tier > prev_tier:
            notify, reason = True, f"escalated {prev_tier.label}->{tier.label}"
        elif flapping and (
            st.flap_notified_at is None or now - st.flap_notified_at >= self.flap_window
        ):
            # One "is flapping" notice per window, instead of fire/resolve spam.
            notify, reason = True, "flapping"
            st.flap_notified_at = now
        elif repeat and not st.acked and st.last_notified is not None:
            if now - st.last_notified >= timedelta(seconds=repeat_interval_s):
                notify, reason = True, "repeat-until-ack"

        if notify:
            st.last_notified = now
            st.notify_count += 1
        return NotifyDecision(notify=notify, reason=reason, state=st)

    def observe_resolved(self, alert: Alert, now: datetime | None = None) -> NotifyDecision | None:
        now = now or now_utc()
        key = alert.dedup_key()
        st = self._events.get(key)
        if st is None or st.status == "resolved":
            return None                       # never alerted -> nothing to recover
        was_flapping = self.is_flapping(key, now)
        st.status = "resolved"
        st.last_seen = now
        st.acked = False
        if was_flapping or st.snoozed(now):
            # Don't announce recovery for a flapping/snoozed event — it'll re-fire.
            return NotifyDecision(notify=False, reason="recovery-suppressed",
                                  state=st, is_recovery=True)
        return NotifyDecision(notify=True, reason="recovered", state=st, is_recovery=True)

    def snooze(self, key: str, minutes: int, now: datetime | None = None) -> bool:
        now = now or now_utc()
        st = self._events.get(key)
        if not st:
            return False
        st.snooze_until = now + timedelta(minutes=minutes)
        return True

    def ack(self, key: str, now: datetime | None = None) -> bool:
        st = self._events.get(key)
        if not st:
            return False
        st.acked = True
        return True

    def repeats_due(self, now: datetime, default_interval_s: int = 300) -> list[EventState]:
        """Firing, unacked events whose repeat interval has elapsed.
        (main.py background loop uses this to re-notify until acked.)"""
        due = []
        for st in self._events.values():
            if st.status != "firing" or st.acked or st.last_notified is None:
                continue
            if now - st.last_notified >= timedelta(seconds=default_interval_s):
                due.append(st)
        return due
