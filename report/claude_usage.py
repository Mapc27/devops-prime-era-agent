"""Token / context statistics of the Claude Code sessions that built this project.

Reads local Claude Code transcripts (~/.claude/projects/<project>/*.jsonl), dedupes API calls by message id
and writes report/claude_usage.json + report/img/chart-claude-context.png.

  uv run python report/claude_usage.py
"""

import collections
import glob
import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.path.expanduser("~/.claude/projects/-Users-mapcdev-Projects-devops-prime-era-agent"))
KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def collect():
    calls, tools, seen_tu, compacts, models, prompts = {}, collections.Counter(), set(), [], collections.Counter(), set()
    for f in sorted(glob.glob(str(SRC / "*.jsonl"))):
        for line in open(f):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
                compacts.append(e["timestamp"])
            m = e.get("message") or {}
            if e.get("type") == "user" and isinstance(m.get("content"), str) and not e.get("isMeta") \
                    and not e.get("isCompactSummary") and not m["content"].startswith("<"):
                prompts.add(e["uuid"])
            if e.get("type") != "assistant":
                continue
            for c in m.get("content") if isinstance(m.get("content"), list) else []:
                if c.get("type") == "tool_use" and c["id"] not in seen_tu:
                    seen_tu.add(c["id"])
                    tools[c["name"]] += 1
            if m.get("id") not in calls:
                models[m.get("model")] += 1
            calls[m.get("id")] = (e["timestamp"], m.get("usage") or {})
    seq = sorted(calls.values(), key=lambda x: x[0])
    tot = {k: sum(u.get(k, 0) or 0 for _, u in seq) for k in KEYS}
    ctx = [sum(u.get(k, 0) or 0 for k in KEYS if k != "output_tokens") for _, u in seq]
    s = sorted(ctx)
    inp = tot["input_tokens"] + tot["cache_read_input_tokens"] + tot["cache_creation_input_tokens"]
    return seq, ctx, compacts, {
        "api_calls": len(seq), "models": dict(models), "user_prompts": len(prompts), "tool_calls": sum(tools.values()),
        "tools": dict(tools.most_common()), "tokens": tot, "tokens_total": sum(tot.values()),
        "cache_hit_share": round(tot["cache_read_input_tokens"] / inp, 3),
        "context": {"p50": s[len(s) // 2], "p90": s[int(len(s) * .9)], "max": s[-1], "mean": sum(s) // len(s)},
        "compactions": len(compacts), "first": seq[0][0], "last": seq[-1][0]}


def chart(seq, ctx, compacts):
    fig, ax = plt.subplots(figsize=(9, 3.4))
    x = range(len(ctx))
    ax.fill_between(x, [c / 1000 for c in ctx], color="#4f8cff", alpha=.35, step="post")
    ax.plot(x, [c / 1000 for c in ctx], color="#4f8cff", lw=1)
    for t in compacts:
        i = next((i for i, (ts, _) in enumerate(seq) if ts >= t), len(seq) - 1)
        ax.axvline(i, color="#e5534b", ls="--", lw=1)
        ax.text(i, max(ctx) / 1000 * .95, " compaction", color="#e5534b", fontsize=8)
    ax.axhline(1000, color="#888", ls=":", lw=1)
    ax.text(len(ctx) * .75, 1015, "окно контекста 1M", fontsize=8, color="#666")
    ax.set(xlabel="вызов модели (по порядку)", ylabel="тыс. токенов", ylim=(0, 1080),
           title="Claude Code: размер контекста на каждый вызов Opus 5.5")
    fig.tight_layout()
    fig.savefig(ROOT / "report/img/chart-claude-context.png")


if __name__ == "__main__":
    if not list(SRC.glob("*.jsonl")):
        raise SystemExit(f"no Claude Code transcripts in {SRC}, keeping report/claude_usage.json")
    seq, ctx, compacts, stats = collect()
    chart(seq, ctx, compacts)
    (ROOT / "report/claude_usage.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    print(json.dumps(stats, ensure_ascii=False, indent=1))
