"""Capture screenshots of the running UIs for the report (headless Chrome).

  uv run python report/screenshots.py
"""

import subprocess
import sys
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent / "img"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def phoenix_project():
    try:
        for p in httpx.get("http://localhost:6006/v1/projects", timeout=5).json()["data"]:
            if p["name"] == "ops-crew":
                return p["id"]
    except Exception:
        return None


def shot(name, url, w=1600, h=1000, wait_ms=60000):
    subprocess.run([CHROME, "--headless=new", "--hide-scrollbars", f"--window-size={w},{h}", "--run-all-compositor-stages-before-draw",
                    f"--virtual-time-budget={wait_ms}", f"--screenshot={OUT / name}", url], capture_output=True, timeout=120)
    print(name, (OUT / name).exists())


def main():
    pid = phoenix_project()
    targets = {
        "shot-grafana-agent.png": ("http://localhost:3000/d/opscrew-agent?orgId=1&kiosk&from=now-3h&to=now&refresh=", 1600, 2200),
        "shot-grafana-lab.png": ("http://localhost:3000/d/lab-prod?orgId=1&kiosk&from=now-3h&to=now&refresh=", 1600, 1500),
        "shot-prometheus-alerts.png": ("http://localhost:9090/alerts", 1600, 1400),
        "shot-alertmanager.png": ("http://localhost:9093/#/alerts", 1600, 900),
        "shot-agent-ui.png": ("http://localhost:8088/", 1400, 1400),
    }
    if pid:
        targets["shot-phoenix-traces.png"] = (f"http://localhost:6006/projects/{pid}/traces", 1700, 1000)
        targets["shot-phoenix-sessions.png"] = (f"http://localhost:6006/projects/{pid}/sessions", 1700, 1000)
    only = set(sys.argv[1:])
    for name, (url, w, h) in targets.items():
        if not only or name in only:
            shot(name, url, w, h)


if __name__ == "__main__":
    main()
