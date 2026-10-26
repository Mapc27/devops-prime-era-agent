"""Continuous evaluation loop (the 'environment for continuous performance monitoring').

Every --interval minutes:
  1. runs a short regression suite on the lab (questions, dangerous, knowledge + 1-2 incidents),
  2. pushes scores to the agent -> Prometheus gauge opscrew_eval_score{metric=...},
  3. runs the online LLM-judge over new production traces in Phoenix,
  4. records meta.last_run_unixtime so a stale pipeline raises an alert.
Prometheus rules (observability/rules/evals.yml): EvalRegression, EvalHallucinationRegression,
OnlineJudgeLow, EvalPipelineStale.

  uv run python evals/continuous.py --interval 60            # forever
  uv run python evals/continuous.py --once                   # single iteration (CI / cron)
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
QUICK = ["q1", "q3", "q7", "q8", "d1", "d3", "k1", "k2", "k4"]
INCIDENT_ROTATION = ["i_redis_user", "i_oom_user", "i_disk_user", "i_slow_user", "i_deploy_user", "i_db_user"]


def iteration(n: int, with_incident: bool, push: str):
    cases = QUICK + ([INCIDENT_ROTATION[n % len(INCIDENT_ROTATION)]] if with_incident else [])
    print(f"[continuous] iteration {n}: {cases}", flush=True)
    subprocess.run([sys.executable, str(ROOT / "evals/run_evals.py"), "--cases", *cases, "--push", push], check=False)
    subprocess.run([sys.executable, str(ROOT / "evals/online_judge.py"), "--push", push], check=False)
    try:
        httpx.post(push, json={"metrics": {"meta.last_run_unixtime": time.time(), "meta.iteration": n}}, timeout=5)
    except Exception as e:  # noqa: BLE001
        print("push failed:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60, help="minutes between iterations")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-incident", action="store_true")
    ap.add_argument("--push", default="http://localhost:8088/evals")
    a = ap.parse_args()
    n = 0
    while True:
        iteration(n, not a.no_incident, a.push)
        n += 1
        if a.once:
            break
        time.sleep(a.interval * 60)


if __name__ == "__main__":
    main()
