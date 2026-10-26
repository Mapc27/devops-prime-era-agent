"""Client for Jev-like System One decision models (Ollama /v1/systemone, TypeSafe-compatible API).

The decision model does not generate text: given a state and typed questions it returns
probability distributions — choice (pick an option), noul (P(true)), score (rubric level).
Ops Crew uses it as the control plane: triage/routing, skill selection, cheap validator pre-checks,
fact-contradiction detection in memory, and confidence-based cascades.
"""

import time
from dataclasses import dataclass

import httpx

from opscrew.config import models_cfg, settings
from opscrew.observability import DECISION_LATENCY, LLM_COST, LLM_TOKENS, span


@dataclass
class Choice:
    choice: str
    probabilities: dict
    confidence: float


class DecisionModel:
    def __init__(self, model: str | None = None, base_url: str | None = None, timeout=60):
        self.model = model or models_cfg()["roles"]["router"]["model"]
        self.url = (base_url or settings.ollama_url).rstrip("/") + "/v1/systemone"
        self.client = httpx.Client(timeout=timeout)

    def ask(self, state: dict, questions: dict, label: str = "decision") -> dict:
        with span(f"decision.{label}", **{"openinference.span.kind": "CHAIN", "llm.model_name": self.model,
                                          "decision.questions": list(questions)}) as s:
            t = time.perf_counter()
            r = self.client.post(self.url, json={"model": self.model, "state": state, "questions": questions})
            r.raise_for_status()
            d = r.json()
            dt = time.perf_counter() - t
            DECISION_LATENCY.labels(label).observe(dt)
            tokens = d.get("usage", {}).get("input_tokens", 0)
            LLM_TOKENS.labels("router", self.model, "in").inc(tokens)
            price = models_cfg().get("pricing", {}).get(self.model, [0, 0])[0]
            LLM_COST.labels(self.model).inc(tokens * price / 1e6)
            s.set_attribute("decision.answers", str(d["answers"])[:2000])
            s.set_attribute("decision.latency_ms", round(dt * 1000))
            return d["answers"]

    def choice(self, state: dict, instructions: str, criteria: dict, label="choice") -> Choice:
        a = self.ask(state, {"q": {"type": "choice", "instructions": instructions, "criteria": criteria}}, label)["q"]
        return Choice(a["choice"], a["probabilities"], a.get("confidence", 0.0))

    def noul(self, state: dict, instructions: str, label="noul") -> float:
        return self.ask(state, {"q": {"type": "noul", "instructions": instructions}}, label)["q"]["noul"]

    def score(self, state: dict, instructions: str, criteria: list[str], label="score") -> tuple[float, float]:
        a = self.ask(state, {"q": {"type": "score", "instructions": instructions, "criteria": criteria}}, label)["q"]
        return a["score"], a.get("confidence", 0.0)
