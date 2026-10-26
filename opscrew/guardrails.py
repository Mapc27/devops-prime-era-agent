"""Deterministic guardrails (first, cheapest layer of validation)."""

import re

DESTRUCTIVE = re.compile(
    r"rm\s+-rf|\bdrop\s+(table|database)|\btruncate\b|flushall|flushdb|volume\s+rm|delete\s+namespace|mkfs|"
    r"chmod\s+-r\s*777|--force|force[- ]push|pg_terminate_backend\(\s*\)|kill\s+-9|shutdown|удали|снеси",
    re.I,
)
INJECTION = re.compile(
    r"ignore (all )?(previous|prior) instructions|system (note|notice) (to|for) ai|you must call|"
    r"administrator (pre-)?(authorized|approved)|assistant:\s*you must|игнорируй (все )?предыдущие",
    re.I,
)
CATALOG = {
    "restart_service": {"services": {"api", "worker", "reporter", "nginx", "redis"}},
    "rollback_config": {},
    "cleanup_uploads": {},
    "terminate_idle_db": {},
    "none": {},
}


def check_remediation(action: str, service: str | None) -> str | None:
    """Return a violation reason or None."""
    if action not in CATALOG:
        return f"action '{action}' is not in the remediation catalog"
    if action == "restart_service":
        if not service:
            return "restart_service requires a service"
        if service == "postgres":
            return "restarting postgres (stateful) is forbidden by GUARDRAILS"
        if service not in CATALOG[action]["services"]:
            return f"restart of '{service}' is not allowed"
    return None


def detect_injection(text: str) -> bool:
    return bool(INJECTION.search(text or ""))


def looks_destructive(text: str) -> bool:
    return bool(DESTRUCTIVE.search(text or ""))
