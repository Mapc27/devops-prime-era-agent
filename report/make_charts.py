"""Charts for the report from collected results (bench, decision bench, A/B, evals, trajectories).

  uv run python report/make_charts.py      -> report/img/chart-*.png
"""

import glob
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "report/img"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150,
                     "axes.grid": True, "grid.alpha": 0.25})
C = {"ornith:9b": "#4f8cff", "granite4.2:8b": "#2fbf71", "gemma4:12b": "#f2a33a", "gemma4:26b": "#e5534b",
     "qwen3.8:27b": "#9b6bdf", "qwen2.5:7b-instruct": "#8a8f98", "muse-glimmer:30b": "#444444"}
CATS = ["factual", "real_twin", "hallucination", "tool_call", "multi_step", "json", "reasoning", "injection", "long_context"]
LBL = ["factual", "real twin\n(over-refusal)", "hallucination\nresistance", "tool call", "multi-step", "json",
       "reasoning", "injection\nresistance", "long ctx"]


def bench():
    out = {}
    for f in glob.glob(str(ROOT / "bench/results/*.json")):
        if any(x in f for x in ("decision", "engines", "__think")):
            continue
        s = json.loads(Path(f).read_text())["summary"]
        out[s["model"]] = s
    return out


def heatmap(b):
    models = sorted(b, key=lambda m: -b[m]["overall"])
    M = np.array([[b[m]["scores"].get(c, b[m]["scores"].get("long", np.nan) if c == "long_context" else np.nan) for c in CATS]
                  for m in models], dtype=float)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    im = ax.imshow(M, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(CATS)), LBL, fontsize=8)
    ax.set_yticks(range(len(models)), [f"{m}  (overall {b[m]['overall']:.2f})" for m in models])
    for i in range(len(models)):
        for j in range(len(CATS)):
            v = M[i, j]
            ax.text(j, i, "OOM" if np.isnan(v) else f"{v:.2f}", ha="center", va="center", fontsize=8)
    ax.grid(False)
    ax.set_title("Бенчмарк агентных свойств моделей (1.0 = лучше)")
    fig.colorbar(im, ax=ax, fraction=0.025)
    fig.tight_layout()
    fig.savefig(IMG / "chart-bench-heatmap.png")
    plt.close(fig)


def scatter(b):
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for m, s in b.items():
        mem = (s.get("memory") or {}).get("size_gb") or 0
        ax.scatter(s["gen_tok_s"], s["overall"], s=mem * 40, color=C.get(m, "#555"), alpha=0.75, edgecolor="k")
        ax.annotate(f"{m}\n{mem:.0f} GB", (s["gen_tok_s"], s["overall"]), xytext=(6, -4), textcoords="offset points", fontsize=8)
    ax.set_xlabel("скорость генерации, tok/s")
    ax.set_ylabel("overall score")
    ax.set_title("Качество vs скорость (размер круга = RAM модели)")
    ax.set_ylim(0, 1.05)
    fig.tight_layout()
    fig.savefig(IMG / "chart-bench-scatter.png")
    plt.close(fig)


def memory_bar(b):
    models = sorted(b, key=lambda m: (b[m].get("memory") or {}).get("size_gb") or 0)
    m8 = [(b[m].get("memory") or {}).get("size_gb") or 0 for m in models]
    m20 = [(b[m].get("memory_long_ctx") or {}).get("size_gb") or 0 for m in models]
    fig, ax = plt.subplots(figsize=(8, 3.8))
    y = np.arange(len(models))
    ax.barh(y - 0.2, m8, 0.4, label="ctx 8k", color="#4f8cff")
    ax.barh(y + 0.2, m20, 0.4, label="ctx 20k", color="#f2a33a")
    ax.axvline(17, color="#e5534b", ls="--")
    ax.text(17.2, len(models) - 0.6, "≈ лимит GPU Metal\n(24 GB unified)", color="#e5534b", fontsize=8)
    ax.set_yticks(y, models)
    ax.set_xlabel("память модели в Ollama, GB")
    ax.set_title("Память моделей vs лимит GPU на M4 Pro 24 GB")
    ax.legend()
    fig.tight_layout()
    fig.savefig(IMG / "chart-bench-memory.png")
    plt.close(fig)


def decision():
    d = json.loads((ROOT / "bench/results/decision_models.json").read_text())
    fig, ax = plt.subplots(figsize=(8, 4))
    for r in d:
        acc = (r["acc_route"] + r["acc_danger"] + r["acc_ground"]) / 3
        mk = "o" if r["kind"] == "decision" else "s"
        ax.scatter(r["latency_ms_p50"], acc, marker=mk, s=120, color="#4f8cff" if r["kind"] == "decision" else "#8a8f98", edgecolor="k")
        lab = r["model"] + (f"  ECE={r['route_ece']}" if r.get("route_ece") is not None else "  (LLM, без confidence)")
        ax.annotate(lab, (r["latency_ms_p50"], acc), xytext=(6, 4), textcoords="offset points", fontsize=8)
    ax.set_xlabel("латентность p50, мс")
    ax.set_ylabel("средняя точность (route/danger/grounding)")
    ax.set_title("Jev-like decision-модели (●) vs LLM-классификаторы (■)")
    ax.set_ylim(0.75, 1.03)
    fig.tight_layout()
    fig.savefig(IMG / "chart-decision.png")
    plt.close(fig)


def ab():
    keys = [("product.incident_resolution_rate", "resolution"), ("agent.root_cause_accuracy", "root cause"),
            ("agent.fix_accuracy", "fix"), ("product.escalation_rate", "escalation")]
    runs = {}
    for c in "AB":
        p = ROOT / f"evals/results/ab_{c}.dir"
        if p.exists():
            runs[f"A/B {c}"] = json.loads((ROOT / p.read_text().strip() / "report.json").read_text())["metrics"]
    fp = ROOT / "evals/results/full.dir"
    if fp.exists():
        runs["Final (A + fixes)"] = json.loads((ROOT / fp.read_text().strip() / "report.json").read_text())["metrics"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [3, 1.4]})
    x = np.arange(len(keys))
    w = 0.8 / max(1, len(runs))
    cols = ["#8a8f98", "#f2a33a", "#2fbf71"]
    for i, (n, m) in enumerate(runs.items()):
        ax1.bar(x + i * w, [m[k] for k, _ in keys], w, label=n, color=cols[i % 3])
        ax2.bar(i, m["infra.latency_incident_p95_s"], color=cols[i % 3])
    ax1.set_xticks(x + w * (len(runs) - 1) / 2, [l for _, l in keys])
    ax1.set_ylim(0, 1.05)
    ax1.legend(fontsize=8)
    ax1.set_title("Качество на инцидентах: A/B → финал")
    ax2.set_xticks(range(len(runs)), [n.replace(" (A + fixes)", "") for n in runs], fontsize=8)
    ax2.set_title("p95 длительность, с")
    fig.tight_layout()
    fig.savefig(IMG / "chart-ab.png")
    plt.close(fig)


def evals():
    d = ROOT / (ROOT / "evals/results/full.dir").read_text().strip()
    m = json.loads((d / "report.json").read_text())["metrics"]
    groups = {"product": "#4f8cff", "agent": "#2fbf71", "llm": "#f2a33a"}
    items = [(k, v) for k, v in m.items() if isinstance(v, (int, float)) and k.split(".")[0] in groups and 0 <= v <= 1]
    fig, ax = plt.subplots(figsize=(9, 6))
    y = np.arange(len(items))
    ax.barh(y, [v for _, v in items], color=[groups[k.split(".")[0]] for k, _ in items])
    for i, (k, v) in enumerate(items):
        ax.text(v + 0.01, i, f"{v:.2f}", va="center", fontsize=8)
    ax.set_yticks(y, [k for k, _ in items], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.12)
    ax.set_title("Evals (33 кейса): продуктовые / агентные / LLM метрики")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c, label=g) for g, c in groups.items()], loc="lower right")
    fig.tight_layout()
    fig.savefig(IMG / "chart-evals.png")
    plt.close(fig)

    cases = [json.loads(l) for l in open(d / "cases.jsonl")]
    cats = ["knowledge", "questions", "dangerous", "incidents"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.8))
    data = [[c["duration_s"] for c in cases if c["category"] == k] for k in cats]
    ax1.boxplot(data, tick_labels=cats, showmeans=True)
    ax1.set_ylabel("секунды")
    ax1.set_title("Длительность run по типам запросов")
    inc = [c for c in cases if c["category"] == "incidents"]
    ax2.bar(range(len(inc)), [c["tool_steps"] for c in inc],
            color=["#2fbf71" if c.get("resolved") else "#e5534b" for c in inc])
    ax2.set_xticks(range(len(inc)), [c["id"].replace("i_", "") for c in inc], rotation=60, fontsize=7)
    ax2.set_title("Шаги инструментов по инцидентам (зел. = решён)")
    fig.tight_layout()
    fig.savefig(IMG / "chart-evals-latency.png")
    plt.close(fig)


def timeline():
    cands = sorted(glob.glob(str(ROOT / ".data/demo/trajectories/*.json"))) or \
        sorted(glob.glob(str(ROOT / ".data/eval-*/trajectories/*.json")))
    t = None
    for f in cands:
        d = json.loads(Path(f).read_text())
        if d.get("outcome") == "resolved":
            t = d
            break
    if not t:
        return
    ev = t["trajectory"]
    t0 = ev[0]["ts"]
    nodes = [(e["node"], e["ts"] - t0) for e in ev]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    palette = {"triage": "#9b6bdf", "recall": "#9b6bdf", "plan": "#4f8cff", "investigate": "#4f8cff", "diagnose": "#4f8cff",
               "validate_diagnosis": "#f2a33a", "remediate": "#2fbf71", "validate_remediation": "#f2a33a",
               "human_gate": "#e5534b", "execute": "#e5534b", "verify": "#8a8f98", "scribe": "#8a8f98", "respond": "#8a8f98"}
    starts = [0] + [n[1] for n in nodes[:-1]]
    for i, ((name, end), st) in enumerate(zip(nodes, starts)):
        ax.barh(i, max(end - st, 0.5), left=st, color=palette.get(name, "#555"))
        ax.text(end + 1, i, f"{end - st:.0f} s", va="center", fontsize=7)
    ax.set_yticks(range(len(nodes)), [n[0] for n in nodes], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("секунды от начала run")
    ax.set_title(f"Траектория инцидента «{t['input'][:50]}…» по агентам")
    fig.tight_layout()
    fig.savefig(IMG / "chart-trajectory.png")
    plt.close(fig)


def engines():
    d = json.loads((ROOT / "bench/results/engines.json").read_text())
    fig, ax = plt.subplots(figsize=(8, 3.4))
    x = np.arange(len(d))
    ax.bar(x - 0.2, [r["ollama"]["tg_tok_s"] for r in d], 0.4, label="Ollama", color="#4f8cff")
    ax.bar(x + 0.2, [r["llama_cpp"].get("tg_tok_s", 0) for r in d], 0.4, label="llama.cpp", color="#8a8f98")
    ax.set_xticks(x, [r["model"] for r in d])
    ax.set_ylabel("генерация, tok/s")
    ax.set_title("Ollama vs llama.cpp на одном GGUF-файле")
    ax.legend()
    fig.tight_layout()
    fig.savefig(IMG / "chart-engines.png")
    plt.close(fig)


if __name__ == "__main__":
    b = bench()
    for fn in (lambda: heatmap(b), lambda: scatter(b), lambda: memory_bar(b), decision, ab, evals, timeline, engines):
        try:
            fn()
        except Exception as e:  # keep generating the rest
            print("chart failed:", e)
    print(sorted(p.name for p in IMG.glob("chart-*.png")))
