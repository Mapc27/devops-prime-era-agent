"""Live integration checks for test cases not covered by offline evals (docs/00-task-analysis.md §5).

  uv run python evals/live_checks.py tc22 tc12        # needs Ollama
  uv run python evals/live_checks.py tc19             # stops/starts Ollama, needs the stack
  uv run python evals/live_checks.py tc21             # clean copy -> uv sync -> pytest -> compose build
Results are merged into evals/results/live_checks.json
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evals/results/live_checks.json"
PY = sys.executable


def run_py(code: str, env: dict) -> str:
    e = {**os.environ, "OPSCREW_TRACING": "false", **env}
    p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=e, cwd=ROOT, timeout=900)
    return (p.stdout + p.stderr).strip()


def tc22():
    """Heavy tier model is unavailable -> router falls back to the next tier without failing."""
    cfg = (ROOT / "config/models.yaml").read_text().replace('"ornith:9b",      family: qwen', '"does-not-exist:9b", family: qwen', 1)
    tmp = Path(tempfile.mkdtemp()) / "models.yaml"
    tmp.write_text(cfg)
    code = ("import asyncio; from opscrew.llm.router import chat\n"
            "r = asyncio.run(chat('heavy','test').ainvoke('Reply with the single word OK'))\n"
            "print('ANSWER:', r.content[:80]); print('MODEL:', r.response_metadata.get('model'))")
    out = run_py(code, {"OPSCREW_MODELS": str(tmp), "OPSCREW_DATA": tempfile.mkdtemp()})
    ok = "ANSWER:" in out and "MODEL: granite4.2:8b" in out
    return {"id": "TC-22", "name": "fallback when the heavy model is unavailable", "ok": ok, "evidence": out[-300:]}


def tc12():
    """Changing a persona .md file changes behaviour (USER.md format rule)."""
    code = ("import asyncio; from opscrew.agents import nodes\n"
            "s={'input':'What does HTTP 503 mean?','lang':'en','route':{'tier':'light'}}\n"
            "print(asyncio.run(nodes.answer(s))['answer'][:300])")
    base = run_py(code, {"OPSCREW_DATA": tempfile.mkdtemp()})
    pdir = Path(tempfile.mkdtemp())
    for f in (ROOT / "opscrew/persona").glob("*.md"):
        shutil.copy(f, pdir / f.name)
    (pdir / "USER.md").write_text((pdir / "USER.md").read_text() +
                                  "\n- ОБЯЗАТЕЛЬНО: каждый ответ начинай со строки `TL;DR:` и одной фразы-итога.\n")
    changed = run_py(code, {"OPSCREW_DATA": tempfile.mkdtemp(), "OPSCREW_PERSONA_DIR": str(pdir)})
    ok = ("TL;DR" not in base[:40]) and ("TL;DR" in changed[:60])
    return {"id": "TC-12", "name": "persona file change changes behaviour", "ok": ok,
            "evidence": {"baseline": base[:160], "with_rule": changed[:160]}}


def alert_state(name):
    try:
        for a in httpx.get("http://localhost:9090/api/v1/alerts", timeout=5).json()["data"]["alerts"]:
            if a["labels"].get("alertname") == name:
                return a["state"]
    except Exception:
        return "error"
    return "inactive"


def tc19():
    """Ollama goes down -> agent probe -> opscrew_llm_engine_up=0 -> LLMEngineDown fires; recovers after restart."""
    t0 = time.time()
    subprocess.run(["brew", "services", "stop", "ollama"], capture_output=True)
    state, fired_after = "inactive", None
    while time.time() - t0 < 180:
        state = alert_state("LLMEngineDown")
        if state == "firing":
            fired_after = round(time.time() - t0)
            break
        time.sleep(5)
    shot = ROOT / "report/img/shot-alert-llm-engine-down.png"
    subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--hide-scrollbars",
                    "--window-size=1600,900", "--run-all-compositor-stages-before-draw", "--virtual-time-budget=20000",
                    f"--screenshot={shot}", "http://localhost:9090/alerts?state=firing"], capture_output=True, timeout=120)
    subprocess.run(["brew", "services", "start", "ollama"], capture_output=True)
    t1, resolved_after = time.time(), None
    while time.time() - t1 < 180:
        if alert_state("LLMEngineDown") == "inactive":
            resolved_after = round(time.time() - t1)
            break
        time.sleep(5)
    return {"id": "TC-19", "name": "LLM engine down -> alert", "ok": fired_after is not None and resolved_after is not None,
            "evidence": {"fired_after_s": fired_after, "resolved_after_restart_s": resolved_after, "screenshot": shot.name}}


def tc21():
    """Clean copy of the repo (no .venv/.data) -> uv sync -> pytest -> docker compose config/build."""
    dst = Path(tempfile.mkdtemp()) / "opscrew-clean"
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".venv", ".data", "__pycache__", "results", "*.pdf", "report/img"))
    steps = {}
    t = time.time()
    for name, cmd in [("uv sync", ["uv", "sync", "-q"]), ("pytest", ["uv", "run", "pytest", "-q"]),
                      ("compose config", ["docker", "compose", "-p", "opscrew-clean", "config", "-q"]),
                      ("compose build", ["docker", "compose", "-p", "opscrew-clean", "build", "-q", "config-init", "executor", "lab-control", "agent"])]:
        p = subprocess.run(cmd, cwd=dst, capture_output=True, text=True, timeout=1800)
        steps[name] = {"rc": p.returncode, "tail": (p.stdout + p.stderr).strip().splitlines()[-1:] if (p.stdout + p.stderr).strip() else []}
    shutil.rmtree(dst, ignore_errors=True)
    return {"id": "TC-21", "name": "clean copy builds and tests pass", "ok": all(s["rc"] == 0 for s in steps.values()),
            "evidence": {**steps, "duration_s": round(time.time() - t)}}


if __name__ == "__main__":
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    for name in sys.argv[1:]:
        r = globals()[name]()
        res[r["id"]] = r
        print(json.dumps(r, ensure_ascii=False)[:600], flush=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False))
