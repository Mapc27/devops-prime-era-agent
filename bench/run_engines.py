"""Inference engine comparison on the SAME model file (GGUF blob from the Ollama store).

Engines: Ollama (HTTP API) vs llama.cpp (llama-bench, Metal). Measures prompt processing (pp)
and token generation (tg) throughput, plus Ollama TTFT. Results -> bench/results/engines.json

  uv run python bench/run_engines.py --models granite4.2:8b qwen2.5:7b-instruct
"""

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path

import httpx

OLLAMA = "http://localhost:11434"
MANIFESTS = Path.home() / ".ollama/models/manifests/registry.ollama.ai/library"
BLOBS = Path.home() / ".ollama/models/blobs"
OUT = Path(__file__).parent / "results/engines.json"
PROMPT = ("Summarize the following incident log for an on-call engineer.\n" +
          "\n".join(f"2026-10-12T10:{i // 60:02d}:{i % 60:02d}Z api ERROR GET /cart 500 redis ConnectionError attempt={i}" for i in range(40)))


def blob_for(model: str) -> Path | None:
    name, tag = model.split(":")
    mf = MANIFESTS / name / tag
    if not mf.exists():
        return None
    layers = json.loads(mf.read_text())["layers"]
    d = max(layers, key=lambda x: x["size"])["digest"].replace(":", "-")
    p = BLOBS / d
    return p if p.read_bytes()[:4] == b"GGUF" else None


def bench_ollama(model, reps=3):
    c = httpx.Client(timeout=600)
    c.post(f"{OLLAMA}/api/generate", json={"model": model, "prompt": "hi", "options": {"num_predict": 1}})  # load
    pp, tg, ttft = [], [], []
    for i in range(reps):
        r = c.post(f"{OLLAMA}/api/generate", json={"model": model, "prompt": f"[session {time.time_ns()}]\n" + PROMPT, "stream": False, "raw": True,
                                                   "options": {"num_predict": 128, "temperature": 0, "num_ctx": 4096, "seed": i}}).json()
        pp.append(r["prompt_eval_count"] / (r["prompt_eval_duration"] / 1e9))
        tg.append(r["eval_count"] / (r["eval_duration"] / 1e9))
        ttft.append(r["prompt_eval_duration"] / 1e6)
    runner = next((m.get("details", {}).get("format") for m in c.get(f"{OLLAMA}/api/ps").json().get("models", [])), None)
    ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout
    c.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0})
    return {"pp_tok_s": round(statistics.median(pp), 1), "tg_tok_s": round(statistics.median(tg), 1),
            "ttft_ms": round(statistics.median(ttft)), "prompt_tokens": r["prompt_eval_count"], "format": runner,
            "ollama_ps": ps.strip().splitlines()[-1] if ps.strip() else ""}


def bench_llamacpp(blob: Path, n_prompt=512, n_gen=128, reps=3):
    p = subprocess.run(["llama-bench", "-m", str(blob), "-p", str(n_prompt), "-n", str(n_gen), "-r", str(reps), "-o", "json", "-ngl", "99"],
                       capture_output=True, text=True, timeout=1800)
    rows = json.loads(p.stdout)
    out = {}
    for r in rows:
        key = "pp_tok_s" if r.get("n_prompt", 0) > 0 and r.get("n_gen", 0) == 0 else "tg_tok_s"
        out[key] = round(r["avg_ts"], 1)
    out["backend"] = rows[0].get("backends") if rows else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=["granite4.2:8b", "qwen2.5:7b-instruct"])
    a = ap.parse_args()
    res = []
    for m in a.models:
        blob = blob_for(m)
        print("===", m, blob, flush=True)
        o = bench_ollama(m)
        print("ollama", o, flush=True)
        l = bench_llamacpp(blob) if blob else {"note": "not a GGUF blob (MLX weights) — llama.cpp cannot load it"}
        print("llama.cpp", l, flush=True)
        res.append({"model": m, "ollama": o, "llama_cpp": l, "blob_gguf": bool(blob)})
        time.sleep(3)
    OUT.write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
