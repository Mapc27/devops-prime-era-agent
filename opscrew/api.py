"""Ops Crew HTTP API.

POST /chat                    {message}                 -> answer or pending approval
POST /runs/{run_id}/approve   {decision, by, comment}   -> resume after human decision
GET  /runs/pending                                      -> runs awaiting approval
GET  /runs/{run_id}                                     -> saved trajectory
POST /alert                   Alertmanager webhook      -> background investigation (deduplicated)
POST /evals                   {metrics: {name: value}}  -> exports offline eval scores as gauges
GET  /metrics                                           -> Prometheus
GET  /                                                  -> minimal web UI
"""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from opscrew.config import models_cfg, settings
from opscrew.graph import Runner
from opscrew.llm.router import probe_engine
from opscrew.observability import EVAL_SCORE, log, setup_logging, setup_tracing

runner: Runner | None = None
pending: dict[str, dict] = {}
results: dict[str, dict] = {}
recent_alerts: dict[str, float] = {}
ALERT_DEDUP_S = 900


async def _probe_loop():
    while True:
        await asyncio.to_thread(probe_engine)
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app):
    global runner
    setup_logging()
    setup_tracing()
    models_cfg()  # fails fast if the cross-family rule is violated
    runner = Runner()
    await runner.__aenter__()
    task = asyncio.create_task(_probe_loop())
    log.info("ops crew api started")
    yield
    task.cancel()
    await runner.__aexit__(None, None, None)


app = FastAPI(title="Ops Crew", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str


class ApproveIn(BaseModel):
    decision: str = "approve"
    by: str = "human"
    comment: str = ""


def _public(res: dict) -> dict:
    out = {k: v for k, v in res.items() if k != "state"}
    st = res.get("state", {})
    out["route"] = st.get("route")
    out["trajectory"] = st.get("trajectory")
    return out


def _track(res: dict):
    if res["status"] == "pending_approval":
        pending[res["run_id"]] = {"since": time.time(), **res["approval_request"], "input": res["state"].get("input")}
    else:
        pending.pop(res["run_id"], None)
        results[res["run_id"]] = _public(res)


@app.post("/chat")
async def chat_ep(body: ChatIn):
    res = await runner.run(body.message)
    _track(res)
    return _public(res)


@app.post("/runs/{run_id}/approve")
async def approve(run_id: str, body: ApproveIn):
    if run_id not in pending:
        raise HTTPException(404, "no pending approval for this run")
    res = await runner.resume(run_id, body.decision, body.by, body.comment)
    _track(res)
    return _public(res)


@app.get("/runs/pending")
def list_pending():
    return pending


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    p = settings.data_dir / "trajectories" / f"{run_id}.json"
    if p.exists():
        return json.loads(p.read_text())
    if run_id in pending:
        return {"status": "pending_approval", **pending[run_id]}
    raise HTTPException(404)


def _alert_text(a: dict) -> str:
    lb, an = a.get("labels", {}), a.get("annotations", {})
    return (f"ALERT {lb.get('alertname')} severity={lb.get('severity')} service={lb.get('service', lb.get('job', ''))}: "
            f"{an.get('summary', '')} {an.get('value', '')}").strip()


async def _investigate_alert(text: str):
    try:
        res = await runner.run(text, source="alert")
        _track(res)
    except Exception as e:  # noqa: BLE001
        log.exception(f"alert investigation failed: {e}")


@app.post("/alert")
async def alert(payload: dict):
    started = []
    now = time.time()
    for a in payload.get("alerts", []):
        if a.get("status") != "firing":
            continue
        name = a.get("labels", {}).get("alertname", "?")
        if now - recent_alerts.get(name, 0) < ALERT_DEDUP_S:
            continue
        recent_alerts[name] = now
        text = _alert_text(a)
        asyncio.create_task(_investigate_alert(text))
        started.append(text)
    log.info(f"alert webhook: started {len(started)} investigations")
    return {"started": started}


@app.post("/alerts/sink")
async def sink(payload: dict):
    for a in payload.get("alerts", []):
        log.info(f"alertmanager: {a.get('status')} {a.get('labels', {}).get('alertname')}")
    return {"ok": True}


@app.post("/evals")
def evals(payload: dict):
    for k, v in payload.get("metrics", {}).items():
        if isinstance(v, (int, float)):
            EVAL_SCORE.labels(k).set(v)
    return {"ok": True}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    return {"ok": True, "models": {k: v["model"] for k, v in models_cfg()["roles"].items()}}


@app.get("/", response_class=HTMLResponse)
def ui():
    return UI


UI = """<!doctype html><html><head><meta charset="utf-8"><title>Ops Crew</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1115;--fg:#e6e6e6;--mut:#9aa0a6;--card:#171a21;--acc:#4f8cff;--ok:#2fbf71;--bad:#e5534b}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 16px}
textarea{width:100%;box-sizing:border-box;background:var(--card);color:var(--fg);border:1px solid #2a2f3a;border-radius:8px;padding:10px;min-height:70px}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:8px 14px;margin:8px 8px 0 0;cursor:pointer}
button.bad{background:var(--bad)} button.ok{background:var(--ok)}
.card{background:var(--card);border:1px solid #2a2f3a;border-radius:10px;padding:12px;margin:12px 0;white-space:pre-wrap}
.traj{font:12px ui-monospace,monospace;color:var(--mut)} .mut{color:var(--mut)}
</style></head><body><main>
<h1>🛠️ Ops Crew <span class="mut">— multi-agent SRE assistant</span></h1>
<textarea id="m" placeholder="Describe an incident or ask a question…"></textarea>
<button onclick="send()">Send</button><span id="st" class="mut"></span>
<div id="pending"></div><div id="out"></div>
<script>
async function send(){const m=document.getElementById('m').value;st.textContent=' running… (local LLMs, up to a few minutes)';
 const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})});
 show(await r.json());st.textContent='';loadPending()}
function show(d){const o=document.getElementById('out');const c=document.createElement('div');c.className='card';
 const traj=(d.trajectory||[]).map(e=>e.node.padStart(20)+'  '+JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k])=>k!='node'&&k!='ts'))).slice(0,160)).join('\\n');
 c.innerHTML='<b>'+(d.status=='pending_approval'?'⏸ awaiting approval':(d.outcome||''))+'</b> <span class=mut>run '+d.run_id+'</span>\\n\\n'+
 (d.answer||'').replace(/</g,'&lt;')+'\\n\\n<div class=traj>'+traj.replace(/</g,'&lt;')+'</div>';o.prepend(c)}
async function loadPending(){const p=await (await fetch('/runs/pending')).json();const el=document.getElementById('pending');el.innerHTML='';
 for(const [id,r] of Object.entries(p)){const c=document.createElement('div');c.className='card';
  c.innerHTML='<b>Approval required</b> <span class=mut>run '+id+'</span>\\nIncident: '+(r.input||'')+'\\nDiagnosis: '+r.diagnosis.root_cause+
  '\\nAction: <b>'+r.remediation.action+' '+(r.remediation.service||'')+'</b>\\nRationale: '+r.remediation.rationale+'\\nRollback: '+r.remediation.rollback_plan+
  '\\nValidator: '+JSON.stringify(r.validation)+'\\n';
  for(const dec of ['approve','reject']){const b=document.createElement('button');b.textContent=dec;b.className=dec=='approve'?'ok':'bad';
   b.onclick=async()=>{st.textContent=' executing…';const x=await fetch('/runs/'+id+'/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:dec,by:'web-ui'})});show(await x.json());st.textContent='';loadPending()};c.appendChild(b)}
  el.appendChild(c)}}
loadPending();setInterval(loadPending,10000);
</script></main></body></html>"""


def main():
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")


if __name__ == "__main__":
    main()
