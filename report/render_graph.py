"""Render the real LangGraph topology (from code) with graphviz: report/img/graph-langgraph.png"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opscrew.graph import build_graph  # noqa: E402

COL = {"triage": "#E9D8FD", "recall": "#E9D8FD", "answer": "#E8F0FE", "learn": "#E8F0FE", "refuse": "#FCE8E6",
       "plan": "#D2E3FC", "investigate": "#D2E3FC", "diagnose": "#D2E3FC", "validate_diagnosis": "#FEEFC3",
       "remediate": "#CEEAD6", "validate_remediation": "#FEEFC3", "human_gate": "#F6AEA9", "execute": "#F6AEA9",
       "verify": "#E8EAED", "scribe": "#E8EAED", "respond": "#E8EAED"}
g = build_graph().get_graph()
lines = ['digraph G { rankdir=TB; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11];',
         'edge [fontname="Helvetica", fontsize=9];']
for n in g.nodes:
    shape = "oval" if n.startswith("__") else "box"
    lines.append(f'"{n}" [shape={shape}, fillcolor="{COL.get(n, "#FFFFFF")}"];')
for e in g.edges:
    style = "dashed" if e.conditional else "solid"
    lines.append(f'"{e.source}" -> "{e.target}" [style={style}];')
lines.append('labelloc="t"; label="Граф LangGraph Ops Crew (сгенерирован из кода; пунктир = условные переходы)"; }')
out = Path(__file__).parent / "img/graph-langgraph.png"
subprocess.run(["dot", "-Tpng", "-Gdpi=150", "-o", str(out)], input="\n".join(lines), text=True, check=True)
print(out)
