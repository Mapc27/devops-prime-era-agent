"""Observability: Prometheus metrics, OpenTelemetry traces (-> Phoenix), JSON logs (-> Loki).

Traces carry the agent trajectory (graph nodes, LLM calls, tool calls) via OpenInference
LangChain instrumentation; custom attributes add routing / validation / memory context.
"""

import json
import os
import logging
import sys
import time
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram

from opscrew.config import settings

# ---------------------------------------------------------------- metrics
RUNS = Counter("opscrew_runs_total", "Agent runs", ["kind", "outcome"])
RUN_DURATION = Histogram("opscrew_run_duration_seconds", "End-to-end run duration", ["kind"],
                         buckets=(1, 2, 5, 10, 20, 40, 60, 120, 180, 300, 600))
LLM_LATENCY = Histogram("opscrew_llm_latency_seconds", "LLM call latency", ["role", "model", "tier"],
                        buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 40, 60, 120))
LLM_TOKENS = Counter("opscrew_llm_tokens_total", "Tokens", ["role", "model", "direction"])
LLM_COST = Counter("opscrew_llm_equiv_cost_usd_total", "Equivalent cloud API cost of local calls", ["model"])
LLM_ERRORS = Counter("opscrew_llm_errors_total", "LLM errors / fallbacks", ["role", "model", "kind"])
ROUTER = Counter("opscrew_router_decisions_total", "Routing decisions", ["kind", "tier", "reason"])
DECISION_LATENCY = Histogram("opscrew_decision_latency_seconds", "Jev-like decision model latency", ["question"],
                             buckets=(0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 5))
VERDICTS = Counter("opscrew_validator_verdicts_total", "Validator verdicts", ["stage", "verdict"])
GUARD_BLOCKS = Counter("opscrew_guardrail_blocks_total", "Guardrail blocks", ["reason"])
TOOL_CALLS = Counter("opscrew_tool_calls_total", "Tool calls", ["tool", "status"])
STEPS = Histogram("opscrew_tool_steps_per_run", "Tool steps per investigation", buckets=(0, 1, 2, 3, 4, 6, 8, 12))
MEMORY_OPS = Counter("opscrew_memory_ops_total", "Memory operations", ["layer", "op"])
MEMORY_SIZE = Gauge("opscrew_memory_items", "Items in memory layer", ["layer", "state"])
HITL = Counter("opscrew_hitl_decisions_total", "Human-in-the-loop decisions", ["decision"])
ENGINE_UP = Gauge("opscrew_llm_engine_up", "1 if Ollama reachable")
ENGINE_LOADED = Gauge("opscrew_llm_loaded_model_bytes", "Loaded model memory", ["model"])
EVAL_SCORE = Gauge("opscrew_eval_score", "Latest offline eval metric", ["metric"])

# ---------------------------------------------------------------- logging


class JsonLog(logging.Formatter):
    def format(self, r):
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)), "level": r.levelname,
             "service": "opscrew", "logger": r.name, "msg": r.getMessage()}
        for k in ("run_id", "node", "trace_id", "model", "tier"):
            if hasattr(r, k):
                d[k] = getattr(r, k)
        try:
            from opentelemetry import trace
            ctx = trace.get_current_span().get_span_context()
            if ctx.trace_id:
                d["trace_id"] = format(ctx.trace_id, "032x")
        except Exception:
            pass
        return json.dumps(d, ensure_ascii=False)


def setup_logging(level=logging.INFO):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonLog())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "mcp", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


log = logging.getLogger("opscrew")

# ---------------------------------------------------------------- tracing
_tracer = None
_NOISE = ("GET /runs", "GET /metrics", "GET /health", "GET /", "POST /alerts/sink", "POST /evals", "fastapi.")


class _AgentOnlyExporter:
    """Drops service HTTP spans (UI polling, /metrics scrapes) so Phoenix shows agent trajectories only."""

    def __init__(self, inner):
        self.inner = inner

    def export(self, spans):
        keep = [s for s in spans if not (s.name == "GET" or s.name.startswith(_NOISE))]
        return self.inner.export(keep) if keep else _ok()

    def shutdown(self):
        return self.inner.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.inner.force_flush(timeout_millis)


def _ok():
    from opentelemetry.sdk.trace.export import SpanExportResult
    return SpanExportResult.SUCCESS


def setup_tracing(service_name="opscrew"):
    global _tracer
    from opentelemetry import trace
    if not settings.tracing:
        _tracer = trace.get_tracer("opscrew")
        return _tracer
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name,
                                                            "openinference.project.name": os.getenv("OPSCREW_PROJECT", "ops-crew")}))
        provider.add_span_processor(BatchSpanProcessor(_AgentOnlyExporter(OTLPSpanExporter(endpoint=settings.otlp_endpoint, insecure=True))))
        trace.set_tracer_provider(provider)
        LangChainInstrumentor().instrument(tracer_provider=provider)
    except Exception as e:  # tracing must never break the agent
        log.warning(f"tracing disabled: {e}")
    _tracer = trace.get_tracer("opscrew")
    return _tracer


def tracer():
    global _tracer
    if _tracer is None:
        from opentelemetry import trace
        _tracer = trace.get_tracer("opscrew")
    return _tracer


@contextmanager
def span(name, **attrs):
    with tracer().start_as_current_span(name) as s:
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else json.dumps(v, ensure_ascii=False)[:4000])
        yield s


def annotate(**attrs):
    """Attach attributes to the current span (e.g. routing decision, validator verdict)."""
    from opentelemetry import trace
    s = trace.get_current_span()
    for k, v in attrs.items():
        if v is not None:
            s.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else json.dumps(v, ensure_ascii=False)[:4000])
