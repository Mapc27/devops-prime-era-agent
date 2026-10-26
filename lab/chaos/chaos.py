"""Inject / reset incident scenarios in the lab.

  uv run python lab/chaos/chaos.py list
  uv run python lab/chaos/chaos.py inject redis_down
  uv run python lab/chaos/chaos.py reset redis_down
  uv run python lab/chaos/chaos.py reset-all
"""

import copy
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCEN = yaml.safe_load((Path(__file__).parent / "scenarios.yaml").read_text())
BASELINE = json.loads((ROOT / "lab/config/baseline.json").read_text())


def dc(*args, stdin=None):
    return subprocess.run(["docker", "compose", "-p", "lab", "-f", str(ROOT / "docker-compose.yml"), *args],
                          input=stdin, capture_output=True, text=True, check=False)


def write_config(cfg: dict, previous: dict):
    dc("exec", "-T", "lab-control", "sh", "-c", "cat > /config/previous.json", stdin=json.dumps(previous, indent=2))
    dc("exec", "-T", "lab-control", "sh", "-c", "cat > /config/current.json", stdin=json.dumps(cfg, indent=2))


def deep_merge(base, patch):
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict):
            out[k] = deep_merge(out.get(k, {}), v)
        elif v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def get(sid):
    for s in SCEN:
        if s["id"] == sid:
            return s
    sys.exit(f"unknown scenario {sid}")


def apply(step):
    if "stop" in step:
        dc("stop", step["stop"])
    elif "start" in step:
        dc("start", step["start"])
    elif "config" in step:
        new = deep_merge(BASELINE, step["config"])
        new["version"] = BASELINE["version"] + 1
        new["deployed_by"] = "ci (release 2026.10.12-1)"
        write_config(new, BASELINE)
        dc("restart", "api", "worker", "reporter")
    elif "config_baseline" in step:
        write_config(BASELINE, BASELINE)
        dc("restart", "api", "worker", "reporter")
    elif "fill_disk" in step:
        dc("exec", "-T", "api", "sh", "-c", "dd if=/dev/zero of=/data/db-dump-2026-10-12.tmp bs=1M count=16 2>/dev/null; df -h /data | tail -1")
    elif "cleanup" in step:
        dc("exec", "-T", "api", "sh", "-c", "rm -f /data/*.tmp")
    elif "feedback" in step:
        q = urllib.parse.quote(step["feedback"])
        dc("exec", "-T", "api", "python", "-c", f"import urllib.request;urllib.request.urlopen('http://localhost:8000/feedback?msg={q}')")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for s in SCEN:
            print(f"{s['id']:16} {s['title']}")
    elif cmd == "inject":
        for st in get(sys.argv[2])["inject"]:
            apply(st)
        print("injected", sys.argv[2])
    elif cmd == "reset":
        for st in get(sys.argv[2])["reset"]:
            apply(st)
        print("reset", sys.argv[2])
    elif cmd == "reset-all":
        apply({"start": "redis"})
        apply({"cleanup": True})
        apply({"config_baseline": True})
        print("lab reset to baseline")


if __name__ == "__main__":
    main()
