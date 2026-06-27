"""Dead-man's switch + peer cross-watch.

Local watchdog: Alertmanager forwards the always-firing `Watchdog` alert on a
steady cadence; every receipt feeds the timer. If the heartbeat stops (local
Prometheus/Alertmanager/pipeline died) the timer expires and the narrator
self-alarms.

Peer cross-watch: each site's narrator polls the OTHER site's /healthz. If the
peer goes silent, we raise the alarm here — so an outage on one side cannot
silence its own alarm; the surviving side speaks for it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from .models import now_utc

log = logging.getLogger("narrator.watchdog")


@dataclass
class WatchdogTimer:
    deadline_s: int
    last_beat: datetime | None = None
    alarmed: bool = False

    def feed(self, now: datetime | None = None) -> None:
        self.last_beat = now or now_utc()
        if self.alarmed:
            log.info("watchdog: heartbeat restored")
        self.alarmed = False

    def expired(self, now: datetime | None = None) -> bool:
        now = now or now_utc()
        if self.last_beat is None:
            # Grace: don't alarm before we've ever seen a beat (fresh start).
            return False
        return now - self.last_beat > timedelta(seconds=self.deadline_s)

    def silent_for(self, now: datetime | None = None) -> int:
        now = now or now_utc()
        if self.last_beat is None:
            return 0
        return int((now - self.last_beat).total_seconds())


@dataclass
class PeerWatch:
    url: str
    peer_site: str
    fail_threshold: int = 3
    consecutive_fails: int = 0
    alarmed: bool = False

    async def check(self, client: httpx.AsyncClient) -> bool:
        """Return True if the peer is healthy. Tracks consecutive failures."""
        if not self.url:
            return True
        try:
            r = await client.get(f"{self.url.rstrip('/')}/healthz", timeout=8.0)
            ok = r.status_code == 200
        except Exception as e:  # noqa: BLE001
            log.debug("peer check failed: %s", e)
            ok = False
        if ok:
            if self.alarmed:
                log.info("peer %s reachable again", self.peer_site)
            self.consecutive_fails = 0
            self.alarmed = False
        else:
            self.consecutive_fails += 1
        return ok

    def should_alarm(self) -> bool:
        return (
            self.consecutive_fails >= self.fail_threshold
            and not self.alarmed
        )
