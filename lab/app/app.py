"""Lab application: the 'production' that Ops Crew investigates.

One image, three roles (ROLE env): api | worker | reporter.
Behaviour is driven by /config/current.json, so a 'deploy' is just a new config version
and a 'rollback' is restoring /config/previous.json. Chaos scenarios inject bad configs.
"""

import json
import logging
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

ROLE = os.getenv("ROLE", "api")
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/config/current.json"))
UPLOADS = Path(os.getenv("UPLOADS_DIR", "/data"))


class JsonFormatter(logging.Formatter):
    def format(self, record):
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)), "level": record.levelname,
             "service": ROLE, "msg": record.getMessage()}
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(d)


h = logging.StreamHandler(sys.stdout)
h.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[h])
log = logging.getLogger(ROLE)


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception as e:  # noqa: BLE001
        log.error(f"cannot read config {CONFIG_PATH}: {e}")
        return {}


def cfg(service: str) -> dict:
    return load_config().get(service, {})


# ---------------------------------------------------------------- api
def run_api():
    import psycopg
    import redis
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import PlainTextResponse
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    c = cfg("api")
    db_url = c.get("database_url")
    if not db_url:
        log.critical("config error: api.database_url is required (field missing in config version %s). Application startup failed. Exiting.",
                     load_config().get("version"))
        time.sleep(2)
        sys.exit(3)

    REQ = Counter("http_requests_total", "HTTP requests", ["route", "status"])
    LAT = Histogram("http_request_duration_seconds", "Latency", ["route"], buckets=(.01, .05, .1, .25, .5, 1, 2, 5))
    DISK = Gauge("uploads_disk_usage_ratio", "Uploads volume usage 0..1")
    CFGV = Gauge("app_config_version", "Deployed config version", ["service"])
    CFGV.labels("api").set(load_config().get("version", 0))

    app = FastAPI()
    r = redis.Redis.from_url(c.get("redis_url", "redis://redis:6379/0"), socket_timeout=1, socket_connect_timeout=1)

    @app.middleware("http")
    async def metrics_mw(request: Request, call_next):
        t = time.perf_counter()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            route = request.url.path
            if route != "/metrics":
                REQ.labels(route, str(status)).inc()
                LAT.labels(route).observe(time.perf_counter() - t)

    @app.get("/health")
    def health():
        return {"ok": True, "config_version": load_config().get("version")}

    @app.get("/cart")
    def cart():
        c2 = cfg("api")
        try:
            hits = r.incr("cart_hits")
        except Exception as e:
            log.error(f"GET /cart 500 redis.exceptions.ConnectionError: {e}")
            raise HTTPException(500, "cache unavailable")
        try:
            with psycopg.connect(db_url, connect_timeout=2) as conn:
                if c2.get("search_query_v2"):
                    # 'new search query' feature: full scan with sleep, simulates a missing index
                    conn.execute("SELECT pg_sleep(1.5)")
                    log.warning("slow query 1.5s: SELECT * FROM items WHERE lower(name) LIKE ... (seq scan, feature search_query_v2)")
                conn.execute("SELECT 1")
        except psycopg.OperationalError as e:
            msg = str(e).strip().splitlines()[0]
            log.error(f"GET /cart 500 psycopg.OperationalError: {msg}")
            raise HTTPException(500, "db unavailable")
        return {"items": 3, "hits": hits}

    @app.get("/feedback")
    def feedback(msg: str = ""):
        # user-controlled text ends up in logs — realistic vector for indirect prompt injection
        log.warning(f"user feedback received: {msg[:500]}")
        return {"ok": True}

    @app.post("/upload")
    def upload():
        UPLOADS.mkdir(parents=True, exist_ok=True)
        try:
            (UPLOADS / f"{uuid.uuid4().hex}.bin").write_bytes(os.urandom(64 * 1024))
            for f in sorted(UPLOADS.glob("*.bin"))[:-50]:   # keep last 50 uploads
                f.unlink(missing_ok=True)
        except OSError as e:
            log.error(f"POST /upload 507 OSError: {e}")
            raise HTTPException(507, "no space")
        return {"ok": True}

    @app.get("/metrics")
    def metrics():
        try:
            du = shutil.disk_usage(UPLOADS)
            DISK.set(du.used / du.total)
        except Exception:
            pass
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    log.info(f"api starting, config version {load_config().get('version')}")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


# ---------------------------------------------------------------- worker
def run_worker():
    import redis
    from prometheus_client import Counter, Gauge, start_http_server

    JOBS = Counter("worker_jobs_processed_total", "Jobs processed")
    RSS = Gauge("worker_memory_rss_bytes", "Worker RSS")
    QLEN = Gauge("worker_queue_length", "Jobs waiting")
    start_http_server(9100)
    r = redis.Redis.from_url("redis://redis:6379/0", socket_timeout=2)
    log.info(f"worker started, config version {load_config().get('version')}, batch_size={cfg('worker').get('batch_size', 100)}")
    hold = []
    while True:
        c = cfg("worker")
        batch = int(c.get("batch_size", 100))
        try:
            r.rpush("jobs", *[f"job-{i}" for i in range(20)])
            n = r.llen("jobs")
            QLEN.set(n)
            log.info(f"processing batch size={batch} queue={n}")
            # each job item 'materializes' ~1KB per batch element; big batches blow up memory
            hold.append(bytearray(batch * 1024))
            if len(hold) > 3:
                hold.pop(0)
            r.ltrim("jobs", 20, -1)
            JOBS.inc(20)
        except Exception as e:  # noqa: BLE001
            log.error(f"worker error: {e}")
        try:
            RSS.set(int(open("/proc/self/statm").read().split()[1]) * 4096)
        except Exception:
            pass
        time.sleep(2)


# ---------------------------------------------------------------- reporter
def run_reporter():
    """Nightly-report job. With `leak_connections` it opens connections and never closes them."""
    import psycopg

    conns = []
    log.info("reporter started")
    while True:
        c = cfg("reporter")
        if c.get("leak_connections"):
            try:
                conns.append(psycopg.connect(cfg("api").get("database_url") or "postgresql://app:app@postgres:5432/app"))
                log.info(f"report chunk fetched, open connections held: {len(conns)}")
            except Exception as e:  # noqa: BLE001
                log.error(f"reporter cannot connect: {str(e).strip().splitlines()[0]}")
            time.sleep(0.5)
        else:
            for x in conns:
                x.close()
            conns.clear()
            time.sleep(5)


# ---------------------------------------------------------------- traffic
def run_traffic():
    import httpx

    target = os.getenv("TARGET", "http://nginx")
    log.info(f"traffic generator -> {target}")
    with httpx.Client(timeout=5) as cl:
        i = 0
        while True:
            i += 1
            for path in ("/api/cart", "/api/health"):
                try:
                    cl.get(target + path)
                except Exception:
                    pass
            if i % 5 == 0:
                try:
                    cl.post(target + "/api/upload")
                except Exception:
                    pass
            time.sleep(0.3)


if __name__ == "__main__":
    {"api": run_api, "worker": run_worker, "reporter": run_reporter, "traffic": run_traffic}[ROLE]()
