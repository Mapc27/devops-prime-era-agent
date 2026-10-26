"""lab-control: the only component with access to the Docker API.

Exposes a *closed* set of operations (no arbitrary commands):
  GET  /services                      status/restarts/memory of lab services
  GET  /services/{name}               details + last exit code / OOMKilled flag
  POST /actions/restart/{name}        restart a stateless service
  POST /actions/rollback_config       restore previous config version and restart affected services
  POST /actions/cleanup_uploads       delete *.tmp junk and old uploads (keeps newest 20 uploads)
  POST /actions/terminate_idle_db     pg_terminate_backend() for connections idle > 30s
  GET  /metrics                       Prometheus exporter for container state
All mutating endpoints require the X-Control-Token header (given only to the ops-tools MCP server).
"""

import json
import os
import shutil
import time
from pathlib import Path

import docker
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

PROJECT = os.getenv("COMPOSE_PROJECT", "lab")
TOKEN = os.getenv("CONTROL_TOKEN", "change-me")
CONFIG_DIR = Path("/config")
SERVICES = ["api", "worker", "reporter", "postgres", "redis", "nginx"]
STATELESS = {"api", "worker", "reporter", "nginx"}
RESTARTABLE = STATELESS | {"redis"}  # postgres restart is deliberately NOT allowed (stateful)

dk = docker.from_env()
app = FastAPI(title="lab-control")

UP = Gauge("lab_container_up", "1 if container running", ["service"])
RESTARTS = Gauge("lab_container_restarts", "Restart count", ["service"])
OOM = Gauge("lab_container_oom_killed", "1 if last exit was OOMKilled", ["service"])
MEM = Gauge("lab_container_memory_bytes", "Memory usage", ["service"])
MEMLIM = Gauge("lab_container_memory_limit_bytes", "Memory limit", ["service"])


def container(name):
    cs = dk.containers.list(all=True, filters={"label": [f"com.docker.compose.project={PROJECT}",
                                                         f"com.docker.compose.service={name}"]})
    if not cs:
        raise HTTPException(404, f"service {name} not found")
    return cs[0]


def describe(name, with_stats=False):
    c = container(name)
    st = c.attrs["State"]
    d = {
        "service": name,
        "status": st.get("Status"),
        "restarting": st.get("Restarting"),
        "restarts": c.attrs.get("RestartCount", 0),
        "exit_code": st.get("ExitCode"),
        "oom_killed": st.get("OOMKilled"),
        "started_at": st.get("StartedAt"),
        "error": st.get("Error") or None,
    }
    if with_stats and st.get("Running"):
        try:
            s = c.stats(stream=False)
            d["memory_mb"] = round(s["memory_stats"].get("usage", 0) / 2**20, 1)
            lim = s["memory_stats"].get("limit", 0)
            d["memory_limit_mb"] = round(lim / 2**20, 1) if lim and lim < 2**40 else None
        except Exception:
            pass
    return d


def auth(token):
    if token != TOKEN:
        raise HTTPException(401, "bad control token")


@app.get("/services")
def services():
    return [describe(s) for s in SERVICES]


@app.get("/services/{name}")
def service(name: str):
    if name not in SERVICES:
        raise HTTPException(404)
    return describe(name, with_stats=True)


@app.post("/actions/restart/{name}")
def restart(name: str, x_control_token: str = Header("")):
    auth(x_control_token)
    if name not in RESTARTABLE:
        raise HTTPException(403, f"restart of {name} is not allowed (stateful or unknown)")
    container(name).restart(timeout=10)
    return {"ok": True, "action": "restart", "service": name}


@app.post("/actions/rollback_config")
def rollback(x_control_token: str = Header("")):
    auth(x_control_token)
    prev, cur = CONFIG_DIR / "previous.json", CONFIG_DIR / "current.json"
    if not prev.exists():
        raise HTTPException(409, "no previous config version")
    old = json.loads(cur.read_text()).get("version")
    shutil.copy(cur, CONFIG_DIR / "rolled_back.json")
    shutil.copy(prev, cur)
    new = json.loads(cur.read_text()).get("version")
    from concurrent.futures import ThreadPoolExecutor

    def _restart(s):
        try:
            container(s).restart(timeout=5)
        except Exception:
            pass
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(_restart, ("api", "worker", "reporter")))
    return {"ok": True, "action": "rollback_config", "from_version": old, "to_version": new}


@app.post("/actions/cleanup_uploads")
def cleanup(x_control_token: str = Header("")):
    auth(x_control_token)
    c = container("api")
    r = c.exec_run(["sh", "-c", "rm -f /data/*.tmp; ls -1t /data/*.bin 2>/dev/null | tail -n +21 | xargs -r rm -f; df -h /data | tail -1"])
    return {"ok": r.exit_code == 0, "action": "cleanup_uploads", "output": r.output.decode()[-300:]}


@app.post("/actions/terminate_idle_db")
def terminate_idle(x_control_token: str = Header("")):
    auth(x_control_token)
    c = container("postgres")
    sql = ("SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE state='idle' "
           "AND state_change < now() - interval '30 seconds' AND pid <> pg_backend_pid();")
    r = c.exec_run(["psql", "-U", "app", "-d", "app", "-tAc", sql])
    return {"ok": r.exit_code == 0, "action": "terminate_idle_db", "terminated": r.output.decode().strip()}


@app.get("/metrics")
def metrics():
    for s in SERVICES:
        try:
            c = container(s)
            st = c.attrs["State"]
            UP.labels(s).set(1 if st.get("Running") and not st.get("Restarting") else 0)
            RESTARTS.labels(s).set(c.attrs.get("RestartCount", 0))
            OOM.labels(s).set(1 if st.get("OOMKilled") else 0)
        except Exception:
            UP.labels(s).set(0)
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _mem_loop():
    while True:
        for s in SERVICES:
            try:
                c = container(s)
                if c.attrs["State"].get("Running"):
                    st = c.stats(stream=False)
                    MEM.labels(s).set(st["memory_stats"].get("usage", 0))
                    lim = st["memory_stats"].get("limit", 0)
                    if lim and lim < 2**40:
                        MEMLIM.labels(s).set(lim)
            except Exception:
                pass
        time.sleep(10)


import threading  # noqa: E402

threading.Thread(target=_mem_loop, daemon=True).start()
