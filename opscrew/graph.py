"""Ops Crew orchestration graph (LangGraph).

triage ─┬─ question ──────────► answer ───────────────────────────────────────────────┐
        ├─ knowledge_update ──► learn ────────────────────────────────────────────────┤
        ├─ dangerous ─────────► refuse ───────────────────────────────────────────────┤
        └─ incident ──► recall ► plan ► investigate ► diagnose ► validate_diagnosis    │
                                         ▲                 revise │ approve │ escalate │
                                         └────────────────────────┘    ▼        └──────┤
                                       remediate ◄─ revise ─ validate_remediation      │
                                                              approve │ escalate ──────┤
                                                              human_gate (interrupt)   │
                                                     approve ▼          reject ▼       │
                                                 execute ► verify ► scribe ◄───────────┤
                                                                      └──► respond ◄───┘
"""

import json
import time
import uuid

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from opscrew.agents import nodes as N
from opscrew.agents.state import OpsState
from opscrew.config import settings
from opscrew.observability import RUN_DURATION, RUNS, annotate, log, span


def build_graph(checkpointer=None):
    g = StateGraph(OpsState)
    for name in ("triage", "recall", "answer", "learn", "refuse", "plan", "investigate", "diagnose", "validate_diagnosis",
                 "remediate", "validate_remediation", "human_gate", "execute", "verify", "scribe", "respond"):
        g.add_node(name, getattr(N, name))
    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", N.after_triage, ["answer", "learn", "refuse", "recall"])
    for n in ("answer", "learn", "refuse"):
        g.add_edge(n, "respond")
    g.add_edge("recall", "plan")
    g.add_edge("plan", "investigate")
    g.add_edge("investigate", "diagnose")
    g.add_edge("diagnose", "validate_diagnosis")
    g.add_conditional_edges("validate_diagnosis", N.after_diag_validation, ["remediate", "investigate", "respond"])
    g.add_edge("remediate", "validate_remediation")
    g.add_conditional_edges("validate_remediation", N.after_rem_validation, ["human_gate", "remediate", "respond"])
    g.add_conditional_edges("human_gate", N.after_human, ["execute", "scribe"])
    g.add_edge("execute", "verify")
    g.add_edge("verify", "scribe")
    g.add_edge("scribe", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)


class Runner:
    """Runs the graph with tracing, metrics, trajectory persistence and HITL resume."""

    def __init__(self):
        self._cm = None
        self.graph = None

    async def __aenter__(self):
        self._cm = AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "checkpoints.sqlite"))
        saver = await self._cm.__aenter__()
        self.graph = build_graph(saver)
        return self

    async def __aexit__(self, *exc):
        await self._cm.__aexit__(*exc)

    async def _invoke(self, payload, run_id: str, kind_hint: str):
        cfg = {"configurable": {"thread_id": run_id}, "recursion_limit": 60,
               "metadata": {"run_id": run_id}, "run_name": f"opscrew.{kind_hint}"}
        t = time.time()
        with span("opscrew.run", **{"openinference.span.kind": "AGENT", "session.id": run_id, "run.id": run_id,
                                    "input.value": payload if isinstance(payload, str) else json.dumps(payload, default=str)[:2000]}):
            try:
                state = await self.graph.ainvoke(payload, cfg)
            except Exception as e:
                RUNS.labels(kind_hint, "error").inc()
                log.exception(f"run {run_id} failed: {e}")
                raise
            snap = await self.graph.aget_state(cfg)
            pending = [i.value for t_ in snap.tasks for i in (t_.interrupts or [])]
            kind = state.get("route", {}).get("kind", kind_hint)
            if pending:
                annotate(**{"output.value": "awaiting human approval", "opscrew.outcome": "pending_approval"})
                return {"run_id": run_id, "status": "pending_approval", "approval_request": pending[0], "state": state}
            outcome = state.get("outcome", "unknown")
            RUNS.labels(kind, outcome).inc()
            RUN_DURATION.labels(kind).observe(time.time() - t)
            annotate(**{"output.value": state.get("answer", ""), "opscrew.outcome": outcome, "opscrew.kind": kind})
            self._save_trajectory(run_id, state)
            return {"run_id": run_id, "status": "done", "answer": state.get("answer"), "outcome": outcome, "state": state}

    async def run(self, text: str, source: str = "user", run_id: str | None = None):
        run_id = run_id or uuid.uuid4().hex[:10]
        return await self._invoke({"run_id": run_id, "input": text, "source": source}, run_id, "new")

    async def resume(self, run_id: str, decision: str, by: str = "human", comment: str = ""):
        return await self._invoke(Command(resume={"decision": decision, "by": by, "comment": comment}), run_id, "resume")

    @staticmethod
    def _save_trajectory(run_id, state):
        d = settings.data_dir / "trajectories"
        d.mkdir(exist_ok=True)
        keep = {k: state.get(k) for k in ("input", "route", "skill", "plan", "evidence", "diagnosis", "diag_validation",
                                          "remediation", "rem_validation", "approval", "execution", "verification",
                                          "outcome", "answer", "tool_steps", "revisions", "injection_detected",
                                          "memory_hits", "trajectory")}
        (d / f"{run_id}.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1, default=str))
