import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field


class OpsState(TypedDict, total=False):
    run_id: str
    input: str
    source: str                      # user | alert
    lang: str                        # ru | en
    route: dict                      # kind, severity, complexity, confidence, tier, skill
    memory_context: str
    memory_hits: dict
    skill: str
    plan: dict
    evidence: Annotated[list, operator.add]
    findings: str
    tool_steps: int
    injection_detected: bool
    diagnosis: dict
    diag_validation: dict
    revisions: int
    remediation: dict
    rem_validation: dict
    rem_revisions: int
    approval: dict
    execution: dict
    verification: dict
    postmortem: str
    learned: dict
    answer: str
    outcome: str                     # answered | resolved | escalated | refused | learned | rejected | unresolved
    trajectory: Annotated[list, operator.add]


# ---------------------------------------------------------------- structured outputs
class Plan(BaseModel):
    hypotheses: list[str] = Field(description="2-4 hypotheses")
    plan: list[str] = Field(description="3-6 steps, each naming a tool")


class Diagnosis(BaseModel):
    root_cause: str
    affected_service: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    summary: str
    mitigation_hint: str


class Verdict(BaseModel):
    verdict: Literal["approve", "revise", "escalate"]
    issues: list[str] = []
    unsupported_claims: list[str] = []


class Remediation(BaseModel):
    action: Literal["restart_service", "rollback_config", "cleanup_uploads", "terminate_idle_db", "none"]
    service: str = Field("", description="REQUIRED for restart_service: one of api, worker, reporter, nginx, redis")
    rationale: str
    expected_effect: str
    rollback_plan: str
    risk: Literal["low", "medium", "high"]


class FactItem(BaseModel):
    subject: str
    text: str


class Facts(BaseModel):
    facts: list[FactItem]
