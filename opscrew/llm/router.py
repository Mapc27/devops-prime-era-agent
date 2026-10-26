"""Model router: maps agent roles and task complexity onto model tiers, with fallbacks.

Tiers:
  L0  Jev-like decision model (classification, routing, pre-checks)      ~0.1-0.3 s
  L1  light local chat model (simple answers, scribe, cheap steps)
  L2  heavy quantized local model (investigation, remediation planning)
  V   validator — local model of a *different family* than L1/L2
  L3  optional cloud model (OpenAI-compatible), only as fallback / for hard cases
"""

import os
import time
from functools import lru_cache

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel

from opscrew.config import models_cfg, settings
from opscrew.observability import (ENGINE_LOADED, ENGINE_UP, LLM_COST, LLM_ERRORS, LLM_LATENCY, LLM_TOKENS,
                                   ROUTER, annotate, log)


class MetricsCallback(BaseCallbackHandler):
    """Records latency / tokens / equivalent cost per (role, model, tier)."""

    def __init__(self, role: str, model: str, tier: str):
        self.role, self.model, self.tier = role, model, tier
        self._t = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        self._t[run_id] = time.perf_counter()

    def on_llm_end(self, response, *, run_id, **kw):
        dt = time.perf_counter() - self._t.pop(run_id, time.perf_counter())
        LLM_LATENCY.labels(self.role, self.model, self.tier).observe(dt)
        tin = tout = 0
        try:
            msg = response.generations[0][0].message
            um = getattr(msg, "usage_metadata", None) or {}
            tin, tout = um.get("input_tokens", 0), um.get("output_tokens", 0)
        except Exception:
            pass
        LLM_TOKENS.labels(self.role, self.model, "in").inc(tin)
        LLM_TOKENS.labels(self.role, self.model, "out").inc(tout)
        pin, pout = models_cfg().get("pricing", {}).get(self.model, [0, 0])
        LLM_COST.labels(self.model).inc((tin * pin + tout * pout) / 1e6)

    def on_llm_error(self, error, *, run_id, **kw):
        self._t.pop(run_id, None)
        LLM_ERRORS.labels(self.role, self.model, type(error).__name__).inc()


def _build(role_cfg: dict, role: str) -> BaseChatModel:
    cfg = models_cfg()
    eng = cfg["engine"]
    model = role_cfg["model"]
    cb = [MetricsCallback(role, model, role_cfg.get("tier", "?"))]
    if role_cfg.get("base_url"):  # OpenAI-compatible cloud endpoint
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, base_url=role_cfg["base_url"], api_key=os.getenv(role_cfg["api_key_env"], ""),
                          temperature=0, timeout=120, callbacks=cb, max_retries=1)
    from langchain_ollama import ChatOllama
    return ChatOllama(model=model, base_url=settings.ollama_url, temperature=0,
                      num_ctx=role_cfg.get("num_ctx", eng.get("num_ctx", 12288)),
                      keep_alive=eng.get("keep_alive", "30m"), reasoning=False, callbacks=cb, seed=42,
                      metadata={"tier": role_cfg.get("tier"), "family": role_cfg.get("family"), "role": role})


def _available(role_cfg: dict) -> bool:
    if role_cfg.get("enabled") is False:
        return False
    if role_cfg.get("base_url"):
        return bool(os.getenv(role_cfg.get("api_key_env", ""), ""))
    return True


def _chain(tier: str) -> list[str]:
    cfg = models_cfg()
    roles = cfg["roles"]
    return [tier] + [t for t in cfg["routing"]["fallback"].get(tier, []) if t in roles and _available(roles[t])]


@lru_cache(maxsize=64)
def chat(tier: str, role: str = "agent"):
    """Chat model for a tier ('light'|'heavy'|'validator'|'cloud') with configured fallbacks."""
    roles = models_cfg()["roles"]
    models = [_build(roles[t], role) for t in _chain(tier)]
    return models[0].with_fallbacks(models[1:]) if len(models) > 1 else models[0]


@lru_cache(maxsize=64)
def structured(tier: str, schema, role: str = "agent"):
    """Structured-output model (JSON schema -> constrained decoding in Ollama) with fallbacks."""
    roles = models_cfg()["roles"]
    models = [_build(roles[t], role).with_structured_output(schema, method="json_schema") for t in _chain(tier)]
    return models[0].with_fallbacks(models[1:]) if len(models) > 1 else models[0]


def with_tools(tier: str, tools, role: str = "investigator"):
    roles = models_cfg()["roles"]
    models = [_build(roles[t], role).bind_tools(tools) for t in _chain(tier)]
    return models[0].with_fallbacks(models[1:]) if len(models) > 1 else models[0]


def model_info(tier: str) -> dict:
    r = models_cfg()["roles"][tier]
    return {"model": r["model"], "family": r["family"], "tier": r.get("tier")}


def pick_tier(kind: str, complexity: str, confidence: float) -> tuple[str, str]:
    """Routing policy. Returns (tier, reason)."""
    rc = models_cfg()["routing"]
    if kind in ("question", "knowledge_update", "dangerous"):
        tier, reason = rc["simple"], f"kind={kind}"
    else:
        tier, reason = rc.get(complexity, rc["complex"]), f"complexity={complexity}"
    if confidence < rc["confidence_threshold"] and tier == rc["simple"] and kind != "dangerous":
        tier, reason = rc["complex"], f"low router confidence {confidence:.2f} -> escalate"
    ROUTER.labels(kind, tier, reason.split(" ")[0].split("=")[0]).inc()
    annotate(**{"route.kind": kind, "route.tier": tier, "route.reason": reason, "route.confidence": confidence,
                "route.model": models_cfg()["roles"][tier]["model"]})
    return tier, reason


def probe_engine() -> bool:
    """Health + loaded models (exported as metrics)."""
    try:
        r = httpx.get(settings.ollama_url.rstrip("/") + "/api/ps", timeout=3)
        r.raise_for_status()
        ENGINE_UP.set(1)
        ENGINE_LOADED.clear()
        for m in r.json().get("models", []):
            ENGINE_LOADED.labels(m["name"]).set(m.get("size", 0))
        return True
    except Exception as e:
        ENGINE_UP.set(0)
        log.warning(f"ollama probe failed: {e}")
        return False
