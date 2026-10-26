"""executor: sandbox for read-only diagnostic commands.

Security model (defence in depth, see docs/07-isolation.md):
  1. allowlist of binaries + per-binary argument validation (no shell, no pipes, no redirects)
  2. container: non-root, read-only rootfs, cap_drop=ALL, no-new-privileges, pids/mem/cpu limits
  3. network: only the lab network, no internet egress
  4. timeouts and output truncation
"""

import re
import shlex
import subprocess

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="executor")

MAX_OUT = 4000
TIMEOUT = 10

FORBIDDEN_SQL = re.compile(r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|copy|vacuum|pg_terminate_backend|pg_cancel_backend)\b", re.I)
SAFE_REDIS = {"info", "ping", "dbsize", "llen", "memory", "config", "client", "slowlog", "get", "ttl", "type", "scan"}
SAFE_REDIS_SUB = {"memory": {"stats", "usage", "doctor"}, "config": {"get"}, "client": {"list", "info"}, "slowlog": {"get", "len"}}


def check(argv: list[str]) -> str | None:
    """Return None if allowed, else reason."""
    if not argv:
        return "empty command"
    b = argv[0]
    rest = argv[1:]
    if any(ch in " ".join(argv) for ch in ["|", ";", "&", "`", "$(", ">", "<"]):
        return "shell metacharacters are not allowed"
    if b in ("df", "free", "uptime", "ss", "nproc", "date", "hostname", "nslookup", "getent", "dig"):
        return None
    if b in ("du", "ls", "stat"):
        return None if all(not a.startswith("/proc/sys") for a in rest) else "path not allowed"
    if b in ("ping",):
        return None if "-c" in rest else "ping requires -c"
    if b == "curl":
        bad = {"-X", "--request", "-d", "--data", "--data-raw", "-F", "--form", "-T", "--upload-file", "-o", "--output", "-O"}
        if bad & set(rest):
            return "only GET requests without output files are allowed"
        urls = [a for a in rest if a.startswith("http")]
        if not urls or not all(re.match(r"https?://(api|nginx|worker|redis|postgres|prometheus|loki)(:\d+)?(/|$)", u) for u in urls):
            return "curl allowed only to lab services"
        return None
    if b == "psql":
        sql = " ".join(rest)
        if "-c" not in rest:
            return "psql requires -c with a single read-only query"
        if FORBIDDEN_SQL.search(sql):
            return "only read-only SQL is allowed"
        return None
    if b == "redis-cli":
        cmd = [a for a in rest if not a.startswith("-") and a not in ("redis",)]
        if not cmd:
            return "redis-cli requires a command"
        c0 = cmd[0].lower()
        if c0 not in SAFE_REDIS:
            return f"redis command {c0} not allowed"
        if c0 in SAFE_REDIS_SUB and (len(cmd) < 2 or cmd[1].lower() not in SAFE_REDIS_SUB[c0]):
            return f"redis {c0} subcommand not allowed"
        return None
    return f"binary '{b}' is not in the allowlist"


class Cmd(BaseModel):
    command: str


@app.post("/exec")
def execute(c: Cmd):
    try:
        argv = shlex.split(c.command)
    except ValueError as e:
        return {"allowed": False, "reason": f"parse error: {e}"}
    reason = check(argv)
    if reason:
        return {"allowed": False, "reason": reason}
    if argv[0] == "psql" and "-h" not in argv:
        argv[1:1] = ["-h", "postgres", "-U", "app", "-d", "app"]
    if argv[0] == "redis-cli" and "-h" not in argv:
        argv[1:1] = ["-h", "redis"]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, env={"PGPASSWORD": "app", "PATH": "/usr/local/bin:/usr/bin:/bin"})
        out = (p.stdout + p.stderr)[-MAX_OUT:]
        return {"allowed": True, "exit_code": p.returncode, "output": out}
    except subprocess.TimeoutExpired:
        return {"allowed": True, "exit_code": -1, "output": "timeout"}
    except FileNotFoundError:
        return {"allowed": False, "reason": f"{argv[0]} not installed"}


@app.get("/health")
def health():
    return {"ok": True}
