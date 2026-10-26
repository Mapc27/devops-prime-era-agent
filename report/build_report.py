"""Build report/report.pdf from report/REPORT.md.

Placeholders like {{TABLE:bench}} are filled from bench/eval results, then markdown -> HTML -> PDF
(headless Chrome).  uv run python report/build_report.py
"""

import glob
import json
import re
import subprocess
from pathlib import Path

import markdown

R = Path(__file__).resolve().parent
ROOT = R.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def t_bench():
    rows = []
    for f in sorted(glob.glob(str(ROOT / "bench/results/*.json"))):
        if "decision" in f or "engines" in f or "__think" in f:
            continue
        s = json.loads(Path(f).read_text())["summary"]
        sc = s["scores"]
        name = s["model"] + (" ⚠️ Metal OOM" if s["overall"] < 0.3 else "")
        lc = sc.get("long_context", "OOM" if "long" in sc else None)
        rows.append((name, sc.get("factual"), sc.get("real_twin"), sc.get("hallucination"), sc.get("tool_call"), sc.get("multi_step"),
                     sc.get("json"), s.get("json_strict"), sc.get("reasoning"), sc.get("injection"), lc,
                     s["overall"], s["gen_tok_s"], s.get("prompt_tok_s"), s.get("ttft_ms_median"), s["load_s"],
                     (s.get("memory") or {}).get("size_gb")))
    rows.sort(key=lambda r: -r[11])
    return md_table(["model", "fact", "real", "halluc", "tool", "multi", "json", "json strict", "reason", "inject", "long ctx",
                     "overall", "gen tok/s", "pp tok/s", "TTFT ms", "load s", "RAM GB"], rows)


def t_decision():
    f = ROOT / "bench/results/decision_models.json"
    if not f.exists():
        return "_нет данных_"
    rows = [(d["model"], d["kind"], d["acc_route"], d["acc_danger"], d["acc_ground"], d["latency_ms_p50"], d["latency_ms_p95"],
             d.get("route_ece")) for d in json.loads(f.read_text())]
    return md_table(["model", "type", "routing acc", "danger acc", "grounding acc", "p50 ms", "p95 ms", "ECE"], rows)


def t_engines():
    f = ROOT / "bench/results/engines.json"
    if not f.exists():
        return "_нет данных_"
    rows = []
    for d in json.loads(f.read_text()):
        o, l = d["ollama"], d["llama_cpp"]
        rows.append((d["model"], o.get("pp_tok_s"), o.get("tg_tok_s"), o.get("ttft_ms"), l.get("pp_tok_s"), l.get("tg_tok_s"), l.get("backend")))
    return md_table(["model", "Ollama pp tok/s", "Ollama tg tok/s", "Ollama TTFT ms", "llama.cpp pp tok/s", "llama.cpp tg tok/s", "llama.cpp backend"], rows)


def latest_eval():
    runs = sorted(glob.glob(str(ROOT / "evals/results/*/report.json")))
    full = [r for r in runs if sum(1 for _ in open(Path(r).parent / "cases.jsonl")) >= 25] if runs else []
    return Path((full or runs)[-1]).parent if runs else None


def t_evals():
    d = latest_eval()
    if not d:
        return "_нет данных_"
    m = json.loads((d / "report.json").read_text())["metrics"]
    groups = {"product": "Продуктовые", "agent": "Агентные", "llm": "LLM", "infra": "Инфраструктурные"}
    rows = [(groups[k.split(".")[0]], k.split(".", 1)[1], v) for k, v in m.items()]
    return f"Прогон `{d.name}`\n\n" + md_table(["группа", "метрика", "значение"], rows)


def t_eval_cases():
    d = latest_eval()
    if not d:
        return "_нет данных_"
    rows = []
    for line in open(d / "cases.jsonl"):
        r = json.loads(line)
        ok = r.get("resolved", r.get("answer_ok", r.get("refused_ok", r.get("supersede_ok", r.get("route_ok")))))
        rows.append((r["id"], r["category"], r.get("kind"), r.get("tier"), r.get("outcome"), "✅" if ok else "❌", r.get("tool_steps"),
                     r.get("revisions"), r["duration_s"], (r.get("root_cause") or r.get("error") or "")[:80].replace("|", "/")))
    return md_table(["case", "cat", "route", "tier", "outcome", "ok", "steps", "rev", "s", "root cause / note"], rows)


def tc_matrix():
    live = {}
    f = ROOT / "evals/results/live_checks.json"
    if f.exists():
        live = json.loads(f.read_text())
    def lv(tid):
        r = live.get(tid)
        return ("✅" if r and r["ok"] else "❌" if r else "⏳"), ("`evals/live_checks.py`: " + json.dumps(r["evidence"], ensure_ascii=False)[:110]) if r else "не прогонялся"
    rows = [
        ("TC-01", "E", "галлюцинации: несуществующие сущности", "✅", "bench: hallucination + real_twin, 7 моделей"),
        ("TC-02", "E", "tool call по JSON-схеме", "✅", "bench tool_call: 1.0 у всех рабочих моделей"),
        ("TC-03", "E", "многошаговая задача", "✅", "bench multi_step"),
        ("TC-04", "E", "строгий JSON", "✅", "bench json / json_strict"),
        ("TC-05", "E", "needle-in-haystack 8k/16k", "✅", "bench long_context (qwen3.8 — OOM)"),
        ("TC-06", "E", "prompt injection в tool output", "✅", "bench injection + eval i_injection"),
        ("TC-07", "I", "запрос проходит ≥3 агентов в одном трейсе", "✅", "Phoenix: триаж → … → scribe в одном trace"),
        ("TC-08", "I", "простой и сложный запрос на разных моделях", "✅", "evals: tier light/heavy в таблице кейсов"),
        ("TC-09", "I", "валидатор ловит неверный ответ → revise → escalate", "✅", "evals/A/B: 2 эскалации, неверный сервис пойман"),
        ("TC-10", "U", "validator family ≠ worker family", "✅", "tests/test_config.py"),
        ("TC-11", "I", "выбор нужного skill", "✅", "skill_selection_accuracy 0.93"),
        ("TC-12", "I", "изменение persona-файла меняет поведение", *lv("TC-12")),
        ("TC-13", "I", "факт из сессии 1 используется в сессии 2", "✅", "evals k4/k5 memory_recall 1.0"),
        ("TC-14", "I", "новый факт инвалидирует старый", "✅", "evals k2 supersede 1.0 + tests/test_memory.py"),
        ("TC-15", "S", "нет доступа к файлам хоста", "✅", "tests/test_sandbox_policy.py + проверка из контейнера"),
        ("TC-16", "S", "нет egress в интернет", "✅", "internal-сети; curl example.com → BLOCKED"),
        ("TC-17", "S", "деструктивное действие требует HITL", "✅", "6/6 dangerous refused; HITL-демо; токен без approve → DENIED"),
        ("TC-18", "O", "каждый запрос трассируется", "✅", "Phoenix projects ops-crew / ops-crew-demo"),
        ("TC-19", "O", "падение LLM-движка → алерт", *lv("TC-19")),
        ("TC-20", "E", "полный eval-прогон с метриками 4 групп", "✅", "§11"),
        ("TC-21", "I", "чистая копия → сборка и тесты", *lv("TC-21")),
        ("TC-22", "I", "fallback при недоступной модели", *lv("TC-22")),
    ]
    return "## 14. Матрица тест-кейсов\n\nТест-кейсы из `docs/00-task-analysis.md` §5 и их фактический статус (U — unit, I — integration, E — eval, S — security, O — observability).\n\n" + \
        md_table(["TC", "тип", "проверяет", "статус", "чем подтверждено"], rows)


def continuous():
    log = ROOT / "evals/results/continuous.log"
    if not log.exists():
        return "_continuous evals ещё не запускались_"
    lines = [json.loads(l) for l in log.read_text().splitlines() if l.startswith('{"id"')]
    judge = [l for l in log.read_text().splitlines() if l.startswith('{"judged"')]
    ok = sum(1 for r in lines if r.get("resolved") or r.get("answer_ok") or r.get("refused_ok") or r.get("outcome") == "learned")
    out = f"**Результат итерации continuous evals:** {ok} из {len(lines)} кейсов успешны"
    inc = [r for r in lines if r["id"].startswith("i_")]
    if inc:
        out += f"; инцидент `{inc[0]['id']}` — {inc[0]['outcome']} за {inc[0]['duration_s']} с"
    if judge:
        j = json.loads(judge[-1])
        out += f". Online judge: оценено {j['judged']} новых трейсов, среднее {j['mean']}, доля «needs_review» {j['low_share']}"
    return out + ". Метрики видны в Grafana (панель «Latest offline eval scores»), алерты качества — в Prometheus."


FILL = {"bench": t_bench, "decision": t_decision, "engines": t_engines, "evals": t_evals, "eval_cases": t_eval_cases}

CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font: 10.5pt/1.45 -apple-system, 'Helvetica Neue', Arial, sans-serif; color: #1d1d1f; }
h1 { font-size: 22pt; margin: 0 0 6pt; } h2 { font-size: 15pt; margin-top: 18pt; border-bottom: 1px solid #ddd; padding-bottom: 3pt; page-break-after: avoid; }
h3 { font-size: 12pt; margin-top: 12pt; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 8.3pt; margin: 6pt 0 10pt; page-break-inside: auto; }
th, td { border: 1px solid #d0d0d5; padding: 3pt 4pt; vertical-align: top; } th { background: #f2f2f5; }
tr { page-break-inside: avoid; }
code { font: 8.6pt ui-monospace, Menlo, monospace; background: #f4f4f6; padding: 0 2pt; border-radius: 2pt; }
pre { background: #f4f4f6; padding: 6pt; font-size: 8pt; overflow: hidden; white-space: pre-wrap; page-break-inside: avoid; }
img { max-width: 100%; display: block; margin: 6pt auto; page-break-inside: avoid; border: 1px solid #eee; }
.pb { page-break-after: always; } .toc ul { columns: 2; font-size: 9.5pt; } .toc li { margin: 1pt 0; } blockquote { color: #555; border-left: 3px solid #ccc; margin: 6pt 0; padding: 0 8pt; }
"""


def main():
    src = (R / "REPORT.md").read_text()
    src = re.sub(r"\{\{TABLE:(\w+)\}\}", lambda m: FILL[m.group(1)](), src)
    src = src.replace("{{TC_MATRIX}}", tc_matrix()).replace("{{CONTINUOUS_RESULTS}}", continuous())
    # python-markdown needs a blank line before a list that follows a paragraph
    out, prev = [], ""
    for line in src.splitlines():
        if re.match(r"^  [-*] ", line):   # 2-space nested items -> 4 spaces (python-markdown)
            line = "  " + line
        is_item = bool(re.match(r"^(\s*)([-*]|\d+\.) ", line))
        prev_item = bool(re.match(r"^(\s*)([-*]|\d+\.) ", prev))
        if is_item and prev.strip() and not prev_item and not prev.startswith("|"):
            out.append("")
        out.append(line)
        prev = line
    src = "\n".join(out)
    (R / "REPORT.filled.md").write_text(src)
    html = markdown.markdown(src, extensions=["tables", "fenced_code", "toc", "sane_lists"], extension_configs={"toc": {"toc_depth": "2"}})
    html = html.replace("<p>[[pagebreak]]</p>", '<div class="pb"></div>')
    doc = f"<!doctype html><html><head><meta charset='utf-8'><title>Ops Crew — отчёт</title><style>{CSS}</style></head><body>{html}</body></html>"
    (R / "report.html").write_text(doc)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                    f"--print-to-pdf={R / 'report.pdf'}", f"file://{R / 'report.html'}"], check=True, capture_output=True)
    print("written", R / "report.pdf")


if __name__ == "__main__":
    main()
