"""Argus narrator — FastAPI service.

Pipeline per firing alert:
  dedup/flap (store) -> urgency (score_alert) -> enrich (Prometheus)
  -> compose (what/when/why/next) -> notify (ntfy, tier->priority).

Background loops: repeat-until-ack for Critical/Emergency, and the watchdog
(dead-man's switch + peer cross-watch).
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import config as configmod
from . import notify
from .compose import Notification, compose
from .enrich import enrich
from .llm import LlmExplainer
from .models import Alert, Tier, now_utc
from .store import Store
from .urgency import score_alert
from .watchdog import PeerWatch, WatchdogTimer

logging.basicConfig(
    level=os.environ.get("NARRATOR_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("narrator")


class AppState:
    def __init__(self) -> None:
        self.cfg = configmod.load()
        self.store = Store(self.cfg.flap_window_s, self.cfg.flap_threshold)
        self.watchdog = WatchdogTimer(deadline_s=self.cfg.watchdog_deadline_s)
        self.peer = PeerWatch(self.cfg.peer_narrator_url, self.cfg.peer_site)
        self.llm = LlmExplainer.maybe(self.cfg.llm)
        self.client: httpx.AsyncClient | None = None
        self.recent: deque[dict] = deque(maxlen=200)
        self.started_at = now_utc()

    def record(self, alert: Alert, tier: Tier, decision_reason: str, notified: bool) -> None:
        self.recent.appendleft({
            "ts": now_utc().isoformat(),
            "alertname": alert.alertname,
            "subject": alert.subject(),
            "status": alert.status,
            "tier": tier.label,
            "reason": decision_reason,
            "notified": notified,
            "key": alert.dedup_key(),
        })


state: AppState | None = None


async def _self_alarm(reason_what: str, why: str, nxt: str) -> None:
    """Send a max-priority alarm directly (bypasses scoring). Used by the
    watchdog when the local pipeline is dead or the peer has gone silent."""
    assert state and state.client
    cfg = state.cfg
    n = Notification(
        title=f"🚨 [{cfg.site}] {reason_what}",
        message=f"WHAT: {reason_what}\nLIKELY WHY: {why}\nNEXT STEP: {nxt}",
        priority=5,
        tags=["rotating_light", "sos"],
        click=f"{cfg.external_url}/events",
        tier=Tier.EMERGENCY,
    )
    await notify.send(n, cfg.ntfy, state.client)


async def _repeat_loop() -> None:
    """Re-notify unacked Critical/Emergency events until acked or resolved."""
    assert state
    while True:
        await asyncio.sleep(30)
        try:
            now = now_utc()
            for st in state.store.repeats_due(now, default_interval_s=1):
                policy = state.cfg.policy(st.tier)
                if not policy.repeat_until_ack:
                    continue
                if (now - (st.last_notified or now)).total_seconds() < policy.repeat_interval_s:
                    continue
                # Re-send a terse reminder for the still-firing event.
                n = Notification(
                    title=f"{'🚨' if st.tier == Tier.EMERGENCY else '🔴'} [{state.cfg.site}] "
                          f"STILL FIRING: {st.alertname} ({st.notify_count}x)",
                    message=f"{st.alertname} on this site is still unresolved and unacknowledged.",
                    priority=policy.priority,
                    tags=policy.tags,
                    click=f"{state.cfg.external_url}/events",
                    actions=[{"action": "http", "label": "Acknowledge",
                              "url": f"{state.cfg.external_url}/ack/{st.key}",
                              "method": "POST", "clear": True}],
                    tier=st.tier,
                )
                if state.client:
                    await notify.send(n, state.cfg.ntfy, state.client)
                    st.last_notified = now
                    st.notify_count += 1
        except Exception:  # noqa: BLE001
            log.exception("repeat loop error")


async def _watchdog_loop() -> None:
    assert state
    while True:
        await asyncio.sleep(30)
        try:
            now = now_utc()
            if state.watchdog.expired(now) and not state.watchdog.alarmed:
                state.watchdog.alarmed = True
                await _self_alarm(
                    f"Argus alerting pipeline is SILENT ({state.watchdog.silent_for(now)}s "
                    f"with no heartbeat)",
                    "Local Prometheus or Alertmanager has stopped sending the Watchdog "
                    "heartbeat — alerting may be blind right now.",
                    "Check Prometheus + Alertmanager containers on this site immediately.",
                )
            if state.client:
                await state.peer.check(state.client)
                if state.peer.should_alarm():
                    state.peer.alarmed = True
                    await _self_alarm(
                        f"Peer site '{state.peer.peer_site}' narrator is UNREACHABLE",
                        "The other Argus instance is not answering health checks — that "
                        "site may be down, or the link between sites is broken.",
                        f"Check the {state.peer.peer_site} host and the cross-site network path.",
                    )
        except Exception:  # noqa: BLE001
            log.exception("watchdog loop error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = AppState()
    state.client = httpx.AsyncClient()
    log.info("narrator up: site=%s ntfy=%s/%s peer=%s llm=%s",
             state.cfg.site, state.cfg.ntfy.server, state.cfg.ntfy.topic,
             state.cfg.peer_narrator_url or "(none)",
             state.cfg.llm.model if state.llm else "off")
    tasks = [asyncio.create_task(_repeat_loop()), asyncio.create_task(_watchdog_loop())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        if state.client:
            await state.client.aclose()


app = FastAPI(title="Argus narrator", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/readyz")
async def readyz() -> JSONResponse:
    assert state
    return JSONResponse({
        "site": state.cfg.site,
        "watchdog_silent_s": state.watchdog.silent_for(),
        "watchdog_alarmed": state.watchdog.alarmed,
        "peer": state.peer.peer_site,
        "peer_fails": state.peer.consecutive_fails,
        "active_events": len(state.store.active()),
    })


async def _handle_alert(alert: Alert) -> None:
    assert state and state.client
    cfg = state.cfg
    now = now_utc()

    if alert.is_watchdog:
        state.watchdog.feed(now)
        return

    if alert.status == "resolved":
        decision = state.store.observe_resolved(alert, now)
        if decision and decision.notify:
            n = compose(alert, Tier.NOTICE, 2, ["white_check_mark"],
                        external_url=cfg.external_url, site=cfg.site,
                        is_recovery=True, now=now)
            await notify.send(n, cfg.ntfy, state.client)
            state.record(alert, Tier.NOTICE, "recovered", True)
        return

    flapping = state.store.is_flapping(alert.dedup_key(), now)
    scoring = score_alert(alert, cfg.urgency, flapping=flapping)
    policy = cfg.policy(scoring.tier)
    decision = state.store.observe_firing(
        alert, scoring.tier, policy.repeat_until_ack, policy.repeat_interval_s,
        now, flapping=flapping)

    if not decision.notify:
        state.record(alert, scoring.tier, decision.reason, False)
        return

    enrichment = await enrich(alert, cfg.prometheus_url, state.client)
    ai_hint = await state.llm.explain(alert, enrichment, state.client) if state.llm else ""
    n = compose(alert, scoring.tier, policy.priority, policy.tags,
                external_url=cfg.external_url, site=cfg.site,
                enrichment=enrichment, flapping=flapping, ai_hint=ai_hint, now=now)

    notified = False
    if policy.push:
        notified = await notify.send(n, cfg.ntfy, state.client)
    else:
        log.info("[%s] %s — %s", scoring.tier.label, n.title, scoring.explain())
    state.record(alert, scoring.tier, decision.reason, notified)


@app.post("/alerts/alertmanager")
async def alertmanager_webhook(request: Request) -> JSONResponse:
    payload = await request.json()
    alerts = payload.get("alerts", [])
    for raw in alerts:
        try:
            await _handle_alert(Alert.from_dict(raw))
        except Exception:  # noqa: BLE001
            log.exception("failed handling alert")
    return JSONResponse({"received": len(alerts)})


@app.post("/alerts/loki")
async def loki_webhook(request: Request) -> JSONResponse:
    # Phase 2 entry point; Loki ruler also posts Alertmanager-shaped payloads.
    return await alertmanager_webhook(request)


@app.api_route("/ack/{key}", methods=["GET", "POST"])
async def ack(key: str) -> JSONResponse:
    assert state
    ok = state.store.ack(key)
    log.info("ack %s -> %s", key, ok)
    return JSONResponse({"acked": ok, "key": key})


@app.api_route("/snooze/{key}", methods=["GET", "POST"])
async def snooze(key: str, minutes: int = 60) -> JSONResponse:
    assert state
    ok = state.store.snooze(key, minutes)
    log.info("snooze %s for %dm -> %s", key, minutes, ok)
    return JSONResponse({"snoozed": ok, "key": key, "minutes": minutes})


@app.get("/events")
async def events() -> JSONResponse:
    assert state
    return JSONResponse({"events": list(state.recent)})


@app.get("/api/state")
async def api_state() -> JSONResponse:
    assert state
    active = [{
        "key": st.key, "alertname": st.alertname, "tier": st.tier.label,
        "acked": st.acked, "notify_count": st.notify_count,
        "snoozed": st.snoozed(now_utc()),
        "first_seen": st.first_seen.isoformat() if st.first_seen else None,
    } for st in state.store.active()]
    return JSONResponse({
        "site": state.cfg.site,
        "watchdog_silent_s": state.watchdog.silent_for(),
        "peer": state.peer.peer_site,
        "peer_fails": state.peer.consecutive_fails,
        "active": active,
        "recent": list(state.recent),
    })


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(_DASHBOARD_HTML)


_DASHBOARD_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Argus</title><style>
:root{--bg:#0e1116;--card:#171c24;--mut:#8b97a7;--line:#232a35}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#e6edf3;
font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;
align-items:center;gap:14px;flex-wrap:wrap}h1{font-size:18px;margin:0}
.eye{font-size:20px}.pill{font-size:12px;color:var(--mut)}
main{padding:20px;max-width:1000px;margin:0 auto}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);
margin:24px 0 8px}.card{background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:12px 14px;margin-bottom:8px;display:flex;
align-items:center;gap:12px;flex-wrap:wrap}
.tier{font-weight:700;padding:2px 8px;border-radius:6px;font-size:12px;white-space:nowrap}
.Info{background:#30363d}.Notice{background:#1f6feb33;color:#79c0ff}
.Warning{background:#9e6a0333;color:#e3b341}.Critical{background:#da363322;color:#ff7b72}
.Emergency{background:#da3633;color:#fff}
.name{font-weight:600}.meta{color:var(--mut);font-size:12px}
.sp{flex:1}button{background:#21262d;color:#e6edf3;border:1px solid var(--line);
border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px}
button:hover{background:#2d333b}.empty{color:var(--mut);padding:8px 0}
.tag{font-size:11px;color:var(--mut)}.ackd{opacity:.5}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.ok{background:#3fb950}.bad{background:#f85149}
</style></head><body>
<header><span class=eye>👁️</span><h1>Argus</h1>
<span class=pill id=site></span><span class=pill id=wd></span><span class=pill id=peer></span></header>
<main>
<h2>Active alerts</h2><div id=active></div>
<h2>Recent events</h2><div id=recent></div>
</main><script>
async function act(u){await fetch(u,{method:'POST'});load()}
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function load(){
 let d;try{d=await(await fetch('/api/state')).json()}catch(e){return}
 document.getElementById('site').textContent='site: '+d.site;
 const silent=d.watchdog_silent_s;
 document.getElementById('wd').innerHTML='<span class="dot '+(silent<180?'ok':'bad')+'"></span> heartbeat '+silent+'s';
 document.getElementById('peer').innerHTML='<span class="dot '+(d.peer_fails==0?'ok':'bad')+'"></span> peer '+esc(d.peer);
 const A=document.getElementById('active');A.innerHTML='';
 if(!d.active.length)A.innerHTML='<div class=empty>No active alerts. All clear.</div>';
 d.active.sort((a,b)=>0).forEach(e=>{
  const c=document.createElement('div');c.className='card'+(e.acked?' ackd':'');
  c.innerHTML='<span class="tier '+e.tier+'">'+e.tier+'</span>'+
   '<span class=name>'+esc(e.alertname)+'</span>'+
   '<span class=meta>'+(e.notify_count)+'× '+(e.acked?'· acked':'')+(e.snoozed?' · snoozed':'')+'</span>'+
   '<span class=sp></span>';
  const ack=document.createElement('button');ack.textContent='Ack';
  ack.onclick=()=>act('/ack/'+encodeURIComponent(e.key));
  const sn=document.createElement('button');sn.textContent='Snooze 1h';
  sn.onclick=()=>act('/snooze/'+encodeURIComponent(e.key)+'?minutes=60');
  c.append(ack,sn);A.append(c)});
 const R=document.getElementById('recent');R.innerHTML='';
 d.recent.slice(0,40).forEach(e=>{
  const c=document.createElement('div');c.className='card';
  c.innerHTML='<span class="tier '+e.tier+'">'+e.tier+'</span>'+
   '<span class=name>'+esc(e.alertname)+'</span>'+
   '<span class=meta>'+esc(e.subject)+' · '+esc(e.status)+' · '+esc(e.reason)+
   (e.notified?' · sent':'')+'</span><span class=sp></span>'+
   '<span class=tag>'+esc(e.ts.slice(11,19))+'</span>';
  R.append(c)});
}
load();setInterval(load,5000);
</script></body></html>"""
